"""
Cal.com booking + Google Calendar enrichment for Lumi outbound calls.

During the call the agent books via POST /scheduling/book (Cal.com-shaped body;
full name + address come from the lead DB row, not the tool).
After the call ends, the ElevenLabs webhook appends the call summary to the
calendar event description.
"""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.cal_com import CalComClient, CalComError
from app.utils.appointment_format import format_appointment_label
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


def format_calendar_description(
    *,
    full_name: str,
    phone: str,
    address: str,
    summary_text: str | None = None,
) -> str:
    lines = [
        f"Customer: {full_name}",
        f"Phone: {phone}",
        f"Address: {address}",
        "",
    ]
    if summary_text and summary_text.strip():
        lines.append("Summary:")
        lines.append(summary_text.strip())
    else:
        lines.append("Summary: (pending — call in progress)")
    return "\n".join(lines)


def summary_from_webhook(data: dict[str, Any]) -> str:
    """ElevenLabs post_call_transcription analysis.transcript_summary."""
    analysis = data.get("analysis") or {}
    return str(analysis.get("transcript_summary") or "").strip()


def resolve_lead_for_booking(
    store: DedupStore,
    phone_no: str,
) -> dict[str, str]:
    """Load full name + address from the outbound-call row for this phone."""
    row = store.get_latest_called_by_phone(phone_no) or {}
    return {
        "full_name": (row.get("name") or "").strip(),
        "address": (row.get("address") or "").strip(),
        "phone_no": (row.get("phone_no") or row.get("dial_to") or phone_no).strip(),
        "conversation_id": (row.get("conversation_id") or "").strip(),
    }


async def book_appointment(
    *,
    store: DedupStore,
    start: str,
    phone_no: str,
    full_name: str = "",
    address: str = "",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Create Cal.com booking and persist calendar IDs for post-call summary."""
    client = CalComClient()

    lead = resolve_lead_for_booking(store, phone_no)
    full_name = (full_name or lead["full_name"]).strip()
    address = (address or lead["address"]).strip()
    phone_no = (phone_no or lead["phone_no"]).strip()
    if not full_name:
        raise CalComError("Could not resolve customer name for booking")
    if not address:
        raise CalComError("Could not resolve customer address for booking")

    conv_id = (conversation_id or lead["conversation_id"] or "").strip()

    description = format_calendar_description(
        full_name=full_name,
        phone=phone_no,
        address=address,
    )

    metadata: dict[str, str] = {}
    if conv_id:
        metadata["conversation_id"] = conv_id

    result = await client.create_booking(
        start=start,
        full_name=full_name,
        phone=phone_no,
        address=address,
        metadata=metadata or None,
    )

    google_event_uid = result.get("google_event_uid")
    if google_event_uid:
        try:
            await client.update_google_calendar_description(
                google_event_uid=google_event_uid,
                description=description,
            )
        except CalComError as exc:
            logger.warning("Initial calendar description update failed: %s", exc)

    if conv_id:
        appointment_start = result.get("start") or start
        appointment_label = (
            format_appointment_label(appointment_start) if appointment_start else None
        )
        store.set_cal_booking(
            conversation_id=conv_id,
            cal_booking_uid=result["booking_uid"],
            google_event_uid=google_event_uid,
            appointment_start=appointment_start,
            appointment_label=appointment_label,
        )

    return {
        "success": True,
        "booking_uid": result["booking_uid"],
        "title": result.get("title"),
        "start": result.get("start"),
        "full_name": full_name,
        "address": address,
    }


async def append_transcript_to_calendar(
    *,
    store: DedupStore,
    conversation_id: str,
    webhook_data: dict[str, Any],
) -> dict[str, Any]:
    """After call ends, update the Google Calendar event with the call summary."""
    row = store.get_by_conversation_id(conversation_id)
    if not row:
        return {"action": "skipped", "reason": "no_db_row"}

    google_event_uid = row.get("google_event_uid")
    cal_booking_uid = row.get("cal_booking_uid")

    client = CalComClient()
    if not google_event_uid and cal_booking_uid:
        try:
            google_event_uid = await client.google_event_uid_for_booking(cal_booking_uid)
            if google_event_uid:
                store.set_cal_booking(
                    conversation_id=conversation_id,
                    cal_booking_uid=cal_booking_uid,
                    google_event_uid=google_event_uid,
                )
        except CalComError as exc:
            logger.warning(
                "Could not resolve google_event_uid from cal_booking_uid=%s: %s",
                cal_booking_uid,
                exc,
            )
    if not google_event_uid:
        return {"action": "skipped", "reason": "no_google_event_uid"}

    full_name = row.get("name") or "Customer"
    phone = row.get("phone_no") or row.get("dial_to") or ""
    address = row.get("address") or ""

    summary = summary_from_webhook(webhook_data)
    if not summary:
        return {"action": "skipped", "reason": "empty_summary"}

    description = format_calendar_description(
        full_name=full_name,
        phone=phone,
        address=address,
        summary_text=summary,
    )

    try:
        await client.update_google_calendar_description(
            google_event_uid=google_event_uid,
            description=description,
        )
    except CalComError as exc:
        logger.error("Calendar summary update failed conv=%s: %s", conversation_id, exc)
        return {"action": "error", "error": str(exc)}

    return {"action": "updated", "google_event_uid": google_event_uid}
