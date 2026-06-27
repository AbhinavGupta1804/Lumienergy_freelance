"""
Orchestrates outbound calls for a single lead.

Resolves dial number, calls ElevenLabs API, and records success in the dedup store.
Supports initial sheet-triggered calls and scheduled callback retries.
"""

import logging

from app.integrations.elevenlabs import ElevenLabsClient, ElevenLabsCallError
from app.integrations.twilio_calls import attach_status_callback
from app.models.lead import Lead
from app.utils.dedup_store import DedupStore
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)


def _name_parts(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


class CallOrchestrator:
    """Place one outbound AI call per lead."""

    def __init__(self, dedup_store: DedupStore) -> None:
        self._dedup = dedup_store
        self._elevenlabs = ElevenLabsClient()

    async def process_lead(self, lead: Lead) -> dict:
        """
        Initiate call for one lead if not already processed.

        Returns a status dict for logging / API responses.
        """
        if self._dedup.is_processed(lead.row_key):
            logger.info("Skipping row %s — already processed", lead.row_number)
            return {"skipped": True, "reason": "already_processed", "row_key": lead.row_key}

        to_number = normalize_e164(lead.dial_number) or normalize_e164(lead.phone_no)
        if not to_number:
            to_number = lead.phone_no.strip()

        cancelled = self._dedup.cancel_active_callbacks_for_phone(
            to_number, except_row_key=lead.row_key
        )
        if cancelled:
            logger.info(
                "Cancelled %s older callback row(s) for phone %s",
                cancelled,
                to_number,
            )

        if not to_number or len("".join(c for c in to_number if c.isdigit())) < 10:
            logger.error(
                "Invalid phone for row %s: %r (check Phone column)",
                lead.row_number,
                lead.phone_no,
            )
            self._dedup.mark_processed(
                row_key=lead.row_key,
                row_number=lead.row_number,
                name=lead.full_name,
                address=lead.address,
                email=lead.email,
                status="failed",
                track_callback=False,
            )
            return {
                "skipped": False,
                "success": False,
                "error": f"Invalid phone_no: {lead.phone_no!r}",
                "row_key": lead.row_key,
            }

        return await self._dial(
            row_key=lead.row_key,
            row_number=lead.row_number,
            name=lead.full_name,
            address=lead.address,
            email=lead.email,
            to_number=to_number,
            phone_no=lead.phone_no_e164,
            is_retry=False,
        )

    async def retry_call_for_row(self, row: dict) -> dict:
        """Scheduled callback — reuse stored lead row."""
        row_key = row.get("row_key") or ""
        to_number = normalize_e164(row.get("dial_to") or row.get("phone_no") or "")
        if not to_number:
            self._dedup.release_call_in_progress(row_key)
            return {"success": False, "error": "no_phone", "row_key": row_key}

        first, last = _name_parts(row.get("name") or "")
        return await self._dial(
            row_key=row_key,
            row_number=int(row.get("row_number") or 0),
            name=row.get("name") or "",
            address=row.get("address") or "",
            email=(row.get("email") or "").strip(),
            to_number=to_number,
            phone_no=normalize_e164(row.get("phone_no") or "") or to_number,
            is_retry=True,
            first_name=first,
            last_name=last,
        )

    async def _dial(
        self,
        *,
        row_key: str,
        row_number: int,
        name: str,
        address: str,
        email: str = "",
        to_number: str,
        phone_no: str,
        is_retry: bool,
        first_name: str = "",
        last_name: str = "",
    ) -> dict:
        if not first_name and not last_name:
            first_name, last_name = _name_parts(name)

        try:
            result = await self._elevenlabs.initiate_outbound_call(
                to_number=to_number,
                first_name=first_name,
                last_name=last_name,
                address=address,
                phone_no=phone_no,
            )
        except ElevenLabsCallError as exc:
            logger.error(
                "Call failed row_key=%s retry=%s: %s",
                row_key,
                is_retry,
                exc,
            )
            if is_retry:
                self._dedup.release_call_in_progress(row_key)
                from datetime import datetime, timedelta, timezone

                existing = self._dedup.get_by_row_key(row_key) or {}
                attempt = int(existing.get("callback_attempt") or 0)
                retry_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
                self._dedup.update_callback_outcome(
                    row_key=row_key,
                    callback_attempt=attempt,
                    callback_status="active",
                    next_retry_at=retry_at,
                    last_twilio_status=None,
                    call_in_progress=False,
                )
            else:
                self._dedup.mark_processed(
                    row_key=row_key,
                    row_number=row_number,
                    name=name,
                    address=address,
                    email=email,
                    status="failed",
                    track_callback=False,
                )
            return {"skipped": False, "success": False, "error": str(exc), "row_key": row_key}

        call_sid = result.get("callSid") or result.get("call_sid")
        conversation_id = result.get("conversation_id")

        if call_sid:
            attached = await attach_status_callback(call_sid)
            if not attached:
                logger.debug(
                    "Status callback not attached for call_sid=%s (expected with ElevenLabs)",
                    call_sid,
                )

        if is_retry:
            self._dedup.update_call_started_for_retry(
                row_key=row_key,
                call_sid=call_sid,
                conversation_id=conversation_id,
            )
        else:
            self._dedup.mark_processed(
                row_key=row_key,
                row_number=row_number,
                name=name,
                address=address,
                email=email,
                call_sid=call_sid,
                conversation_id=conversation_id,
                phone_no=phone_no,
                dial_to=to_number,
                status="called",
            )

        logger.info(
            "Call started row=%s retry=%s callSid=%s conversation_id=%s",
            row_number,
            is_retry,
            call_sid,
            conversation_id,
        )
        return {
            "skipped": False,
            "success": True,
            "row_key": row_key,
            "call_sid": call_sid,
            "conversation_id": conversation_id,
            "to_number": to_number,
            "is_retry": is_retry,
        }
