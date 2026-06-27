"""
Log customer-facing messages to the database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.utils.dedup_store import DedupStore
from app.utils.message_store import CustomerMessageStore
from app.utils.phone import normalize_e164
from app.utils.ws_hub import admin_ws_hub

logger = logging.getLogger(__name__)


def _broadcast_message(record: dict) -> None:
    admin_ws_hub.schedule_broadcast(record)


def _lead_context(store: DedupStore | None, phone: str | None) -> dict[str, str]:
    if not store or not phone:
        return {}
    row = store.get_latest_called_by_phone(normalize_e164(phone) or phone) or {}
    return {
        "lead_row_key": (row.get("row_key") or "").strip(),
        "lead_name": (row.get("name") or "").strip(),
        "call_sid": (row.get("call_sid") or "").strip(),
        "conversation_id": (row.get("conversation_id") or "").strip(),
    }


def log_outbound_message(
    *,
    message_store: CustomerMessageStore,
    dedup_store: DedupStore | None,
    channel: str,
    message_type: str,
    body: str,
    to_address: str,
    from_address: str | None = None,
    provider_id: str = "",
    status: str = "sent",
    lead_row_key: str = "",
    lead_name: str = "",
    call_sid: str = "",
    conversation_id: str = "",
    customer_phone: str | None = None,
) -> None:
    ctx = _lead_context(dedup_store, customer_phone or to_address)
    settings = get_settings()
    from_addr = from_address or (
        settings.twilio_phone_number if channel == "sms" else settings.smtp_from_email
    )
    now = datetime.now(timezone.utc).isoformat()
    msg_id = message_store.log_message(
        direction="outbound",
        channel=channel,
        message_type=message_type,
        body=body,
        from_address=from_addr,
        to_address=to_address,
        lead_row_key=lead_row_key or ctx.get("lead_row_key", ""),
        lead_name=lead_name or ctx.get("lead_name", ""),
        call_sid=call_sid or ctx.get("call_sid", ""),
        conversation_id=conversation_id or ctx.get("conversation_id", ""),
        provider_id=provider_id or None,
        status=status,
    )
    _broadcast_message(
        {
            "id": msg_id,
            "direction": "outbound",
            "channel": channel,
            "message_type": message_type,
            "body": body,
            "from_address": from_addr,
            "to_address": to_address,
            "lead_row_key": lead_row_key or ctx.get("lead_row_key", ""),
            "lead_name": lead_name or ctx.get("lead_name", ""),
            "provider_id": provider_id or None,
            "status": status,
            "created_at": now,
        }
    )


def log_inbound_message(
    *,
    message_store: CustomerMessageStore,
    dedup_store: DedupStore | None,
    channel: str,
    body: str,
    from_address: str,
    to_address: str,
    provider_id: str = "",
    message_type: str = "inbound_reply",
) -> None:
    ctx = _lead_context(dedup_store, from_address)
    now = datetime.now(timezone.utc).isoformat()
    msg_id = message_store.log_message(
        direction="inbound",
        channel=channel,
        message_type=message_type,
        body=body,
        from_address=from_address,
        to_address=to_address,
        lead_row_key=ctx.get("lead_row_key", ""),
        lead_name=ctx.get("lead_name", ""),
        call_sid=ctx.get("call_sid", ""),
        conversation_id=ctx.get("conversation_id", ""),
        provider_id=provider_id or None,
        status="received",
    )
    if channel == "sms":
        _broadcast_message(
            {
                "id": msg_id,
                "direction": "inbound",
                "channel": "sms",
                "message_type": message_type,
                "body": body,
                "from_address": from_address,
                "to_address": to_address,
                "lead_row_key": ctx.get("lead_row_key", ""),
                "lead_name": ctx.get("lead_name", ""),
                "provider_id": provider_id or None,
                "status": "received",
                "created_at": now,
            }
        )


def log_outbound_failure(
    *,
    message_store: CustomerMessageStore,
    dedup_store: DedupStore | None,
    channel: str,
    message_type: str,
    body: str,
    to_address: str,
    error: str,
    customer_phone: str | None = None,
    **extra: Any,
) -> None:
    log_outbound_message(
        message_store=message_store,
        dedup_store=dedup_store,
        channel=channel,
        message_type=message_type,
        body=body,
        to_address=to_address,
        status=f"failed: {error}"[:200],
        customer_phone=customer_phone,
        **{k: v for k, v in extra.items() if k in (
            "lead_row_key", "lead_name", "call_sid", "conversation_id"
        )},
    )
