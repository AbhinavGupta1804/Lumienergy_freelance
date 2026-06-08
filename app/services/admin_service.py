"""
Admin dashboard data — Supabase calls + bill uploads.

Requires DATABASE_BACKEND=supabase and Supabase credentials in .env.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_CALL_COLUMNS = (
    "row_key, row_number, name, address, phone_no, dial_to, "
    "call_sid, conversation_id, status, processed_at, "
    "sms_eligible, sms_sent, upload_token_used, "
    "call_duration_secs, call_successful, transcript_summary, "
    "termination_reason, call_ended_at"
)

_BILL_COLUMNS = (
    "id, lead_row_key, upload_token, storage_path, original_name, "
    "content_type, size_bytes, status, uploaded_at"
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
