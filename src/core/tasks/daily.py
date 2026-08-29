from typing import Callable, Dict, Optional, Tuple

from ..signer import Signer
from .base import BaseTask

# 进度回调：progress(stage, payload)，与 Bot 的 StageCallback 一致
ProgressCallback = Optional[Callable[[str, Dict], None]]


class DailyTask(BaseTask):
    def __init__(self, session, logger, config, cancel_event=None):
        super().__init__(session, logger, config, cancel_event)
        self.api = {
            "task_data": "https://interface.music.163.com/api/music/partner/daily/task/get"
        }

    def execute(self) -> bool:
        try:
            complete, task_data = self._get_daily_tasks()
            if not complete:
                self._process_tasks(task_data)
            return True
        except Exception as e:
            self.logger.error(f"执行每日任务失败: {str(e)}")
            return False

    def _get_daily_tasks(self) -> Tuple[bool, Dict]:
        """获取每日任务"""
        response = self.session.get(url=self.api["task_data"]).json()

        # 接口异常（例如限流 code=301、data 为 null）时给出明确错误，
        # 避免后续 AttributeError 导致任务"静默失败"
        if response.get("code") != 200:
            raise RuntimeError(
                f"获取每日任务失败: {response.get('message') or '未知错误'} "
                f"(响应码: {response.get('code')})")

        task_data = response.get("data") or {}

        count = task_data.get("count", 0)
        completed_count = task_data.get("completedCount", 0)
        today_task = f"[{completed_count}/{count}]"
        complete = count == completed_count

        self.logger.info(f'今日任务：{"已完成" if complete else "未完成"}{today_task}')
        return complete, task_data

    def _process_tasks(self, task_data: Dict, progress: ProgressCallback = None) -> None:
        """处理未完成的任务，每完成一首回调一次进度。

        Args:
            task_data: 每日任务数据
            progress: 可选回调 progress("daily", {"count": 总数, "completed": 已完成数})
        """
        self.logger.info("开始评分...")
        works = task_data.get("works") or []
        task_id = task_data.get("id") or ""
        signer = Signer(self.session, task_id, self.logger, self.config,
                        cancel_event=self.cancel_event)

        total = len(works)
        completed = sum(1 for t in works if t.get("completed"))
        if progress:
            progress("daily", {"count": total, "completed": completed})

        for task in works:
            work = task["work"]
            if task.get("completed"):
                self.logger.info(f'{work["name"]}「{work["authorName"]}」已有评分：{int(task["score"])}分')
            else:
                signer.sign(work)
                completed += 1
                if progress:
                    progress("daily", {"count": total, "completed": completed})
