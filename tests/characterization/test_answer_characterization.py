# -*- coding: utf-8 -*-
"""Characterization tests for answer normalization and validation."""

from __future__ import annotations

from api.answer_check import check_answer, check_judgement, check_multiple, check_single, cut
from api.base import _parse_work_record_list, normalize_answer_text


class _TikuStub:
    true_list = ["正确", "对", "√", "是"]
    false_list = ["错误", "错", "×", "否", "不对", "不正确"]


def test_cut_splits_on_first_available_delimiter():
    assert cut("A、B、C") == ["A", "B", "C"]
    assert cut("A,B,C") == ["A", "B", "C"]
    assert cut("A B C") == ["A", "B", "C"]
    assert cut("") is None
    assert cut(None) is None


def test_check_single_rejects_strong_delimiters():
    assert check_single("A") is True
    assert check_single("A. 文本") is True
    # 顿号是句内标点，不再视为多选分隔符（上游 PR #631）；
    # 多选切分仍由 cut() 使用顿号。
    assert check_single("A、B") is True
    assert check_single("坚持独立负责、不参与国际组织的活动") is True
    assert check_single("A\nB") is False


def test_check_multiple_uses_cut():
    assert check_multiple("A、B") is True
    assert check_multiple("A") is True
    assert check_multiple("") is False


def test_check_judgement_aliases():
    stub = _TikuStub()
    assert check_judgement("对", stub.true_list, stub.false_list) == 1
    assert check_judgement("错误", stub.true_list, stub.false_list) == 0
    assert check_judgement("maybe", stub.true_list, stub.false_list) == -1


def test_check_answer_type_rules():
    stub = _TikuStub()
    assert check_answer("A", "single", stub) is True
    # 顿号答案不再被误判为多选（上游 PR #631）
    assert check_answer("A、B", "single", stub) is True
    assert check_answer("A\nB", "single", stub) is False
    assert check_answer("A、B", "multiple", stub) is True
    assert check_answer("正确", "judgement", stub) is True
    assert check_answer("maybe", "judgement", stub) is False
    assert check_answer("填空", "completion", stub) is True


def test_normalize_answer_text_stability():
    assert normalize_answer_text("B. 按 ESC 键") == normalize_answer_text("按ESC键")
    assert normalize_answer_text("对") == "TRUE"
    assert normalize_answer_text("错误") == "FALSE"
    # Current behavior: the leading "A、" is treated as an option prefix, so the
    # normalized value is "BC". Cross-format differences are handled by the
    # full-score fallback in study_work; this test pins the existing behavior.
    assert normalize_answer_text("A、B、C") == "BC"


def test_parse_work_record_list():
    records = _parse_work_record_list(
        '<span class="viewNum">第1次</span><span class="viewScore">80.0分</span>'
        '<span class="viewNum">第2次</span><span class="viewScore">100分</span>'
    )
    assert records == [(1, 80.0), (2, 100.0)]


def test_parse_work_record_list_mismatch_does_not_zip_shift():
    records = _parse_work_record_list(
        '<span class="viewNum">第1次</span><span class="viewScore">80.0分</span>'
        '<span class="viewNum">第2次</span>'
    )
    assert records == [(1, 0.0), (2, 0.0)]
