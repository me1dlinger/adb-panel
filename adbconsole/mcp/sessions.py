"""MCP 会话管理：Streamable HTTP 会话与旧版 HTTP+SSE 通道。

每个旧版 SSE 会话持有一个消息队列；POST /messages 的响应写入队列，
由 /sse 的长连接推送给客户端。所有操作线程安全。
"""

from __future__ import annotations

import queue
import threading
import time
import uuid


class McpSession:
    def __init__(self, protocol: str = "", transport: str = "sse") -> None:
        self.id = uuid.uuid4().hex
        self.protocol = protocol or "2024-11-05"
        self.transport = transport
        self.queue: queue.Queue = queue.Queue(maxsize=500)
        self.created = time.time()


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, McpSession] = {}

    def create(self, protocol: str = "", transport: str = "sse") -> McpSession:
        self.prune()
        session = McpSession(protocol, transport)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> McpSession | None:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            # 唤醒可能阻塞在队列上的 SSE 生成器，使其退出。
            try:
                session.queue.put_nowait(None)
            except queue.Full:
                pass

    def push(self, session_id: str, message: dict) -> bool:
        session = self.get(session_id)
        if session is None:
            return False
        try:
            session.queue.put_nowait(message)
        except queue.Full:
            return False
        return True

    def prune(self, max_age: float = 3600.0) -> None:
        cutoff = time.time() - max_age
        with self._lock:
            stale = [sid for sid, session in self._sessions.items() if session.created < cutoff]
            for sid in stale:
                self._sessions.pop(sid, None)


sessions = SessionStore()
