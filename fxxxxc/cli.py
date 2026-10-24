# -*- coding: utf-8 -*-
"""Console entry point for the CLI (``python -m fxxxxc.cli`` / ``fxxxxc``)."""

from __future__ import annotations


def main() -> int:
    # main.py keeps the CLI argument surface; importing it lazily keeps
    # `python -m fxxxxc.engine` startup independent from the CLI stack.
    import main

    try:
        main.main()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
