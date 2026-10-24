# -*- coding: utf-8 -*-
"""Desktop engine entry point.

Example:
    FXXXXC_ENGINE_TOKEN=secret python -m fxxxxc.engine \
        --host 127.0.0.1 --port 0 --data-dir "%APPDATA%/FXXXXC"
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import sys
import threading
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fxxxxc-engine", description="FXXXXC desktop engine")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (loopback only)")
    parser.add_argument("--port", type=int, default=0, help="bind port; 0 picks a free port")
    parser.add_argument("--data-dir", default=None, help="data directory for config/cookies/logs")
    parser.add_argument(
        "--token-env",
        default="FXXXXC_ENGINE_TOKEN",
        help="environment variable that carries the bearer token",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=0,
        help="exit automatically when this pid dies (GUI watchdog)",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    return parser


def _pid_alive_windows(pid: int) -> bool:
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_INVALID_PARAMETER = 87
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    # A pid that never existed / was fully closed reports invalid parameter;
    # access denied means the process exists but is protected.
    return kernel32.GetLastError() != ERROR_INVALID_PARAMETER


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        if os.name == "nt":
            return _pid_alive_windows(pid)
        return _pid_alive_posix(pid)
    except Exception:
        # Watchdog must never take the engine down on its own errors.
        return True


def _open_parent_wait_handle(pid: int):
    """Open a SYNCHRONIZE handle to the parent.

    Holding this handle removes the Windows pid-reuse race: pids are recycled
    aggressively after a process exits, so polling OpenProcess(pid) can see an
    unrelated newcomer. Waiting on the handle fires exactly when the parent
    dies, regardless of reuse.
    """
    if os.name != "nt" or pid <= 0:
        return None
    try:
        import ctypes

        SYNCHRONIZE = 0x00200000
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        return handle or None
    except Exception:
        return None


def _watch_stdin(stop: threading.Event, request_stop) -> None:  # noqa: ANN001
    """Exit when the GUI's stdin pipe closes.

    The desktop GUI always pipes stdin. When it dies, the pipe breaks and
    ``read`` returns — no permissions or pid-reuse caveats involved.
    Interactive terminal runs are detected and skipped.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return
    except Exception:
        return
    try:
        sys.stdin.read(1)
    except Exception:
        return
    if not stop.is_set():
        print(json.dumps({"status": "stdin-eof", "pid": os.getpid()}), flush=True)
        request_stop(None, None)


def _watch_parent(parent_pid: int, stop: threading.Event, request_stop) -> None:  # noqa: ANN001
    handle = _open_parent_wait_handle(parent_pid)
    if handle is None and not _pid_alive(parent_pid):
        # Parent already gone before we could watch it.
        request_stop(None, None)
        return
    kernel32 = None
    if handle is not None:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    while not stop.is_set():
        if handle is not None:
            # WAIT_OBJECT_0 (0) == parent died
            if kernel32.WaitForSingleObject(handle, 2000) == 0:
                break
        else:
            if not _pid_alive(parent_pid):
                break
            stop.wait(2.0)
    if handle is not None:
        kernel32.CloseHandle(handle)
    if not stop.is_set():
        print(
            json.dumps({"status": "parent-gone", "pid": os.getpid()}),
            flush=True,
        )
        request_stop(None, None)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    import fxxxxc

    if args.version:
        print(f"fxxxxc-engine {fxxxxc.__version__}")
        return 0

    if not args.host.startswith("127."):
        print("engine refuses to bind a non-loopback address", file=sys.stderr)
        return 2

    if args.data_dir:
        from fxxxxc.paths import set_data_dir

        set_data_dir(args.data_dir)

    token = os.environ.get(args.token_env, "")
    if not token:
        token = secrets.token_urlsafe(32)
        os.environ[args.token_env] = token

    # Import after the data dir is configured so api.config resolves paths.
    from fxxxxc.engine.server import create_server
    from fxxxxc.engine.service import EngineService
    from fxxxxc.paths import get_data_dir

    service = EngineService(data_dir=get_data_dir())
    server = create_server(args.host, args.port, service, token)
    port = server.server_address[1]

    runtime_path = Path(service.data_dir) / "engine-runtime.json"
    runtime_path.write_text(
        json.dumps({"port": port, "pid": os.getpid(), "version": fxxxxc.__version__}),
        encoding="utf-8",
    )

    stop = threading.Event()

    def request_stop(signum, frame):  # noqa: ANN001 - signal handler
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    if args.parent_pid > 0:
        threading.Thread(
            target=_watch_parent,
            args=(args.parent_pid, stop, request_stop),
            daemon=True,
            name="parent-watchdog",
        ).start()

    # stdin EOF is the primary crash-net: the GUI pipes our stdin, so a dead
    # GUI closes the pipe even if taskkill/signals never fire.
    threading.Thread(
        target=_watch_stdin,
        args=(stop, request_stop),
        daemon=True,
        name="stdin-watchdog",
    ).start()

    print(
        json.dumps({"status": "ready", "port": port, "pid": os.getpid(), "data_dir": str(service.data_dir)}),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.broadcast_shutdown()
        server.server_close()
        service.study_stop()
        service.close()
        try:
            runtime_path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
