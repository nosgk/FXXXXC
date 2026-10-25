import os
import sys

from loguru import logger
from tqdm import tqdm

from api.config import GlobalConst as gc

tqdm_stream = sys.stderr

# 日志缓冲区，用于在手动答题时缓存后台日志，答题结束后统一输出
log_buffer = []
MAX_LOG_BUFFER_SIZE = 1000


def tqdm_sink(msg):
    manual_locked = False
    try:
        # 动态获取 api.answer 模块中的 TikuManual 锁，避免循环导入
        if 'api.answer' in sys.modules:
            TikuManual = getattr(sys.modules['api.answer'], 'TikuManual', None)
            if TikuManual and getattr(TikuManual, '_manual_lock', None):
                manual_locked = TikuManual._manual_lock.locked()
    except (AttributeError, KeyError, ImportError):
        pass

    if manual_locked:
        if len(log_buffer) < MAX_LOG_BUFFER_SIZE:
            log_buffer.append(msg)
    else:
        if log_buffer:
            for buffered_msg in log_buffer:
                tqdm.write(buffered_msg.rstrip(), file=tqdm_stream)
            log_buffer.clear()
        tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()


# 日志等级记录制度：
#   TRACE/DEBUG  常规资源读取、解析等流水账（仅供排障，console 与 GUI 总线不显示）
#   INFO         对用户有意义的过程事件（任务开始/完成、阶段切换、统计）
#   WARNING/ERROR 异常与失败
# 三个出口的默认等级：
#   控制台(tqdm_sink)=INFO，文件=DEBUG（FXXXXC_LOG_LEVEL 可覆盖），
#   GUI 事件总线=INFO（fxxxxc/engine/service.py 的 log sink）。
bus_level = os.environ.get("FXXXXC_LOG_LEVEL", "INFO").upper()
console_level = os.environ.get("FXXXXC_CONSOLE_LOG_LEVEL", "INFO").upper()
file_level = os.environ.get("FXXXXC_LOG_LEVEL", "DEBUG").upper()
try:
    os.makedirs(os.path.dirname(gc.LOG_PATH) or ".", exist_ok=True)
except OSError:
    pass

logger.remove()
logger.add(tqdm_sink, colorize=True, enqueue=True, level=console_level)
logger.add(gc.LOG_PATH, rotation="10 MB", level=file_level)
