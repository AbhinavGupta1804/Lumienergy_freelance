"""
Admin dashboard data — Supabase calls + bill uploads.

Requires DATABASE_BACKEND=supabase and Supabase credentials in .env.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)

_CALL_COLUMNS = (
    "row_key, row_number, name, address, email, phone_no, dial_to, "
    "call_sid, conversation_id, status, processed_at, "
    "sms_eligible, sms_sent, upload_token_used, confirmation_sms_sent, "
    "call_duration_secs, call_successful, transcript_summary, "
    "termination_reason, call_ended_at, "
    "appointment_start, appointment_label, "
    "cal_booking_uid, google_event_uid, "
    "first_call_at, callback_attempt, next_retry_at, callback_status, "
    "call_in_progress, last_twilio_status"
)

_BILL_COLUMNS = (
    "id, lead_row_key, upload_token, storage_path, original_name, "
    "content_type, size_bytes, status, uploaded_at"
)

_MESSAGE_COLUMNS = (
    "id, direction, channel, message_type, body, from_address, to_address, "
    "lead_row_key, lead_name, call_sid, conversation_id, provider_id, status, created_at"
)


class AdminServiceError(Exception):
    """Admin API configuration or query failure."""


class AdminService:
    def __init__(self) -> None:
        settings = get_settings()
        if (settings.database_backend or "sqlite").lower() != "supabase":
            raise AdminServiceError(
                "Admin dashboard requires DATABASE_BACKEND=supabase"
            )
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise AdminServiceError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required"
            )

        from supabase import create_client

        self._client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
        self._bucket = settings.bill_upload_bucket

    def list_calls(
        self,
        *,
        q: str = "",
        filter_by: str = "all",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        resp = (
            self._client.table("processed_leads")
            .select(_CALL_COLUMNS)
            .order("processed_at", desc=True)
            .limit(limit)
            .execute()
        )
        calls = resp.data or []

        bills_resp = (
            self._client.table("bill_uploads")
            .select(_BILL_COLUMNS)
            .order("uploaded_at", desc=True)
            .execute()
        )
        bills_by_lead: dict[str, list[dict]] = {}
        for bill in bills_resp.data or []:
            key = bill.get("lead_row_key") or ""
            bills_by_lead.setdefault(key, []).append(bill)

        rows: list[dict[str, Any]] = []
        query = q.strip().lower()

        for call in calls:
            row_key = call.get("row_key") or ""
            bills = bills_by_lead.get(row_key, [])
            enriched = {**call, "bills": bills, "bill_count": len(bills)}

            if query and not self._matches_query(enriched, query):
                continue
            if not self._matches_filter(enriched, filter_by):
                continue

            rows.append(enriched)

        return rows

    def list_messages(
        self,
        *,
        q: str = "",
        direction: str = "all",
        channel: str = "all",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = (
            self._client.table("customer_messages")
            .select(_MESSAGE_COLUMNS)
            .order("created_at", desc=True)
            .limit(limit)
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

    @staticmethod
    def customer_phone_for_message(message: dict[str, Any]) -> str:
        direction = (message.get("direction") or "").lower()
        if direction == "inbound":
            return normalize_e164(message.get("from_address") or "") or (
                message.get("from_address") or ""
            ).strip()
        return normalize_e164(message.get("to_address") or "") or (
            message.get("to_address") or ""
        ).strip()

    def list_conversations(
        self,
        *,
        q: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """SMS threads grouped by customer phone (sidebar)."""
        messages = self.list_messages(channel="sms", limit=5000)
        by_phone: dict[str, dict[str, Any]] = {}

        for msg in messages:
            phone = self.customer_phone_for_message(msg)
            if not phone:
                continue
            existing = by_phone.get(phone)
            created = msg.get("created_at") or ""
            if not existing:
                by_phone[phone] = {
                    "phone": phone,
                    "lead_name": (msg.get("lead_name") or "").strip(),
                    "last_message": (msg.get("body") or "")[:120],
                    "last_message_at": created,
                    "last_direction": msg.get("direction"),
                }
                continue
            if created > (existing.get("last_message_at") or ""):
                existing["last_message"] = (msg.get("body") or "")[:120]
                existing["last_message_at"] = created
                existing["last_direction"] = msg.get("direction")
            name = (msg.get("lead_name") or "").strip()
            if name and not existing.get("lead_name"):
                existing["lead_name"] = name

        rows = sorted(
            by_phone.values(),
            key=lambda r: r.get("last_message_at") or "",
            reverse=True,
        )
        if q.strip():
            needle = q.strip().lower()
            rows = [
                r
                for r in rows
                if needle
                in f"{r.get('lead_name', '')} {r.get('phone', '')} {r.get('last_message', '')}".lower()
            ]
        return rows[:limit]

    def get_conversation_messages(
        self,
        phone: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """All SMS for one customer phone, oldest first (chat thread)."""
        normalized = normalize_e164(phone) or phone.strip()
        if not normalized:
            return []

        q = normalized.replace('"', '\\"')
        phone_filter = f'from_address.eq."{q}",to_address.eq."{q}"'

        resp = (
            self._client.table("customer_messages")
            .select(_MESSAGE_COLUMNS)
            .eq("channel", "sms")
            .or_(phone_filter)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def get_call(self, row_key: str) -> dict[str, Any] | None:
        resp = (
            self._client.table("processed_leads")
            .select(_CALL_COLUMNS)
            .eq("row_key", row_key)
            .maybe_single()
            .execute()
        )
        if not resp.data:
            return None

        bills_resp = (
            self._client.table("bill_uploads")
            .select(_BILL_COLUMNS)
            .eq("lead_row_key", row_key)
            .order("uploaded_at", desc=True)
            .execute()
        )
        bills = bills_resp.data or []
        return {**resp.data, "bills": bills, "bill_count": len(bills)}

    def get_bill_signed_url(
        self,
        bill_id: int,
        *,
        download: bool = False,
        expires_in: int = 3600,
    ) -> dict[str, str]:
        resp = (
            self._client.table("bill_uploads")
            .select("id, storage_path, original_name, content_type")
            .eq("id", bill_id)
            .maybe_single()
            .execute()
        )
        if not resp.data:
            raise AdminServiceError("Bill not found")

        path = resp.data.get("storage_path") or ""
        if not path:
            raise AdminServiceError("Bill has no storage path")

        options: dict | None = None
        if download:
            name = resp.data.get("original_name") or "bill"
            options = {"download": name}

        signed = self._client.storage.from_(self._bucket).create_signed_url(
            path,
            expires_in,
            options,
        )

        url = signed.get("signedURL") or signed.get("signedUrl") or ""
        if not url:
            raise AdminServiceError("Could not create signed URL")

        return {
            "url": url,
            "content_type": resp.data.get("content_type") or "application/octet-stream",
            "original_name": resp.data.get("original_name") or "",
        }

    @staticmethod
    def _matches_query(row: dict, query: str) -> bool:
        haystack = " ".join(
            str(row.get(k) or "")
            for k in ("name", "phone_no", "dial_to", "address", "row_key")
        ).lower()
        return query in haystack

    @staticmethod
    def _matches_filter(row: dict, filter_by: str) -> bool:
        if filter_by == "all":
            return True
        if filter_by == "bill_uploaded":
            return row.get("bill_count", 0) > 0
        if filter_by == "no_bill":
            return row.get("bill_count", 0) == 0
        if filter_by == "sms_sent":
            return bool(row.get("sms_sent"))
        if filter_by == "call_failed":
            return not AdminService._is_call_successful(row)
        if filter_by == "callback_active":
            return row.get("callback_status") == "active"
        return True

    @staticmethod
    def _is_call_successful(row: dict) -> bool:
        val = str(row.get("call_successful") or "").lower()
        if val in ("true", "success", "yes", "1"):
            return True
        if val in ("false", "failure", "failed", "no", "0"):
            return False
        return bool(val)


def get_admin_service() -> AdminService:
    return AdminService()
