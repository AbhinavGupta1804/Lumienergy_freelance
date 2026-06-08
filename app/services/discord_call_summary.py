"""
Build and send post-call summaries to Discord after ElevenLabs webhooks.
"""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.integrations.discord_notify import send_discord_embed
from app.services.call_analytics import extract_post_call_analytics
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)

_SUCCESS_COLORS = {
    "success": 0x2B7A4B,
    "failure": 0xC0392B,
    "unknown": 0x95A5A6,
}


def _truncate(text: str | None, limit: int = 1000) -> str:
    if not text:
        return "—"
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _format_ended_at_phoenix(iso_timestamp: str | None) -> str:
    """Format call end time in America/Phoenix (MST, UTC−7, no DST)."""
    if not iso_timestamp:
        return "—"
    try:
        raw = str(iso_timestamp).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        phoenix = dt.astimezone(ZoneInfo(get_settings().business_timezone))
        return phoenix.strftime("%Y-%m-%d %I:%M %p %Z")
    except (ValueError, TypeError):
        return _truncate(iso_timestamp, 80)


def _sms_status(row: dict | None, sms_result: dict | None) -> str:
    if not row:
        return "—"
    if row.get("sms_sent"):
        return "Sent"
    if row.get("sms_eligible"):
        action = (sms_result or {}).get("action", "")
        if action == "sent":
            return "Sent"
        if action == "skipped":
            return f"Eligible, not sent ({sms_result.get('reason', '?')})"
        if action == "failed":
            return f"Failed ({sms_result.get('error', '?')})"
        return "Eligible, pending"
    return "Not eligible (Step 6b not reached)"


def build_discord_summary(
    *,
    payload: dict[str, Any],
    lead_row: dict | None,
    sms_result: dict | None,
) -> tuple[str, str, list[dict[str, str]], int]:
    """Return (title, description, fields, embed_color)."""
    data = payload.get("data") or {}
    analytics = extract_post_call_analytics(payload) or {}

    call_successful = (
        analytics.get("call_successful")
        or (data.get("analysis") or {}).get("call_successful")
        or "unknown"
    )
    color = _SUCCESS_COLORS.get(str(call_successful).lower(), 0x3498DB)

    name = (lead_row or {}).get("name") or "Unknown lead"
    phone = (lead_row or {}).get("dial_to") or (lead_row or {}).get("phone_no") or "—"

    summary = analytics.get("transcript_summary") or (
        (data.get("analysis") or {}).get("transcript_summary")
    )
    event_type = payload.get("type", "call_ended")
    if event_type == "post_call_audio":
        summary = summary or "(Audio-only webhook — no transcript summary.)"

    title = f"Call ended — {name}"
    description = _truncate(summary, 3500)

    fields = [
        {"name": "Customer", "value": name, "inline": True},
        {"name": "Phone", "value": phone, "inline": True},
        {"name": "Sheet row", "value": str((lead_row or {}).get("row_number", "—")), "inline": True},
        {"name": "Duration", "value": _format_duration(analytics.get("call_duration_secs")), "inline": True},
        {"name": "Bill SMS", "value": _sms_status(lead_row, sms_result), "inline": True},
        {
            "name": "Termination",
            "value": _truncate(analytics.get("termination_reason"), 200),
            "inline": True,
        },
        {
            "name": "Ended at (Phoenix)",
            "value": _format_ended_at_phoenix(analytics.get("call_ended_at")),
            "inline": True,
        },
        {
            "name": "IDs",
            "value": _truncate(
                f"conv: {data.get('conversation_id', '—')}\n"
                f"call: {(lead_row or {}).get('call_sid', '—')}",
                200,
            ),
            "inline": False,
        },
    ]
    return title, description, fields, color


async def notify_call_ended_discord(
    *,
    payload: dict[str, Any],
    store: DedupStore,
    sms_result: dict | None = None,
) -> bool:
    """Post call summary embed to Discord (non-blocking errors)."""
    data = payload.get("data") or {}
    conversation_id = data.get("conversation_id", "")
    lead_row = store.get_by_conversation_id(conversation_id) if conversation_id else None

    title, description, fields, color = build_discord_summary(
        payload=payload,
        lead_row=lead_row,
        sms_result=sms_result,
    )

    try:
        return await send_discord_embed(
            title=title,
            description=description,
            fields=fields,
            color=color,
        )
    except Exception as exc:
        logger.error("Discord summary failed: %s", exc)
        return False
