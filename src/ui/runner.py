"""后台任务管理：在子线程中运行任务，通过队列把日志与状态事件送回 GUI 主线程。

事件格式（dict）：
    {"type": "log", "level": "INFO", "line": "..."}
    {"type": "status", "state": "busy|idle", "kind": "..."}
    {"type": "progress", "text": "..."}
    {"type": "validate", "success": bool, "message": "..."}
    {"type": "done", "record": {运行记录}}
"""
import logging
import queue
import threading
import time
from typing import Callable, Dict, Optional, Tuple

import requests

from ..core.pipeline import run_cookie_refresh, run_pipeline
from ..utils.config import Config
from ..utils.logger import Logger
from ..utils.notification import NotificationService
from ..validators.cookie import CookieValidator
from .history import RunHistory


class LogEmitter(logging.Handler):
    """将 logging 输出同时写入事件队列（供GUI显示）和当前运行的日志文件。"""

    def __init__(self, event_queue: queue.Queue):
        super().__init__(level=logging.DEBUG)
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        ))
        self._queue = event_queue
        self._file = None
        self._file_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._queue.put({"type": "log", "level": record.levelname, "line": line})
            with self._file_lock:
                if self._file is not None:
                    self._file.write(line + "\n")
                    self._file.flush()
        except Exception:
            # 日志系统不允许抛出异常
            pass

    def attach_file(self, path: str) -> None:
        with self._file_lock:
            self._file = open(path, "a", encoding="utf-8")

    def detach_file(self) -> None:
        with self._file_lock:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    def __del__(self):
        try:
            self.detach_file()
        except Exception:
            pass


class RunManager:
    """管理任务运行：开始/结束、状态标记、结果记录。"""

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        self.emitter = LogEmitter(self.queue)
        root = logging.getLogger()
        # 确保 root 级别足够低，能够捕获所有日志
        root.setLevel(logging.DEBUG)
        # 避免重复添加
        if not any(isinstance(h, LogEmitter) for h in root.handlers):
            root.addHandler(self.emitter)
        self.busy = False
        self.cancel_event = threading.Event()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def request_cancel(self) -> None:
        """请求终止当前任务；worker 会在下一个检查点（等待/任务间隙）退出。"""
        self.cancel_event.set()
    def start_pipeline(self) -> bool:
        """启动每日任务流程（后台线程）。返回是否真正启动。"""
        return self._start("任务运行", self._pipeline_worker)

    def start_refresh(self) -> bool:
        """启动 Cookie 刷新流程（后台线程）。返回是否真正启动。"""
        return self._start("Cookie刷新", self._refresh_worker)

    def validate_async(self, music_u: str, csrf: str) -> bool:
        """异步验证 Cookie（只读请求，不评分）。返回是否真正启动。"""
        if self.busy:
            return False
        self.busy = True
        self.cancel_event.clear()

        def work():
            try:
                logger = Logger()
                if self.cancel_event.is_set():
                    logger.warning("Cookie 验证已被用户终止")
                    self._emit(type="validate", success=False, message="验证已被用户终止")
                    return
                session = requests.Session()
                session.cookies.set("MUSIC_U", music_u)
                session.cookies.set("__csrf", csrf)
                is_valid, message = CookieValidator(session, logger).validate()
                if self.cancel_event.is_set():
                    logger.warning("Cookie 验证已被用户终止")
                    self._emit(type="validate", success=False, message="验证已被用户终止")
                    return
                if is_valid:
                    logger.info(f"✅ Cookie验证通过：{message}")
                else:
                    logger.error(f"❌ Cookie验证失败：{message}")
                self._emit(type="validate", success=is_valid, message=message)
            except Exception as e:
                logger = Logger()
                logger.error(f"❌ Cookie验证异常：{str(e)}")
                self._emit(type="validate", success=False, message=str(e))
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()
        return True

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _emit(self, **event) -> None:
        self.queue.put(event)

    def _start(self, kind: str, worker: Callable[[], Tuple[bool, str]]) -> bool:
        """通用启动器：开线程、绑定日志文件、保存运行记录。返回是否真正启动。"""
        if self.busy:
            return False
        self.busy = True
        self.cancel_event.clear()

        def wrapped():
            run_id = RunHistory.new_id()
            log_path = RunHistory.log_path(run_id)
            record = {
                "id": run_id,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "success": False,
                "summary": "",
                "log_file": log_path,
            }
            self.emitter.attach_file(log_path)
            try:
                success, summary = worker()
                record["success"] = bool(success)
                record["summary"] = summary
            except Exception as e:
                try:
                    logging.getLogger(__name__).error(f"运行过程中出现未捕获异常: {str(e)}")
                except Exception:
                    pass
                record["success"] = False
                record["summary"] = f"异常: {str(e)}"
            finally:
                self.emitter.detach_file()
                self.busy = False

            try:
                RunHistory.save(record)
            except Exception:
                pass
            self._emit(type="done", record=record)

        threading.Thread(target=wrapped, daemon=True).start()
        return True

    def _pipeline_worker(self) -> Tuple[bool, str]:
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)

        def on_stage(stage: str, payload: dict) -> None:
            if stage == "account":
                self._emit(type="account", username=payload.get("username", ""))
            else:
                self._emit(type="stats", stage=stage, payload=payload)

        result = run_pipeline(
            config, logger, notifier,
            progress=lambda m: self._emit(type="progress", text=m),
            on_stage=on_stage,
            cancel_event=self.cancel_event,
        )
        # 兜底：若运行结束时仍未上报过用户名（例如旧逻辑），补发一次
        if result.username:
            self._emit(type="account", username=result.username)
        if result.success:
            return True, "执行成功"
        return False, result.reason or "执行失败"

    def _refresh_worker(self) -> Tuple[bool, str]:
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)
        ok = run_cookie_refresh(
            config, logger, notifier,
            progress=lambda m: self._emit(type="progress", text=m),
            cancel_event=self.cancel_event,
        )
        if ok:
            return True, "Cookie刷新成功"
        return False, "Cookie刷新失败（请检查手机号/密码/GitHub配置）"
