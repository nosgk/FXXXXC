# -*- coding: utf-8 -*-
"""媒体代理（/media）、tiku.ocs.fetch 与枚举留空的回归测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from fxxxxc.engine import server as server_mod
from fxxxxc.engine.protocol import RpcError
from fxxxxc.engine.service import EngineService, validate_config_value


class _FakeResp:
    def __init__(self, content=b"img", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "image/png"}


@pytest.fixture(autouse=True)
def _clear_media_cache():
    server_mod._MEDIA_CACHE.clear()
    yield
    server_mod._MEDIA_CACHE.clear()


class TestMediaProxy:
    def test_allowed_host_fetched_with_referer(self):
        url = "https://p.ananas.chaoxing.com/star3/240_130c/abc.png"
        with patch("requests.get",
                          return_value=_FakeResp()) as mock_get:
            status, body, ctype = server_mod.fetch_media(url)
        assert status == 200 and body == b"img" and ctype == "image/png"
        assert mock_get.call_args.kwargs["headers"]["Referer"].startswith(
            "https://mooc2-ans.chaoxing.com")

    def test_disallowed_host_rejected_without_request(self):
        with patch("requests.get") as mock_get:
            status, _, _ = server_mod.fetch_media("https://evil.example.com/x.png")
        assert status == 403
        mock_get.assert_not_called()

    def test_cache_hit_avoids_second_fetch(self):
        url = "http://p.ananas.chaoxing.com/star3/240_130c/a.jpg"
        with patch("requests.get",
                          return_value=_FakeResp()) as mock_get:
            server_mod.fetch_media(url)
            server_mod.fetch_media(url)
        assert mock_get.call_count == 1

    def test_upstream_failure_maps_to_502(self):
        with patch("requests.get",
                          side_effect=requests.exceptions.ConnectTimeout("down")):
            assert server_mod.fetch_media(
                "https://p.ananas.chaoxing.com/x.png")[0] == 502


class TestOcsFetchRpc:
    def _service(self, tmp_path):
        return EngineService(data_dir=tmp_path)

    def test_fetch_parses_wrappers_json(self, tmp_path):
        payload = '[{"name":"t","url":"https://x/q?kw=${title}"}]'
        resp = MagicMock(status_code=200, text=payload)
        with patch("requests.get", return_value=resp):
            result = self._service(tmp_path).tiku_ocs_fetch(
                {"url": "https://bank.example/config"})
        assert result["ok"] is True
        assert result["count"] == 1
        assert "${title}" in result["wrappers"]

    def test_fetch_extracts_json_from_explanatory_text(self, tmp_path):
        payload = '欢迎使用某题库，配置如下：\n[{"name":"t","url":"https://x/q"}]\n祝使用愉快'
        resp = MagicMock(status_code=200, text=payload)
        with patch("requests.get", return_value=resp):
            result = self._service(tmp_path).tiku_ocs_fetch({"url": "https://x"})
        assert result["count"] == 1

    def test_fetch_rejects_non_json(self, tmp_path):
        resp = MagicMock(status_code=200, text="<html>hello</html>")
        with patch("requests.get", return_value=resp):
            with pytest.raises(RpcError):
                self._service(tmp_path).tiku_ocs_fetch({"url": "https://x"})

    def test_fetch_requires_http_url(self, tmp_path):
        with pytest.raises(RpcError):
            self._service(tmp_path).tiku_ocs_fetch({"url": "ftp://x"})


class TestEnumEmptyOption:
    def test_enum_blank_is_valid(self):
        for section, key in (("common", "notopen_action"),
                             ("tiku", "manual_mode_default")):
            normalized, error = validate_config_value(section, key, "  ")
            assert error is None
            assert normalized == ""

    def test_separator_blank_falls_back_to_default(self):
        normalized, error = validate_config_value("tiku", "manual_mode_separator", "")
        assert error is None
        assert normalized == ";"

    def test_invalid_enum_still_reports(self):
        _, error = validate_config_value("common", "notopen_action", "nope")
        assert error

    def test_config_set_persists_blank_enum(self, tmp_path):
        service = EngineService(data_dir=tmp_path)
        service.config_set({"config": {"common": {"notopen_action": ""}}})
        assert service._read_config()["common"]["notopen_action"] == ""
        # 留空后运行时回退默认 retry
        assert service._common_config()["notopen_action"] == "retry"
