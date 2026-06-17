"""
Lead / call persistence — SQLite (local) or Supabase Postgres (cloud).

Set DATABASE_BACKEND=supabase and Supabase credentials in .env to use cloud.
Otherwise uses SQLite at DEDUP_DB_PATH (default data/processed_leads.db).
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

_PROCESSED_LEADS_COLUMNS = (
    "row_key, row_number, name, address, call_sid, conversation_id, "
    "phone_no, dial_to, sms_eligible, sms_sent, status, processed_at, "
    "call_duration_secs, call_successful, transcript_summary, "
    "termination_reason, call_ended_at, cal_booking_uid, google_event_uid, "
    "appointment_start, appointment_label, upload_token, confirmation_sms_sent"
)


class _DedupBackend(Protocol):
    def is_processed(self, row_key: str) -> bool: ...
    def mark_processed(self, **kwargs: Any) -> None: ...
    def get_by_call_sid(self, call_sid: str) -> dict | None: ...
    def get_by_conversation_id(self, conversation_id: str) -> dict | None: ...
    def mark_sms_eligible(
        self, phone: str, *, conversation_id: str | None = None
    ) -> dict | None: ...
    def get_pending_sms_eligible_by_phone(self, phone: str) -> dict | None: ...
    def claim_sms_send(self, call_sid: str) -> bool: ...
    def release_sms_send(self, call_sid: str) -> None: ...
    def mark_sms_sent(self, call_sid: str) -> None: ...
    def set_upload_token(self, call_sid: str, token: str) -> None: ...
    def update_post_call_analytics(self, **kwargs: Any) -> bool: ...
    def set_cal_booking(
        self,
        *,
        conversation_id: str,
        cal_booking_uid: str,
        google_event_uid: str | None = None,
        appointment_start: str | None = None,
        appointment_label: str | None = None,
    ) -> bool: ...
    def get_by_upload_token(self, upload_token: str) -> dict | None: ...
    def claim_confirmation_sms_send(self, row_key: str) -> bool: ...
    def release_confirmation_sms_send(self, row_key: str) -> None: ...
    def get_latest_called_by_phone(self, phone: str) -> dict | None: ...
    def list_processed(self, limit: int = 50) -> list[dict]: ...


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    return dict(row)


class SqliteDedupBackend:
    """Local SQLite file (development / fallback)."""

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
                CREATE TABLE IF NOT EXISTS processed_leads (
                    row_key TEXT PRIMARY KEY,
                    row_number INTEGER NOT NULL,
                    name TEXT,
                    address TEXT,
                    call_sid TEXT,
                    conversation_id TEXT,
                    status TEXT NOT NULL DEFAULT 'called',
                    processed_at TEXT NOT NULL,
                    phone_no TEXT,
                    dial_to TEXT,
                    sms_eligible INTEGER NOT NULL DEFAULT 0,
                    sms_sent INTEGER NOT NULL DEFAULT 0,
                    call_duration_secs INTEGER,
                    call_successful TEXT,
                    transcript_summary TEXT,
                    termination_reason TEXT,
                    call_ended_at TEXT
                )
                """
            )
            self._migrate_columns(conn)
            conn.commit()

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(processed_leads)")}
        additions = {
            "phone_no": "TEXT",
            "dial_to": "TEXT",
            "sms_eligible": "INTEGER NOT NULL DEFAULT 0",
            "sms_sent": "INTEGER NOT NULL DEFAULT 0",
            "call_duration_secs": "INTEGER",
            "call_successful": "TEXT",
            "transcript_summary": "TEXT",
            "termination_reason": "TEXT",
            "call_ended_at": "TEXT",
            "upload_token": "TEXT",
            "upload_token_used": "INTEGER NOT NULL DEFAULT 0",
            "cal_booking_uid": "TEXT",
            "google_event_uid": "TEXT",
            "appointment_start": "TEXT",
            "appointment_label": "TEXT",
            "confirmation_sms_sent": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, typedef in additions.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE processed_leads ADD COLUMN {col} {typedef}")

    def is_processed(self, row_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_leads WHERE row_key = ?",
                (row_key,),
            ).fetchone()
        return row is not None

    def mark_processed(
        self,
        *,
        row_key: str,
        row_number: int,
        name: str,
        address: str,
        call_sid: str | None = None,
        conversation_id: str | None = None,
        phone_no: str | None = None,
        dial_to: str | None = None,
        status: str = "called",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_leads
                (row_key, row_number, name, address, call_sid, conversation_id,
                 phone_no, dial_to, sms_eligible, sms_sent, status, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    row_key,
                    row_number,
                    name,
                    address,
                    call_sid,
                    conversation_id,
                    phone_no,
                    dial_to,
                    status,
                    now,
                ),
            )
            conn.commit()
        logger.info("Marked row_key=%s as processed (status=%s)", row_key, status)

    def get_by_call_sid(self, call_sid: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads WHERE call_sid = ?
                """,
                (call_sid,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def get_by_conversation_id(self, conversation_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads WHERE conversation_id = ?
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def mark_sms_eligible(
        self,
        phone: str,
        *,
        conversation_id: str | None = None,
    ) -> dict | None:
        with self._connect() as conn:
            if conversation_id:
                row = conn.execute(
                    """
                    SELECT row_key, call_sid, conversation_id, dial_to, phone_no
                    FROM processed_leads
                    WHERE conversation_id = ? AND sms_sent = 0
                    ORDER BY processed_at DESC
                    LIMIT 1
                    """,
                    (conversation_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT row_key, call_sid, conversation_id, dial_to, phone_no
                    FROM processed_leads
                    WHERE (dial_to = ? OR phone_no = ?)
                      AND call_sid IS NOT NULL AND sms_sent = 0
                    ORDER BY processed_at DESC
                    LIMIT 1
                    """,
                    (phone, phone),
                ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE processed_leads SET sms_eligible = 1 WHERE row_key = ?",
                (row["row_key"],),
            )
            conn.commit()
        return _row_to_dict(row)

    def get_pending_sms_eligible_by_phone(self, phone: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE (dial_to = ? OR phone_no = ?)
                  AND sms_eligible = 1 AND sms_sent = 0
                  AND call_sid IS NOT NULL
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (phone, phone),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def claim_sms_send(self, call_sid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads SET sms_sent = 1
                WHERE call_sid = ? AND sms_sent = 0
                """,
                (call_sid,),
            )
            conn.commit()
            claimed = cur.rowcount > 0
        if claimed:
            logger.debug("Claimed SMS send slot for call_sid=%s", call_sid)
        return claimed

    def release_sms_send(self, call_sid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_leads SET sms_sent = 0 WHERE call_sid = ?",
                (call_sid,),
            )
            conn.commit()

    def mark_sms_sent(self, call_sid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_leads SET sms_sent = 1 WHERE call_sid = ?",
                (call_sid,),
            )
            conn.commit()

    def set_upload_token(self, call_sid: str, token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_leads SET upload_token = ? WHERE call_sid = ?",
                (token, call_sid),
            )
            conn.commit()
        logger.debug("Upload token stored for call_sid=%s", call_sid)

    def update_post_call_analytics(
        self,
        *,
        conversation_id: str,
        call_duration_secs: int | None = None,
        call_successful: str | None = None,
        transcript_summary: str | None = None,
        termination_reason: str | None = None,
        call_ended_at: str | None = None,
    ) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET call_duration_secs = ?,
                    call_successful = ?,
                    transcript_summary = ?,
                    termination_reason = ?,
                    call_ended_at = ?
                WHERE conversation_id = ?
                """,
                (
                    call_duration_secs,
                    call_successful,
                    transcript_summary,
                    termination_reason,
                    call_ended_at,
                    conversation_id,
                ),
            )
            conn.commit()
            updated = cur.rowcount > 0
        if updated:
            logger.info(
                "Saved post-call analytics conversation_id=%s duration=%ss successful=%s",
                conversation_id,
                call_duration_secs,
                call_successful,
            )
        else:
            logger.warning(
                "No DB row for post-call analytics conversation_id=%s",
                conversation_id,
            )
        return updated

    def set_cal_booking(
        self,
        *,
        conversation_id: str,
        cal_booking_uid: str,
        google_event_uid: str | None = None,
        appointment_start: str | None = None,
        appointment_label: str | None = None,
    ) -> bool:
        sets = ["cal_booking_uid = ?", "google_event_uid = ?"]
        params: list[Any] = [cal_booking_uid, google_event_uid]
        if appointment_start is not None:
            sets.append("appointment_start = ?")
            params.append(appointment_start)
        if appointment_label is not None:
            sets.append("appointment_label = ?")
            params.append(appointment_label)
        params.append(conversation_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE processed_leads
                SET {", ".join(sets)}
                WHERE conversation_id = ?
                """,
                tuple(params),
            )
            conn.commit()
            updated = cur.rowcount > 0
        if updated:
            logger.info(
                "Stored Cal booking conversation_id=%s uid=%s appointment=%s",
                conversation_id,
                cal_booking_uid,
                appointment_label,
            )
        return updated

    def get_by_upload_token(self, upload_token: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_PROCESSED_LEADS_COLUMNS} FROM processed_leads WHERE upload_token = ?",
                (upload_token,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def claim_confirmation_sms_send(self, row_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads SET confirmation_sms_sent = 1
                WHERE row_key = ? AND confirmation_sms_sent = 0
                """,
                (row_key,),
            )
            conn.commit()
            return cur.rowcount > 0

    def release_confirmation_sms_send(self, row_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_leads SET confirmation_sms_sent = 0 WHERE row_key = ?",
                (row_key,),
            )
            conn.commit()

    def get_latest_called_by_phone(self, phone: str) -> dict | None:
        digits = "".join(c for c in phone if c.isdigit())
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM processed_leads
                WHERE status = 'called'
                  AND (
                    REPLACE(REPLACE(REPLACE(phone_no, '+', ''), ' ', ''), '-', '') = ?
                    OR REPLACE(REPLACE(REPLACE(dial_to, '+', ''), ' ', ''), '-', '') = ?
                  )
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (digits, digits),
            ).fetchall()
        return _row_to_dict(rows[0]) if rows else None

    def list_processed(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT row_key, row_number, name, address, call_sid, conversation_id,
                       status, processed_at
                FROM processed_leads
                ORDER BY processed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def _pg_eq_value(value: str) -> str:
    """Quote PostgREST filter values (E.164 phones contain '+')."""
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


class SupabaseDedupBackend:
    """Supabase Postgres via service role (server-side only)."""

    def __init__(self, url: str, service_role_key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, service_role_key)
        self._table = self._client.table("processed_leads")
        logger.info("DedupStore using Supabase Postgres")

    @staticmethod
    def _phone_or_filter(phone: str) -> str:
        q = _pg_eq_value(phone)
        return f"dial_to.eq.{q},phone_no.eq.{q}"

    def is_processed(self, row_key: str) -> bool:
        resp = self._table.select("row_key").eq("row_key", row_key).limit(1).execute()
        return bool(resp.data)

    def mark_processed(
        self,
        *,
        row_key: str,
        row_number: int,
        name: str,
        address: str,
        call_sid: str | None = None,
        conversation_id: str | None = None,
        phone_no: str | None = None,
        dial_to: str | None = None,
        status: str = "called",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._table.upsert(
            {
                "row_key": row_key,
                "row_number": row_number,
                "name": name,
                "address": address,
                "call_sid": call_sid,
                "conversation_id": conversation_id,
                "phone_no": phone_no,
                "dial_to": dial_to,
                "sms_eligible": False,
                "sms_sent": False,
                "status": status,
                "processed_at": now,
            },
            on_conflict="row_key",
        ).execute()
        logger.info("Marked row_key=%s as processed (status=%s)", row_key, status)

    def get_by_call_sid(self, call_sid: str) -> dict | None:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("call_sid", call_sid)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def get_by_conversation_id(self, conversation_id: str) -> dict | None:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("conversation_id", conversation_id)
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def mark_sms_eligible(
        self,
        phone: str,
        *,
        conversation_id: str | None = None,
    ) -> dict | None:
        if conversation_id:
            resp = (
                self._table.select("row_key, call_sid, conversation_id, dial_to, phone_no")
                .eq("conversation_id", conversation_id)
                .eq("sms_sent", False)
                .order("processed_at", desc=True)
                .limit(1)
                .execute()
            )
        else:
            resp = (
                self._table.select("row_key, call_sid, conversation_id, dial_to, phone_no")
                .eq("sms_sent", False)
                .or_(self._phone_or_filter(phone))
                .not_.is_("call_sid", "null")
                .order("processed_at", desc=True)
                .limit(1)
                .execute()
            )
        if not resp.data:
            return None
        row = resp.data[0]
        self._table.update({"sms_eligible": True}).eq("row_key", row["row_key"]).execute()
        return row

    def get_pending_sms_eligible_by_phone(self, phone: str) -> dict | None:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("sms_eligible", True)
            .eq("sms_sent", False)
            .or_(self._phone_or_filter(phone))
            .not_.is_("call_sid", "null")
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def claim_sms_send(self, call_sid: str) -> bool:
        resp = (
            self._table.update({"sms_sent": True})
            .eq("call_sid", call_sid)
            .eq("sms_sent", False)
            .execute()
        )
        claimed = bool(resp.data)
        if claimed:
            logger.debug("Claimed SMS send slot for call_sid=%s", call_sid)
        return claimed

    def release_sms_send(self, call_sid: str) -> None:
        self._table.update({"sms_sent": False}).eq("call_sid", call_sid).execute()

    def mark_sms_sent(self, call_sid: str) -> None:
        self._table.update({"sms_sent": True}).eq("call_sid", call_sid).execute()

    def set_upload_token(self, call_sid: str, token: str) -> None:
        self._table.update({"upload_token": token}).eq("call_sid", call_sid).execute()
        logger.debug("Upload token stored for call_sid=%s", call_sid)

    def update_post_call_analytics(
        self,
        *,
        conversation_id: str,
        call_duration_secs: int | None = None,
        call_successful: str | None = None,
        transcript_summary: str | None = None,
        termination_reason: str | None = None,
        call_ended_at: str | None = None,
    ) -> bool:
        payload = {
            k: v
            for k, v in {
                "call_duration_secs": call_duration_secs,
                "call_successful": call_successful,
                "transcript_summary": transcript_summary,
                "termination_reason": termination_reason,
                "call_ended_at": call_ended_at,
            }.items()
            if v is not None
        }
        if not payload:
            return False
        resp = (
            self._table.update(payload)
            .eq("conversation_id", conversation_id)
            .execute()
        )
        updated = bool(resp.data)
        if updated:
            logger.info(
                "Saved post-call analytics conversation_id=%s duration=%ss successful=%s",
                conversation_id,
                call_duration_secs,
                call_successful,
            )
        else:
            logger.warning(
                "No DB row for post-call analytics conversation_id=%s",
                conversation_id,
            )
        return updated

    def set_cal_booking(
        self,
        *,
        conversation_id: str,
        cal_booking_uid: str,
        google_event_uid: str | None = None,
        appointment_start: str | None = None,
        appointment_label: str | None = None,
    ) -> bool:
        payload: dict[str, Any] = {
            "cal_booking_uid": cal_booking_uid,
            "google_event_uid": google_event_uid,
        }
        if appointment_start is not None:
            payload["appointment_start"] = appointment_start
        if appointment_label is not None:
            payload["appointment_label"] = appointment_label
        resp = (
            self._table.update(payload)
            .eq("conversation_id", conversation_id)
            .execute()
        )
        updated = bool(resp.data)
        if updated:
            logger.info(
                "Stored Cal booking conversation_id=%s uid=%s appointment=%s",
                conversation_id,
                cal_booking_uid,
                appointment_label,
            )
        return updated

    def get_by_upload_token(self, upload_token: str) -> dict | None:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("upload_token", upload_token)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def claim_confirmation_sms_send(self, row_key: str) -> bool:
        resp = (
            self._table.update({"confirmation_sms_sent": True})
            .eq("row_key", row_key)
            .eq("confirmation_sms_sent", False)
            .execute()
        )
        return bool(resp.data)

    def release_confirmation_sms_send(self, row_key: str) -> None:
        self._table.update({"confirmation_sms_sent": False}).eq("row_key", row_key).execute()

    def get_latest_called_by_phone(self, phone: str) -> dict | None:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return None
        for col in ("phone_no", "dial_to"):
            resp = (
                self._table.select("*")
                .eq("status", "called")
                .like(col, f"%{digits}%")
                .order("processed_at", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0]
        return None

    def list_processed(self, limit: int = 50) -> list[dict]:
        resp = (
            self._table.select(
                "row_key, row_number, name, address, call_sid, conversation_id, status, processed_at"
            )
            .order("processed_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []


class DedupStore:
    """Facade — picks SQLite or Supabase from settings."""

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        backend = (settings.database_backend or "sqlite").lower()

        if backend == "supabase":
            if not settings.supabase_url or not settings.supabase_service_role_key:
                raise ValueError(
                    "DATABASE_BACKEND=supabase requires SUPABASE_URL and "
                    "SUPABASE_SERVICE_ROLE_KEY"
                )
            self._impl: _DedupBackend = SupabaseDedupBackend(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
        else:
            path = db_path or settings.dedup_db_path
            self._impl = SqliteDedupBackend(path)
            logger.info("DedupStore using SQLite at %s", path)

    def is_processed(self, row_key: str) -> bool:
        return self._impl.is_processed(row_key)

    def mark_processed(self, **kwargs: Any) -> None:
        self._impl.mark_processed(**kwargs)

    def get_by_call_sid(self, call_sid: str) -> dict | None:
        return self._impl.get_by_call_sid(call_sid)

    def get_by_conversation_id(self, conversation_id: str) -> dict | None:
        return self._impl.get_by_conversation_id(conversation_id)

    def mark_sms_eligible(
        self, phone: str, *, conversation_id: str | None = None
    ) -> dict | None:
        return self._impl.mark_sms_eligible(phone, conversation_id=conversation_id)

    def get_pending_sms_eligible_by_phone(self, phone: str) -> dict | None:
        return self._impl.get_pending_sms_eligible_by_phone(phone)

    def claim_sms_send(self, call_sid: str) -> bool:
        return self._impl.claim_sms_send(call_sid)

    def release_sms_send(self, call_sid: str) -> None:
        self._impl.release_sms_send(call_sid)

    def mark_sms_sent(self, call_sid: str) -> None:
        self._impl.mark_sms_sent(call_sid)

    def set_upload_token(self, call_sid: str, token: str) -> None:
        self._impl.set_upload_token(call_sid, token)

    def update_post_call_analytics(self, **kwargs: Any) -> bool:
        return self._impl.update_post_call_analytics(**kwargs)

    def set_cal_booking(
        self,
        *,
        conversation_id: str,
        cal_booking_uid: str,
        google_event_uid: str | None = None,
        appointment_start: str | None = None,
        appointment_label: str | None = None,
    ) -> bool:
        return self._impl.set_cal_booking(
            conversation_id=conversation_id,
            cal_booking_uid=cal_booking_uid,
            google_event_uid=google_event_uid,
            appointment_start=appointment_start,
            appointment_label=appointment_label,
        )

    def get_by_upload_token(self, upload_token: str) -> dict | None:
        return self._impl.get_by_upload_token(upload_token)

    def claim_confirmation_sms_send(self, row_key: str) -> bool:
        return self._impl.claim_confirmation_sms_send(row_key)

    def release_confirmation_sms_send(self, row_key: str) -> None:
        self._impl.release_confirmation_sms_send(row_key)

    def get_latest_called_by_phone(self, phone: str) -> dict | None:
        return self._impl.get_latest_called_by_phone(phone)

    def list_processed(self, limit: int = 50) -> list[dict]:
        return self._impl.list_processed(limit)
