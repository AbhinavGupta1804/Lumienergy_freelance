"""
Admin dashboard API — calls, bills, SMS conversations, WebSocket.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.integrations.twilio_sms import TwilioSmsError, send_sms
from app.services.admin_service import AdminServiceError, get_admin_service
from app.services.message_logger import log_outbound_failure, log_outbound_message
from app.utils.phone import normalize_e164
from app.utils.ws_hub import admin_ws_hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class SendMessageBody(BaseModel):
    phone: str = Field(..., description="Customer phone E.164 or US 10-digit")
    body: str = Field(..., min_length=1, max_length=1600)


def _service():
    try:
        return get_admin_service()
    except AdminServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.websocket("/ws")
async def admin_websocket(websocket: WebSocket) -> None:
    """Real-time message updates for the admin chat UI."""
    await admin_ws_hub.connect(websocket)
    try:
        while True:
            # Keep connection alive; client may send "ping"
            await websocket.receive_text()
    except WebSocketDisconnect:
        admin_ws_hub.disconnect(websocket)


@router.get("/conversations")
async def list_conversations(
    q: str = Query("", description="Search name, phone, message"),
    limit: int = Query(200, ge=1, le=500),
) -> dict:
    rows = _service().list_conversations(q=q, limit=limit)
    return {"conversations": rows, "count": len(rows)}


@router.get("/conversations/messages")
async def get_conversation_messages(
    phone: str = Query(..., description="Customer phone"),
    limit: int = Query(500, ge=1, le=2000),
) -> dict:
    normalized = normalize_e164(phone) or phone.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    rows = _service().get_conversation_messages(normalized, limit=limit)
    lead_name = ""
    for row in reversed(rows):
        name = (row.get("lead_name") or "").strip()
        if name:
            lead_name = name
            break
    return {
        "phone": normalized,
        "lead_name": lead_name,
        "messages": rows,
        "count": len(rows),
    }


@router.post("/conversations/messages")
async def send_conversation_message(
    payload: SendMessageBody,
    request: Request,
) -> dict:
    to_number = normalize_e164(payload.phone) or payload.phone.strip()
    if not to_number:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message body is required")

    try:
        result = await send_sms(to_number=to_number, body=body)
    except TwilioSmsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    message_store = getattr(request.app.state, "message_store", None)
    dedup_store = getattr(request.app.state, "dedup_store", None)

    if message_store:
        if result.success:
            log_outbound_message(
                message_store=message_store,
                dedup_store=dedup_store,
                channel="sms",
                message_type="admin_manual",
                body=body,
                to_address=to_number,
                provider_id=result.message_sid,
                customer_phone=to_number,
            )
        else:
            log_outbound_failure(
                message_store=message_store,
                dedup_store=dedup_store,
                channel="sms",
                message_type="admin_manual",
                body=body,
                to_address=to_number,
                error=result.error,
                customer_phone=to_number,
            )

    if not result.success:
        raise HTTPException(status_code=502, detail=result.error or "SMS send failed")

    return {"ok": True, "message_sid": result.message_sid, "to": to_number}


@router.get("/calls")
async def list_calls(
    q: str = Query("", description="Search name, phone, address"),
    filter: str = Query("all", alias="filter"),
    limit: int = Query(500, ge=1, le=1000),
) -> dict:
    allowed = {"all", "bill_uploaded", "no_bill", "sms_sent", "call_failed", "callback_active"}
    filter_by = (filter or "all").strip()
    if filter_by not in allowed:
        raise HTTPException(status_code=400, detail=f"filter must be one of {sorted(allowed)}")

    rows = _service().list_calls(q=q, filter_by=filter_by, limit=limit)
    return {"calls": rows, "count": len(rows)}


@router.get("/messages")
async def list_messages(
    q: str = Query("", description="Search body, phone, email, lead name"),
    direction: str = Query("all", description="all, inbound, or outbound"),
    channel: str = Query("all", description="all, sms, or email"),
    limit: int = Query(500, ge=1, le=1000),
) -> dict:
    allowed_direction = {"all", "inbound", "outbound"}
    allowed_channel = {"all", "sms", "email"}
    if direction not in allowed_direction:
        raise HTTPException(
            status_code=400,
            detail=f"direction must be one of {sorted(allowed_direction)}",
        )
    if channel not in allowed_channel:
        raise HTTPException(
            status_code=400,
            detail=f"channel must be one of {sorted(allowed_channel)}",
        )

    rows = _service().list_messages(
        q=q,
        direction=direction,
        channel=channel,
        limit=limit,
    )
    return {"messages": rows, "count": len(rows)}


@router.get("/calls/{row_key}")
async def get_call(row_key: str) -> dict:
    row = _service().get_call(row_key)
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return row


@router.get("/bills/{bill_id}/signed-url")
async def bill_signed_url(
    bill_id: int,
    download: bool = Query(False),
) -> dict:
    try:
        return _service().get_bill_signed_url(bill_id, download=download)
    except AdminServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
