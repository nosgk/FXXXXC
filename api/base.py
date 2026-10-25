# -*- coding: utf-8 -*-
import random
import secrets
import re
import threading
import time
from enum import Enum, IntEnum
from hashlib import md5
from typing import Callable, Optional, Literal

import requests
from loguru import logger
from api.redact import redact_mapping, redact_url
from requests import RequestException
from tqdm import tqdm

from api.answer import Tiku, TikuManual, _choice_letters, _has_image, _image_choice
from api.cipher import AESCipher
from api.config import GlobalConst as gc
from api.cookies import save_cookies
from api.decode import (
    decode_course_list,
    decode_course_point,
    decode_course_card,
    decode_course_folder,
    decode_questions_info,
)

from fxxxxc.infra.rate_limit import RateLimiter
from fxxxxc.infra.session import SessionManager
from fxxxxc.text import (
    _JUDGE_FALSE_SET,
    _JUDGE_TRUE_SET,
    _parse_work_record_detail,
    _parse_work_record_list,
    clean_res,
    match_option_letter,
    multi_cut,
    normalize_answer_text,
    normalize_text,
    random_answer,
)


def get_timestamp():
    return str(int(time.time() * 1000))


def _strict_judgement_answer(tiku, response) -> str:
    """Return a recognized judgement value without invoking random fallback."""
    if not isinstance(response, str):
        return ""
    value = response.strip().lower()
    true_list = getattr(tiku, "true_list", [])
    false_list = getattr(tiku, "false_list", [])
    if not isinstance(true_list, (list, tuple, set)):
        true_list = []
    if not isinstance(false_list, (list, tuple, set)):
        false_list = []
    true_values = {
        "true", "t", "1", "对", "正确", "√", "是", "yes", "y",
        *(str(item).strip().lower() for item in true_list),
    }
    false_values = {
        "false", "f", "0", "错", "错误", "×", "否", "no", "n", "不对", "不正确",
        *(str(item).strip().lower() for item in false_list),
    }
    if value in true_values:
        return "true"
    if value in false_values:
        return "false"
    return ""


class Account:
    username = None
    password = None
    last_login = None
    isSuccess = None

    def __init__(self, _username, _password):
        self.username = _username
        self.password = _password


class StudyResult(Enum):
    SUCCESS = 0
    FORBIDDEN = 1  # 403
    ERROR = 2
    TIMEOUT = 3

    def is_success(self):
        return self == StudyResult.SUCCESS

    def is_failure(self):
        return self != StudyResult.SUCCESS


class SignType(IntEnum):
    NORMAL = 0
    GESTURE = 3
    LOCATION = 4


class ActivityStatus(IntEnum):
    ACTIVE = 1
    INACTIVE = 2


class ActivityType(IntEnum):
    SIGNIN = 2


