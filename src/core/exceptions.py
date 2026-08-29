"""任务进程相关内容：手动终止异常与可中断睡眠。"""
import time
from typing import Optional

# 终止原因的统一文案（runner / pipeline / UI 共用）
CANCELLED_REASON = "任务已被用户终止"


class TaskCancelledError(Exception):
    """任务被用户（UI）主动终止时抛出。"""


def sleep_interruptible(seconds: float, cancel_event=None) -> None:
    """可中断睡眠：cancel_event 被 set 时立即抛出 TaskCancelledError。

    Args:
        seconds: 需要等待的秒数
        cancel_event: 可选 threading.Event；被 set 时中断等待
    """
    end = time.time() + max(0.0, float(seconds))
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelledError(CANCELLED_REASON)
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))
