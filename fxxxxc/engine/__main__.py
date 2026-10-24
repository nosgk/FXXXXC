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
    parser.add_argument("--version", action="store_true", help="print version and exit")
    return parser


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
