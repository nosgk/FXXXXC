# -*- coding: utf-8 -*-
"""Tests for fxxxxc config/events/cancellation/paths helpers."""

from __future__ import annotations

import threading

from fxxxxc import cancellation, config, events, paths


def test_ini_round_trip(tmp_path):
    target = tmp_path / "nested" / "config.ini"
    config.save_ini(target, {"common": {"jobs": "4", "speed": 1.5}, "tiku": {"provider": "AI"}})
    data = config.load_ini(target)
    assert data["common"]["jobs"] == "4"
    assert data["common"]["speed"] == "1.5"
    assert data["tiku"]["provider"] == "AI"


def test_load_missing_ini_returns_empty(tmp_path):
    assert config.load_ini(tmp_path / "missing.ini") == {}


def test_event_bus_fans_out_and_replays():
    bus = events.EventBus(replay=2)
    seen: list[str] = []
    bus.emit("a", {"x": 1})
    bus.emit("b", {"y": 2})
    bus.subscribe(seen.append)
    bus.emit("c", {"z": 3})
    # replay=2 keeps the last two events, so the new subscriber sees a and b
    # before receiving live event c.
    assert [event.type for event in seen] == ["a", "b", "c"]
    assert bus.recent(1)[0].type == "c"


def test_event_bus_swallows_listener_errors():
    bus = events.EventBus()

    def broken(event):
        raise RuntimeError("boom")

    seen: list[str] = []
    bus.subscribe(broken)
    bus.subscribe(seen.append)
    event = bus.emit("t", {})
    assert seen == [event]


def test_cancellation_token_sleep_returns_early():
    token = cancellation.CancellationToken()
    threading.Timer(0.05, token.cancel).start()
    assert token.wait(5) is True
    assert token.is_cancelled() is True


def test_pause_token_wait_respects_cancellation():
    pause = cancellation.PauseToken()
    token = cancellation.CancellationToken()
    pause.pause()
    threading.Timer(0.05, token.cancel).start()
    pause.wait_if_paused(token)
    assert token.is_cancelled() is True


def test_paths_helpers(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.get_data_dir() == tmp_path.resolve()

    resolved = paths.set_data_dir(tmp_path / "data")
    assert resolved == (tmp_path / "data").resolve()
    assert paths.config_path().parent == resolved

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert paths.app_data_dir() == tmp_path / "appdata" / paths.APP_NAME
    assert paths.local_app_data_dir() == tmp_path / "appdata" / paths.APP_NAME

    assert (paths.resource_root() / "resource").exists()
    assert paths.resource_path("resource/font_map_table.json").exists()
