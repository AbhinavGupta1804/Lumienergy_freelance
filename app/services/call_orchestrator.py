"""
Orchestrates outbound calls for a single lead.

Resolves dial number (test vs production), calls ElevenLabs API,
and records success in the dedup store.
"""

import logging

from app.config import get_settings
from app.integrations.elevenlabs import ElevenLabsClient, ElevenLabsCallError
from app.integrations.twilio_calls import attach_status_callback
from app.models.lead import Lead
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class CallOrchestrator:
    """Place one outbound AI call per lead."""

    def __init__(self, dedup_store: DedupStore) -> None:
        self._dedup = dedup_store
        self._elevenlabs = ElevenLabsClient()

    def _resolve_to_number(self, lead: Lead) -> str:
        """In test mode, always dial the fixed test number."""
        settings = get_settings()
        if settings.test_mode:
            return settings.test_call_number
        number = lead.dial_number
        if not number.startswith("+"):
            number = f"+{number.lstrip('0')}"
        return number

    async def process_lead(self, lead: Lead) -> dict:
        """
        Initiate call for one lead if not already processed.

        Returns a status dict for logging / API responses.
        """
        if self._dedup.is_processed(lead.row_key):
            logger.info("Skipping row %s — already processed", lead.row_number)
            return {"skipped": True, "reason": "already_processed", "row_key": lead.row_key}

        to_number = self._resolve_to_number(lead)
        if not to_number or len("".join(c for c in to_number if c.isdigit())) < 10:
            logger.error(
                "Invalid phone for row %s: %r (check phone_no column D)",
                lead.row_number,
                lead.phone_no,
            )
            self._dedup.mark_processed(
                row_key=lead.row_key,
                row_number=lead.row_number,
                name=lead.full_name,
                address=lead.address,
                status="failed",
            )
            return {
                "skipped": False,
                "success": False,
                "error": f"Invalid phone_no: {lead.phone_no!r}",
                "row_key": lead.row_key,
            }

        settings = get_settings()

        if settings.test_mode:
            logger.info(
                "TEST_MODE: dialing %s instead of sheet phone %s",
                to_number,
                lead.phone_no or "(empty)",
            )

        try:
            result = await self._elevenlabs.initiate_outbound_call(
                to_number=to_number,
                first_name=lead.first_name,
                address=lead.address,
                phone_no=lead.phone_no_e164,
            )
        except ElevenLabsCallError as exc:
            logger.error("Call failed for row %s: %s", lead.row_number, exc)
            self._dedup.mark_processed(
                row_key=lead.row_key,
                row_number=lead.row_number,
                name=lead.full_name,
                address=lead.address,
                status="failed",
            )
            return {"skipped": False, "success": False, "error": str(exc), "row_key": lead.row_key}

        call_sid = result.get("callSid") or result.get("call_sid")
        conversation_id = result.get("conversation_id")

        if call_sid:
            attached = await attach_status_callback(call_sid)
            if not attached:
                logger.warning(
                    "Status callback not attached for call_sid=%s — post-call SMS may not fire",
                    call_sid,
                )

        self._dedup.mark_processed(
            row_key=lead.row_key,
            row_number=lead.row_number,
            name=lead.full_name,
            address=lead.address,
            call_sid=call_sid,
            conversation_id=conversation_id,
            phone_no=lead.phone_no_e164,
            dial_to=to_number,
            status="called",
        )

        logger.info(
            "Call started row=%s callSid=%s conversation_id=%s",
            lead.row_number,
            call_sid,
            conversation_id,
        )
        return {
            "skipped": False,
            "success": True,
            "row_key": lead.row_key,
            "call_sid": call_sid,
            "conversation_id": conversation_id,
            "to_number": to_number,
        }
