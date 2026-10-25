# -*- coding: utf-8 -*-
"""Answer normalization, option matching and work-record parsing."""

from __future__ import annotations

import random
import re
from difflib import SequenceMatcher

from loguru import logger

from api.answer_check import cut


def multi_cut(answer: str, origin_html_content: str = "", logger=logger):
    """Split a multi-choice answer and warn when extraction fails."""
    res = cut(answer)
    if res is None:
        logger.warning(
            f"未能从网页中提取题目信息, 以下为相关信息：\n\t{answer}\n\n{origin_html_content}\n"
        )
        logger.warning("未能正确提取题目选项信息! 请反馈并提供以上信息")
        return None
    return res


def clean_res(res):
    cleaned_res = []
    if isinstance(res, str):
        res = [res]
    for item in res:
        cleaned = (
            re.sub(r"^[A-Za-z]\s*[.、:：)?）]?\s*|[.,!?;:，。！？；：]", "", item)
            if len(item) > 1
            else item
        )
        cleaned_res.append(cleaned.strip())
    return cleaned_res


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    char_map = str.maketrans(
        {
            "⻛": "风",
            "⻔": "门",
            "⻋": "车",
            "⻢": "马",
        }
    )
    normalized = text.translate(char_map)
    normalized = re.sub(r"^[A-Za-z]\s*[.、:：)?）]?\s*", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r'[，。！？；：,.!?;:()（）\[\]【】"“”‘’\-_/\\|]', "", normalized)
    return normalized.lower()


def get_option_text(option: str) -> str:
    return re.sub(r"^[A-Za-z]\s*[.、:：)?）]?\s*", "", option).strip()


def best_option_by_similarity(target: str, options: list, threshold: float = 0.8) -> str:
    if not target or not options:
        return ""
    target_norm = normalize_text(target)
    if not target_norm:
        return ""

    best_letter = ""
    best_score = 0.0
    for option in options:
        option_text = get_option_text(option)
        option_norm = normalize_text(option_text)
        if not option_norm:
            continue
        score = SequenceMatcher(None, target_norm, option_norm).ratio()
        if score > best_score:
            best_score = score
            best_letter = option[:1]

    if best_score >= threshold:
        logger.info(
            f"相似度兜底匹配成功: {best_letter} (score={best_score:.2f}, threshold={threshold:.2f})"
        )
        return best_letter
    return ""


# 仅保留中/日/韩文字符与字母数字，用于容错全等比对（ocsjs AnswerUtil 的
# “只保留中文数字英文”清洗策略）。
_BARE_TEXT_RE = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af]+")


def _bare_text(text: str) -> str:
    return _BARE_TEXT_RE.sub("", text or "")


def match_option_letter(target, options, threshold: float = 0.8) -> str:
    """ocsjs AnswerUtil 式选项字母匹配，逐级放宽：

    1. 原文全等；
    2. 归一化全等（去空白/标点/全半角差异）；
    3. 仅保留中英日韩数字后全等（容忍缺失标点、大小写差异）；
    4. 子序列匹配（答案字符按序出现在选项中）；
    5. 相似度兜底（SequenceMatcher）。

    命中返回选项字母（选项首字符），未命中返回空串。
    """
    if target is None or not options:
        return ""
    target_text = str(target).strip()
    if not target_text:
        return ""
    target_norm = normalize_text(target_text)
    target_bare = _bare_text(target_norm)

    for option in options:
        if get_option_text(option) == target_text:
            return str(option)[:1]
    if target_norm:
        for option in options:
            if normalize_text(get_option_text(option)) == target_norm:
                return str(option)[:1]
    if target_bare:
        for option in options:
            if _bare_text(normalize_text(get_option_text(option))) == target_bare:
                return str(option)[:1]
    if target_norm:
        for option in options:
            if is_subsequence(target_norm, get_option_text(option)):
                return str(option)[:1]
    return best_option_by_similarity(target_text, options, threshold)


def is_subsequence(a, o):
    iter_o = iter(o.lower())
    return all(c in iter_o for c in a.lower())


