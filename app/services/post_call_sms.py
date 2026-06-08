"""
Post-call SMS after voice calls end.

Primary trigger (ElevenLabs outbound):
  POST /webhooks/elevenlabs/post-call — configure in ElevenLabs dashboard.
  Twilio Status Callbacks on EL-initiated calls go to ElevenLabs, not your server.

Secondary trigger (if you place calls via Twilio REST directly):
  POST /webhooks/twilio/status — CallStatus=completed.

During the call, mark_bill_sms_ready (Step 6b) sets sms_eligible=1.
"""

import logging
from uuid import uuid4

from app.config import get_settings
from app.integrations.twilio_sms import SmsSendResult, TwilioSmsError, build_sms_body, send_sms
from app.integrations.twilio_webhooks import customer_phone_from_callback
from app.utils.dedup_store import DedupStore
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)


class PostCallSmsService:
    def __init__(self, store: DedupStore) -> None:
        self._store = store

    def mark_ready_by_phone(
        self,
        phone_no: str,
        *,
        conversation_id: str | None = None,
    ) -> dict:
        """
        Called by ElevenLabs tool when conversation reaches Step 6b.
        Prefer conversation_id so we flag the live call, not another call to the same number.
        """
        normalized = normalize_e164(phone_no)
        if not normalized:
            return {"ok": False, "reason": "invalid_phone"}

        updated = self._store.mark_sms_eligible(
            normalized,
            conversation_id=conversation_id or None,
        )
        if not updated:
            logger.warning(
                "mark_bill_sms_ready: no active call for %s conversation_id=%s",
                normalized,
                conversation_id,
            )
            return {"ok": False, "reason": "no_matching_call"}

        logger.info(
            "SMS eligible flagged customer_phone=%s conversation_id=%s row_key=%s call_sid=%s",
            normalized,
            updated.get("conversation_id"),
            updated.get("row_key"),
            updated.get("call_sid"),
        )
        return {
            "ok": True,
            "row_key": updated.get("row_key"),
            "call_sid": updated.get("call_sid"),
            "conversation_id": updated.get("conversation_id"),
        }

    async def on_status_callback(self, callback: dict[str, str]) -> dict:
        """
        Handle Twilio Status Callback POST (all CallStatus values).

        Only sends SMS when CallStatus=completed and sms_eligible=1.
        """
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

        customer_phone = customer_phone_from_callback(callback)
        logger.info(
            "Call completed event call_sid=%s customer_phone=%s direction=%s duration=%s",
            call_sid,
            customer_phone,
            callback.get("direction"),
            callback.get("duration"),
        )

        return await self._send_if_eligible(
            call_sid,
            customer_phone=customer_phone,
            source="twilio_status_callback",
        )

    async def on_call_completed(self, call_sid: str, call_status: str) -> dict:
        """Backward-compatible entry for status-only handlers."""
        return await self.on_status_callback(
            {"call_sid": call_sid, "status": call_status, "direction": "outbound-api"}
        )

    async def on_conversation_ended(self, conversation_id: str) -> dict:
        """
        ElevenLabs post-call webhook — conversation finished.

        Looks up call_sid by conversation_id stored when the outbound call started.
        """
        row = self._store.get_by_conversation_id(conversation_id)
        if not row:
            logger.warning(
                "ElevenLabs post-call: unknown conversation_id=%s",
                conversation_id,
            )
            return {"action": "skipped", "reason": "unknown_conversation_id"}

        send_row = row
        if not row.get("sms_eligible"):
            phone = row.get("dial_to") or row.get("phone_no") or ""
            pending = self._store.get_pending_sms_eligible_by_phone(phone)
            if pending:
                logger.info(
                    "Post-call webhook for conversation_id=%s (sms_eligible=0) — "
                    "using pending eligible conversation_id=%s call_sid=%s",
                    conversation_id,
                    pending.get("conversation_id"),
                    pending.get("call_sid"),
                )
                send_row = pending
            else:
                logger.info(
                    "Conversation ended conversation_id=%s call_sid=%s sms_eligible=0",
                    conversation_id,
                    row.get("call_sid"),
                )

        call_sid = send_row.get("call_sid") or ""
        if not call_sid:
            return {"action": "skipped", "reason": "missing_call_sid"}

        return await self._send_if_eligible(
            call_sid,
            customer_phone=send_row.get("dial_to") or send_row.get("phone_no") or "",
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
        if not settings.sms_enabled:
            logger.info("SMS disabled — skip call_sid=%s", call_sid)
            return {"action": "skipped", "reason": "sms_disabled", "source": source}

        row = self._store.get_by_call_sid(call_sid)
        if not row:
            logger.warning("No DB row for completed call_sid=%s", call_sid)
            return {"action": "skipped", "reason": "unknown_call_sid", "source": source}

        if row.get("sms_sent"):
            logger.info("SMS already sent for call_sid=%s — skip duplicate", call_sid)
            return {"action": "skipped", "reason": "already_sent", "source": source}

        if settings.sms_require_eligible and not row.get("sms_eligible"):
            logger.info(
                "Call completed but SMS not eligible call_sid=%s (no mark_bill_sms_ready)",
                call_sid,
            )
            return {"action": "skipped", "reason": "not_eligible", "source": source}

        to_number = row.get("dial_to") or row.get("phone_no") or customer_phone
        to_number = normalize_e164(to_number) or to_number
        if not to_number:
            return {"action": "skipped", "reason": "no_phone", "source": source}

        if not self._store.claim_sms_send(call_sid):
            logger.info("SMS send already claimed for call_sid=%s", call_sid)
            return {"action": "skipped", "reason": "already_sent", "source": source}

        # Generate a unique upload token and persist it so the landing page can
        # validate it.  We store it before sending the SMS so the token is always
        # in the DB by the time the customer clicks the link.
        upload_token = str(uuid4())
        self._store.set_upload_token(call_sid, upload_token)

        base_url = settings.sms_bill_upload_base_url.rstrip("/")
        upload_link = f"{base_url}/?token={upload_token}"

        try:
            result: SmsSendResult = await send_sms(to_number=to_number, body=build_sms_body(upload_link))
        except TwilioSmsError as exc:
            self._store.release_sms_send(call_sid)
            logger.error(
                "SMS failure call_sid=%s customer_phone=%s error=%s",
                call_sid,
                to_number,
                exc,
            )
            return {"action": "failed", "error": str(exc), "source": source}

        if not result.success:
            self._store.release_sms_send(call_sid)
            logger.error(
                "SMS failure call_sid=%s customer_phone=%s error=%s",
                call_sid,
                to_number,
                result.error,
            )
            return {"action": "failed", "error": result.error, "source": source}

        logger.info(
            "SMS sent successfully call_sid=%s customer_phone=%s message_sid=%s",
            call_sid,
            to_number,
            result.message_sid,
        )
        return {
            "action": "sent",
            "message_sid": result.message_sid,
            "to": to_number,
            "source": source,
        }
