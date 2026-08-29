"""运行历史管理：将每次运行的结果与日志保存到 data/history/ 目录。"""
import json
import os
import time
import uuid
from typing import Dict, List

from ..utils.paths import get_project_root

# 项目根目录（源码运行/打包 exe 时都指向真实数据目录）
PROJECT_ROOT = get_project_root()

HISTORY_DIR = os.path.join(PROJECT_ROOT, "data", "history")


class RunHistory:
    """运行历史的存取工具。"""

    @staticmethod
    def _ensure_dir() -> None:
        os.makedirs(HISTORY_DIR, exist_ok=True)

    @staticmethod
    def new_id() -> str:
        """生成运行ID：时间戳 + 随机后缀，避免冲突"""
        return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    @staticmethod
    def log_path(run_id: str) -> str:
        return os.path.join(HISTORY_DIR, f"{run_id}.log")

    @staticmethod
    def meta_path(run_id: str) -> str:
        return os.path.join(HISTORY_DIR, f"{run_id}.json")

    @staticmethod
    def save(record: Dict) -> None:
        """保存一条运行记录（JSON 元数据）。日志文件由 Runner 单独写入。"""
        RunHistory._ensure_dir()
        path = RunHistory.meta_path(record["id"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_all() -> List[Dict]:
        """按时间倒序返回所有运行记录（不含日志内容）。"""
        RunHistory._ensure_dir()
        records = []
        for name in os.listdir(HISTORY_DIR):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(HISTORY_DIR, name), "r", encoding="utf-8") as f:
                    records.append(json.load(f))
            except Exception:
                continue
        records.sort(key=lambda r: r.get("id", ""), reverse=True)
        return records

    @staticmethod
    def load_log(run_id: str) -> str:
        """读取指定运行的日志内容。"""
        path = RunHistory.log_path(run_id)
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    @staticmethod
    def delete(run_id: str) -> bool:
        """删除一条运行记录（元数据 + 日志）。"""
        try:
            for path in (RunHistory.meta_path(run_id), RunHistory.log_path(run_id)):
                if os.path.exists(path):
                    os.remove(path)
            return True
        except Exception:
            return False
