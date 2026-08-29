"""共享运行流程：命令行 (main.py) 与图形界面 (gui.py) 复用同一套执行逻辑。"""
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import requests

from ..utils.config import Config
from ..utils.logger import Logger
from ..utils.notification import NotificationService
from ..validators.cookie import CookieValidator
from .bot import MusicPartnerBot
from .exceptions import CANCELLED_REASON, TaskCancelledError
from .tasks.cookie_refresh import CookieRefreshTask


@dataclass
class PipelineResult:
    """一次任务运行的汇总结果。"""
    success: bool
    reason: str = ""
    username: str = ""
    details: Dict = field(default_factory=dict)


ProgressCallback = Optional[Callable[[str], None]]


def run_pipeline(
    config: Config,
    logger: Logger,
    notifier: Optional[NotificationService] = None,
    progress: ProgressCallback = None,
    on_stage: Optional[Callable[[str, Dict], None]] = None,
    cancel_event=None,
) -> PipelineResult:
    """执行完整的音乐合伙人每日任务流程。

    Args:
        config: 配置对象
        logger: 日志对象
        notifier: 通知服务（可选）
        progress: 进度回调函数，用于 UI 显示阶段状态（可选）
        on_stage: 阶段统计回调 on_stage(stage, payload)，用于 UI 显示任务进度（可选）
        cancel_event: 可选的 threading.Event，被 set 时终止任务（可选）

    Returns:
        PipelineResult: 运行结果，包含成功状态、失败原因和用户昵称
    """
    def step(message: str) -> None:
        if progress is not None:
            progress(message)

    def stage(stage_name: str, payload: Dict) -> None:
        if on_stage is not None:
            on_stage(stage_name, payload)

    username = ""
    try:
        step("正在初始化会话...")
        session = requests.Session()
        session.cookies.set("MUSIC_U", config.get("Cookie_MUSIC_U"))
        session.cookies.set("__csrf", config.get("Cookie___csrf"))

        # 验证 Cookie
        step("正在验证 Cookie...")
        validator = CookieValidator(session, logger)
        is_valid, message = validator.validate()

        if not is_valid:
            logger.error(message)
            if notifier is not None:
                notifier.send_notification(
                    "网易云音乐合伙人 - Cookie失效提醒",
                    f"请更新Cookie\n详细信息: {message}"
                )
            return PipelineResult(False, reason=message, username="")

        # 验证用户信息
        step("正在验证用户信息...")
        bot = MusicPartnerBot(config, logger, session)
        profile = bot.get_profile()
        username = profile.get("nickname", "") if profile else ""

        # 立即上报用户名（实时显示，无需等待整个任务流程结束）
        if username:
            stage("account", {"username": username})

        # 处理基础评分任务
        step("正在进行每日评分任务...")
        success = bot.run(profile, progress=stage, cancel_event=cancel_event)

        if not success:
            return PipelineResult(False, reason="任务执行失败，请查看日志", username=username)

        step("任务执行完成")
        return PipelineResult(True, reason="", username=username)

    except TaskCancelledError:
        logger.warning(CANCELLED_REASON)
        return PipelineResult(False, reason=CANCELLED_REASON, username=username)

    except Exception as e:
        logger.error(f"程序异常: {str(e)}")
        if notifier is not None:
            try:
                notifier.send_notification(
                    "网易云音乐合伙人 - 异常提醒",
                    f"程序异常: {str(e)}"
                )
            except Exception as notify_error:
                logger.error(f"发送异常通知时出错: {str(notify_error)}")
        return PipelineResult(False, reason=f"程序异常: {str(e)}", username="")


def prepare_refresh_env(config: Config, env: Optional[Dict] = None) -> None:
    """将配置文件中的登录/GitHub 配置注入环境变量（不覆盖已存在的环境变量）。

    Args:
        config: 配置对象
        env: 目标环境字典，默认使用 os.environ
    """
    mapping = {
        "netease_phone": "NETEASE_PHONE",
        "netease_password": "NETEASE_PASSWORD",
        "netease_md5_password": "NETEASE_MD5_PASSWORD",
        "gh_token": "GH_TOKEN",
        "gh_repo": "GH_REPO",
    }
    target = env if env is not None else os.environ
    for config_key, env_key in mapping.items():
        if not target.get(env_key) and config.get(config_key):
            target[env_key] = config.get(config_key)


def run_cookie_refresh(
    config: Config,
    logger: Logger,
    notifier: Optional[NotificationService] = None,
    progress: ProgressCallback = None,
    cancel_event=None,
) -> bool:
    """执行 Cookie 自动刷新任务（登录并更新 GitHub Secrets）。"""
    def step(message: str) -> None:
        if progress is not None:
            progress(message)

    step("正在准备 Cookie 刷新环境...")
    prepare_refresh_env(config)
    step("正在执行 Cookie 刷新任务...")
    task = CookieRefreshTask(logger, notifier, cancel_event=cancel_event)
    return bool(task.execute())
