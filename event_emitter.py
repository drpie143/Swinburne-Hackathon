# ====================================================================
# EVENT EMITTER - Real-time pipeline events via WebSocket
# ====================================================================

import json
import asyncio
from typing import Dict, Set, Callable, Any
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class PipelineEvent:
    """Event được gửi qua WebSocket khi pipeline step thay đổi."""
    transaction_id: str
    step: str           # submit, phase1, routing, planner, executor, vision, evaluate, report, detective, decision
    status: str         # active, done, error, skipped
    detail: str         # Mô tả chi tiết
    data: dict = None   # Dữ liệu bổ sung (optional)
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class PipelineEventEmitter:
    """
    Singleton event emitter cho pipeline.

    Backend gọi emit() khi mỗi step thay đổi.
    WebSocket connections listen và nhận events real-time.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._connections: Dict[str, Set[asyncio.Queue]] = {}  # transaction_id -> set of queues
        self._global_connections: Set[asyncio.Queue] = set()   # listen to all events
        self._initialized = True

    def subscribe(self, transaction_id: str = None) -> asyncio.Queue:
        """
        Subscribe để nhận events.

        Args:
            transaction_id: Nếu có, chỉ nhận events của transaction đó.
                           Nếu None, nhận tất cả events.

        Returns:
            asyncio.Queue để await events
        """
        queue = asyncio.Queue()

        if transaction_id:
            if transaction_id not in self._connections:
                self._connections[transaction_id] = set()
            self._connections[transaction_id].add(queue)
        else:
            self._global_connections.add(queue)

        return queue

    def unsubscribe(self, queue: asyncio.Queue, transaction_id: str = None):
        """Hủy subscription."""
        if transaction_id and transaction_id in self._connections:
            self._connections[transaction_id].discard(queue)
            if not self._connections[transaction_id]:
                del self._connections[transaction_id]
        else:
            self._global_connections.discard(queue)

    def emit(self, event: PipelineEvent):
        """
        Emit event đến tất cả subscribers.

        Gọi từ synchronous code (orchestrator nodes).
        """
        # Log to console
        status_icons = {'active': '⏳', 'done': '✅', 'error': '❌', 'skipped': '⏭️'}
        icon = status_icons.get(event.status, '•')
        print(f"   {icon} [{event.step.upper()}] {event.status}: {event.detail[:80]}")

        # Queue event for async delivery
        # Send to transaction-specific subscribers
        if event.transaction_id in self._connections:
            for queue in self._connections[event.transaction_id]:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        # Send to global subscribers
        for queue in self._global_connections:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def emit_step(self, transaction_id: str, step: str, status: str, detail: str, data: dict = None):
        """Helper để emit event nhanh."""
        self.emit(PipelineEvent(
            transaction_id=transaction_id,
            step=step,
            status=status,
            detail=detail,
            data=data,
        ))


# Singleton instance
event_emitter = PipelineEventEmitter()
