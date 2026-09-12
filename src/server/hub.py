"""事件总线：把任务运行过程中的日志/状态事件分发给所有 SSE 订阅者。"""
import queue
import threading
from typing import Dict, List, Optional


class EventHub:
    """线程安全的事件分发中心（发布-订阅）。"""

    def __init__(self, max_queue: int = 2000):
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._max_queue = max_queue

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: Dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                # 订阅者消费过慢时丢弃最旧事件，保证运行不被阻塞
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass
