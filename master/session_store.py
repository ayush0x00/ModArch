"""Redis-backed session store: conversation turns keyed by session_id with TTL."""
from __future__ import annotations

import json
import uuid
from typing import Any

import config

SESSION_KEY_PREFIX = "session:"


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _session_ttl_seconds() -> int:
    return getattr(config, "REDIS_SESSION_TTL_SECONDS", 86400)


async def create_session(redis: Any) -> str | None:
    """Create a new session (no data yet). Returns session_id or None if redis is None."""
    if redis is None:
        return None
    session_id = str(uuid.uuid4())
    key = _session_key(session_id)
    await redis.setex(key, _session_ttl_seconds(), json.dumps([]))
    return session_id


def get_or_create_session_id(redis: Any, session_id_from_client: str | None) -> str | None:
    """Return client's session_id if valid (non-empty), else None. Does not create; use create_session for that."""
    if redis is None:
        return None
    if session_id_from_client and session_id_from_client.strip():
        return session_id_from_client.strip()
    return None


async def load_session(redis: Any, session_id: str) -> list[dict[str, Any]] | None:
    """Load session turns from Redis. Returns list of turn dicts or None if not found / redis None."""
    if redis is None or not session_id:
        return None
    key = _session_key(session_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


async def append_turn(redis: Any, session_id: str, turn: dict[str, Any]) -> None:
    """Append one turn to the session and refresh TTL. No-op if redis is None or session_id empty."""
    if redis is None or not session_id:
        return
    key = _session_key(session_id)
    raw = await redis.get(key)
    turns: list[dict[str, Any]] = []
    if raw is not None:
        try:
            data = json.loads(raw)
            turns = data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            pass
    turns.append(turn)
    await redis.setex(key, _session_ttl_seconds(), json.dumps(turns))
