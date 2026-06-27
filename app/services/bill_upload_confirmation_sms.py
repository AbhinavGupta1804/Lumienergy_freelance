"""
Send consultation confirmation after bill upload (SMS or email per NOTIFICATION_CHANNEL).

Triggered by POST /webhooks/bill-upload/complete (called from Vercel upload.js).
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.integrations.customer_notifications import send_confirmation_notification
from app.services.message_logger import log_outbound_failure, log_outbound_message
from app.utils.appointment_format import format_appointment_parts
from app.utils.dedup_store import DedupStore
from app.utils.message_store import CustomerMessageStore
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)


def _first_name_from_row(row: dict) -> str:
    name = (row.get("name") or "").strip()
    if not name:
        return ""
    return name.split(None, 1)[0]


class BillUploadConfirmationSmsService:
    def __init__(
        self,
        store: DedupStore,
        message_store: CustomerMessageStore | None = None,
    ) -> None:
        self._store = store
        self._message_store = message_store

    async def on_bill_uploaded(self, upload_token: str) -> dict:
        settings = get_settings()
        if not settings.confirmation_sms_enabled:
            return {"action": "skipped", "reason": "confirmation_disabled"}

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
                "No appointment_label for row_key=%s — skip confirmation",
                row_key,
            )
            return {"action": "skipped", "reason": "no_appointment"}

        appointment_date = ""
        appointment_time = ""
        appointment_start = (row.get("appointment_start") or "").strip()
        if appointment_start:
            appointment_date, appointment_time = format_appointment_parts(
                appointment_start
            )
        elif " at " in appointment_label:
            appointment_date, appointment_time = appointment_label.rsplit(" at ", 1)

        phone = normalize_e164(row.get("dial_to") or row.get("phone_no") or "") or (
            row.get("dial_to") or row.get("phone_no") or ""
        ).strip()
        email = (row.get("email") or "").strip()

        if not self._store.claim_confirmation_sms_send(row_key):
            return {"action": "skipped", "reason": "already_sent"}

        result = await send_confirmation_notification(
            phone=phone,
            email=email,
            appointment_label=appointment_label,
            first_name=_first_name_from_row(row),
            full_name=(row.get("name") or "").strip(),
            appointment_date=appointment_date,
            appointment_time=appointment_time,
        )

        if not result.success:
            self._store.release_confirmation_sms_send(row_key)
            if self._message_store and result.body:
                log_outbound_failure(
                    message_store=self._message_store,
                    dedup_store=self._store,
                    channel=result.channel,
                    message_type="confirmation",
                    body=result.body,
                    to_address=result.to,
                    error=result.error,
                    customer_phone=phone,
                    lead_row_key=row_key,
                    lead_name=(row.get("name") or "").strip(),
                    call_sid=(row.get("call_sid") or "").strip(),
                    conversation_id=(row.get("conversation_id") or "").strip(),
                )
            logger.error(
                "Confirmation notification failed row_key=%s channel=%s to=%s: %s",
                row_key,
                result.channel,
                result.to,
                result.error,
            )
            return {
                "action": "failed",
                "error": result.error,
                "channel": result.channel,
            }

        if self._message_store and result.body:
            log_body = result.body
            if result.channel == "email" and result.subject:
                log_body = f"Subject: {result.subject}\n\n{result.body}"
            log_outbound_message(
                message_store=self._message_store,
                dedup_store=self._store,
                channel=result.channel,
                message_type="confirmation",
                body=log_body,
                to_address=result.to,
                provider_id=result.provider_id,
                lead_row_key=row_key,
                lead_name=(row.get("name") or "").strip(),
                call_sid=(row.get("call_sid") or "").strip(),
                conversation_id=(row.get("conversation_id") or "").strip(),
                customer_phone=phone,
            )

        logger.info(
            "Confirmation notification sent row_key=%s channel=%s to=%s id=%s",
            row_key,
            result.channel,
            result.to,
            result.provider_id,
        )
        return {
            "action": "sent",
            "channel": result.channel,
            "to": result.to,
            "message_sid": result.provider_id,
            "appointment": appointment_label,
        }
