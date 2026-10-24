# -*- coding: utf-8 -*-
"""Engine contract tests: HTTP JSON-RPC, WebSocket events and manual flow."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import threading
import time

import pytest
import requests

from fxxxxc.engine.protocol import RpcError
from fxxxxc.engine.server import create_server
from fxxxxc.engine.service import EngineService


@pytest.fixture()
def service(tmp_path):
    svc = EngineService(data_dir=tmp_path)
    yield svc
    svc.close()


@pytest.fixture()
def server(service):
    httpd = create_server("127.0.0.1", 0, service, "test-token")
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", httpd
    httpd.shutdown()
    httpd.server_close()


def _rpc(base: str, method: str, params: dict | None = None, token: str = "test-token", request_id: int = 1):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.post(
        f"{base}/rpc",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        headers=headers,
        timeout=5,
    )
    return response


def test_health_is_public(server):
    base, _ = server
    response = requests.get(f"{base}/health", timeout=5)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["state"] == "idle"


def test_rpc_requires_token(server):
    base, _ = server
    response = _rpc(base, "app.info", token="")
    assert response.status_code == 401


def test_rpc_app_info_and_config_roundtrip(server, service):
    base, _ = server
    result = _rpc(base, "app.info").json()["result"]
    assert result["state"] == "idle"
    assert result["data_dir"] == str(service.data_dir)

    _rpc(base, "config.set", {"config": {"common": {"jobs": "6", "speed": "1.5"}}})
    config = _rpc(base, "config.get").json()["result"]["config"]
    assert config["common"]["jobs"] == "6"
    assert config["common"]["speed"] == "1.5"


def test_rpc_unknown_method_returns_error(server):
    base, _ = server
    payload = _rpc(base, "nope").json()
    assert payload["error"]["code"] == -32601


def test_study_start_requires_course_ids(service):
    with pytest.raises(RpcError) as excinfo:
        service.dispatch("study.start", {})
    assert excinfo.value.code == -32602


def test_study_start_without_credentials_reports_error(service):
    service.dispatch("study.start", {"course_ids": ["1"]})
    status: dict = {}
    for _ in range(100):
        status = service.dispatch("study.status", {})
        if status["state"] == "error":
            break
        time.sleep(0.05)
    assert status["state"] == "error"
    assert "账号" in status["detail"] or "cookies" in status["detail"]


def test_config_set_rejects_nested_values(service):
    with pytest.raises(RpcError):
        service.dispatch("config.set", {"config": {"common": {"jobs": {"a": 1}}}})


def test_manual_answer_flow(service):
    captured: dict = {}
    done = threading.Event()

    def on_event(event):
        if event.type == "manual.question":
            captured.update(event.data)
            done.set()

    service.bus.subscribe(on_event)
    results: list = []

    def ask():
        results.append(
            service.ask_manual([{"title": "题目", "type": "single", "options": "A. 甲\nB. 乙"}])
        )

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    assert done.wait(5), "manual.question event not emitted"

    batch_id = captured["batch_id"]
    assert service.dispatch("manual.answer", {"batch_id": batch_id, "index": 0, "answer": "A"})["ok"]
    worker.join(5)
    assert results and results[0] == ["A"]


def test_manual_skip_flow(service):
    captured: dict = {}
    done = threading.Event()

    def on_event(event):
        if event.type == "manual.question":
            captured.update(event.data)
            done.set()

    service.bus.subscribe(on_event)
    results: list = []

    def ask():
        results.append(service.ask_manual([{"title": "题目", "type": "single", "options": ""}]))

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    assert done.wait(5)

    service.dispatch("manual.skip", {"batch_id": captured["batch_id"], "index": 0})
    worker.join(5)
    assert results and results[0] == [None]


def test_websocket_receives_bus_events(server, service):
    base, httpd = server
    port = httpd.server_address[1]
    key = base64.b64encode(os.urandom(16)).decode()

    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        request = (
            "GET /events HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(1024)
        assert b"101 Switching Protocols" in response
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        assert expected_accept.encode() in response

        service.dispatch("config.set", {"config": {"common": {"jobs": "3"}}})
        sock.settimeout(5)
        frame = sock.recv(4096)
        assert frame[0] & 0x0F == 0x1  # text frame
        length = frame[1] & 0x7F
        payload = json.loads(frame[2 : 2 + length].decode("utf-8"))
        assert payload["method"] == "event"
        assert payload["params"]["type"] in {"config.changed", "log"}
    finally:
        sock.close()


def test_config_set_normalizes_valid_values(service):
    result = service.dispatch("config.set", {"config": {"common": {"jobs": "99", "speed": "3"}}})
    assert result["ok"] is True
    assert result["normalized"]["common"]["jobs"] == "16"  # clamped to schema max
    assert result["normalized"]["common"]["speed"] == "2"
    stored = service.dispatch("config.get", {})["config"]["common"]
    assert stored["jobs"] == "16"
    assert stored["speed"] == "2"


def test_config_set_rejects_invalid_values_fail_closed(service):
    with pytest.raises(RpcError) as excinfo:
        service.dispatch("config.set", {"config": {"common": {"speed": "abc"}}})
    assert excinfo.value.code == -32602
    assert "speed" in excinfo.value.message
    # fail-closed: nothing was written
    stored = service.dispatch("config.get", {})["config"].get("common", {})
    assert "speed" not in stored


def test_config_set_rejects_unknown_tiku_provider(service):
    with pytest.raises(RpcError) as excinfo:
        service.dispatch("config.set", {"config": {"tiku": {"provider": "NoSuchProvider"}}})
    assert "NoSuchProvider" in excinfo.value.message


def test_config_validate_does_not_write(service):
    result = service.dispatch("config.validate", {"config": {"common": {"notopen_action": "bogus"}}})
    assert result["ok"] is False
    assert result["errors"]
    assert "notopen_action" not in service.dispatch("config.get", {})["config"].get("common", {})
