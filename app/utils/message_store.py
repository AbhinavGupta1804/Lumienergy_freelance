"""
Persist inbound/outbound customer SMS and email for the admin dashboard.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

_MESSAGE_COLUMNS = (
    "id, direction, channel, message_type, body, from_address, to_address, "
    "lead_row_key, lead_name, call_sid, conversation_id, provider_id, status, created_at"
)


class _MessageBackend(Protocol):
    def log_message(self, **kwargs: Any) -> int | None: ...
    def list_messages(
        self,
        *,
        q: str = "",
        direction: str = "all",
        channel: str = "all",
        limit: int = 500,
    ) -> list[dict]: ...


class SqliteMessageBackend:
    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'general',
                    body TEXT NOT NULL,
                    from_address TEXT,
                    to_address TEXT,
                    lead_row_key TEXT,
                    lead_name TEXT,
                    call_sid TEXT,
                    conversation_id TEXT,
                    provider_id TEXT,
                    status TEXT NOT NULL DEFAULT 'sent',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_customer_messages_created_at
                ON customer_messages (created_at DESC)
                """
            )
            conn.commit()

    def log_message(self, **kwargs: Any) -> int | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO customer_messages
                (direction, channel, message_type, body, from_address, to_address,
                 lead_row_key, lead_name, call_sid, conversation_id, provider_id,
                 status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kwargs.get("direction", "outbound"),
                    kwargs.get("channel", "sms"),
                    kwargs.get("message_type", "general"),
                    kwargs.get("body", ""),
                    kwargs.get("from_address"),
                    kwargs.get("to_address"),
                    kwargs.get("lead_row_key"),
                    kwargs.get("lead_name"),
                    kwargs.get("call_sid"),
                    kwargs.get("conversation_id"),
                    kwargs.get("provider_id"),
                    kwargs.get("status", "sent"),
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_messages(
        self,
        *,
        q: str = "",
        direction: str = "all",
        channel: str = "all",
        limit: int = 500,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []

        if direction != "all":
            clauses.append("direction = ?")
            params.append(direction)
        if channel != "all":
            clauses.append("channel = ?")
            params.append(channel)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {_MESSAGE_COLUMNS}
                FROM customer_messages
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        items = [dict(r) for r in rows]
        if q.strip():
            needle = q.strip().lower()
            items = [
                m
                for m in items
                if needle
                in " ".join(
                    str(m.get(k) or "")
                    for k in (
                        "body",
                        "from_address",
                        "to_address",
                        "lead_name",
                        "lead_row_key",
                        "message_type",
                    )
                ).lower()
            ]
        return items


class SupabaseMessageBackend:
    def __init__(self, url: str, service_role_key: str) -> None:
        from supabase import create_client

        self._table = create_client(url, service_role_key).table("customer_messages")

    def log_message(self, **kwargs: Any) -> int | None:
        payload = {
            k: v
            for k, v in {
                "direction": kwargs.get("direction", "outbound"),
                "channel": kwargs.get("channel", "sms"),
                "message_type": kwargs.get("message_type", "general"),
                "body": kwargs.get("body", ""),
                "from_address": kwargs.get("from_address"),
                "to_address": kwargs.get("to_address"),
                "lead_row_key": kwargs.get("lead_row_key"),
                "lead_name": kwargs.get("lead_name"),
                "call_sid": kwargs.get("call_sid"),
                "conversation_id": kwargs.get("conversation_id"),
                "provider_id": kwargs.get("provider_id"),
                "status": kwargs.get("status", "sent"),
            }.items()
            if v is not None
        }
        resp = self._table.insert(payload).execute()
        if resp.data:
            return resp.data[0].get("id")
        return None

    def list_messages(
        self,
        *,
        q: str = "",
        direction: str = "all",
        channel: str = "all",
        limit: int = 500,
    ) -> list[dict]:
        query = self._table.select(_MESSAGE_COLUMNS).order("created_at", desc=True).limit(
            limit
        )
        if direction != "all":
            query = query.eq("direction", direction)
        if channel != "all":
            query = query.eq("channel", channel)
        resp = query.execute()
        items = resp.data or []
        if q.strip():
            needle = q.strip().lower()
            items = [
                m
                for m in items
                if needle
                in " ".join(
                    str(m.get(k) or "")
                    for k in (
                        "body",
                        "from_address",
                        "to_address",
                        "lead_name",
                        "lead_row_key",
                        "message_type",
                    )
                ).lower()
            ]
        return items


class CustomerMessageStore:
    def __init__(self, sqlite_path: str | None = None) -> None:
        settings = get_settings()
        backend = (settings.database_backend or "sqlite").lower()
        if backend == "supabase":
            if not settings.supabase_url or not settings.supabase_service_role_key:
                raise ValueError(
                    "DATABASE_BACKEND=supabase requires SUPABASE_URL and "
                    "SUPABASE_SERVICE_ROLE_KEY"
                )
            self._impl: _MessageBackend = SupabaseMessageBackend(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
        else:
            path = sqlite_path or settings.dedup_db_path
            self._impl = SqliteMessageBackend(path)

    def log_message(self, **kwargs: Any) -> int | None:
        msg_id = self._impl.log_message(**kwargs)
        logger.debug(
            "Logged message id=%s direction=%s channel=%s type=%s",
            msg_id,
            kwargs.get("direction"),
            kwargs.get("channel"),
            kwargs.get("message_type"),
        )
        return msg_id

    def list_messages(self, **kwargs: Any) -> list[dict]:
        return self._impl.list_messages(**kwargs)
