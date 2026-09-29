"""
After a bill lands in Supabase, attach it to the matching Zoho CRM Lead.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.integrations.zoho_crm import ZohoCrmError, attach_file_to_lead, zoho_crm_configured
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class ZohoBillAttachmentService:
    def __init__(self, store: DedupStore) -> None:
        self._store = store

    async def attach_for_upload_token(self, upload_token: str) -> dict[str, Any]:
        settings = get_settings()
        token = (upload_token or "").strip()
        if not token:
            return {"action": "skipped", "reason": "missing_token"}
        if not zoho_crm_configured():
            return {"action": "skipped", "reason": "zoho_oauth_not_configured"}

        lead = self._store.get_by_upload_token(token)
        if not lead:
            return {"action": "skipped", "reason": "unknown_token"}

        zoho_id = (lead.get("zoho_lead_id") or "").strip()
        if not zoho_id:
            # Fallback: another row (sheet row_*) may hold the Zoho id for same phone/email
            zoho_id = self._resolve_zoho_id_fallback(lead)
        if not zoho_id:
            return {
                "action": "skipped",
                "reason": "missing_zoho_lead_id",
                "row_key": lead.get("row_key"),
            }

        bill = self._latest_bill_upload(token=token, row_key=lead.get("row_key") or "")
        if not bill:
            return {
                "action": "skipped",
                "reason": "no_bill_upload_row",
                "row_key": lead.get("row_key"),
            }

        storage_path = (bill.get("storage_path") or "").strip()
        if not storage_path:
            return {"action": "skipped", "reason": "missing_storage_path"}

        try:
            content = self._download_bill_bytes(storage_path)
        except Exception as exc:
            logger.exception("Supabase download failed path=%s", storage_path)
            return {"action": "failed", "error": f"download_failed: {exc}"}

        filename = (bill.get("original_name") or storage_path.rsplit("/", 1)[-1] or "utility-bill")
        content_type = (bill.get("content_type") or "application/octet-stream")

        try:
            zoho_resp = await attach_file_to_lead(
                zoho_lead_id=zoho_id,
                filename=str(filename),
                content=content,
                content_type=str(content_type),
            )
        except ZohoCrmError as exc:
            logger.error("Zoho attach failed token=%s: %s", token, exc)
            return {
                "action": "failed",
                "error": str(exc),
                "zoho_lead_id": zoho_id,
                "row_key": lead.get("row_key"),
            }

        self._mark_bill_attached(bill_id=bill.get("id"), zoho_lead_id=zoho_id)
        return {
            "action": "attached",
            "zoho_lead_id": zoho_id,
            "row_key": lead.get("row_key"),
            "storage_path": storage_path,
            "bytes": len(content),
            "zoho": zoho_resp,
            "bucket": settings.bill_upload_bucket,
        }

    def _resolve_zoho_id_fallback(self, lead: dict) -> str:
        """Find zoho_lead_id on a sibling sheet/CRM row (same phone/email)."""
        phone = (lead.get("phone_no") or lead.get("dial_to") or "").strip()
        email = (lead.get("email") or "").strip()

        for matched in (
            self._store.find_lead_with_zoho_by_phone(phone) if phone else None,
            self._store.find_lead_with_zoho_by_email(email) if email else None,
        ):
            if not matched:
                continue
            zid = (matched.get("zoho_lead_id") or "").strip()
            if zid:
                return zid
        return ""

    def _supabase(self):
        from supabase import create_client

        settings = get_settings()
        url = (settings.supabase_url or "").strip()
        key = (settings.supabase_service_role_key or "").strip()
        if not url or not key:
            raise RuntimeError("Supabase URL/service role key not configured")
        return create_client(url, key)

    def _latest_bill_upload(self, *, token: str, row_key: str) -> dict | None:
        client = self._supabase()
        query = (
            client.table("bill_uploads")
            .select("*")
            .eq("upload_token", token)
            .order("id", desc=True)
            .limit(1)
        )
        resp = query.execute()
        rows = resp.data or []
        if rows:
            return rows[0]
        if row_key:
            resp2 = (
                client.table("bill_uploads")
                .select("*")
                .eq("lead_row_key", row_key)
                .order("id", desc=True)
                .limit(1)
                .execute()
            )
            rows2 = resp2.data or []
            if rows2:
                return rows2[0]
        return None

    def _download_bill_bytes(self, storage_path: str) -> bytes:
        settings = get_settings()
        client = self._supabase()
        bucket = settings.bill_upload_bucket or "bill_upload"
        # Website stores files under row keys like "website:<uuid>/file.jpg".
        # storage3 parses paths with yarl.URL(), which treats "website:" as a URL
        # scheme and strips it → downloads the wrong key → 404. Encode colons.
        safe_path = storage_path.replace(":", "%3A") if ":" in storage_path else storage_path
        data = client.storage.from_(bucket).download(safe_path)
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        # Some client versions return memoryview / file-like
        if hasattr(data, "read"):
            return data.read()
        return bytes(data)

    def _mark_bill_attached(self, *, bill_id: Any, zoho_lead_id: str) -> None:
        if bill_id is None:
            return
        try:
            client = self._supabase()
            client.table("bill_uploads").update(
                {"status": "zoho_attached"}
            ).eq("id", bill_id).execute()
        except Exception:
            logger.exception(
                "Could not mark bill_uploads id=%s as zoho_attached (non-fatal)", bill_id
            )
