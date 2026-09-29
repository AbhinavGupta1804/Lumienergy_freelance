"""
Stage 0 — instant welcome SMS when a new lead submits the form.

Triggered from POST /webhooks/sheets/new-lead (Google Apps Script on form submit).
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.integrations.twilio_sms import (
    TwilioSmsError,
    build_welcome_sms_body,
    send_sms,
)
from app.models.lead import Lead
from app.services.message_logger import log_outbound_failure, log_outbound_message
from app.utils.dedup_store import DedupStore
from app.utils.message_store import CustomerMessageStore
from app.utils.phone import normalize_e164
from app.utils.sms_consent import is_sms_consent_granted

logger = logging.getLogger(__name__)


class InstantLeadSmsService:
    """Send the immediate form-submit confirmation text via Twilio."""

    def __init__(
        self,
        store: DedupStore,
        message_store: CustomerMessageStore,
    ) -> None:
        self._store = store
        self._message_store = message_store

    async def on_new_lead(self, lead: Lead) -> dict:
        settings = get_settings()
        if not settings.welcome_sms_enabled:
            return {"action": "skipped", "reason": "welcome_sms_disabled"}

        if not is_sms_consent_granted(lead.transactional_sms_consent):
            logger.info(
                "Skip welcome SMS — no transactional consent row=%s",
                lead.row_number,
            )
            return {"action": "skipped", "reason": "no_sms_consent"}

        to_number = normalize_e164(lead.phone_no) or lead.phone_no.strip()
        if not to_number or len("".join(c for c in to_number if c.isdigit())) < 10:
            logger.warning(
                "Skip welcome SMS — invalid phone row=%s phone=%r",
                lead.row_number,
                lead.phone_no,
            )
            return {"action": "skipped", "reason": "invalid_phone"}

        if self._message_store.has_successful_outbound(
            lead_row_key=lead.row_key,
            message_type="welcome",
        ):
            return {"action": "skipped", "reason": "already_sent"}

        body = build_welcome_sms_body()
        try:
            result = await send_sms(to_number=to_number, body=body)
        except TwilioSmsError as exc:
            logger.error(
                "Welcome SMS config error row=%s: %s",
                lead.row_number,
                exc,
            )
            return {"action": "failed", "error": str(exc)}

        if not result.success:
            log_outbound_failure(
                message_store=self._message_store,
                dedup_store=self._store,
                channel="sms",
                message_type="welcome",
                body=body,
                to_address=to_number,
                error=result.error,
                customer_phone=to_number,
                lead_row_key=lead.row_key,
                lead_name=lead.full_name,
            )
            logger.error(
                "Welcome SMS failed row=%s to=%s: %s",
                lead.row_number,
                to_number,
                result.error,
            )
            return {"action": "failed", "error": result.error}

        log_outbound_message(
            message_store=self._message_store,
            dedup_store=self._store,
            channel="sms",
            message_type="welcome",
            body=body,
            to_address=to_number,
            provider_id=result.message_sid,
            lead_row_key=lead.row_key,
            lead_name=lead.full_name,
            customer_phone=to_number,
        )

        logger.info(
            "Welcome SMS sent row=%s to=%s sid=%s",
            lead.row_number,
            to_number,
            result.message_sid,
        )
        return {
            "action": "sent",
            "to": to_number,
            "message_sid": result.message_sid,
        }
