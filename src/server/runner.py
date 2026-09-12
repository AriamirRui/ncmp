"""任务运行器：在后台线程执行任务流程，并把日志/状态通过 EventHub 广播给 Web 前端。"""
import logging
import threading
import time
from typing import Callable, Dict, Optional, Tuple

import requests

from ..core.exceptions import CANCELLED_REASON
from ..core.pipeline import run_cookie_refresh, run_pipeline
from ..store.history import RunHistory
from ..utils.config import Config
from ..utils.logger import Logger
from ..utils.notification import NotificationService
from ..validators.cookie import CookieValidator
from .hub import EventHub

USER_INFO_URL = "https://music.163.com/api/nuser/account/get"


class HubLogHandler(logging.Handler):
    """把 logging 输出转发到事件流，并同时写入当前运行的日志文件。"""

    def __init__(self, hub: EventHub):
        super().__init__(level=logging.DEBUG)
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        self._hub = hub
        self._file = None
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._hub.publish({
                "type": "log",
                "level": record.levelname,
                "line": line,
                "ts": time.time(),
            })
            with self._lock:
                if self._file is not None:
                    self._file.write(line + "\n")
                    self._file.flush()
        except Exception:
            pass

    def attach_file(self, path: str) -> None:
        with self._lock:
            self._file = open(path, "a", encoding="utf-8")

    def detach_file(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None


def _empty_stats() -> Dict:
    return {
        "daily": {"count": 0, "completed": 0},
        "extra": {"max": 15, "done": 0},
    }


class TaskRunner:
    """管理任务运行状态、日志广播与运行历史。"""

    def __init__(self, hub: EventHub):
        self.hub = hub
        self.emitter = HubLogHandler(hub)
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        if not any(isinstance(h, HubLogHandler) for h in root.handlers):
            root.addHandler(self.emitter)

        self.busy = False
        self.kind = ""
        self.cancel_event = threading.Event()
        self.username = ""
        self.stats = _empty_stats()
        self.last_result: Optional[Dict] = None
        self.current_run_id: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict:
        return {
            "busy": self.busy,
            "kind": self.kind,
            "username": self.username,
            "stats": self.stats,
            "last_result": self.last_result,
            "cancel_requested": self.cancel_event.is_set(),
            "current_run_id": self.current_run_id,
            "subscribers": self.hub.subscriber_count(),
        }

    def publish_state(self) -> None:
        self.hub.publish({"type": "state", "state": self.snapshot()})

    # ------------------------------------------------------------------
    # Cookie 验证（同步，供前端点击"验证"时调用）
    # ------------------------------------------------------------------
    def validate(self, music_u: str, csrf: str) -> Dict:
        logger = Logger()
        try:
            if not music_u or not csrf:
                return {"valid": False, "message": "Cookie 不完整", "nickname": ""}

            session = requests.Session()
            session.cookies.set("MUSIC_U", music_u)
            session.cookies.set("__csrf", csrf)

            valid, message = CookieValidator(session, logger).validate()
            nickname = ""
            if valid:
                try:
                    profile = (session.get(USER_INFO_URL).json() or {}).get("profile") or {}
                    nickname = profile.get("nickname", "")
                except Exception:
                    nickname = ""
                if nickname:
                    self.username = nickname
            logger.info(f"{'✅' if valid else '❌'} Cookie 验证结果：{message}")
            self.publish_state()
            return {"valid": bool(valid), "message": message, "nickname": nickname}
        except Exception as e:
            logger.error(f"❌ Cookie 验证异常：{str(e)}")
            return {"valid": False, "message": f"验证异常: {e}", "nickname": ""}

    # ------------------------------------------------------------------
    # 运行控制
    # ------------------------------------------------------------------
    def start_pipeline(self) -> bool:
        return self._start("任务运行", self._pipeline_worker)

    def start_refresh(self) -> bool:
        return self._start("Cookie刷新", self._refresh_worker)

    def cancel(self) -> bool:
        if not self.busy:
            return False
        self.cancel_event.set()
        logging.getLogger(__name__).warning(f"⏹ 收到终止请求，正在停止{self.kind}…")
        self.publish_state()
        return True

    def _start(self, kind: str, worker: Callable[[], Tuple[bool, str]]) -> bool:
        with self._lock:
            if self.busy:
                return False
            self.busy = True
            self.kind = kind
            self.cancel_event.clear()
            self.stats = _empty_stats()
        self.publish_state()
        threading.Thread(target=self._run_wrapper, args=(kind, worker), daemon=True).start()
        return True

    def _run_wrapper(self, kind: str, worker: Callable[[], Tuple[bool, str]]) -> None:
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
        with self._lock:
            self.current_run_id = run_id
        self.emitter.attach_file(log_path)
        try:
            success, summary = worker()
            record["success"] = bool(success)
            record["summary"] = summary
        except Exception as e:
            logging.getLogger(__name__).error(f"运行过程中出现未捕获异常: {str(e)}")
            record["success"] = False
            record["summary"] = f"异常: {e}"
        finally:
            self.emitter.detach_file()
            with self._lock:
                self.busy = False
                self.kind = ""
                self.current_run_id = None

        try:
            RunHistory.save(record)
        except Exception:
            pass

        self.last_result = {
            "success": record["success"],
            "summary": record["summary"],
            "kind": kind,
            "time": record["time"],
            "run_id": run_id,
        }
        self.hub.publish({"type": "done", "record": record})
        self.publish_state()

    # ------------------------------------------------------------------
    # 后台 worker
    # ------------------------------------------------------------------
    def _pipeline_worker(self) -> Tuple[bool, str]:
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)

        def on_stage(stage: str, payload: dict) -> None:
            if stage == "account":
                self.username = payload.get("username", "") or self.username
                self.hub.publish({"type": "account", "username": self.username})
            else:
                self._apply_stats(stage, payload)
                self.hub.publish({"type": "stats", "stage": stage, "payload": payload})

        result = run_pipeline(
            config, logger, notifier,
            progress=lambda m: self.hub.publish({"type": "progress", "text": m}),
            on_stage=on_stage,
            cancel_event=self.cancel_event,
        )
        if result.username:
            self.username = result.username
        if result.success:
            return True, "执行成功"
        return False, result.reason or "执行失败"

    def _refresh_worker(self) -> Tuple[bool, str]:
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)
        ok = run_cookie_refresh(
            config, logger, notifier,
            progress=lambda m: self.hub.publish({"type": "progress", "text": m}),
            cancel_event=self.cancel_event,
        )
        if ok:
            return True, "Cookie刷新成功"
        return False, "Cookie刷新失败（请检查手机号/密码/GitHub配置）"

    def _apply_stats(self, stage: str, payload: Dict) -> None:
        try:
            if stage == "daily":
                self.stats["daily"] = {
                    "count": int(payload.get("count", 0) or 0),
                    "completed": int(payload.get("completed", 0) or 0),
                }
            elif stage == "extra_meta":
                self.stats["extra"] = {
                    "max": int(payload.get("max", 15) or 15),
                    "done": int(payload.get("completed", 0) or 0),
                }
            elif stage == "extra_progress":
                self.stats["extra"] = {
                    "max": int(payload.get("max", 15) or 15),
                    "done": int(payload.get("done", 0) or 0),
                }
        except Exception:
            pass


__all__ = ["CANCELLED_REASON", "HubLogHandler", "TaskRunner"]
