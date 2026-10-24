#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail if internal development documents are staged for commit.

The repository keeps architecture notes, ADRs, scan reports and the harness
plan in `docs/`, which is intentionally ignored. This guard catches the case
where someone force-adds them.
"""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN_PREFIXES = ("docs/", "design-system/", "plan/")
FORBIDDEN_SUFFIXES = (
    "HARNESS_ENGINEERING_PLAN.md",
    "ISSUE_BACKLOG.md",
    "SCAN_REPORT.md",
    "STATIC_BASELINE.md",
    "TEST_BASELINE.md",
)


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    bad = []
    for path in staged_files():
        if path.startswith(FORBIDDEN_PREFIXES) or path.endswith(FORBIDDEN_SUFFIXES):
            bad.append(path)
    if bad:
        print("Refusing to commit internal development documents:", file=sys.stderr)
        for path in bad:
            print(f"  - {path}", file=sys.stderr)
        print("Keep them local under docs/ (gitignored).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
