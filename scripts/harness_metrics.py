#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness metrics for the FXXXXC repository.

This script is intentionally dependency-free so it can run in a bare Python
environment and in CI before project dependencies are installed.

Usage:
    python scripts/harness_metrics.py
    python scripts/harness_metrics.py --json
    python scripts/harness_metrics.py --markdown
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "release",
    ".dart_tool",
    ".idea",
    ".vscode",
    "node_modules",
}

BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler, ast.BoolOp, ast.Match)


@dataclass
class FunctionMetric:
    name: str
    line: int
    length: int
    branches: int


@dataclass
class FileMetric:
    path: str
    lines: int
    code_lines: int
    functions: int
    classes: int
    longest_function: FunctionMetric | None
    imports: list[str] = field(default_factory=list)


@dataclass
class Metrics:
    root: str
    python_files: int = 0
    python_lines: int = 0
    python_code_lines: int = 0
    functions: int = 0
    classes: int = 0
    test_files: int = 0
    test_functions: int = 0
    test_lines: int = 0
    duplicate_blocks: int = 0
    files: list[FileMetric] = field(default_factory=list)
    top_functions: list[FunctionMetric] = field(default_factory=list)
    import_edges: list[tuple[str, str]] = field(default_factory=list)
    test_ratio: float = 0.0


def iter_python_files(root: pathlib.Path) -> Iterable[pathlib.Path]:
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def is_test_file(path: pathlib.Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def count_code_lines(source: str) -> int:
    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def imports_for(tree: ast.AST) -> list[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split(".")[0])
    return sorted(result)


def function_metrics(tree: ast.AST) -> list[FunctionMetric]:
    result: list[FunctionMetric] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        branches = sum(1 for child in ast.walk(node) if isinstance(child, BRANCH_NODES))
        result.append(
            FunctionMetric(
                name=node.name,
                line=node.lineno,
                length=end - node.lineno + 1,
                branches=branches,
            )
        )
    return result


def duplicate_block_count(files: list[pathlib.Path], window: int = 6) -> int:
    """Count normalized windows that appear in more than one location.

    This is a heuristic, not a clone detector. It is useful as a trend metric.
    """
    blocks: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        normalized = [line.strip() for line in lines]
        for index in range(0, max(0, len(normalized) - window + 1)):
            chunk = tuple(
                line
                for line in normalized[index : index + window]
                if line and not line.startswith("#")
            )
            if len(chunk) >= window - 1:
                blocks[chunk].append((str(path), index + 1))
    return sum(1 for locations in blocks.values() if len(locations) > 1)


def collect(root: pathlib.Path) -> Metrics:
    metrics = Metrics(root=str(root))
    files = list(iter_python_files(root))
    metrics.python_files = len(files)

    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"warning: cannot parse {path}: {exc}", file=sys.stderr)
            continue

        functions = function_metrics(tree)
        classes = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
        longest = max(functions, key=lambda item: (item.length, item.branches), default=None)
        relative = str(path.relative_to(root)).replace("\\", "/")
        file_metric = FileMetric(
            path=relative,
            lines=source.count("\n") + 1,
            code_lines=count_code_lines(source),
            functions=len(functions),
            classes=classes,
            longest_function=longest,
            imports=imports_for(tree),
        )
        metrics.files.append(file_metric)
        metrics.python_lines += file_metric.lines
        metrics.python_code_lines += file_metric.code_lines
        metrics.functions += file_metric.functions
        metrics.classes += file_metric.classes
        metrics.top_functions.extend(functions)

        if is_test_file(path):
            metrics.test_files += 1
            metrics.test_lines += file_metric.lines
            metrics.test_functions += sum(
                1 for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )

    metrics.top_functions.sort(key=lambda item: (item.length, item.branches), reverse=True)
    metrics.top_functions = metrics.top_functions[:20]
    metrics.duplicate_blocks = duplicate_block_count(files)
    if metrics.python_lines:
        metrics.test_ratio = round(metrics.test_lines / metrics.python_lines, 4)

    module_names = {
        path.stem
        for path in files
    }
    for path in files:
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        source_name = path.stem
        for imported in imports_for(tree):
            if imported in module_names:
                metrics.import_edges.append((source_name, imported))

    metrics.files.sort(key=lambda item: item.lines, reverse=True)
    return metrics


def render_markdown(metrics: Metrics) -> str:
    lines = [
        "# Harness Metrics",
        "",
        f"Root: `{metrics.root}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Python files | {metrics.python_files} |",
        f"| Python lines | {metrics.python_lines} |",
        f"| Python code lines | {metrics.python_code_lines} |",
        f"| Functions | {metrics.functions} |",
        f"| Classes | {metrics.classes} |",
        f"| Test files | {metrics.test_files} |",
        f"| Test functions | {metrics.test_functions} |",
        f"| Test lines | {metrics.test_lines} |",
        f"| Test ratio | {metrics.test_ratio:.2%} |",
        f"| Duplicate 6-line blocks | {metrics.duplicate_blocks} |",
        "",
        "## Largest files",
        "",
        "| File | Lines | Code | Functions | Classes | Longest function |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in metrics.files[:15]:
        longest = item.longest_function
        longest_text = (
            f"`{longest.name}` ({longest.length} lines, {longest.branches} branches)"
            if longest else "—"
        )
        lines.append(
            f"| `{item.path}` | {item.lines} | {item.code_lines} | {item.functions} | {item.classes} | {longest_text} |"
        )

    lines.extend(["", "## Top functions by length", "", "| Function | Lines | Branches |", "|---|---:|---:|"])
    for item in metrics.top_functions[:15]:
        lines.append(f"| `{item.name}` | {item.length} | {item.branches} |")

    lines.extend(["", "## Import edges", ""])
    if metrics.import_edges:
        for source, target in metrics.import_edges:
            lines.append(f"- `{source}` → `{target}`")
    else:
        lines.append("_No internal import edges detected._")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent)
    parser.add_argument("--json", action="store_true", help="print JSON instead of a summary")
    parser.add_argument("--markdown", action="store_true", help="print Markdown instead of a summary")
    args = parser.parse_args()

    root = args.root.resolve()
    metrics = collect(root)

    if args.json:
        print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
        return 0
    if args.markdown:
        print(render_markdown(metrics))
        return 0

    print(f"root: {metrics.root}")
    print(f"python files: {metrics.python_files}")
    print(f"python lines: {metrics.python_lines} ({metrics.python_code_lines} code)")
    print(f"functions: {metrics.functions}, classes: {metrics.classes}")
    print(f"tests: {metrics.test_files} files, {metrics.test_functions} tests, {metrics.test_lines} lines "
          f"({metrics.test_ratio:.2%})")
    print(f"duplicate 6-line blocks: {metrics.duplicate_blocks}")
    print("largest files:")
    for item in metrics.files[:8]:
        print(f"  {item.lines:5}  {item.path}")
    print("longest functions:")
    for item in metrics.top_functions[:8]:
        print(f"  {item.length:4} lines / {item.branches:3} branches  {item.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
