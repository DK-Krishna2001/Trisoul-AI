"""One-time authorization for user-confirmed emergency-contact calls."""

from __future__ import annotations

import secrets
import threading
import time


class EmergencyCallAuthorizer:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._actions: dict[str, tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str, session_id: str) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            self._remove_expired_locked()
            self._actions[token] = (user_id, session_id, expires_at)
        return token

    def consume(self, token: str, user_id: str, session_id: str) -> bool:
        with self._lock:
            self._remove_expired_locked()
            action = self._actions.get(token)
            if not action or action[0] != user_id or action[1] != session_id:
                return False
            del self._actions[token]

        return True

    def _remove_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [token for token, (_, _, expires_at) in self._actions.items() if expires_at <= now]
        for token in expired:
            del self._actions[token]
