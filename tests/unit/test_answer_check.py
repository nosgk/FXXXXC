# -*- coding: utf-8 -*-
"""顿号分隔符与单选答案校验的回归测试（对齐上游 PR #631）。"""

from __future__ import annotations

from api.answer_check import check_answer, check_multiple, check_single, cut


class FakeTiku:
    is_manual = False
    skip_answer_validation = False
    true_list = ['正确', '对']
    false_list = ['错误', '错']


def test_answer_with_dunhao_not_rejected_as_multiple():
    assert check_single('坚持独立负责、不参与国际组织的活动')
    assert check_single('点面结合、标本兼治')


def test_comma_is_sentence_punctuation():
    assert check_single('对,错')
    assert check_single('对，错')


def test_strong_delimiters_still_reject():
    assert not check_single('答案1\n答案2')
    assert not check_single('答案1|答案2')
    assert not check_single('答案1#答案2')
    assert not check_single('答案1\t答案2')
    assert not check_single('答案1\r答案2')


def test_plain_answers():
    assert check_single('生态文明')
    assert not check_single(None)
    assert not check_single('   ')


def test_cut_still_splits_on_dunhao():
    assert cut('尊重自然、顺应自然、保护自然') == ['尊重自然', '顺应自然', '保护自然']
    assert check_multiple('尊重自然、顺应自然')


def test_check_answer_single_with_dunhao_passes():
    assert check_answer('坚持独立负责、不参与国际组织的活动', 'single', FakeTiku())


def test_check_answer_single_judgement_word_rejected():
    assert not check_answer('正确', 'single', FakeTiku())
