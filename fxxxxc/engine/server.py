# -*- coding: utf-8 -*-
"""Local HTTP + WebSocket transport for the desktop engine.

The server binds to 127.0.0.1 only and requires a bearer token that the GUI
generates and passes through the environment. WebSocket support is a small
RFC6455 subset (text frames, ping/pong, close) so the engine has no third
party dependency.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import OrderedDict
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit

from api.logger import logger
from fxxxxc.engine.protocol import INVALID_PARAMS, METHOD_NOT_FOUND, RpcError

# ---------------------------------------------------------------- 媒体代理

# 只允许超星相关域名的图片走代理，防止本机服务被当成任意代理使用
_MEDIA_ALLOWED_HOST_SUFFIXES = (
    "chaoxing.com",
    "chaoxing.cn",
    "xuexitong.com",
)
_MEDIA_MAX_BYTES = 5 * 1024 * 1024
_MEDIA_CACHE_MAX_ENTRIES = 300
_MEDIA_CACHE: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()
_MEDIA_HEADERS = {
    # 官方图床按 Referer 防盗链：不带来源的直连请求会被拒绝
    "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}


def _media_host_allowed(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _MEDIA_ALLOWED_HOST_SUFFIXES
    )


def fetch_media(url: str) -> tuple[int, bytes, str]:
    """拉取平台图片：命中内存缓存直接返回，否则带 Referer 回源。"""
    import requests

    if not url:
        return 400, b"", ""
    if not _media_host_allowed(url):
        return 403, b"", ""

    cached = _MEDIA_CACHE.get(url)
    if cached is not None:
        _MEDIA_CACHE.move_to_end(url)
        return 200, cached[0], cached[1]

    try:
        resp = requests.get(url, headers=_MEDIA_HEADERS, timeout=(5, 15))
    except requests.RequestException as exc:
        logger.warning("媒体代理获取失败: {} ({})", url, exc)
        return 502, b"", ""
    if resp.status_code != 200 or not resp.content:
        return 404, b"", ""
    if len(resp.content) > _MEDIA_MAX_BYTES:
        return 413, b"", ""

    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    _MEDIA_CACHE[url] = (resp.content, content_type)
    _MEDIA_CACHE.move_to_end(url)
    while len(_MEDIA_CACHE) > _MEDIA_CACHE_MAX_ENTRIES:
        _MEDIA_CACHE.popitem(last=False)
    return 200, resp.content, content_type

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_BODY = 1024 * 1024


def _ws_accept(key: str) -> str:
    digest = hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _encode_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x80 | opcode, length)
    elif length < 65536:
        header = struct.pack("!BBH", 0x80 | opcode, 126, length)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
    return header + payload


def _read_exact(sock, count: int) -> bytes:
    buffer = b""
    while len(buffer) < count:
        chunk = sock.recv(count - len(buffer))
        if not chunk:
            raise ConnectionError("socket closed")
        buffer += chunk
    return buffer


class WebSocketClient:
    """One connected GUI. Sends bus events as text frames."""

    def __init__(self, sock, service):
        self.sock = sock
        self.service = service
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def send_json(self, payload: str) -> None:
        data = payload.encode("utf-8")
        with self.lock:
            self.sock.sendall(_encode_frame(data, opcode=0x1))

    def send_pong(self, payload: bytes) -> None:
        with self.lock:
            self.sock.sendall(_encode_frame(payload, opcode=0x0A))

    def on_event(self, event) -> None:
        try:
            self.send_json(event.to_json())
        except Exception:
            self.closed.set()

    def run(self) -> None:
        self.service.bus.subscribe(self.on_event)
        try:
            while not self.closed.is_set():
                header = _read_exact(self.sock, 2)
                opcode = header[0] & 0x0F
                masked = header[1] & 0x80
                length = header[1] & 0x7F
                if length == 126:
                    length = struct.unpack("!H", _read_exact(self.sock, 2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", _read_exact(self.sock, 8))[0]
                mask = _read_exact(self.sock, 4) if masked else b"\x00\x00\x00\x00"
                payload = _read_exact(self.sock, length) if length else b""
                if masked:
                    payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

                if opcode == 0x8:  # close
                    with self.lock:
                        try:
                            self.sock.sendall(_encode_frame(payload, opcode=0x8))
                        except Exception:
                            pass
                    break
                if opcode == 0x9:  # ping
                    self.send_pong(payload)
        except (ConnectionError, OSError):
            pass
        finally:
            self.service.bus.unsubscribe(self.on_event)
            self.closed.set()


class EngineHandler(BaseHTTPRequestHandler):
    server_version = "FXXXXCEngine/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: N802 - stdlib signature
        logger.debug(f"engine http: {fmt % args}")

    @property
    def service(self):
        return self.server.service  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        expected = self.server.token  # type: ignore[attr-defined]
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[len("Bearer ") :] == expected
        return self.headers.get("X-Engine-Token", "") == expected

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib signature
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "version": self.service.version(),
                    "pid": self.service.pid(),
                    "state": self.service.state(),
                },
            )
            return
        if path == "/events":
            self._handle_websocket()
            return
        if path == "/media":
            self._handle_media()
            return
        self._send_json(404, {"error": "not found"})

    def _handle_media(self) -> None:
        """本地媒体代理：为 GUI 图片带上平台 Referer（官方图床有防盗链）。

        仅允许超星相关域名，结果带浏览器缓存头；引擎只绑定 127.0.0.1。
        """
        from urllib.parse import parse_qs, unquote

        query = parse_qs(urlsplit(self.path).query)
        target = unquote(query.get("url", [""])[0])
        status, body, content_type = fetch_media(target)
        if status != 200:
            self._send_json(status, {"error": "media fetch failed"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type or "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - stdlib signature
        path = urlsplit(self.path).path
        if path != "/rpc":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send_json(400, {"error": "invalid body size"})
            return

        raw = self.rfile.read(length)
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": INVALID_PARAMS, "message": "method/params invalid"},
                },
            )
            return

        try:
            result = self.service.dispatch(method, params)
            payload = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            payload = {"jsonrpc": "2.0", "id": request_id, "error": exc.to_dict()}
        except Exception as exc:  # noqa: BLE001 - report as engine error
            logger.error("engine rpc {} failed: {}", method, exc)
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            }
        self._send_json(200, payload)

    def _handle_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self._send_json(400, {"error": "websocket handshake required"})
            return

        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", _ws_accept(key))
        self.end_headers()

        client = WebSocketClient(self.connection, self.service)
        self.server.clients.add(client)  # type: ignore[attr-defined]
        try:
            client.run()
        finally:
            self.server.clients.discard(client)  # type: ignore[attr-defined]
            self.close_connection = True


class EngineServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service, token: str):
        self.service = service
        self.token = token
        self.clients: set[WebSocketClient] = set()
        super().__init__(address, EngineHandler)

    def broadcast_shutdown(self) -> None:
        for client in list(self.clients):
            try:
                client.send_json(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "event",
                            "params": {"type": "engine.stopping", "seq": 0, "data": {}},
                        }
                    )
                )
            except Exception:
                pass


def create_server(host: str, port: int, service, token: str) -> EngineServer:
    return EngineServer((host, port), service, token)