class Chaoxing:
    # 引擎可选注入的进度回调（CLI 为 None 时零开销）。回调异常必须被吞掉，
    # 任何监听方的故障都不能中断学习线程。类级默认值保证绕过 __init__ 构造的
    # 测试实例也拥有该属性。
    progress_hook: Optional[Callable[[dict], None]] = None

    def __init__(self, account: Account = None, tiku: Tiku = None, **kwargs):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku
        self.kwargs = kwargs
        self.rollback_times = 0
        self.rate_limiter = RateLimiter(0.5)  # 其他接口速率限制比较松
        self.video_log_limiter = RateLimiter(2)  # 上报进度极其容易卡验证码，限制2s一次
        self._cancel_event = threading.Event()
        self.progress_hook = None

    def emit_progress(self, data: dict) -> None:
        hook = self.progress_hook
        if hook is None:
            return
        try:
            hook(data)
        except Exception:  # noqa: BLE001 - progress must never break study
            logger.debug("进度回调异常，已忽略")

    def cancel(self) -> None:
        """Request cancellation of long-running study loops."""
        self._cancel_event.set()

    def should_stop(self) -> bool:
        return self._cancel_event.is_set()

    def _sleep(self, seconds: float) -> None:
        """Sleep in slices so cancel() is responsive."""
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._cancel_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def login(self, login_with_cookies=False):
        if login_with_cookies:
            logger.info("Logging in with cookies")
            SessionManager.update_cookies()
            logger.debug(
                "Logged in with cookies: {} cookie entries",
                len(SessionManager.get_instance()._session.cookies),
            )
            if not self._validate_cookie_session():
                logger.warning("Cookie 登录校验失败，尝试使用账号密码重新登录")
                if self.account and self.account.username and self.account.password:
                    return self.login(login_with_cookies=False)
                return {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
            logger.info("登录成功...")
            try:
                realname = self.get_name()
                if realname:
                    logger.info(f"当前登录用户: {realname}")
            except Exception as e:
                logger.debug(f"获取当前登录用户名失败: {e}")
            return {"status": True, "msg": "登录成功"}

        _session = requests.Session()
        _url = "https://passport2.chaoxing.com/fanyalogin"
        _data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0,
        }
        logger.trace("正在尝试登录...")
        resp = _session.post(_url, headers=gc.HEADERS, data=_data)
        try:
            payload = resp.json()
        except ValueError:
            return {
                "status": False,
                "msg": f"登录接口返回非 JSON 内容 (HTTP {resp.status_code})",
            }

        if payload.get("status") is True:
            save_cookies(_session)
            SessionManager.update_cookies()
            logger.info("登录成功...")
            try:
                realname = self.get_name()
                if realname:
                    logger.info(f"当前登录用户: {realname}")
            except Exception as e:
                logger.debug(f"获取当前登录用户名失败: {e}")
            return {"status": True, "msg": "登录成功"}

        message = payload.get("msg2") or payload.get("msg") or "登录失败"
        return {"status": False, "msg": str(message)}

    @staticmethod
    def get_name() -> str:
        _session = SessionManager.get_session()
        try:
            resp = _session.get("https://passport2.chaoxing.com/mooc/accountManage", timeout=10)
            if resp.status_code == 200:
                match = re.search(r'id="messageName"\s+value="([^"]*)"', resp.text)
                if match:
                    return match.group(1).strip()
        except Exception as e:
            logger.debug(f"获取用户名失败: {e}")
        return ""

    def _validate_cookie_session(self) -> bool:
        session = SessionManager.get_instance()._session
        if not session.cookies.get("_uid"):
            return False

        test_session = requests.Session()
        test_session.headers.update(gc.HEADERS)
        test_session.cookies.update(session.cookies.get_dict())

        try:
            resp = test_session.post(
                "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata",
                data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
                timeout=8,
            )
        except RequestException as exc:
            logger.debug("Cookie validation request failed: {}", exc)
            return False

        if resp.status_code != 200:
            return False

        if "passport2.chaoxing.com" in resp.text or "login" in resp.text.lower():
            return False

        return True

    def get_fid(self):
        _session = SessionManager.get_session()
        return _session.cookies.get("fid", 1024)

    def get_uid(self):
        s = SessionManager.get_session()
        if "_uid" in s.cookies:
            return s.cookies["_uid"]
        if "UID" in s.cookies:
            return s.cookies["UID"]
        raise ValueError("Cannot get uid !")

    def get_course_list(self):
        _session = SessionManager.get_session()
        _url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        # 入参与官方 interaction 页面保持一致且全部可控：
        #   courseType=1      只拉“我学的课”
        #   courseFolderId=0  顶层列表（文件夹内的课程由下方逐文件夹补齐）
        #   query             官方搜索框的关键字（本程序在 GUI 侧过滤，固定为空）
        #   superstarClass=0  不含超星示范班课程
        _data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}
        logger.trace("正在读取所有的课程列表...")

        # 接口突然抽风, 增加headers
        # 有可能只是referer的问题
        _headers = {
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
        }
        _resp = _session.post(_url, headers=_headers, data=_data)
        # logger.trace(f"原始课程列表内容:\n{_resp.text}")
        if _resp.status_code != 200:
            logger.error("读取课程列表失败: {}", _resp.status_code)
            return []
        logger.info("课程列表读取完毕...")
        course_list = decode_course_list(_resp.text)

        _interaction_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
        _interaction_resp = _session.get(_interaction_url)
        if _interaction_resp.status_code != 200:
            logger.warning("读取课程文件夹失败: {}", _interaction_resp.status_code)
            course_folder = []
        else:
            course_folder = decode_course_folder(_interaction_resp.text)
        for folder in course_folder:
            _data = {
                "courseType": 1,
                "courseFolderId": folder["id"],
                "query": "",
                "superstarClass": 0,
            }
            _resp = _session.post(_url, data=_data)
            if _resp.status_code == 200:
                course_list += decode_course_list(_resp.text)
            else:
                logger.warning("读取文件夹 {} 课程失败: {}", folder.get("id"), _resp.status_code)
        if not course_list:
            logger.warning("课程列表为空，请检查登录状态或账号课程")
        return course_list

    def get_activity_list(self, course: dict) -> list[dict]:
        s = SessionManager.get_session()
        url = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"
        params = {
            "fid": self.get_fid(),
            "courseId": course["courseId"],
            "classId": course["clazzId"],
            "showNotStartedActive": 0,
            "_": get_timestamp()
        }
        resp = s.get(url, params=params, allow_redirects=False)
        if resp.status_code != 200:
            logger.error("Failed to get activity list, return code: " + str(resp.status_code))
            logger.debug("Request url: {}", redact_url(resp.url))
            return []

        data = resp.json()
        if data["result"] != 1:
            logger.error("Unknown status: {} {}", data["result"], data["errorMsg"])
            logger.debug("Request url: {}", redact_url(resp.url))
            return []

        return data["data"]["activeList"]

    def pre_sign(self, course: dict, activity_id):
        s = SessionManager.get_session()
        params = {
            "general": 1,
            "sys": 1,
            "ls": 1,
            "appType": 15,
            "tid": '',
            "ut": 's',
            "uid": self.get_uid(),
            "activePrimaryId": activity_id,
            "courseId": course["courseId"],
            "classId": course["clazzId"],
        }
        resp = s.get('https://mobilelearn.chaoxing.com/newsign/preSign', params=params)
        resp_txt = resp.text
        logger.debug("Request url: {}", redact_url(resp.url))
        if resp.status_code != 200:
            logger.error("Failed to get sign in, return code: " + str(resp.status_code) + "message: " + resp_txt)

        return resp_txt

    def sign_in_normal(self, course: dict, activity_id, name="", obj_id="aaa", lat=-1, lon=-1, type_=SignType.NORMAL):
        s = SessionManager.get_session()
        params = {
            "activeId": activity_id,
            "uid": self.get_uid(),
            "fid": self.get_fid(),
            "courseId": course["courseId"],
            "classId": course["clazzId"],
            "clientip": "",
            "objectId": obj_id,
            "name": name,
            "useragent": "",
            "latitude": lat,
            "longitude": lon,
            "appType": "15",
        }

        resp = s.get("https://mobilelearn.chaoxing.com/pptSign/stuSignajax", params=params)

        resp_txt = resp.text
        if resp.status_code != 200:
            logger.error("Failed to get sign in, return code: " + str(resp.status_code) + "message: " + resp_txt)

        if type_ != SignType.LOCATION:
            return resp_txt

        pattern = r"[^0-9\.]*(.+)米[^0-9\.]*"
        msg = re.match(pattern, resp_txt)
        logger.warning(f"距离签到位置 {msg}m")
        # TOD0: Implement triangulation for location signs
        return resp_txt

    def get_course_point(self, _courseid, _clazzid, _cpi):
        _session = SessionManager.get_session()
        _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={_courseid}&clazzid={_clazzid}&cpi={_cpi}&ut=s"
        logger.trace("URL: {}", redact_url(_url))
        logger.trace("开始读取课程所有章节...")
        _resp = _session.get(_url)
        if _resp.status_code != 200:
            logger.error("课程章节读取失败: {}", _resp.status_code)
            return {"hasLocked": False, "points": []}

        logger.trace(f"原始章节列表内容:\n{_resp.text}")
        logger.info("课程章节读取成功...")
        return decode_course_point(_resp.text)

    def get_job_list(self, course: dict, point: dict) -> tuple[list[dict], dict]:
        _session = SessionManager.get_session()
        self.rate_limiter.limit_rate()
        job_list = []
        job_info = {}
        cards_params = {
            "clazzid": course["clazzId"],
            "courseid": course["courseId"],
            "knowledgeid": point["id"],
            "ut": "s",
            "cpi": course["cpi"],
            "v": "2025-0424-1038-3",
            "mooc2": 1
        }

        try:
            expected_jobs = int(point.get("jobCount") or 0)
        except (TypeError, ValueError):
            expected_jobs = 0

        # 学习界面任务卡片数, 很少有3个的, 但是对于章节解锁任务点少一个都不行, 可以从API /mooc-ans/mycourse/studentstudyAjax获取值, 或者干脆直接加, 但二者都会造成额外的请求
        for _possible_num in "0123456":

            logger.trace("开始读取章节所有任务点...")

            cards_params.update({"num": _possible_num})
            _resp = _session.get("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards", params=cards_params)
            if _resp.status_code != 200:
                logger.error(f"未知错误: {_resp.status_code} 正在跳过")
                logger.error(_resp.text)
                return [], {}

            _job_list, _job_info = decode_course_card(_resp.text)
            if _job_info.get("notOpen", False):
                # 直接返回, 节省一次请求
                logger.info("该章节未开放")
                return [], _job_info

            job_list += _job_list
            job_info.update(_job_info)

            # 章节列表已经给出任务点数量时，提前停止，避免固定 7 次请求。
            if expected_jobs and len(job_list) >= expected_jobs:
                break

        if not job_list:
            self.study_emptypage(course, point)

        logger.trace(f"原始任务点列表内容:\n{_resp.text}")
        logger.info("章节任务点读取成功...")

        return job_list, job_info

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]"
            .encode()).hexdigest()

    def video_progress_log(
            self,
            _session,
            _course,
            _job,
            _job_info,
            _dtoken,
            _duration,
            _playingTime,
            _type: str = "Video",
            _isdrag: int = 3,
            headers: Optional[dict] = None,
    ) -> tuple[bool, int]:

        if headers is None:
            logger.warning("null headers")
            headers = gc.VIDEO_HEADERS

        self.video_log_limiter.limit_rate(random_time=True, random_max=2)

        if "courseId" in _job["otherinfo"]:
            logger.error(_job["otherinfo"])
            raise RuntimeError("this is not possible")

        enc = self.get_enc(_course["clazzId"], _job["jobid"], _job["objectid"], _playingTime, _duration, self.get_uid())
        params = {
            "clazzId": _course["clazzId"],
            "playingTime": _playingTime,
            "duration": _duration,
            "clipTime": f"0_{_duration}",
            "objectId": _job["objectid"],
            "otherInfo": _job["otherinfo"],
            "courseId": _course["courseId"],
            "jobid": _job["jobid"],
            "userid": self.get_uid(),
            "isdrag": _isdrag,
            "view": "pc",
            "enc": enc,
            "dtype": _type
        }

        _url = (
            f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/"
            f"{_course['cpi']}/"
            f"{_dtoken}"
        )

        face_capture_enc = _job["videoFaceCaptureEnc"]
        att_duration = _job["attDuration"]
        att_duration_enc = _job["attDurationEnc"]

        if face_capture_enc:
            params["videoFaceCaptureEnc"] = face_capture_enc
        if att_duration:
            params["attDuration"] = att_duration
        if att_duration_enc:
            params["attDurationEnc"] = att_duration_enc

        def perform_request(rt_val):
            params.update({"rt": rt_val, "_t": get_timestamp()})
            res = _session.get(_url, params=params, headers=headers)
            if res.status_code == 403 or '验证码' in res.text or 'validate' in res.text:
                logger.warning("检测到验证码拦截，正在尝试自动通过验证码...")
                try:
                    from api.captcha import CxCaptcha
                    cookies_str = "; ".join([f"{k}={v}" for k, v in _session.cookies.items()])
                    ua = headers.get("User-Agent", gc.HEADERS.get("User-Agent"))
                    ocr_inst = getattr(self, '_ocr', None)
                    if ocr_inst is None:
                        from api.captcha import ocr_init
                        ocr_inst = ocr_init()
                        if ocr_inst:
                            self._ocr = ocr_inst
                    captcha_solver = CxCaptcha(user_agent=ua, cookies=cookies_str, ocr=ocr_inst)
                    solved = False
                    for attempt in range(3):
                        logger.info(f"第 {attempt + 1} 次尝试通关验证码...")
                        if captcha_solver.try_pass():
                            logger.success("验证码通关成功！")
                            solved = True
                            break
                        else:
                            logger.warning("验证码验证失败，正在重试...")
                            time.sleep(2)
                    if solved:
                        _session.cookies.update(captcha_solver.s.cookies)
                        res = _session.get(_url, params=params, headers=headers)
                    else:
                        logger.error("多次验证码通关失败，可能需要手动干预。")
                except Exception as e:
                    logger.error(f"验证码通关逻辑异常: {e}")
            return res

        rt = _job['rt']
        if not rt:
            rt_search = re.search(r"-rt_([1d])", _job['otherinfo'])
            if rt_search:
                rt_char = rt_search.group(1)
                rt = "0.9" if rt_char == "d" else "1"
                logger.trace(f"Got rt from otherinfo: {rt}")

        if rt:
            logger.trace(f"Got rt: {rt}")
            _job['rt'] = rt
            resp = perform_request(rt)
        else:
            logger.warning("Failed to get rt")
            for rt in [0.9, 1]:
                resp = perform_request(rt)
                if resp.status_code == 200:
                    logger.trace(resp.text)
                    return resp.json()["isPassed"], 200
                elif resp.status_code == 403:
                    logger.warning("出现403报错, 正常尝试切换rt")
                else:
                    logger.warning("未知错误 jobid={}, status_code={}, 摘要:\n{}",
                                   _job.get("jobid"),
                                   resp.status_code,
                                   resp.text[:200])
                    break

        if resp.status_code == 200:
            logger.trace(resp.text)
            return resp.json()["isPassed"], 200

        elif resp.status_code == 403:
            logger.debug(
                "视频进度上报返回403, jobid={}, 摘要={}",
                _job.get("jobid"),
                resp.text[:200],
            )

            # 若出现两个rt参数都返回403的情况, 则跳过当前任务
            logger.error("出现403报错, 尝试修复无效, 正在跳过当前任务点...")
            logger.error("请求url: {}", redact_url(resp.url))
            logger.error("请求头: {}", redact_mapping(dict(_session.headers) | headers))
            return False, 403

        logger.error(f"未知错误: {resp.status_code}")
        logger.error("请求url: {}", redact_url(resp.url))
        logger.error("请求头：{}", redact_mapping(dict(_session.headers) | headers))
        return False, resp.status_code

    def _refresh_video_status(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]) \
            -> Optional[dict]:
        self.rate_limiter.limit_rate(random_time=True, random_max=0.2)
        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        info_url = (
            f"https://mooc1.chaoxing.com/ananas/status/{job['objectid']}?"
            f"k={self.get_fid()}&flag=normal"
        )
        try:
            resp = session.get(info_url, timeout=8, headers=headers)
        except RequestException as exc:
            logger.debug("刷新视频状态失败: {}", exc)
            return None

        if resp.status_code != 200:
            logger.debug("刷新视频状态返回码异常: {}" % resp.status_code)
            logger.debug(resp.text)
            return None

        try:
            data = resp.json()
        except ValueError as exc:
            logger.debug("解析视频状态响应失败: {}", exc)
            return None

        if data.get("status") == "success":
            return data

        return None

    def _recover_after_forbidden(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]):
        SessionManager.update_cookies()
        refreshed = self._refresh_video_status(session, job, _type)
        if refreshed:
            return refreshed

        if SessionManager.relogin_if_needed(self):
            return self._refresh_video_status(session, job, _type)

        return None

    @staticmethod
    def _close_pbar_safe(pbar_ref):
        if pbar_ref is not None:
            try:
                pbar_ref.leave = False
                pbar_ref.close()
            except Exception as e:
                logger.trace(f"关闭进度条失败: {e}")
        return None

    @staticmethod
    def _get_video_resume_time_seconds(play_time_ms, duration_seconds: int) -> int:
        """把毫秒播放位置换算为续播秒数（官方播放器规则）。

        官方 modules/video/index.js 中 playTime >= 视频总时长时会把续播位置
        重置为 0 重新播放；这里对齐该行为，防止把“已到片尾”当作可续播进度。
        非法输入一律按 0 处理。
        """
        try:
            play_time_seconds = int(play_time_ms) // 1000
        except (TypeError, ValueError):
            return 0
        return play_time_seconds if 0 <= play_time_seconds < duration_seconds else 0

    def study_video(self, _course, _job, _job_info, _speed: float = 1.0,
                    _type: Literal["Video", "Audio"] = "Video") -> StudyResult:
        _session = SessionManager.get_session()

        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        _info_url = (
            f"https://mooc1.chaoxing.com/ananas/status/{_job.get('objectid', '')}"
            f"?k={self.get_fid()}&flag=normal"
        )
        try:
            _info_resp = _session.get(_info_url, headers=headers)
            _video_info = _info_resp.json()
        except (RequestException, ValueError) as exc:
            logger.error("获取视频状态失败: {}", exc)
            return StudyResult.ERROR

        if not isinstance(_video_info, dict) or _video_info.get("status") != "success":
            logger.error("Unknown status: {}", _video_info.get("status") if isinstance(_video_info, dict) else "?")
            return StudyResult.ERROR

        try:
            _dtoken = _video_info["dtoken"]
            duration = int(_video_info["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("视频状态缺少必要字段: {}", exc)
            return StudyResult.ERROR

        # Time in the real world: last_iter, gc.THRESHOLD
        # Time in the video (can be scaled with the speed factor): duration, play_time, last_log_time, wait_time

        raw_play_ms = _job.get("playTime", 0)
        play_time = self._get_video_resume_time_seconds(raw_play_ms, duration)
        # None 表示尚未做过首次上报：进循环立刻上报续播位置，而不是把总时长
        # 写进进度（旧实现先发 duration,duration 的 isdrag=4 上报“瞬间完成”，
        # 平台会把该位置重置为 0，导致 isPassed 永远不落库、任务永远未完成）。
        last_log_time = None
        last_iter = time.time()
        wait_time = int(random.uniform(30, 90))

        logger.info(f"开始任务: {_job.get('name', '')}, 总时长: {duration}s, 续播位置: {play_time}s")
        try:
            raw_play_seconds = int(raw_play_ms) // 1000
        except (TypeError, ValueError):
            raw_play_seconds = 0
        if raw_play_seconds >= duration > 0:
            logger.info("{} 的原始播放位置已到末尾，按官方播放器规则从 0s 续播", _job.get("name", ""))

        forbidden_retry = 0
        max_forbidden_retry = 2
        # 终态确认重试上限：进度走到片尾后，平台偶尔不会立即确认 isPassed。
        # 旧实现会在 100% 处每 1~2s 无限重发上报，表现为“进度卡 100% 不进入
        # 下一个任务”。现在限制确认次数，超限后明确报错并把队列让给后续任务。
        final_attempts = 0
        max_final_attempts = 6

        def _emit_video_progress() -> None:
            self.emit_progress(
                {
                    "kind": _type.lower(),
                    "phase": "progress",
                    "name": _job.get("name", ""),
                    "progress": round(min(1.0, max(0.0, play_time / duration)), 4) if duration > 0 else 0.0,
                    "play_time": int(play_time),
                    "duration": duration,
                }
            )

        # 视频每秒只向外发一次进度事件，避免事件洪泛拖慢 GUI。
        _last_emit_ts = [0.0]

        def _emit_video_progress_throttled() -> None:
            now = time.monotonic()
            if now - _last_emit_ts[0] >= 1.0:
                _last_emit_ts[0] = now
                _emit_video_progress()

        _last_emit_ts[0] = time.monotonic()
        _emit_video_progress()

        passed = False
        pbar = None
        try:
            while not passed:
                if self.should_stop():
                    logger.info("收到取消请求, 停止视频任务: {}", _job.get("name", ""))
                    return StudyResult.ERROR
                # Sometimes the last request needs to be sent several times to complete the task
                # 首次上报续播位置，与后续上报共用错误处理，避免把总时长写入进度
                if last_log_time is None or play_time >= duration or play_time - last_log_time >= wait_time:
                    if play_time >= duration:
                        final_attempts += 1

                    passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration,
                                                            int(play_time), _type, headers=headers)

                    if state == 403:
                        if forbidden_retry >= max_forbidden_retry:
                            logger.warning("403重试失败, 跳过当前任务")
                            return StudyResult.FORBIDDEN
                        forbidden_retry += 1
                        logger.warning(
                            "出现403报错, 正在尝试刷新会话状态 (第{}次)",
                            forbidden_retry,
                        )
                        time.sleep(random.uniform(2, 4))
                        refreshed_meta = self._recover_after_forbidden(_session, _job, _type)
                        if refreshed_meta and refreshed_meta.get("dtoken") and refreshed_meta.get(
                                "duration") is not None:
                            _dtoken = refreshed_meta["dtoken"]
                            duration = int(refreshed_meta["duration"])
                            refreshed_play_time = refreshed_meta.get("playTime")
                            if refreshed_play_time is not None:
                                play_time = self._get_video_resume_time_seconds(refreshed_play_time, duration)
                            # 恢复后立即上报重置后的续播位置，避免用恢复前的旧进度继续
                            last_log_time = None

                            logger.debug("刷新视频状态后，总时长: {}s，续播位置: {}s", duration, play_time)
                            pbar = self._close_pbar_safe(pbar)
                            final_attempts = 0
                            continue
                        else:
                            logger.error("会话恢复失败，刷新后的元数据缺少必要字段 (dtoken, duration)")
                            return StudyResult.ERROR

                    elif not passed and state != 200:
                        return StudyResult.ERROR

                    wait_time = int(random.uniform(30, 90))
                    last_log_time = play_time

                    logger.trace("Progress logged")

                    # 进度已到片尾但平台仍未确认：有界重试后放行，避免死循环。
                    if not passed and play_time >= duration:
                        _emit_video_progress()
                        if final_attempts >= max_final_attempts:
                            logger.error(
                                "视频进度已到片尾，但平台 {} 次上报均未确认完成 (jobid={}), "
                                "跳过当前任务点以继续后续任务。建议稍后重跑或手动检查",
                                final_attempts,
                                _job.get("jobid", ""),
                            )
                            return StudyResult.ERROR
                        logger.debug(
                            "片尾确认第 {}/{} 次未通过, 稍后重试",
                            final_attempts,
                            max_final_attempts,
                        )
                        self._sleep(2)
                        continue

                # Uploading the progress takes time, we assume that the video is still playing in the background, this manually calculates the time elapsed
                dt = (time.time() - last_iter) * _speed
                last_iter = time.time()
                play_time = min(duration, play_time + dt)
                _emit_video_progress_throttled()

                # 检查手动模式锁是否被锁定
                manual_locked = False
                try:
                    manual_locked = TikuManual._manual_lock.locked()
                except Exception as e:
                    logger.trace(f"无法检查手动锁状态: {e}")

                if manual_locked:
                    pbar = self._close_pbar_safe(pbar)
                else:
                    if pbar is None:
                        pbar = tqdm(total=duration, initial=int(play_time), desc=_job["name"],
                                    unit_scale=True, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}', leave=False)
                    pbar.n = int(play_time)
                    pbar.refresh()

                time.sleep(gc.THRESHOLD)
        finally:
            pbar = self._close_pbar_safe(pbar)

        logger.info("任务完成: {}", _job.get("name", ""))
        self.emit_progress({"kind": _type.lower(), "phase": "done", "name": _job.get("name", ""), "progress": 1.0})
        return StudyResult.SUCCESS

    def study_document(self, _course, _job) -> StudyResult:
        """
        Study a document in Chaoxing platform.

        This method makes a GET request to fetch document information for a given course and job.

        Args:
            _course (dict): Dictionary containing course information with keys:
                - courseId: ID of the course
                - clazzId: ID of the class
            _job (dict): Dictionary containing job information with keys:
                - jobid: ID of the job
                - otherinfo: String containing node information
                - jtoken: Authentication token for the job

        Returns:
            requests.Response: Response object from the GET request

        Note:
            This method requires the following helper functions:
            - init_session(): To initialize a new session
            - get_timestamp(): To get current timestamp
            - re module for regular expression matching
        """
        node_matches = re.findall(r"nodeId_(.*?)-", _job.get("otherinfo", ""))
        if not node_matches:
            logger.error("文档任务缺少 nodeId: {}", _job.get("jobid"))
            return StudyResult.ERROR
        _session = SessionManager.get_session()
        _url = (
            "https://mooc1.chaoxing.com/ananas/job/document"
            f"?jobid={_job.get('jobid', '')}"
            f"&knowledgeid={node_matches[0]}"
            f"&courseid={_course.get('courseId', '')}"
            f"&clazzid={_course.get('clazzId', '')}"
            f"&jtoken={_job.get('jtoken', '')}"
            f"&_dc={get_timestamp()}"
        )
        _resp = _session.get(_url)
        if _resp.status_code != 200:
            logger.error("文档任务失败 -> [{}]{}", _resp.status_code, _resp.text[:200])
            return StudyResult.ERROR
        return StudyResult.SUCCESS

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        if not self.tiku or getattr(self.tiku, "DISABLE", False):
            return StudyResult.SUCCESS

        # 清理上一章节可能残留的重做反馈，避免跨章节污染缓存/提示词。
        if hasattr(self.tiku, "set_work_feedback"):
            try:
                self.tiku.set_work_feedback(None)
            except Exception as exc:  # noqa: BLE001 - feedback is best effort
                logger.debug("清理章节检测反馈失败: {}", exc)

        _session = SessionManager.get_session()
        _url = "https://mooc1.chaoxing.com/mooc-ans/api/work"

        def fetch_response_with_retry():
            """Fetch the work page, retrying transient failures up to 3 times.

            This used to be a tenacity decorator. It is now a small explicit
            loop so the core package does not depend on tenacity just for one
            call site.
            """
            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    _resp = _session.get(
                        _url,
                        params={
                            "api": "1",
                            "workId": _job["jobid"].replace("work-", ""),
                            "jobid": _job["jobid"],
                            "originJobId": _job["jobid"],
                            "needRedirect": "true",
                            "skipHeader": "true",
                            "knowledgeid": str(_job_info["knowledgeid"]),
                            "ktoken": _job_info["ktoken"],
                            "cpi": _job_info["cpi"],
                            "ut": "s",
                            "clazzId": _course["clazzId"],
                            "type": "",
                            "enc": _job["enc"],
                            "mooc2": "1",
                            "courseid": _course["courseId"],
                        }
                    )

                    # 未创建完成该测验则不进行答题，目前遇到的情况是未创建完成等同于没题目
                    if '教师未创建完成该测验' in _resp.text:
                        raise PermissionError("教师未创建完成该测验")

                    questions = decode_questions_info(_resp.text)

                    if _resp.status_code == 200 and questions.get("questions"):
                        return _resp, questions

                    logger.warning(
                        f"无效响应 (Code: {getattr(_resp, 'status_code', 'Unknown')}), 重试中...")
                    last_error = RuntimeError(
                        f"请求返回无效数据 (Code: {_resp.status_code})"
                    )
                except PermissionError:
                    raise
                except Exception as exc:  # noqa: BLE001 - retried below
                    last_error = exc

                if attempt < 3:
                    time.sleep(1)

            if last_error is not None:
                raise last_error
            raise RuntimeError("请求章节检测失败")

        # 章节检测最大重做次数（答错后收集错误反馈并重新提交，直到全对）
        # work_redo_enabled=false 时为单轮模式: 提交+检查+报告成绩, 不自动重做(适用于只允许作答一次的课程)
        if bool(self.kwargs.get("work_redo_enabled", False)):
            try:
                max_retries = max(1, int(self.kwargs.get("work_max_retries", 3)))
            except (TypeError, ValueError):
                max_retries = 3
        else:
            max_retries = 0
        query_delay = self.kwargs.get("query_delay", 0)
        feedback_history = None
        last_submitted_score = None
        # 回滚计数只对当前章节检测生效，避免上一章的重做状态影响后续章节。
        chapter_rollback_times = 0

        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.warning(
                    f"章节检测重做第 {attempt}/{max_retries} 轮，携带上一轮错误反馈重新作答")
                time.sleep(2)

            # 1. 获取题目
            final_resp = {}
            questions = {}
            try:
                final_resp, questions = fetch_response_with_retry()
            except PermissionError as e:
                logger.warning(f"跳过章节检测: {e}")
                return StudyResult.SUCCESS
            except Exception as e:
                if attempt > 0:
                    logger.error(f"重做轮无法获取题目(上一轮提交成绩 {last_submitted_score} 分), "
                                 f"该课程可能仅允许作答一次: {e}")
                else:
                    logger.error(f"获取章节检测题目失败, 达到最大重试次数: {e}")
                return StudyResult.ERROR

            _ORIGIN_HTML_CONTENT = final_resp.text  # 用于配合输出网页源码, 帮助修复#391错误

            # 2. 设置上一轮错误反馈（供AI重新作答时参考）
            if feedback_history and hasattr(self.tiku, 'set_work_feedback'):
                try:
                    self.tiku.set_work_feedback(feedback_history)
                    logger.debug("已将上一轮错误反馈设置到题库")
                except Exception as e:
                    logger.warning(f"设置题库错误反馈失败: {e}")

            # 3. 搜题
            total_questions = len(questions["questions"])
            if total_questions <= 0:
                logger.warning("章节检测没有题目，跳过: {}", _job.get("jobid"))
                return StudyResult.SUCCESS
            found_answers = 0
            answers = self.tiku.query_all(questions["questions"], query_delay=query_delay)

            if not isinstance(answers, list):
                logger.error("题库 query_all 返回的数据格式异常，期望列表。将采用随机答案答题")
                answers = [None] * total_questions
            elif len(answers) != total_questions:
                logger.error(
                    f"题库返回的答案数量（{len(answers)}）与题目数量（{total_questions}）不匹配，正在补齐或截断以防错位！")
                answers = list(answers) + [None] * (total_questions - len(answers))
                answers = answers[:total_questions]

            unresolved_image_choice = False
            for q, res in zip(questions["questions"], answers):
                logger.debug(f"当前题目信息 -> {q}")
                answer = ""
                unresolved_question = False
                if _image_choice(q):
                    # 图像中的公式正文不能与 img 标签做子序列/相似度匹配。
                    answer = _choice_letters(res, q)
                    if answer:
                        q[f'answerSource{q["id"]}'] = "cover"
                        found_answers += 1
                        logger.info("图片选择题选项匹配成功：{}", answer)
                    else:
                        q[f'answerSource{q["id"]}'] = "unresolved"
                        unresolved_image_choice = True
                        logger.warning("图片选择题无有效选项字母，留空并仅保存，需人工检查")
                elif _has_image(q) and not res:
                    # 图片不可用时禁止判断题或其他图片题走随机答案分支。
                    answer = ""
                    q[f'answerSource{q["id"]}'] = "unresolved"
                    unresolved_image_choice = True
                    logger.warning("图片题资源不可用，留空并仅保存，需人工检查")
                elif not res:
                    # 随机答题
                    answer = random_answer(q["options"], q["type"])
                    q[f'answerSource{q["id"]}'] = "random"
                else:
                    # 根据响应结果选择答案
                    if q["type"] == "multiple":
                        # 多选处理：每项答案做逐级容错匹配（ocsjs AnswerUtil 策略）
                        options_list = multi_cut(q["options"], _ORIGIN_HTML_CONTENT)
                        res_list = multi_cut(res, _ORIGIN_HTML_CONTENT)
                        if res_list is not None and options_list is not None:
                            for _a in clean_res(res_list):
                                letter = match_option_letter(_a, options_list)
                                if letter:
                                    answer += letter
                            # 对答案进行排序, 否则会提交失败
                            answer = "".join(sorted(set(answer)))
                        # else 如果分割失败那么就直接到下面去随机选
                    elif q["type"] == "single":
                        # 单选也进行切割，主要是防止返回的答案有异常字符
                        options_list = multi_cut(q["options"], _ORIGIN_HTML_CONTENT)
                        if options_list is not None:
                            t_res = clean_res(res)
                            if t_res:
                                answer = match_option_letter(t_res[0], options_list)
                    elif q["type"] == "judgement":
                        if _has_image(q):
                            answer = _strict_judgement_answer(self.tiku, res)
                            if not answer:
                                q[f'answerSource{q["id"]}'] = "unresolved"
                                unresolved_image_choice = True
                                unresolved_question = True
                                logger.warning("图片判断题无有效答案，留空并仅保存，需人工检查")
                        else:
                            answer = "true" if self.tiku.judgement_select(res) else "false"
                    elif q["type"] == "completion":
                        if isinstance(res, list):
                            # 多空填空以 # 分隔（超星题库返回约定）；单空时行为不变
                            blanks = [str(item).strip() for item in res if str(item).strip()]
                            answer = "#".join(blanks)
                        elif isinstance(res, str):
                            answer = res
                    else:
                        # 其他类型直接使用答案 （目前仅知有简答题，待补充处理）
                        answer = res

                    if not answer and not unresolved_question:  # 检查 answer 是否为空
                        logger.warning(f"找到答案但答案未能匹配 -> {res}\t随机选择答案")
                        answer = random_answer(q["options"], q["type"])  # 如果为空，则随机选择答案
                        q[f'answerSource{q["id"]}'] = "random"
                    else:
                        logger.info(f"成功获取到答案：{answer}")
                        q[f'answerSource{q["id"]}'] = "cover"
                        found_answers += 1
                # 填充答案
                q["answerField"][f'answer{q["id"]}'] = answer
                logger.info(f'{q["title"]} 填写答案为 {answer}')
            cover_rate = (found_answers / total_questions) * 100
            logger.info(f"章节检测题库覆盖率： {cover_rate:.0f}%")
            # 提交模式  现在与题库绑定,留空直接提交, 1保存但不提交
            is_manual_mode = bool(getattr(self.tiku, "_is_manual_mode", False))
            if unresolved_image_choice or self.tiku.get_submit_params() == "1":
                questions["pyFlag"] = "1"
            elif is_manual_mode or cover_rate >= self.tiku.COVER_RATE * 100 or chapter_rollback_times >= 1:
                questions["pyFlag"] = ""
            else:
                questions["pyFlag"] = "1"
                logger.info(f"章节检测题库覆盖率低于{self.tiku.COVER_RATE * 100:.0f}%，不予提交")
            self.emit_progress(
                {
                    "kind": "work",
                    "phase": "stats",
                    "name": str(_job.get("jobid", "")),
                    "total": total_questions,
                    "found": found_answers,
                    "cover_rate": round(cover_rate, 1),
                    "submitted": questions.get("pyFlag") == "",
                    "redo_round": attempt,
                }
            )
            # 组建提交表单
            if questions["pyFlag"] == "1":
                for q in questions["questions"]:
                    questions.update(
                        {
                            f'answer{q["id"]}':
                                q["answerField"][f'answer{q["id"]}'] if q[f'answerSource{q["id"]}'] == "cover" else '',
                            f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                        }
                    )
            else:
                for q in questions["questions"]:
                    questions.update(
                        {
                            f'answer{q["id"]}': q["answerField"][f'answer{q["id"]}'],
                            f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                        }
                    )

            del questions["questions"]

            # 4. 提交
            res = _session.post(
                "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew",
                data=questions,
                headers={
                    "Host": "mooc1.chaoxing.com",
                    "sec-ch-ua-platform": '"Windows"',
                    "X-Requested-With": "XMLHttpRequest",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "sec-ch-ua-mobile": "?0",
                    "Origin": "https://mooc1.chaoxing.com",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
                },
            )
            action = "提交" if questions.get("pyFlag") == "" else "保存"
            if res.status_code == 200:
                try:
                    res_json = res.json()
                except ValueError:
                    logger.error(f'{action}答题失败 -> 非 JSON 响应: {res.text[:200]}')
                    return StudyResult.ERROR
                if res_json.get("status"):
                    logger.info(f'{action}答题成功 -> {res_json.get("msg", "")}')
                else:
                    logger.error(f'{action}答题失败 -> {res_json.get("msg", "")}')
                    return StudyResult.ERROR
            else:
                logger.error(f'{action}答题失败 -> {res.text[:200]}')
                return StudyResult.ERROR

            # 5. 若只是保存未提交，无法判断成绩，保持原有行为
            if questions["pyFlag"] == "1":
                return StudyResult.SUCCESS

            # 6. 提交后检查成绩：若未全部正确，则收集错误反馈并重新作答提交
            result_info = self._check_work_result(_session, _course, _job, _job_info, questions)
            if result_info is None:
                # 无法获取成绩详情（如接口异常），按原行为返回成功，避免误判失败
                return StudyResult.SUCCESS

            score = float(result_info.get("score", 0.0) or 0.0)
            unknown = int(result_info.get("unknown", 0) or 0)
            self.emit_progress(
                {
                    "kind": "work",
                    "phase": "scored",
                    "name": str(_job.get("jobid", "")),
                    "score": score,
                    "all_correct": bool(result_info.get("all_correct", False)),
                    "wrong": len(result_info.get("feedback", []) or []),
                }
            )
            if result_info.get("all_correct", False):
                logger.info(f"章节检测全部正确（成绩 {score} 分），通过！")
                return StudyResult.SUCCESS
            if score >= 99.95:
                # 逐题比对存在格式差异或解析失配, 但满分成绩说明实际全对, 以分数为准
                if unknown > 0:
                    logger.warning(f"成绩 {score} 分达到满分, 以分数为准通过"
                                   f"（{unknown} 题答案字段未能解析, 建议人工复核）")
                else:
                    logger.info(f"逐题比对存在格式差异, 但成绩 {score} 分达到满分, 以分数为准, 通过！")
                return StudyResult.SUCCESS
            if unknown > 0:
                # 解析失配且未达满分: 判定不可信, 不触发重做, 保留已提交成绩
                logger.warning(f"{unknown} 题答案字段解析失败且成绩 {score} 分未达满分, 跳过重做判定")
                return StudyResult.SUCCESS

            # 7. 未全对：收集错误反馈，进入下一轮重做
            feedback_history = result_info.get("feedback", [])
            wrong_count = len(feedback_history)
            if attempt >= max_retries:
                # 已是最后一轮(含单轮模式), 保留已提交成绩, 不再触发无意义的重做
                logger.warning(f"章节检测有 {wrong_count}/{total_questions} 题回答错误（成绩 {score} 分），"
                               f"已保留本次成绩, 请人工检查处理")
                return StudyResult.SUCCESS
            logger.warning(
                f"章节检测有 {wrong_count}/{total_questions} 题回答错误（成绩 {score} 分），"
                f"已将错误反馈给AI，准备重新作答提交 (第 {attempt + 1}/{max_retries + 1} 轮)"
            )
            chapter_rollback_times += 1
            self.rollback_times += 1
            last_submitted_score = score

        # 达到最大重试次数仍未全对
        logger.error(f"章节检测重试 {max_retries + 1} 次仍未全部正确，请人工检查处理")
        return StudyResult.ERROR

    def _check_work_result(self, _session, _course, _job, _job_info, questions) -> Optional[dict]:
        """
        章节检测提交后，查询最新一次作答的成绩与对错详情，供判断是否需要重做。

        Args:
            _session: 当前会话
            _course: 课程信息
            _job: 任务点信息
            questions: 提交时使用的表单数据（含 workId / workAnswerId 等）

        Returns:
            {"all_correct": bool, "feedback": list[str], "score": float, "times": int}
            或 None（无法获取成绩详情时返回 None）
        """
        work_id = str(
            questions.get("workId", "")
            or questions.get("workRelationId", "")
            or _job["jobid"].replace("work-", "")
        )
        work_answer_id = str(questions.get("workAnswerId", "") or "")
        course_id = str(_course.get("courseId", ""))
        class_id = str(_course.get("clazzId", ""))
        cpi = str(_course.get("cpi", "") or questions.get("cpi", ""))

        # 1. 获取作答记录列表（提交后服务端异步生成记录，需稍作等待并多次重试）
        records = None
        for attempt in range(5):
            try:
                resp = _session.get(
                    "https://mooc1.chaoxing.com/mooc-ans/work/record-list",
                    params={
                        "courseId": course_id,
                        "classId": class_id,
                        "workId": work_id,
                        "workAnswerId": work_answer_id,
                        "cpi": cpi,
                        "api": "1",
                        "mooc2": "1",
                        "ut": "s",
                    },
                    timeout=20,
                )
                records = _parse_work_record_list(resp.text)
                if records:
                    break
            except Exception as e:
                logger.warning(f"获取章节检测作答记录失败 (第{attempt + 1}次): {e}")
            if attempt < 4:
                time.sleep(1.5)

        if not records:
            # 兜底：重新访问题目页判断是否已通过（详情页=已提交有成绩；可编辑页=未通过可重做）
            logger.warning("无法获取章节检测作答记录，尝试通过题目页状态判断")
            try:
                resp = _session.get(
                    "https://mooc1.chaoxing.com/mooc-ans/api/work",
                    params={
                        "api": "1",
                        "workId": _job["jobid"].replace("work-", ""),
                        "jobid": _job["jobid"],
                        "originJobId": _job["jobid"],
                        "needRedirect": "true",
                        "skipHeader": "true",
                        "knowledgeid": str(_job_info.get("knowledgeid", "") or _job.get("knowledgeid", "")),
                        "ktoken": str(_job_info.get("ktoken", "") or _job.get("ktoken", "")),
                        "cpi": str(_job_info.get("cpi", "") or _job.get("cpi", "") or cpi),
                        "ut": "s",
                        "clazzId": class_id,
                        "type": "",
                        "enc": str(_job.get("enc", "")),
                        "mooc2": "1",
                        "courseid": course_id,
                    },
                    timeout=20,
                )
                html = resp.text
                if 'answerwqbid' in html:
                    # 可编辑页面：说明未全部正确，可重新作答（该判定为页面状态推断, 未核对实际成绩）
                    logger.warning("题目页仍可编辑, 推断章节检测未全部正确(未核对成绩)")
                    return {
                        "all_correct": False,
                        "feedback": [],
                        "score": 0.0,
                        "times": 0,
                    }
                elif '正确答案' in html and '我的答案' in html:
                    # 已提交详情页：解析成绩与对错
                    detail = _parse_work_record_detail(html)
                    if detail:
                        feedback = []
                        all_correct = True
                        unknown = 0
                        for q in detail:
                            if not q.get("parse_ok", True):
                                unknown += 1
                                all_correct = False
                                continue
                            my_ans = (q.get("my_answer") or "").strip()
                            correct_ans = (q.get("correct_answer") or "").strip()
                            if normalize_answer_text(my_ans) != normalize_answer_text(correct_ans):
                                all_correct = False
                                feedback.append(
                                    f"- 题目：{q.get('title', '')}\n"
                                    f"  题型：{q.get('type_label', '')}\n"
                                    f"  你的上次答案：{my_ans or '(空)'}\n"
                                    f"  正确答案：{correct_ans or '(空)'}"
                                )
                        m = re.search(r'本次成绩<i>([\d.]+)</i>分', html)
                        score = float(m.group(1)) if m else 0.0
                        return {
                            "all_correct": all_correct,
                            "feedback": feedback,
                            "score": score,
                            "times": 0,
                            "unknown": unknown,
                        }
                return None
            except Exception as e:
                logger.warning(f"兜底判断章节检测状态失败: {e}")
                return None

        latest_times = max(r[0] for r in records)
        latest_score = dict(records).get(latest_times, 0.0)

        # 2. 获取最新一次作答详情（含每道题对错与正确答案）
        try:
            resp = _session.get(
                "https://mooc1.chaoxing.com/mooc-ans/work/record-detail",
                params={
                    "courseId": course_id,
                    "classId": class_id,
                    "workId": work_id,
                    "workAnswerId": work_answer_id,
                    "times": str(latest_times),
                    "cpi": cpi,
                    "ut": "s",
                    "isdisplaytable": "0",
                    "firstHeader": "2",
                    "isWork": "false",
                    "workSystem": "0",
                    "api": "1",
                    "archive": "false",
                    "mooc2": "1",
                },
                timeout=20,
            )
            detail = _parse_work_record_detail(resp.text)
        except Exception as e:
            logger.warning(f"获取章节检测作答详情失败: {e}")
            return None

        if not detail:
            logger.warning("章节检测作答详情解析为空，跳过成绩检查")
            return None

        # 3. 逐题判断对错，收集错误反馈（解析失配的题跳过并计数, 避免误判全错）
        feedback = []
        all_correct = True
        unknown = 0
        for q in detail:
            if not q.get("parse_ok", True):
                unknown += 1
                all_correct = False
                continue
            my_ans = (q.get("my_answer") or "").strip()
            correct_ans = (q.get("correct_answer") or "").strip()
            if normalize_answer_text(my_ans) != normalize_answer_text(correct_ans):
                all_correct = False
                feedback.append(
                    f"- 题目：{q.get('title', '')}\n"
                    f"  题型：{q.get('type_label', '')}\n"
                    f"  你的上次答案：{my_ans or '(空)'}\n"
                    f"  正确答案：{correct_ans or '(空)'}"
                )

        logger.debug(f"章节检测成绩: {latest_score} 分, 全部正确: {all_correct}, 错题数: {len(feedback)}, 未解析题数: {unknown}")
        return {
            "all_correct": all_correct,
            "feedback": feedback,
            "score": latest_score,
            "times": latest_times,
            "unknown": unknown,
        }

    def study_read(self, _course, _job, _job_info) -> StudyResult:
        """
        阅读任务学习, 仅完成任务点, 并不增长时长
        """
        _session = SessionManager.get_session()
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/ananas/job/readv2",
            params={
                "jobid": _job["jobid"],
                "knowledgeid": _job_info["knowledgeid"],
                "jtoken": _job["jtoken"],
                "courseid": _course["courseId"],
                "clazzid": _course["clazzId"],
            },
        )
        if _resp.status_code != 200:
            logger.error(f"阅读任务学习失败 -> [{_resp.status_code}]{_resp.text}")
            return StudyResult.ERROR
        try:
            _resp_json = _resp.json()
        except ValueError:
            logger.warning("阅读任务返回非 JSON 内容，按成功处理: {}", _resp.text[:200])
            return StudyResult.SUCCESS
        logger.info(f"阅读任务学习 -> {_resp_json.get('msg', '')}")
        return StudyResult.SUCCESS

    def _send_monitor_heartbeat(self, course, point):
        """
        发送章节监控心跳包到 detect.chaoxing.com。

        模拟真实浏览器的 JSONP 打点请求，佐证访问行为的真人属性。

        Args:
            course: 课程信息字典
            point: 当前章节信息字典
        """
        version = get_timestamp()
        callback = f"jsonp{secrets.randbelow(10**21 - 10**20) + 10**20}"
        params = {
            "version": version,
            "refer": "http://i.mooc.chaoxing.com",
            "from": "",
            "fid": self.get_fid(),
            "jsoncallback": callback,
            "t": get_timestamp(),
        }
        referer_url = (
            f"https://mooc1.chaoxing.com/mycourse/studentstudy?"
            f"chapterId={point['id']}&courseId={course['courseId']}"
            f"&clazzid={course['clazzId']}&cpi={course['cpi']}&mooc2=1"
        )
        try:
            session = SessionManager.get_session()
            resp = session.get(
                "https://detect.chaoxing.com/api/monitor",
                params=params,
                headers={"Referer": referer_url},
                timeout=5,
            )
            logger.trace(f"Monitor heartbeat sent -> {resp.status_code}")
        except Exception as e:
            logger.trace(f"Monitor heartbeat failed (non-critical): {e}")

    def study_emptypage(self, _course, point):
        _session = SessionManager.get_session()
        # &cpi=0&verificationcode=&mooc2=1&microTopicId=0&editorPreview=0
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": _course["courseId"],
                "clazzid": _course["clazzId"],
                "chapterId": point["id"],
                "cpi": _course["cpi"],
                "verificationcode": "",
                "mooc2": 1,
                "microTopicId": 0,
                "editorPreview": 0,
            },
            timeout=8,
        )
        if _resp.status_code != 200:
            logger.error(f"空页面任务失败 -> [{_resp.status_code}]{point['title']}")
            return StudyResult.ERROR
        else:
            logger.info(f"空页面任务完成 -> {point['title']}")
            return StudyResult.SUCCESS

    def _access_chapter_for_count(self, _course, point):
        _session = SessionManager.get_session()
        # &cpi=0&verificationcode=&mooc2=1&microTopicId=0&editorPreview=0
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": _course["courseId"],
                "clazzid": _course["clazzId"],
                "chapterId": point["id"],
                "cpi": _course["cpi"],
                "verificationcode": "",
                "mooc2": 1,
                "microTopicId": 0,
                "editorPreview": 0,
            },
            timeout=8,
        )
        if _resp.status_code != 200:
            logger.error(f"章节访问失败 -> [{_resp.status_code}]{point['title']}")
            return None
        else:
            logger.info(f"章节访问成功 -> {point['title']}")
            return _resp.text

    def _extract_and_send_setlog(self, html_text):
        """
        从 studentstudyAjax 返回的 HTML 中提取 setlog URL 并执行。

        该 URL 包含服务端生成的 encode 参数，是记录章节学习次数的关键 API。

        Args:
            html_text: studentstudyAjax 返回的 HTML 内容
        """
        match = re.search(
            r'<script[^>]+src="(https://fystat-ans\.chaoxing\.com/log/setlog[^"]+)"',
            html_text
        )
        if not match:
            logger.trace("未在响应中找到 setlog URL")
            return

        setlog_url = match.group(1)
        try:
            session = SessionManager.get_session()
            resp = session.get(setlog_url, timeout=5)
            logger.trace(f"Setlog sent -> {resp.status_code}")
        except Exception as e:
            logger.trace(f"Setlog failed (non-critical): {e}")

    def increase_chapter_learning_count(self, course, points, target_count):
        """
        增加课程章节学习次数。

        循环遍历课程的所有章节，每访问一个章节页面：
        1. 调 studentstudyAjax 获取页面 HTML（含服务端生成的 setlog URL）
        2. 提取并执行 setlog URL（记录学习次数）
        3. 立即发送 monitor 心跳包（模拟 fn() 首次心跳）
        4. 停留 30 秒（模拟前端 setInterval(fn, 30000) 的间隔）
        5. 再次发送 monitor 心跳包（模拟 30s 后的第二次心跳）
        6. 计数器 +1，继续下一个章节

        Args:
            course: 课程信息字典
            points: 课程所有章节列表
            target_count: 目标总次数

        Returns:
            StudyResult: 操作结果
        """
        total = 0
        consecutive_failures = 0
        max_consecutive_failures = 10
        try:
            interval = float(self.kwargs.get("learning_count_interval", 30) or 30)
        except (TypeError, ValueError):
            interval = 30.0
        logger.info(f"开始增加章节学习次数, 目标总次数: {target_count}, 章节数: {len(points)}")
        if not points:
            logger.warning("章节列表为空, 跳过章节学习次数增加")
            return StudyResult.SUCCESS
        while total < target_count:
            if self.should_stop():
                logger.info("收到取消请求, 停止章节学习次数增加")
                return StudyResult.ERROR
            for point in points:
                if total >= target_count:
                    break
                if self.should_stop():
                    logger.info("收到取消请求, 停止章节学习次数增加")
                    return StudyResult.ERROR
                self.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)
                html_text = self._access_chapter_for_count(course, point)
                if not html_text:
                    logger.error(f"章节学习次数增加失败, 当前章节: {point['title']}")
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            f"章节学习次数增加连续失败 {consecutive_failures} 次, 终止任务"
                        )
                        return StudyResult.ERROR
                    continue

                consecutive_failures = 0

                # 第 1 步：从 HTML 中提取 setlog URL 并执行（真正的计次 API）
                self._extract_and_send_setlog(html_text)

                # 第 2 步：立即发送 monitor 心跳包（模拟 fn()）
                self._send_monitor_heartbeat(course, point)

                # 第 3 步：停留配置的间隔（默认 30 秒，模拟前端 setInterval 间隔）
                self._sleep(interval)

                # 第 4 步：再次发送 monitor 心跳包（模拟 setInterval 触发的第二次心跳）
                self._send_monitor_heartbeat(course, point)

                total += 1
                logger.info(f"章节学习次数进度: {total}/{target_count}")
        logger.info(f"章节学习次数增加完成, 共完成: {total} 次")
        return StudyResult.SUCCESS
