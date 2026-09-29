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


def _normalize_zoho_id(zoho_lead_id: str) -> str:
    zid = (zoho_lead_id or "").strip()
    if zid.lower().startswith("zoho-"):
        return zid[5:]
    return zid


def _phone_last10(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits

_PROCESSED_LEADS_COLUMNS = (
    "row_key, row_number, name, address, email, call_sid, conversation_id, "
    "phone_no, dial_to, sms_eligible, sms_sent, status, processed_at, "
    "call_duration_secs, call_successful, transcript_summary, "
    "termination_reason, call_ended_at, cal_booking_uid, google_event_uid, "
    "appointment_start, appointment_label, upload_token, confirmation_sms_sent, "
    "first_call_at, callback_attempt, next_retry_at, callback_status, "
    "call_in_progress, last_twilio_status, "
    "offer_page, monthly_bill, report_sent, report_email_type, self_booked, "
    "followup_email_status, followup_email_attempt, next_followup_email_at, "
    "nurture_sms_status, nurture_sms_attempt, next_nurture_sms_at, sms_opt_out, "
    "zoho_lead_id"
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
    def get_by_row_key(self, row_key: str) -> dict | None: ...
    def list_due_callbacks(self, *, before_iso: str, limit: int = 20) -> list[dict]: ...
    def claim_callback_dial(self, row_key: str, *, before_iso: str) -> bool: ...
    def release_call_in_progress(self, row_key: str) -> None: ...
    def update_call_started_for_retry(
        self,
        *,
        row_key: str,
        call_sid: str,
        conversation_id: str | None,
    ) -> None: ...
    def update_callback_outcome(
        self,
        *,
        row_key: str,
        callback_attempt: int,
        callback_status: str,
        next_retry_at: str | None,
        last_twilio_status: str | None,
        call_in_progress: bool = False,
    ) -> None: ...
    def release_stale_in_progress(self, *, stale_before_iso: str) -> int: ...
    def cancel_active_callbacks_for_phone(
        self, phone: str, *, except_row_key: str
    ) -> int: ...
    def list_stuck_active_calls(
        self, *, stale_before_iso: str, limit: int = 20
    ) -> list[dict]: ...
    def mark_report_sent(
        self, *, row_key: str, report_email_type: str
    ) -> bool: ...
    def mark_self_booked(self, *, row_key: str) -> bool: ...
    def find_active_callback_by_phone(self, phone: str) -> dict | None: ...
    def find_active_callback_by_email(self, email: str) -> dict | None: ...
    def find_active_followup_by_email(self, email: str) -> dict | None: ...
    def find_active_followup_by_phone(self, phone: str) -> dict | None: ...
    def schedule_followup_email(self, *, row_key: str, next_at_iso: str) -> bool: ...
    def list_due_followup_emails(
        self, *, before_iso: str, limit: int = 20
    ) -> list[dict]: ...
    def claim_followup_email(self, row_key: str, *, before_iso: str) -> bool: ...
    def update_followup_email_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None: ...
    def cancel_followup_emails(self, *, row_key: str) -> bool: ...
    def cancel_pending_callbacks(self, *, row_key: str) -> bool: ...
    def find_lead_by_phone(self, phone: str) -> dict | None: ...
    def find_lead_by_email(self, email: str) -> dict | None: ...
    def find_lead_with_zoho_by_phone(self, phone: str) -> dict | None: ...
    def find_lead_with_zoho_by_email(self, email: str) -> dict | None: ...
    def find_lead_by_zoho_id(self, zoho_lead_id: str) -> dict | None: ...
    def bind_zoho_lead_id(self, **kwargs: Any) -> dict: ...
    def upsert_lead_from_sheet(self, **kwargs: Any) -> dict: ...
    def ensure_lead_for_nurture(self, **kwargs: Any) -> dict: ...
    def schedule_nurture_sms(self, *, row_key: str, next_at_iso: str) -> bool: ...
    def claim_nurture_sms(self, row_key: str) -> bool: ...
    def update_nurture_sms_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None: ...
    def cancel_nurture_sms(self, *, row_key: str, status: str = "cancelled") -> bool: ...
    def set_sms_opt_out(self, *, phone: str) -> int: ...
    def is_sms_opted_out(self, phone: str) -> bool: ...


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
            "first_call_at": "TEXT",
            "callback_attempt": "INTEGER NOT NULL DEFAULT 0",
            "next_retry_at": "TEXT",
            "callback_status": "TEXT NOT NULL DEFAULT 'none'",
            "call_in_progress": "INTEGER NOT NULL DEFAULT 0",
            "last_twilio_status": "TEXT",
            "email": "TEXT",
            "offer_page": "TEXT",
            "monthly_bill": "REAL",
            "report_sent": "INTEGER NOT NULL DEFAULT 0",
            "report_email_type": "TEXT",
            "self_booked": "INTEGER NOT NULL DEFAULT 0",
            "followup_email_status": "TEXT NOT NULL DEFAULT 'none'",
            "followup_email_attempt": "INTEGER NOT NULL DEFAULT 0",
            "next_followup_email_at": "TEXT",
            "nurture_sms_status": "TEXT NOT NULL DEFAULT 'none'",
            "nurture_sms_attempt": "INTEGER NOT NULL DEFAULT 0",
            "next_nurture_sms_at": "TEXT",
            "sms_opt_out": "INTEGER NOT NULL DEFAULT 0",
            "zoho_lead_id": "TEXT",
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
        email: str | None = None,
        status: str = "called",
        track_callback: bool = True,
        sms_eligible: bool = False,
        offer_page: str = "",
        monthly_bill: float = 0.0,
        zoho_lead_id: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        callback_status = "active" if track_callback else "none"
        in_progress = 1 if track_callback else 0
        first_call = now if track_callback else None
        zid = _normalize_zoho_id(zoho_lead_id) or None
        with self._connect() as conn:
            if not zid:
                prev = conn.execute(
                    "SELECT zoho_lead_id FROM processed_leads WHERE row_key = ?",
                    (row_key,),
                ).fetchone()
                if prev and prev[0]:
                    zid = prev[0]
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_leads
                (row_key, row_number, name, address, email, call_sid, conversation_id,
                 phone_no, dial_to, sms_eligible, sms_sent, status, processed_at,
                 first_call_at, callback_attempt, next_retry_at, callback_status,
                 call_in_progress, offer_page, monthly_bill, zoho_lead_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    row_key,
                    row_number,
                    name,
                    address,
                    (email or "").strip() or None,
                    call_sid,
                    conversation_id,
                    phone_no,
                    dial_to,
                    1 if sms_eligible else 0,
                    status,
                    now,
                    first_call,
                    callback_status,
                    in_progress,
                    offer_page or None,
                    monthly_bill or None,
                    zid,
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

    def get_by_row_key(self, row_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_PROCESSED_LEADS_COLUMNS} FROM processed_leads WHERE row_key = ?",
                (row_key,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_due_callbacks(self, *, before_iso: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE callback_status = 'active'
                  AND call_in_progress = 0
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= ?
                ORDER BY next_retry_at ASC
                LIMIT ?
                """,
                (before_iso, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def claim_callback_dial(self, row_key: str, *, before_iso: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET call_in_progress = 1, next_retry_at = NULL
                WHERE row_key = ?
                  AND callback_status = 'active'
                  AND call_in_progress = 0
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= ?
                """,
                (row_key, before_iso),
            )
            conn.commit()
            return cur.rowcount > 0

    def release_call_in_progress(self, row_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_leads SET call_in_progress = 0 WHERE row_key = ?",
                (row_key,),
            )
            conn.commit()

    def update_call_started_for_retry(
        self,
        *,
        row_key: str,
        call_sid: str,
        conversation_id: str | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processed_leads
                SET call_sid = ?, conversation_id = ?, processed_at = ?,
                    call_in_progress = 1, next_retry_at = NULL, status = 'called'
                WHERE row_key = ?
                """,
                (call_sid, conversation_id, now, row_key),
            )
            conn.commit()

    def update_callback_outcome(
        self,
        *,
        row_key: str,
        callback_attempt: int,
        callback_status: str,
        next_retry_at: str | None,
        last_twilio_status: str | None,
        call_in_progress: bool = False,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processed_leads
                SET callback_attempt = ?, callback_status = ?, next_retry_at = ?,
                    last_twilio_status = ?, call_in_progress = ?
                WHERE row_key = ?
                """,
                (
                    callback_attempt,
                    callback_status,
                    next_retry_at,
                    last_twilio_status,
                    1 if call_in_progress else 0,
                    row_key,
                ),
            )
            conn.commit()

    def release_stale_in_progress(self, *, stale_before_iso: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET call_in_progress = 0
                WHERE call_in_progress = 1
                  AND processed_at < ?
                  AND callback_status = 'active'
                """,
                (stale_before_iso,),
            )
            conn.commit()
            return cur.rowcount

    def cancel_active_callbacks_for_phone(
        self, phone: str, *, except_row_key: str
    ) -> int:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET callback_status = 'exhausted',
                    next_retry_at = NULL,
                    call_in_progress = 0
                WHERE callback_status = 'active'
                  AND row_key != ?
                  AND (
                    REPLACE(REPLACE(REPLACE(phone_no, '+', ''), ' ', ''), '-', '') = ?
                    OR REPLACE(REPLACE(REPLACE(dial_to, '+', ''), ' ', ''), '-', '') = ?
                  )
                """,
                (except_row_key, digits, digits),
            )
            conn.commit()
            return cur.rowcount

    def list_stuck_active_calls(
        self, *, stale_before_iso: str, limit: int = 20
    ) -> list[dict]:
        """Calls that started but never received ElevenLabs post-call analytics."""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE callback_status = 'active'
                  AND call_in_progress = 1
                  AND call_ended_at IS NULL
                  AND call_sid IS NOT NULL
                  AND processed_at < ?
                ORDER BY processed_at ASC
                LIMIT ?
                """,
                (stale_before_iso, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def mark_report_sent(self, *, row_key: str, report_email_type: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET report_sent = 1, report_email_type = ?
                WHERE row_key = ?
                """,
                (report_email_type, row_key),
            )
            conn.commit()
            return cur.rowcount > 0

    def mark_self_booked(self, *, row_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET self_booked = 1, callback_status = 'self_booked',
                    next_retry_at = NULL, call_in_progress = 0
                WHERE row_key = ?
                """,
                (row_key,),
            )
            conn.execute(
                """
                UPDATE processed_leads
                SET followup_email_status = 'booked', next_followup_email_at = NULL
                WHERE row_key = ? AND followup_email_status = 'active'
                """,
                (row_key,),
            )
            conn.commit()
            return cur.rowcount > 0

    def find_active_callback_by_phone(self, phone: str) -> dict | None:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE callback_status = 'active'
                  AND (
                    REPLACE(REPLACE(REPLACE(phone_no, '+', ''), ' ', ''), '-', '') = ?
                    OR REPLACE(REPLACE(REPLACE(dial_to, '+', ''), ' ', ''), '-', '') = ?
                  )
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (digits, digits),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_active_callback_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE callback_status = 'active'
                  AND LOWER(email) = ?
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (email,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_active_followup_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE followup_email_status = 'active'
                  AND LOWER(email) = ?
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (email,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_active_followup_by_phone(self, phone: str) -> dict | None:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE followup_email_status = 'active'
                  AND (
                    REPLACE(REPLACE(REPLACE(phone_no, '+', ''), ' ', ''), '-', '') = ?
                    OR REPLACE(REPLACE(REPLACE(dial_to, '+', ''), ' ', ''), '-', '') = ?
                  )
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (digits, digits),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def schedule_followup_email(self, *, row_key: str, next_at_iso: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET followup_email_status = 'active',
                    followup_email_attempt = 0,
                    next_followup_email_at = ?
                WHERE row_key = ?
                """,
                (next_at_iso, row_key),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_due_followup_emails(
        self, *, before_iso: str, limit: int = 20
    ) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE followup_email_status = 'active'
                  AND next_followup_email_at IS NOT NULL
                  AND next_followup_email_at <= ?
                ORDER BY next_followup_email_at ASC
                LIMIT ?
                """,
                (before_iso, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def claim_followup_email(self, row_key: str, *, before_iso: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET next_followup_email_at = NULL
                WHERE row_key = ?
                  AND followup_email_status = 'active'
                  AND next_followup_email_at IS NOT NULL
                  AND next_followup_email_at <= ?
                """,
                (row_key, before_iso),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_followup_email_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processed_leads
                SET followup_email_attempt = ?,
                    followup_email_status = ?,
                    next_followup_email_at = ?
                WHERE row_key = ?
                """,
                (attempt, status, next_at_iso, row_key),
            )
            conn.commit()

    def cancel_followup_emails(self, *, row_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET followup_email_status = 'cancelled',
                    next_followup_email_at = NULL
                WHERE row_key = ?
                  AND followup_email_status = 'active'
                """,
                (row_key,),
            )
            conn.commit()
            return cur.rowcount > 0

    def cancel_pending_callbacks(self, *, row_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET callback_status = 'cancelled',
                    next_retry_at = NULL,
                    call_in_progress = 0
                WHERE row_key = ?
                  AND callback_status = 'active'
                """,
                (row_key,),
            )
            conn.commit()
            return cur.rowcount > 0

    def find_lead_by_phone(self, phone: str) -> dict | None:
        last10 = _phone_last10(phone)
        if not last10:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE substr(REPLACE(REPLACE(REPLACE(COALESCE(phone_no,''), '+', ''), ' ', ''), '-', ''), -10) = ?
                   OR substr(REPLACE(REPLACE(REPLACE(COALESCE(dial_to,''), '+', ''), ' ', ''), '-', ''), -10) = ?
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (last10, last10),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_lead_with_zoho_by_phone(self, phone: str) -> dict | None:
        last10 = _phone_last10(phone)
        if not last10:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE (
                      substr(REPLACE(REPLACE(REPLACE(COALESCE(phone_no,''), '+', ''), ' ', ''), '-', ''), -10) = ?
                   OR substr(REPLACE(REPLACE(REPLACE(COALESCE(dial_to,''), '+', ''), ' ', ''), '-', ''), -10) = ?
                )
                  AND zoho_lead_id IS NOT NULL
                  AND zoho_lead_id <> ''
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (last10, last10),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_lead_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE lower(email) = ?
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (email,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_lead_with_zoho_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE lower(email) = ?
                  AND zoho_lead_id IS NOT NULL
                  AND zoho_lead_id <> ''
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (email,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_lead_by_zoho_id(self, zoho_lead_id: str) -> dict | None:
        zid = _normalize_zoho_id(zoho_lead_id)
        if not zid:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_PROCESSED_LEADS_COLUMNS}
                FROM processed_leads
                WHERE zoho_lead_id = ?
                   OR row_key = ?
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (zid, f"zoho-{zid}"),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def _set_zoho_lead_id(self, *, row_key: str, zoho_lead_id: str) -> None:
        zid = _normalize_zoho_id(zoho_lead_id)
        if not row_key or not zid:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_leads SET zoho_lead_id = ? WHERE row_key = ?",
                (zid, row_key),
            )
            conn.commit()

    def bind_zoho_lead_id(
        self,
        *,
        row_key: str,
        zoho_lead_id: str,
        row_number: int = 0,
        name: str = "",
        address: str = "",
        phone: str = "",
        email: str = "",
    ) -> dict:
        """Attach Zoho Lead ID to an existing sheet row, or create a stub row.

        zoho_lead_id is unique — never stamp the same id onto a second row_key.
        """
        zid = _normalize_zoho_id(zoho_lead_id)
        if not zid:
            return self.get_by_row_key(row_key) or {}
        by_key = self.get_by_row_key(row_key)
        owner = self.find_lead_by_zoho_id(zid)
        if owner and (owner.get("row_key") or "") != (row_key or ""):
            # Already owned by another row (e.g. sheet vs website:*). Keep owner.
            return by_key or owner
        if by_key:
            if (by_key.get("zoho_lead_id") or "") != zid:
                self._set_zoho_lead_id(row_key=by_key["row_key"], zoho_lead_id=zid)
            row = self.get_by_row_key(by_key["row_key"]) or by_key
            row = dict(row)
            row["zoho_lead_id"] = zid
            return row
        if owner:
            return owner
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_leads
                (row_key, row_number, name, address, email, phone_no, dial_to,
                 status, processed_at, callback_status, call_in_progress,
                 nurture_sms_status, nurture_sms_attempt, sms_opt_out, zoho_lead_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'received', ?, 'none', 0, 'none', 0, 0, ?)
                """,
                (
                    row_key,
                    row_number or 0,
                    (name or "").strip() or "Lead",
                    (address or "").strip(),
                    (email or "").strip().lower() or None,
                    (phone or "").strip() or None,
                    (phone or "").strip() or None,
                    now,
                    zid,
                ),
            )
            conn.commit()
        return self.get_by_row_key(row_key) or {"row_key": row_key, "zoho_lead_id": zid}

    def upsert_lead_from_sheet(
        self,
        *,
        row_key: str,
        row_number: int = 0,
        name: str = "",
        address: str = "",
        phone: str = "",
        email: str = "",
        sms_eligible: bool = False,
        offer_page: str = "",
        monthly_bill: float = 0.0,
    ) -> dict:
        """Persist sheet lead + Transactional SMS Consent → sms_eligible immediately."""
        row_key = (row_key or "").strip()
        if not row_key:
            return {}
        now = datetime.now(timezone.utc).isoformat()
        phone_n = (phone or "").strip() or None
        email_n = (email or "").strip().lower() or None
        name_n = (name or "").strip() or "Lead"
        address_n = (address or "").strip()
        eligible = 1 if sms_eligible else 0
        existing = self.get_by_row_key(row_key)
        with self._connect() as conn:
            if existing:
                conn.execute(
                    """
                    UPDATE processed_leads
                    SET row_number = ?,
                        name = ?,
                        address = ?,
                        email = COALESCE(?, email),
                        phone_no = COALESCE(?, phone_no),
                        dial_to = COALESCE(?, dial_to),
                        sms_eligible = ?,
                        offer_page = COALESCE(NULLIF(?, ''), offer_page),
                        monthly_bill = COALESCE(?, monthly_bill)
                    WHERE row_key = ?
                    """,
                    (
                        row_number or int(existing.get("row_number") or 0),
                        name_n,
                        address_n,
                        email_n,
                        phone_n,
                        phone_n,
                        eligible,
                        offer_page or "",
                        monthly_bill or None,
                        row_key,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO processed_leads
                    (row_key, row_number, name, address, email, phone_no, dial_to,
                     sms_eligible, sms_sent, status, processed_at,
                     callback_status, call_in_progress,
                     nurture_sms_status, nurture_sms_attempt, sms_opt_out,
                     offer_page, monthly_bill)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'received', ?, 'none', 0,
                            'none', 0, 0, ?, ?)
                    """,
                    (
                        row_key,
                        row_number or 0,
                        name_n,
                        address_n,
                        email_n,
                        phone_n,
                        phone_n,
                        eligible,
                        now,
                        offer_page or None,
                        monthly_bill or None,
                    ),
                )
            conn.commit()
        logger.info(
            "Sheet lead upserted row_key=%s sms_eligible=%s",
            row_key,
            bool(sms_eligible),
        )
        return self.get_by_row_key(row_key) or {"row_key": row_key}

    def ensure_lead_for_nurture(
        self,
        *,
        phone: str = "",
        email: str = "",
        name: str = "",
        zoho_lead_id: str = "",
        address: str = "",
    ) -> dict:
        zid = _normalize_zoho_id(zoho_lead_id)
        existing = None
        if zid:
            existing = self.find_lead_by_zoho_id(zid)
        if not existing and phone:
            existing = self.find_lead_by_phone(phone)
        if not existing and email:
            existing = self.find_lead_by_email(email)
        if existing:
            if zid and (existing.get("zoho_lead_id") or "") != zid:
                self._set_zoho_lead_id(row_key=existing["row_key"], zoho_lead_id=zid)
                existing = self.get_by_row_key(existing["row_key"]) or existing
                existing = dict(existing)
                existing["zoho_lead_id"] = zid
            return existing

        digits = "".join(c for c in (phone or "") if c.isdigit())
        row_key = f"zoho-{zid}" if zid else f"nurture-{digits or 'unknown'}"
        found = self.get_by_row_key(row_key)
        if found:
            if zid:
                self._set_zoho_lead_id(row_key=row_key, zoho_lead_id=zid)
            return self.get_by_row_key(row_key) or found
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_leads
                (row_key, row_number, name, address, email, phone_no, dial_to,
                 status, processed_at, callback_status, call_in_progress,
                 nurture_sms_status, nurture_sms_attempt, sms_opt_out, zoho_lead_id)
                VALUES (?, 0, ?, ?, ?, ?, ?, 'nurture', ?, 'none', 0, 'none', 0, 0, ?)
                """,
                (
                    row_key,
                    (name or "").strip() or "Lead",
                    (address or "").strip(),
                    (email or "").strip().lower() or None,
                    (phone or "").strip() or None,
                    (phone or "").strip() or None,
                    now,
                    zid or None,
                ),
            )
            conn.commit()
        return self.get_by_row_key(row_key) or {"row_key": row_key}

    def schedule_nurture_sms(self, *, row_key: str, next_at_iso: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET nurture_sms_status = 'active',
                    nurture_sms_attempt = 0,
                    next_nurture_sms_at = ?
                WHERE row_key = ?
                """,
                (next_at_iso, row_key),
            )
            conn.commit()
            return cur.rowcount > 0

    def claim_nurture_sms(self, row_key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET next_nurture_sms_at = NULL
                WHERE row_key = ?
                  AND nurture_sms_status = 'active'
                """,
                (row_key,),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_nurture_sms_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processed_leads
                SET nurture_sms_attempt = ?,
                    nurture_sms_status = ?,
                    next_nurture_sms_at = ?
                WHERE row_key = ?
                """,
                (attempt, status, next_at_iso, row_key),
            )
            conn.commit()

    def cancel_nurture_sms(self, *, row_key: str, status: str = "cancelled") -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET nurture_sms_status = ?,
                    next_nurture_sms_at = NULL
                WHERE row_key = ?
                  AND nurture_sms_status = 'active'
                """,
                (status, row_key),
            )
            conn.commit()
            return cur.rowcount > 0

    def set_sms_opt_out(self, *, phone: str) -> int:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        if not digits:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE processed_leads
                SET sms_opt_out = 1,
                    nurture_sms_status = CASE
                      WHEN nurture_sms_status = 'active' THEN 'opted_out'
                      ELSE nurture_sms_status
                    END,
                    next_nurture_sms_at = CASE
                      WHEN nurture_sms_status = 'active' THEN NULL
                      ELSE next_nurture_sms_at
                    END
                WHERE REPLACE(REPLACE(REPLACE(phone_no, '+', ''), ' ', ''), '-', '') = ?
                   OR REPLACE(REPLACE(REPLACE(dial_to, '+', ''), ' ', ''), '-', '') = ?
                """,
                (digits, digits),
            )
            conn.commit()
            return cur.rowcount

    def is_sms_opted_out(self, phone: str) -> bool:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        if not digits:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM processed_leads
                WHERE sms_opt_out = 1
                  AND (
                    REPLACE(REPLACE(REPLACE(phone_no, '+', ''), ' ', ''), '-', '') = ?
                    OR REPLACE(REPLACE(REPLACE(dial_to, '+', ''), ' ', ''), '-', '') = ?
                  )
                LIMIT 1
                """,
                (digits, digits),
            ).fetchone()
        return row is not None


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
        email: str | None = None,
        status: str = "called",
        track_callback: bool = True,
        sms_eligible: bool = False,
        offer_page: str = "",
        monthly_bill: float = 0.0,
        zoho_lead_id: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        zid = _normalize_zoho_id(zoho_lead_id) or None
        if not zid:
            prev = self.get_by_row_key(row_key)
            if prev and prev.get("zoho_lead_id"):
                zid = prev.get("zoho_lead_id")
        payload: dict[str, Any] = {
            "row_key": row_key,
            "row_number": row_number,
            "name": name,
            "address": address,
            "email": (email or "").strip() or None,
            "call_sid": call_sid,
            "conversation_id": conversation_id,
            "phone_no": phone_no,
            "dial_to": dial_to,
            "sms_eligible": sms_eligible,
            "sms_sent": False,
            "status": status,
            "processed_at": now,
            "callback_attempt": 0,
            "next_retry_at": None,
            "call_in_progress": track_callback,
            "callback_status": "active" if track_callback else "none",
            "offer_page": offer_page or None,
            "monthly_bill": monthly_bill or None,
            "zoho_lead_id": zid,
        }
        if track_callback:
            payload["first_call_at"] = now
        self._table.upsert(payload, on_conflict="row_key").execute()
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

    def get_by_row_key(self, row_key: str) -> dict | None:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("row_key", row_key)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def list_due_callbacks(self, *, before_iso: str, limit: int = 20) -> list[dict]:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("callback_status", "active")
            .eq("call_in_progress", False)
            .not_.is_("next_retry_at", "null")
            .lte("next_retry_at", before_iso)
            .order("next_retry_at")
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def claim_callback_dial(self, row_key: str, *, before_iso: str) -> bool:
        resp = (
            self._table.update({"call_in_progress": True, "next_retry_at": None})
            .eq("row_key", row_key)
            .eq("callback_status", "active")
            .eq("call_in_progress", False)
            .not_.is_("next_retry_at", "null")
            .lte("next_retry_at", before_iso)
            .execute()
        )
        return bool(resp.data)

    def release_call_in_progress(self, row_key: str) -> None:
        self._table.update({"call_in_progress": False}).eq("row_key", row_key).execute()

    def update_call_started_for_retry(
        self,
        *,
        row_key: str,
        call_sid: str,
        conversation_id: str | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._table.update(
            {
                "call_sid": call_sid,
                "conversation_id": conversation_id,
                "processed_at": now,
                "call_in_progress": True,
                "next_retry_at": None,
                "status": "called",
            }
        ).eq("row_key", row_key).execute()

    def update_callback_outcome(
        self,
        *,
        row_key: str,
        callback_attempt: int,
        callback_status: str,
        next_retry_at: str | None,
        last_twilio_status: str | None,
        call_in_progress: bool = False,
    ) -> None:
        self._table.update(
            {
                "callback_attempt": callback_attempt,
                "callback_status": callback_status,
                "next_retry_at": next_retry_at,
                "last_twilio_status": last_twilio_status,
                "call_in_progress": call_in_progress,
            }
        ).eq("row_key", row_key).execute()

    def release_stale_in_progress(self, *, stale_before_iso: str) -> int:
        resp = (
            self._table.update({"call_in_progress": False})
            .eq("call_in_progress", True)
            .eq("callback_status", "active")
            .lt("processed_at", stale_before_iso)
            .execute()
        )
        return len(resp.data or [])

    def cancel_active_callbacks_for_phone(
        self, phone: str, *, except_row_key: str
    ) -> int:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return 0
        cancelled = 0
        for col in ("phone_no", "dial_to"):
            resp = (
                self._table.update(
                    {
                        "callback_status": "exhausted",
                        "next_retry_at": None,
                        "call_in_progress": False,
                    }
                )
                .eq("callback_status", "active")
                .neq("row_key", except_row_key)
                .like(col, f"%{digits}%")
                .execute()
            )
            cancelled += len(resp.data or [])
        return cancelled

    def list_stuck_active_calls(
        self, *, stale_before_iso: str, limit: int = 20
    ) -> list[dict]:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("callback_status", "active")
            .eq("call_in_progress", True)
            .is_("call_ended_at", "null")
            .not_.is_("call_sid", "null")
            .lt("processed_at", stale_before_iso)
            .order("processed_at")
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def mark_report_sent(self, *, row_key: str, report_email_type: str) -> bool:
        resp = (
            self._table.update({"report_sent": True, "report_email_type": report_email_type})
            .eq("row_key", row_key)
            .execute()
        )
        return bool(resp.data)

    def mark_self_booked(self, *, row_key: str) -> bool:
        resp = (
            self._table.update({
                "self_booked": True,
                "callback_status": "self_booked",
                "next_retry_at": None,
                "call_in_progress": False,
            })
            .eq("row_key", row_key)
            .execute()
        )
        (
            self._table.update({
                "followup_email_status": "booked",
                "next_followup_email_at": None,
            })
            .eq("row_key", row_key)
            .eq("followup_email_status", "active")
            .execute()
        )
        return bool(resp.data)

    def find_active_callback_by_phone(self, phone: str) -> dict | None:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return None
        for col in ("phone_no", "dial_to"):
            resp = (
                self._table.select(_PROCESSED_LEADS_COLUMNS)
                .eq("callback_status", "active")
                .like(col, f"%{digits}%")
                .order("processed_at", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0]
        return None

    def find_active_callback_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("callback_status", "active")
            .ilike("email", email)
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def find_active_followup_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("followup_email_status", "active")
            .ilike("email", email)
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def find_active_followup_by_phone(self, phone: str) -> dict | None:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return None
        for col in ("phone_no", "dial_to"):
            resp = (
                self._table.select(_PROCESSED_LEADS_COLUMNS)
                .eq("followup_email_status", "active")
                .like(col, f"%{digits}%")
                .order("processed_at", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0]
        return None

    def schedule_followup_email(self, *, row_key: str, next_at_iso: str) -> bool:
        resp = (
            self._table.update({
                "followup_email_status": "active",
                "followup_email_attempt": 0,
                "next_followup_email_at": next_at_iso,
            })
            .eq("row_key", row_key)
            .execute()
        )
        return bool(resp.data)

    def list_due_followup_emails(
        self, *, before_iso: str, limit: int = 20
    ) -> list[dict]:
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("followup_email_status", "active")
            .not_.is_("next_followup_email_at", "null")
            .lte("next_followup_email_at", before_iso)
            .order("next_followup_email_at")
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def claim_followup_email(self, row_key: str, *, before_iso: str) -> bool:
        resp = (
            self._table.update({"next_followup_email_at": None})
            .eq("row_key", row_key)
            .eq("followup_email_status", "active")
            .not_.is_("next_followup_email_at", "null")
            .lte("next_followup_email_at", before_iso)
            .execute()
        )
        return bool(resp.data)

    def update_followup_email_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None:
        self._table.update({
            "followup_email_attempt": attempt,
            "followup_email_status": status,
            "next_followup_email_at": next_at_iso,
        }).eq("row_key", row_key).execute()

    def cancel_followup_emails(self, *, row_key: str) -> bool:
        resp = (
            self._table.update({
                "followup_email_status": "cancelled",
                "next_followup_email_at": None,
            })
            .eq("row_key", row_key)
            .eq("followup_email_status", "active")
            .execute()
        )
        return bool(resp.data)

    def cancel_pending_callbacks(self, *, row_key: str) -> bool:
        resp = (
            self._table.update({
                "callback_status": "cancelled",
                "next_retry_at": None,
                "call_in_progress": False,
            })
            .eq("row_key", row_key)
            .eq("callback_status", "active")
            .execute()
        )
        return bool(resp.data)

    def _find_lead_rows_by_phone_loose(self, phone: str, *, limit: int = 40) -> list[dict]:
        """Fetch candidate rows; PostgREST can't strip punctuation in filters."""
        last10 = _phone_last10(phone)
        if not last10:
            return []
        # Prefer contiguous digits; also match formatted "(520) 551-4000" via last4.
        last4 = last10[-4:]
        patterns = [
            f"%{last10}%",
            f"%{last10[:3]}%{last10[3:6]}%{last10[6:]}%",
            f"%{last4}%",
        ]
        seen: set[str] = set()
        out: list[dict] = []
        for pattern in patterns:
            for col in ("phone_no", "dial_to"):
                resp = (
                    self._table.select(_PROCESSED_LEADS_COLUMNS)
                    .like(col, pattern)
                    .order("processed_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                for row in resp.data or []:
                    key = row.get("row_key") or ""
                    if key in seen:
                        continue
                    if (
                        _phone_last10(row.get("phone_no") or "") == last10
                        or _phone_last10(row.get("dial_to") or "") == last10
                    ):
                        seen.add(key)
                        out.append(row)
        out.sort(key=lambda r: r.get("processed_at") or "", reverse=True)
        return out

    def find_lead_by_phone(self, phone: str) -> dict | None:
        rows = self._find_lead_rows_by_phone_loose(phone)
        return rows[0] if rows else None

    def find_lead_with_zoho_by_phone(self, phone: str) -> dict | None:
        for row in self._find_lead_rows_by_phone_loose(phone):
            zid = (row.get("zoho_lead_id") or "").strip()
            if zid:
                return row
        return None

    def find_lead_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .ilike("email", email)
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def find_lead_with_zoho_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .ilike("email", email)
            .neq("zoho_lead_id", "")
            .not_.is_("zoho_lead_id", "null")
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def find_lead_by_zoho_id(self, zoho_lead_id: str) -> dict | None:
        zid = _normalize_zoho_id(zoho_lead_id)
        if not zid:
            return None
        resp = (
            self._table.select(_PROCESSED_LEADS_COLUMNS)
            .eq("zoho_lead_id", zid)
            .order("processed_at", desc=True)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]
        return self.get_by_row_key(f"zoho-{zid}")

    def _set_zoho_lead_id(self, *, row_key: str, zoho_lead_id: str) -> None:
        zid = _normalize_zoho_id(zoho_lead_id)
        if not row_key or not zid:
            return
        self._table.update({"zoho_lead_id": zid}).eq("row_key", row_key).execute()

    def bind_zoho_lead_id(
        self,
        *,
        row_key: str,
        zoho_lead_id: str,
        row_number: int = 0,
        name: str = "",
        address: str = "",
        phone: str = "",
        email: str = "",
    ) -> dict:
        """Attach Zoho Lead ID to an existing row, or create a stub.

        zoho_lead_id is unique — never stamp the same id onto a second row_key.
        """
        zid = _normalize_zoho_id(zoho_lead_id)
        if not zid:
            return self.get_by_row_key(row_key) or {}
        by_key = self.get_by_row_key(row_key)
        owner = self.find_lead_by_zoho_id(zid)
        if owner and (owner.get("row_key") or "") != (row_key or ""):
            return by_key or owner
        if by_key:
            if (by_key.get("zoho_lead_id") or "") != zid:
                self._set_zoho_lead_id(row_key=by_key["row_key"], zoho_lead_id=zid)
            row = self.get_by_row_key(by_key["row_key"]) or by_key
            row = dict(row)
            row["zoho_lead_id"] = zid
            return row
        if owner:
            return owner
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "row_key": row_key,
            "row_number": row_number or 0,
            "name": (name or "").strip() or "Lead",
            "address": (address or "").strip(),
            "email": (email or "").strip().lower() or None,
            "phone_no": (phone or "").strip() or None,
            "dial_to": (phone or "").strip() or None,
            "status": "received",
            "processed_at": now,
            "callback_status": "none",
            "call_in_progress": False,
            "nurture_sms_status": "none",
            "nurture_sms_attempt": 0,
            "sms_opt_out": False,
            "sms_eligible": False,
            "zoho_lead_id": zid,
        }
        self._table.upsert(payload, on_conflict="row_key").execute()
        return self.get_by_row_key(row_key) or payload

    def upsert_lead_from_sheet(
        self,
        *,
        row_key: str,
        row_number: int = 0,
        name: str = "",
        address: str = "",
        phone: str = "",
        email: str = "",
        sms_eligible: bool = False,
        offer_page: str = "",
        monthly_bill: float = 0.0,
    ) -> dict:
        """Persist sheet lead + Transactional SMS Consent → sms_eligible immediately."""
        row_key = (row_key or "").strip()
        if not row_key:
            return {}
        now = datetime.now(timezone.utc).isoformat()
        phone_n = (phone or "").strip() or None
        email_n = (email or "").strip().lower() or None
        name_n = (name or "").strip() or "Lead"
        address_n = (address or "").strip()
        existing = self.get_by_row_key(row_key)
        if existing:
            update: dict[str, Any] = {
                "row_number": row_number or int(existing.get("row_number") or 0),
                "name": name_n,
                "address": address_n,
                "sms_eligible": bool(sms_eligible),
            }
            if email_n:
                update["email"] = email_n
            if phone_n:
                update["phone_no"] = phone_n
                update["dial_to"] = phone_n
            if offer_page:
                update["offer_page"] = offer_page
            if monthly_bill:
                update["monthly_bill"] = monthly_bill
            self._table.update(update).eq("row_key", row_key).execute()
        else:
            payload = {
                "row_key": row_key,
                "row_number": row_number or 0,
                "name": name_n,
                "address": address_n,
                "email": email_n,
                "phone_no": phone_n,
                "dial_to": phone_n,
                "sms_eligible": bool(sms_eligible),
                "sms_sent": False,
                "status": "received",
                "processed_at": now,
                "callback_status": "none",
                "call_in_progress": False,
                "nurture_sms_status": "none",
                "nurture_sms_attempt": 0,
                "sms_opt_out": False,
                "offer_page": offer_page or None,
                "monthly_bill": monthly_bill or None,
            }
            self._table.upsert(payload, on_conflict="row_key").execute()
        logger.info(
            "Sheet lead upserted row_key=%s sms_eligible=%s",
            row_key,
            bool(sms_eligible),
        )
        return self.get_by_row_key(row_key) or {"row_key": row_key}

    def ensure_lead_for_nurture(
        self,
        *,
        phone: str = "",
        email: str = "",
        name: str = "",
        zoho_lead_id: str = "",
        address: str = "",
    ) -> dict:
        zid = _normalize_zoho_id(zoho_lead_id)
        existing = None
        if zid:
            existing = self.find_lead_by_zoho_id(zid)
        if not existing and phone:
            existing = self.find_lead_by_phone(phone)
        if not existing and email:
            existing = self.find_lead_by_email(email)
        if existing:
            if zid and (existing.get("zoho_lead_id") or "") != zid:
                self._set_zoho_lead_id(row_key=existing["row_key"], zoho_lead_id=zid)
                existing = self.get_by_row_key(existing["row_key"]) or existing
                existing = dict(existing)
                existing["zoho_lead_id"] = zid
            return existing

        digits = "".join(c for c in (phone or "") if c.isdigit())
        row_key = f"zoho-{zid}" if zid else f"nurture-{digits or 'unknown'}"
        found = self.get_by_row_key(row_key)
        if found:
            if zid:
                self._set_zoho_lead_id(row_key=row_key, zoho_lead_id=zid)
            return self.get_by_row_key(row_key) or found
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "row_key": row_key,
            "row_number": 0,
            "name": (name or "").strip() or "Lead",
            "address": (address or "").strip(),
            "email": (email or "").strip().lower() or None,
            "phone_no": (phone or "").strip() or None,
            "dial_to": (phone or "").strip() or None,
            "status": "nurture",
            "processed_at": now,
            "callback_status": "none",
            "call_in_progress": False,
            "nurture_sms_status": "none",
            "nurture_sms_attempt": 0,
            "sms_opt_out": False,
            "sms_eligible": False,
            "zoho_lead_id": zid or None,
        }
        self._table.upsert(payload, on_conflict="row_key").execute()
        return self.get_by_row_key(row_key) or payload

    def schedule_nurture_sms(self, *, row_key: str, next_at_iso: str) -> bool:
        resp = (
            self._table.update({
                "nurture_sms_status": "active",
                "nurture_sms_attempt": 0,
                "next_nurture_sms_at": next_at_iso,
            })
            .eq("row_key", row_key)
            .execute()
        )
        return bool(resp.data)

    def claim_nurture_sms(self, row_key: str) -> bool:
        resp = (
            self._table.update({"next_nurture_sms_at": None})
            .eq("row_key", row_key)
            .eq("nurture_sms_status", "active")
            .execute()
        )
        return bool(resp.data)

    def update_nurture_sms_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None:
        self._table.update({
            "nurture_sms_attempt": attempt,
            "nurture_sms_status": status,
            "next_nurture_sms_at": next_at_iso,
        }).eq("row_key", row_key).execute()

    def cancel_nurture_sms(self, *, row_key: str, status: str = "cancelled") -> bool:
        resp = (
            self._table.update({
                "nurture_sms_status": status,
                "next_nurture_sms_at": None,
            })
            .eq("row_key", row_key)
            .eq("nurture_sms_status", "active")
            .execute()
        )
        return bool(resp.data)

    def set_sms_opt_out(self, *, phone: str) -> int:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        if not digits:
            return 0
        count = 0
        for col in ("phone_no", "dial_to"):
            resp = (
                self._table.update({
                    "sms_opt_out": True,
                    "nurture_sms_status": "opted_out",
                    "next_nurture_sms_at": None,
                })
                .like(col, f"%{digits}%")
                .eq("nurture_sms_status", "active")
                .execute()
            )
            count += len(resp.data or [])
            # Also mark opt-out on non-active rows
            self._table.update({"sms_opt_out": True}).like(
                col, f"%{digits}%"
            ).execute()
        return count

    def is_sms_opted_out(self, phone: str) -> bool:
        digits = "".join(c for c in (phone or "") if c.isdigit())
        if not digits:
            return False
        for col in ("phone_no", "dial_to"):
            resp = (
                self._table.select("row_key")
                .eq("sms_opt_out", True)
                .like(col, f"%{digits}%")
                .limit(1)
                .execute()
            )
            if resp.data:
                return True
        return False


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

    def get_by_row_key(self, row_key: str) -> dict | None:
        return self._impl.get_by_row_key(row_key)

    def list_due_callbacks(self, *, before_iso: str, limit: int = 20) -> list[dict]:
        return self._impl.list_due_callbacks(before_iso=before_iso, limit=limit)

    def claim_callback_dial(self, row_key: str, *, before_iso: str) -> bool:
        return self._impl.claim_callback_dial(row_key, before_iso=before_iso)

    def release_call_in_progress(self, row_key: str) -> None:
        self._impl.release_call_in_progress(row_key)

    def update_call_started_for_retry(
        self,
        *,
        row_key: str,
        call_sid: str,
        conversation_id: str | None,
    ) -> None:
        self._impl.update_call_started_for_retry(
            row_key=row_key,
            call_sid=call_sid,
            conversation_id=conversation_id,
        )

    def update_callback_outcome(
        self,
        *,
        row_key: str,
        callback_attempt: int,
        callback_status: str,
        next_retry_at: str | None,
        last_twilio_status: str | None,
        call_in_progress: bool = False,
    ) -> None:
        self._impl.update_callback_outcome(
            row_key=row_key,
            callback_attempt=callback_attempt,
            callback_status=callback_status,
            next_retry_at=next_retry_at,
            last_twilio_status=last_twilio_status,
            call_in_progress=call_in_progress,
        )

    def release_stale_in_progress(self, *, stale_before_iso: str) -> int:
        return self._impl.release_stale_in_progress(stale_before_iso=stale_before_iso)

    def cancel_active_callbacks_for_phone(
        self, phone: str, *, except_row_key: str
    ) -> int:
        return self._impl.cancel_active_callbacks_for_phone(
            phone, except_row_key=except_row_key
        )

    def list_stuck_active_calls(
        self, *, stale_before_iso: str, limit: int = 20
    ) -> list[dict]:
        return self._impl.list_stuck_active_calls(
            stale_before_iso=stale_before_iso, limit=limit
        )

    def mark_report_sent(self, *, row_key: str, report_email_type: str) -> bool:
        return self._impl.mark_report_sent(
            row_key=row_key, report_email_type=report_email_type
        )

    def mark_self_booked(self, *, row_key: str) -> bool:
        return self._impl.mark_self_booked(row_key=row_key)

    def find_active_callback_by_phone(self, phone: str) -> dict | None:
        return self._impl.find_active_callback_by_phone(phone)

    def find_active_callback_by_email(self, email: str) -> dict | None:
        return self._impl.find_active_callback_by_email(email)

    def find_active_followup_by_email(self, email: str) -> dict | None:
        return self._impl.find_active_followup_by_email(email)

    def find_active_followup_by_phone(self, phone: str) -> dict | None:
        return self._impl.find_active_followup_by_phone(phone)

    def schedule_followup_email(self, *, row_key: str, next_at_iso: str) -> bool:
        return self._impl.schedule_followup_email(
            row_key=row_key, next_at_iso=next_at_iso
        )

    def list_due_followup_emails(
        self, *, before_iso: str, limit: int = 20
    ) -> list[dict]:
        return self._impl.list_due_followup_emails(before_iso=before_iso, limit=limit)

    def claim_followup_email(self, row_key: str, *, before_iso: str) -> bool:
        return self._impl.claim_followup_email(row_key, before_iso=before_iso)

    def update_followup_email_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None:
        self._impl.update_followup_email_state(
            row_key=row_key, attempt=attempt, status=status, next_at_iso=next_at_iso
        )

    def cancel_followup_emails(self, *, row_key: str) -> bool:
        return self._impl.cancel_followup_emails(row_key=row_key)

    def cancel_pending_callbacks(self, *, row_key: str) -> bool:
        return self._impl.cancel_pending_callbacks(row_key=row_key)

    def find_lead_by_phone(self, phone: str) -> dict | None:
        return self._impl.find_lead_by_phone(phone)

    def find_lead_by_email(self, email: str) -> dict | None:
        return self._impl.find_lead_by_email(email)

    def find_lead_with_zoho_by_phone(self, phone: str) -> dict | None:
        return self._impl.find_lead_with_zoho_by_phone(phone)

    def find_lead_with_zoho_by_email(self, email: str) -> dict | None:
        return self._impl.find_lead_with_zoho_by_email(email)

    def find_lead_by_zoho_id(self, zoho_lead_id: str) -> dict | None:
        return self._impl.find_lead_by_zoho_id(zoho_lead_id)

    def bind_zoho_lead_id(self, **kwargs: Any) -> dict:
        return self._impl.bind_zoho_lead_id(**kwargs)

    def upsert_lead_from_sheet(self, **kwargs: Any) -> dict:
        return self._impl.upsert_lead_from_sheet(**kwargs)

    def ensure_lead_for_nurture(self, **kwargs: Any) -> dict:
        return self._impl.ensure_lead_for_nurture(**kwargs)

    def schedule_nurture_sms(self, *, row_key: str, next_at_iso: str) -> bool:
        return self._impl.schedule_nurture_sms(row_key=row_key, next_at_iso=next_at_iso)

    def claim_nurture_sms(self, row_key: str) -> bool:
        return self._impl.claim_nurture_sms(row_key)

    def update_nurture_sms_state(
        self,
        *,
        row_key: str,
        attempt: int,
        status: str,
        next_at_iso: str | None,
    ) -> None:
        self._impl.update_nurture_sms_state(
            row_key=row_key,
            attempt=attempt,
            status=status,
            next_at_iso=next_at_iso,
        )

    def cancel_nurture_sms(self, *, row_key: str, status: str = "cancelled") -> bool:
        return self._impl.cancel_nurture_sms(row_key=row_key, status=status)

    def set_sms_opt_out(self, *, phone: str) -> int:
        return self._impl.set_sms_opt_out(phone=phone)

    def is_sms_opted_out(self, phone: str) -> bool:
        return self._impl.is_sms_opted_out(phone)
