"""
Post-call notification after voice calls end (bill upload link via SMS or email).

Primary trigger: ElevenLabs POST /webhooks/elevenlabs/post-call
Secondary: Twilio status callback when call was answered.
"""

import logging
from uuid import uuid4

from app.config import get_settings
from app.integrations.customer_notifications import (
    notification_channel,
    send_bill_upload_notification,
)
from app.integrations.twilio_webhooks import customer_phone_from_callback
from app.services.message_logger import log_outbound_failure, log_outbound_message
from app.utils.callback_schedule import is_call_answered
from app.utils.dedup_store import DedupStore
from app.utils.message_store import CustomerMessageStore
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)


def _first_name_from_row(row: dict) -> str:
    name = (row.get("name") or "").strip()
    if not name:
        return ""
    return name.split(None, 1)[0]


class PostCallSmsService:
    """Sends bill-upload link after answered calls (SMS or email per NOTIFICATION_CHANNEL)."""

    def __init__(
        self,
        store: DedupStore,
        message_store: CustomerMessageStore | None = None,
    ) -> None:
        self._store = store
        self._message_store = message_store

    async def on_status_callback(self, callback: dict[str, str]) -> dict:
        """Handle Twilio Status Callback — notify only when call was answered."""
        call_sid = callback.get("call_sid", "")
        status = (callback.get("status") or "").lower()

        if not call_sid:
            return {"action": "ignored", "reason": "missing_call_sid"}

        if status != "completed":
            logger.debug(
                "Twilio status ignored call_sid=%s status=%s",
                call_sid,
                status,
            )
            return {"action": "ignored", "call_status": status}

        try:
            duration = int(callback.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0

        if not is_call_answered(status, duration):
            return {
                "action": "skipped",
                "reason": "not_answered",
                "call_status": status,
                "duration": duration,
            }

        customer_phone = customer_phone_from_callback(callback)
        return await self._send_if_eligible(
            call_sid,
            customer_phone=customer_phone,
            source="twilio_status_callback",
        )

    async def on_call_completed(self, call_sid: str, call_status: str) -> dict:
        return await self.on_status_callback(
            {"call_sid": call_sid, "status": call_status, "direction": "outbound-api"}
        )

    async def on_conversation_ended(
        self,
        conversation_id: str,
        *,
        answered: bool,
    ) -> dict:
        if not answered:
            logger.info(
                "Skip post-call notification — not answered conversation_id=%s",
                conversation_id,
            )
            return {"action": "skipped", "reason": "not_answered"}

        row = self._store.get_by_conversation_id(conversation_id)
        if not row:
            logger.warning(
                "ElevenLabs post-call: unknown conversation_id=%s",
                conversation_id,
            )
            return {"action": "skipped", "reason": "unknown_conversation_id"}

        call_sid = row.get("call_sid") or ""
        if not call_sid:
            return {"action": "skipped", "reason": "missing_call_sid"}

        return await self._send_if_eligible(
            call_sid,
            customer_phone=row.get("dial_to") or row.get("phone_no") or "",
            source="elevenlabs_post_call",
        )

    async def _send_if_eligible(
        self,
        call_sid: str,
        *,
        customer_phone: str,
        source: str,
    ) -> dict:
        settings = get_settings()
        channel = notification_channel()
        if not settings.sms_enabled:
            logger.info("Notifications disabled — skip call_sid=%s", call_sid)
            return {"action": "skipped", "reason": "notifications_disabled", "source": source}

        row = self._store.get_by_call_sid(call_sid)
        if not row:
            logger.warning("No DB row for completed call_sid=%s", call_sid)
            return {"action": "skipped", "reason": "unknown_call_sid", "source": source}

        if row.get("sms_sent"):
            logger.info("Notification already sent for call_sid=%s — skip duplicate", call_sid)
            return {"action": "skipped", "reason": "already_sent", "source": source}

        phone = normalize_e164(
            row.get("dial_to") or row.get("phone_no") or customer_phone
        ) or (row.get("dial_to") or row.get("phone_no") or customer_phone or "").strip()
        email = (row.get("email") or "").strip()

        if channel == "email" and not email:
            return {"action": "skipped", "reason": "no_email", "source": source, "channel": channel}
        if channel == "sms" and not phone:
            return {"action": "skipped", "reason": "no_phone", "source": source, "channel": channel}

        if not self._store.claim_sms_send(call_sid):
            return {"action": "skipped", "reason": "already_sent", "source": source}

        upload_token = str(uuid4())
        self._store.set_upload_token(call_sid, upload_token)

        base_url = settings.sms_bill_upload_base_url.rstrip("/")
        upload_link = f"{base_url}/?token={upload_token}"

        result = await send_bill_upload_notification(
            phone=phone,
            email=email,
            upload_link=upload_link,
            first_name=_first_name_from_row(row),
            full_name=(row.get("name") or "").strip(),
        )

        if not result.success:
            self._store.release_sms_send(call_sid)
            if self._message_store and result.body:
                log_outbound_failure(
                    message_store=self._message_store,
                    dedup_store=self._store,
                    channel=result.channel,
                    message_type="bill_upload",
                    body=result.body,
                    to_address=result.to,
                    error=result.error,
                    customer_phone=phone,
                    lead_row_key=row.get("row_key") or "",
                    lead_name=(row.get("name") or "").strip(),
                    call_sid=call_sid,
                    conversation_id=(row.get("conversation_id") or "").strip(),
                )
            logger.error(
                "Bill upload notification failed call_sid=%s channel=%s to=%s error=%s",
                call_sid,
                result.channel,
                result.to,
                result.error,
            )
            return {
                "action": "failed",
                "error": result.error,
                "source": source,
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
                message_type="bill_upload",
                body=log_body,
                to_address=result.to,
                provider_id=result.provider_id,
                lead_row_key=row.get("row_key") or "",
                lead_name=(row.get("name") or "").strip(),
                call_sid=call_sid,
                conversation_id=(row.get("conversation_id") or "").strip(),
                customer_phone=phone,
            )

        logger.info(
            "Bill upload notification sent call_sid=%s channel=%s to=%s id=%s",
            call_sid,
            result.channel,
            result.to,
            result.provider_id,
        )
        return {
            "action": "sent",
            "channel": result.channel,
            "to": result.to,
            "message_sid": result.provider_id,
            "source": source,
        }
