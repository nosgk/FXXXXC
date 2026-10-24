# -*- coding: utf-8 -*-
"""Allow ``python -m fxxxxc`` to run the CLI."""

from fxxxxc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
