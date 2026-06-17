"""
Send consultation confirmation SMS after the customer uploads their bill.

Triggered by POST /webhooks/bill-upload/complete (called from Vercel upload.js).
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.integrations.twilio_sms import (
    SmsSendResult,
    TwilioSmsError,
    build_confirmation_sms_body,
    send_sms,
)
from app.utils.dedup_store import DedupStore
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)


class BillUploadConfirmationSmsService:
    def __init__(self, store: DedupStore) -> None:
        self._store = store

    async def on_bill_uploaded(self, upload_token: str) -> dict:
        settings = get_settings()
        if not settings.confirmation_sms_enabled:
            return {"action": "skipped", "reason": "confirmation_sms_disabled"}

        token = upload_token.strip()
        if not token:
            return {"action": "skipped", "reason": "missing_token"}

        row = self._store.get_by_upload_token(token)
        if not row:
            return {"action": "skipped", "reason": "unknown_token"}

        row_key = row.get("row_key") or ""
        if row.get("confirmation_sms_sent"):
            return {"action": "skipped", "reason": "already_sent"}

        appointment_label = (row.get("appointment_label") or "").strip()
        if not appointment_label:
            logger.info(
                "No appointment_label for row_key=%s — skip confirmation SMS",
                row_key,
            )
            return {"action": "skipped", "reason": "no_appointment"}

        to_number = normalize_e164(
            row.get("dial_to") or row.get("phone_no") or ""
        ) or (row.get("dial_to") or row.get("phone_no") or "").strip()
        if not to_number:
            return {"action": "skipped", "reason": "no_phone"}

        if not self._store.claim_confirmation_sms_send(row_key):
            return {"action": "skipped", "reason": "already_sent"}

        body = build_confirmation_sms_body(appointment_label)
        try:
            result: SmsSendResult = await send_sms(to_number=to_number, body=body)
        except TwilioSmsError as exc:
            self._store.release_confirmation_sms_send(row_key)
            logger.error(
                "Confirmation SMS failed row_key=%s to=%s: %s",
                row_key,
                to_number,
                exc,
            )
            return {"action": "failed", "error": str(exc)}

        if not result.success:
            self._store.release_confirmation_sms_send(row_key)
            return {"action": "failed", "error": result.error}

        logger.info(
            "Confirmation SMS sent row_key=%s to=%s message_sid=%s",
            row_key,
            to_number,
            result.message_sid,
        )
        return {
            "action": "sent",
            "message_sid": result.message_sid,
            "to": to_number,
            "appointment": appointment_label,
        }
