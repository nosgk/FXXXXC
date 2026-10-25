# -*- coding: utf-8 -*-
"""题库实例（tiku_bank.*）配置与梯度回退链的契约测试。"""

from __future__ import annotations

import pytest

from api.answer import TikuFallback, TikuYanxi
from fxxxxc.engine.service import EngineService, validate_config_value


@pytest.fixture
def service(tmp_path):
    return EngineService(data_dir=tmp_path)


def _write_banks(service, banks: dict[str, dict[str, str]], tiku: dict[str, str] | None = None):
    patch: dict[str, dict[str, str]] = {}
    if tiku:
        patch['tiku'] = tiku
    for section, items in banks.items():
        patch[section] = items
    service.config_set({'config': patch})


class TestBankValidation:
    def test_bank_section_accepts_provider_and_keys(self):
        normalized, errors = validate_config_value(
            'tiku_bank.a1', 'provider', 'TikuYanxi')
        assert errors is None
        assert normalized == 'TikuYanxi'

    def test_bank_enabled_normalizes(self):
        normalized, errors = validate_config_value('tiku_bank.a1', 'enabled', 'TRUE')
        assert errors is None
        assert normalized == 'true'

    def test_bank_priority_normalized(self):
        normalized, errors = validate_config_value('tiku_bank.a1', 'priority', ' 2 ')
        assert errors is None
        assert normalized == '2'

    def test_bank_invalid_priority_reports_error(self):
        _, errors = validate_config_value('tiku_bank.a1', 'priority', 'abc')
        assert errors

    def test_bank_provider_validated_against_registry(self):
        _, errors = validate_config_value('tiku_bank.a1', 'provider', 'NoSuchBank')
        assert errors


class TestBankInstances:
    def test_missing_banks_falls_back_to_legacy(self, service):
        _write_banks(service, {}, tiku={'provider': 'TikuYanxi', 'tokens': 'T1'})
        tiku = service._build_tiku()
        assert isinstance(tiku, TikuYanxi)

    def test_banks_build_fallback_chain_in_priority_order(self, service):
        _write_banks(service, {
            'tiku_bank.second': {'enabled': 'true', 'priority': '1',
                                 'provider': 'TikuYanxi', 'tokens': 'T2'},
            'tiku_bank.first': {'enabled': 'true', 'priority': '0',
                                'provider': 'TikuYanxi', 'tokens': 'T1'},
        })
        tiku = service._build_tiku()
        assert isinstance(tiku, TikuFallback)
        assert [p._conf['tokens'] for p in tiku.providers] == ['T1', 'T2']

    def test_disabled_bank_excluded(self, service):
        _write_banks(service, {
            'tiku_bank.off': {'enabled': 'false', 'provider': 'TikuYanxi', 'tokens': 'TX'},
            'tiku_bank.on': {'enabled': 'true', 'priority': '0',
                             'provider': 'TikuYanxi', 'tokens': 'T1'},
        })
        tiku = service._build_tiku()
        # 只剩一个可用实例 → 直接是单题库而非回退链
        assert isinstance(tiku, TikuYanxi)
        assert tiku._conf['tokens'] == 'T1'

    def test_bank_conf_overrides_global(self, service):
        _write_banks(
            service,
            {'tiku_bank.a': {'enabled': 'true', 'provider': 'TikuYanxi', 'tokens': 'BANK_TOKEN'}},
            tiku={'tokens': 'GLOBAL_TOKEN', 'delay': '2'},
        )
        tiku = service._build_tiku()
        assert tiku._conf['tokens'] == 'BANK_TOKEN'
        # 全局键仍然透传给实例
        assert tiku._conf['delay'] == '2'

    def test_all_disabled_raises(self, service):
        _write_banks(service, {
            'tiku_bank.off': {'enabled': 'false', 'provider': 'TikuYanxi', 'tokens': 'T'},
        })
        with pytest.raises(Exception):
            service._build_tiku()


class TestBankRpc:
    def test_config_remove_only_allows_bank_sections(self, service):
        with pytest.raises(Exception):
            service.config_remove({'sections': ['common']})
        _write_banks(service, {
            'tiku_bank.tmp': {'enabled': 'true', 'provider': 'TikuYanxi', 'tokens': 'T1'},
        })
        result = service.config_remove({'sections': ['tiku_bank.tmp']})
        assert result['removed'] == ['tiku_bank.tmp']
        assert service._bank_instances() == []

    def test_tiku_test_reports_per_bank(self, service):
        _write_banks(service, {
            'tiku_bank.a': {'enabled': 'true', 'priority': '0',
                            'provider': 'TikuYanxi', 'tokens': 'T1'},
            'tiku_bank.b': {'enabled': 'true', 'priority': '1',
                            'provider': 'TikuYanxi', 'tokens': 'T2'},
        })
        result = service.tiku_test()
        assert result['ok'] is True
        assert len(result['banks']) == 2
        assert all(bank['ok'] for bank in result['banks'])
