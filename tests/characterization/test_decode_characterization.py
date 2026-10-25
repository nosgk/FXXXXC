# -*- coding: utf-8 -*-
"""Characterization tests for the HTML parsers.

These tests pin the current public output shape before the module split. They
are intentionally written against fixtures, not the live Chaoxing service.
"""

from __future__ import annotations

from tests.conftest import fixture_text

from api.decode import (
    decode_course_card,
    decode_course_list,
    decode_course_point,
    decode_questions_info,
)


def test_decode_course_list_keeps_not_open_courses_flagged():
    """未开放课程保留并打 notOpen 标记（课程详细状态展示需要），不再静默丢弃。"""
    courses = decode_course_list(fixture_text("html/course_list.html"))

    assert [course["courseId"] for course in courses] == ["course-1", "course-2", "course-3"]
    assert courses[0]["clazzId"] == "clazz-1"
    assert courses[0]["cpi"] == "12345"
    assert courses[0]["title"] == "测试课程一"
    assert courses[0]["teacher"] == "张老师"
    assert courses[1]["desc"] == ""
    assert courses[2]["notOpen"] is True
    assert courses[2]["cpi"] == "1"
    # 无封面条目的 cover 为空字符串，GUI 自行回退占位图
    assert courses[0]["cover"] == ""


def test_decode_course_list_supports_new_space_li_markup():
    """新版空间（mooc1-1 interaction）的 li.course 结构也要能解析。"""
    html = """
    <ul class="course-list" id="courseList">
      <li class="course clearfix" courseid="266406962" clazzid="155239611" personid="504500535"
          id="course_266406962_155239611">
        <div class="course-cover">
          <a href="https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=266406962&amp;clazzid=155239611&amp;vc=1&amp;cpi=504500535&amp;ismooc2=1&amp;v=2">
            <img src="https://p.ananas.chaoxing.com/star3/240_130c/714d16b02f9b7012ac80c5daafabc4ba.png">
          </a>
        </div>
        <div class="course-info">
          <h3 class="inlineBlock">
            <a class="color1" href="https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=266406962&amp;clazzid=155239611&amp;vc=1&amp;cpi=504500535&amp;ismooc2=1&amp;v=2">
              <span class="course-name overHidden2" title="就业指导（第6次开课）">就业指导（第6次开课）</span>
            </a>
          </h3>
          <p class="line2" title="李心婳">李心婳</p>
        </div>
      </li>
    </ul>
    """
    courses = decode_course_list(html)

    assert len(courses) == 1
    course = courses[0]
    assert course["courseId"] == "266406962"
    assert course["clazzId"] == "155239611"
    assert course["cpi"] == "504500535"
    assert course["title"] == "就业指导（第6次开课）"
    assert course["teacher"] == "李心婳"
    assert course["cover"] == "https://p.ananas.chaoxing.com/star3/240_130c/714d16b02f9b7012ac80c5daafabc4ba.png"
    assert course["notOpen"] is False


def test_decode_course_point_preserves_flags():
    result = decode_course_point(fixture_text("html/chapter_list.html"))

    assert result["hasLocked"] is True
    assert [point["id"] for point in result["points"]] == ["101", "102", "103", "104"]
    assert result["points"][0]["jobCount"] == "2"
    assert result["points"][1]["has_finished"] is True
    assert result["points"][2]["need_unlock"] is True
    assert result["points"][3]["has_finished"] is False


def test_decode_course_card_mixed_attachments():
    jobs, info = decode_course_card(fixture_text("html/cards_mixed.html"))

    assert info["ktoken"] == "ktoken-1"
    assert info["knowledgeid"] == "knowledge-1"
    assert [job["type"] for job in jobs] == ["video", "document", "workid", "read", "live"]
    assert jobs[0]["jobid"] == "job-video-1"
    assert jobs[0]["playTime"] == 12000
    assert jobs[1]["jtoken"] == "jtoken-1"
    assert jobs[2]["jobid"] == "work-1"
    assert jobs[3]["jobid"] == "job-read-1"
    assert jobs[4]["liveId"] == "live-1"


def test_decode_course_card_not_open():
    jobs, info = decode_course_card("<html>章节未开放</html>")
    assert jobs == []
    assert info == {"notOpen": True}


def test_decode_questions_info_preserves_form_and_types():
    data = decode_questions_info(fixture_text("html/questions_plain.html"))

    assert data["workId"] == "work-123"
    assert data["workAnswerId"] == "answer-456"
    assert "answer999" not in data
    assert data["answerwqbid"] == "101,102,103,"
    assert [q["id"] for q in data["questions"]] == ["101", "102", "103"]
    assert [q["type"] for q in data["questions"]] == ["single", "multiple", "judgement"]
    assert data["questions"][0]["answerField"] == {
        "answer101": "",
        "answertype101": "0",
    }
    assert "A. 选项甲" in data["questions"][0]["options"]
