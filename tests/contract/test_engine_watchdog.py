# -*- coding: utf-8 -*-
"""进程残留回归：引擎在 GUI（父进程）消失后必须自动退出。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import fxxxxc.engine.__main__ as engine_main

ROOT = Path(__file__).resolve().parents[2]


def test_pid_alive_for_current_process():
    assert engine_main._pid_alive(os.getpid()) is True


def test_pid_alive_for_zero_disables_watchdog():
    # parent_pid<=0 必须视为存活（看门狗关闭），绝不误杀引擎
    assert engine_main._pid_alive(0) is True
    assert engine_main._pid_alive(-1) is True


def test_parent_wait_handle_never_crashes():
    # 环境差异（沙箱拒绝 SYNCHRONIZE 等）下允许返回 None，但绝不抛错；
    # 返回 None 时引擎会退级到 stdin-EOF/轮询通道。
    handle = engine_main._open_parent_wait_handle(os.getpid())
    if handle and os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.CloseHandle(handle)


def test_parent_wait_handle_for_dead_process():
    import gc

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    pid = proc.pid
    proc.kill()
    proc.wait()
    del proc
    gc.collect()
    if engine_main._pid_alive(pid):
        # pid 已被系统复用：跳过（生产路径用句柄等待，不存在该竞态）
        return
    assert engine_main._open_parent_wait_handle(pid) is None


def test_engine_exits_when_parent_dies(tmp_path: Path):
    """E2E：以一个已退出的进程为 parent-pid 启动引擎，引擎应自动退出并清理 runtime。"""
    parent = subprocess.Popen([sys.executable, "-c", "pass"])
    parent.wait()

    env = dict(os.environ)
    env["FXXXXC_DATA_DIR"] = str(tmp_path)
    env["FXXXXC_ENGINE_TOKEN"] = "watchdog-token"
    stderr_log = (tmp_path / "engine-stderr.log").open("w")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "fxxxxc.engine",
            "--port", "0", "--data-dir", str(tmp_path),
            "--parent-pid", str(parent.pid),
        ],
        env=env,
        cwd=str(ROOT),
        stdin=subprocess.PIPE,  # GUI 同款：管道 stdin
        stdout=subprocess.PIPE,
        stderr=stderr_log,
        text=True,
        encoding="utf-8",
    )
    try:
        # 引擎就绪（打印 ready 行）
        line = proc.stdout.readline()
        if not line:
            proc.wait(timeout=10)
            stderr_log.flush()
            stderr = (tmp_path / "engine-stderr.log").read_text(encoding="utf-8", errors="replace")
            msg = "engine died before ready (rc={}): {}".format(proc.returncode, stderr[-1500:])
            raise AssertionError(msg)
        assert json.loads(line)["status"] == "ready"
        runtime = tmp_path / "engine-runtime.json"
        assert runtime.exists()

        # GUI 死亡 => stdin 管道关闭 => 引擎必须自动退出并清理 runtime
        proc.stdin.close()
        code = proc.wait(timeout=15)
        assert code == 0
        assert not runtime.exists(), "引擎退出时必须清理 engine-runtime.json"
    finally:
        stderr_log.close()
        if proc.poll() is None:
            proc.kill()