def random_answer(options: str, q_type: str) -> str:
    answer = ""
    if not options:
        return answer

    if isinstance(options, list):
        options = "\n".join(str(item) for item in options)
    elif not isinstance(options, str):
        options = str(options)

    if q_type == "multiple":
        logger.debug(f"当前选项列表[cut前] -> {options}")
        option_list = multi_cut(options)
        logger.debug(f"当前选项列表[cut后] -> {option_list}")

        if not option_list:
            logger.error("选项为空, 未能正确提取题目选项信息! 请反馈并提供以上信息")
            return answer

        available_options = len(option_list)
        select_count = 0

        if available_options <= 1:
            select_count = available_options
        else:
            max_possible = min(4, available_options)
            min_possible = min(2, available_options)

            weights_map = {
                2: [1.0],
                3: [0.3, 0.7],
                4: [0.1, 0.5, 0.4],
                5: [0.1, 0.4, 0.3, 0.2],
            }

            weights = weights_map.get(max_possible, [0.3, 0.4, 0.3])
            possible_counts = list(range(min_possible, max_possible + 1))
            weights = weights[: len(possible_counts)]

            weights_sum = sum(weights)
            if weights_sum > 0:
                weights = [w / weights_sum for w in weights]

            select_count = random.choices(possible_counts, weights=weights, k=1)[0]

        selected_options = random.sample(option_list, select_count) if select_count > 0 else []
        for option in selected_options:
            answer += option[:1]
        answer = "".join(sorted(answer))
    elif q_type == "single":
        answer = random.choice(options.split("\n"))[:1]
    elif q_type == "judgement":
        answer = "true" if random.choice([True, False]) else "false"
    logger.info(f"随机选择 -> {answer}")
    return answer


def _parse_work_record_list(html_text: str) -> list[tuple[int, float]]:
    """Parse the work record list page into ``(times, score)`` tuples."""
    records = []
    times_list = re.findall(r'viewNum">第(\d+)次', html_text)
    scores = re.findall(r'viewScore">([\d.]+)分', html_text)
    if len(times_list) != len(scores):
        logger.warning(f"作答记录次数/成绩数量不匹配({len(times_list)}/{len(scores)}), 成绩按0处理")
        scores = ["0"] * len(times_list)
    for times, score in zip(times_list, scores):
        try:
            records.append((int(times), float(score)))
        except ValueError:
            continue
    return records


def _parse_work_record_detail(html_text: str) -> list[dict]:
    """Parse the work record detail page into per-question dicts."""
    questions = []
    for match in re.finditer(
        r'<div class="TiMu[^"]*singleQuesId" data="(\d+)"[^>]*>(.*?)(?=<div class="TiMu|$)',
        html_text,
        re.S,
    ):
        question_id = match.group(1)
        block = match.group(2)

        title_match = re.search(r'newZy_TItle">(.*?)</span>(.*?)</div>', block, re.S)
        if title_match:
            type_label = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
            title = re.sub(r"<[^>]+>", "", title_match.group(2))
        else:
            type_label = ""
            title = ""
        title = re.sub(r"\s+", " ", title).strip()

        answer_patterns = [
            r"{label}[:：]</span>\s*<div class=\"fl answerCon\">\s*(.*?)\s*</div>",
            r"{label}[:：]\s*</span>\s*<div[^>]*class=\"[^\"]*answerCon[^\"]*\"[^>]*>\s*(.*?)\s*</div>",
            r"{label}[:：]\s*</span>\s*<span[^>]*>\s*(.*?)\s*</span>",
        ]

        def extract_answer(label):
            for pattern in answer_patterns:
                found = re.search(pattern.format(label=label), block, re.S)
                if found:
                    return re.sub(r"<[^>]+>", "", found.group(1)).strip()
            return None

        my_raw = extract_answer("我的答案")
        correct_raw = extract_answer("正确答案")

        questions.append(
            {
                "id": question_id,
                "title": title,
                "type_label": type_label,
                "my_answer": my_raw or "",
                "correct_answer": correct_raw or "",
                "parse_ok": my_raw is not None and correct_raw is not None,
            }
        )
    return questions


_JUDGE_TRUE_SET = {"TRUE", "T", "1", "对", "正确", "√", "是", "YES", "Y"}
_JUDGE_FALSE_SET = {"FALSE", "F", "0", "错", "错误", "×", "X", "否", "NO", "N", "不对", "不正确"}


def normalize_answer_text(ans) -> str:
    """Normalize an answer for comparison across page formats."""
    s = re.sub(r"\s+", "", str(ans or "")).upper()
    if s in _JUDGE_TRUE_SET:
        return "TRUE"
    if s in _JUDGE_FALSE_SET:
        return "FALSE"
    if re.fullmatch(r"[A-Z0-9]+", s):
        return s
    s = re.sub(r"^[A-Z][.、:：)?）]", "", s)
    s = re.sub(r'[，。、！？；：,.!?;:()（）\[\]【】"“”‘’\-_/\\|]', "", s)
    return s
