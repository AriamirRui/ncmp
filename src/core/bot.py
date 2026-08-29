from typing import Callable, Dict, Optional

import requests

from ..utils.config import Config
from ..utils.logger import Logger
from .exceptions import TaskCancelledError
from .tasks.daily import DailyTask
from .tasks.extra import ExtraTask

# 进度回调签名：callback(stage: str, payload: dict)
StageCallback = Optional[Callable[[str, Dict], None]]


class MusicPartnerBot:
    def __init__(self, config: Config, logger: Logger, session: requests.Session):
        self.config = config
        self.logger = logger
        self.session = session
        self.api = {
            "user_info": "https://music.163.com/api/nuser/account/get",
        }

    def run(self, profile: Dict = None, progress: StageCallback = None,
            cancel_event=None) -> bool:
        try:
            # profile 为 None 时自动验证用户信息（避免重复请求）
            if profile is None:
                self.get_profile()

            # 处理基础评分任务
            daily_task = DailyTask(self.session, self.logger, self.config,
                                   cancel_event=cancel_event)
            complete, task_data = daily_task._get_daily_tasks()
            if progress:
                progress("daily", {
                    "count": int((task_data or {}).get("count", 0)),
                    "completed": int((task_data or {}).get("completedCount", 0)),
                })
            if not complete:
                daily_task._process_tasks(task_data, progress=progress)

            # 处理额外评分任务（task_data 可能缺少 id，做防御）
            extra_task = ExtraTask(self.session, self.logger, self.config,
                                   cancel_event=cancel_event)
            extra_task.process_extra_tasks(str((task_data or {}).get("id", "")),
                                           progress=progress)

            return True

        except TaskCancelledError:
            raise
        except Exception as e:
            self.logger.error(f"执行失败: {str(e)}")
            return False

    def get_profile(self) -> Dict:
        """获取并验证用户信息，返回用户资料字典"""
        try:
            self.logger.info("开始验证用户信息...")
            response = self.session.get(url=self.api["user_info"]).json()

            profile = response.get("profile")
            if profile:
                self.logger.info(f'用户名: {profile["nickname"]}')
                return profile
            else:
                raise RuntimeError("获取用户信息失败")

        except Exception as e:
            raise RuntimeError(f"验证用户信息失败: {str(e)}")

    def _verify_user(self) -> Dict:
        """兼容旧接口：验证用户信息并返回资料"""
        return self.get_profile()
