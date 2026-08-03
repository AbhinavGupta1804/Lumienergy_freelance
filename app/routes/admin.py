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
from app.services.post_call_report import REPORT_ELIGIBLE_OFFERS
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

    dedup_store = getattr(request.app.state, "dedup_store", None)
    if dedup_store:
        lead_row = dedup_store.get_latest_called_by_phone(to_number)
        if lead_row and not lead_row.get("sms_eligible"):
            raise HTTPException(
                status_code=403,
                detail="Transactional SMS consent is not Yes for this customer",
            )

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
    allowed = {
        "all",
        "bill_uploaded",
        "no_bill",
        "sms_sent",
        "call_failed",
        "callback_active",
        "report_sent",
        "report_pending",
        "followup_emails",
        "self_booked",
        # pipeline stages
        "new",
        "trying",
        "reached",
        "booked",
        "confirmed",
        "exhausted",
        "failed",
    }
    filter_by = (filter or "all").strip()
    if filter_by not in allowed:
        raise HTTPException(
            status_code=400, detail=f"filter must be one of {sorted(allowed)}"
        )

    svc = _service()
    # Unfiltered (search only) for stage counts; then apply pipeline filter
    all_rows = svc.list_calls(q=q, filter_by="all", limit=limit)
    counts: dict = {s: 0 for s in (
        "new", "trying", "reached", "booked", "self_booked", "report_sent",
        "bill_uploaded", "confirmed", "exhausted", "failed",
    )}
    counts["all"] = len(all_rows)
    counts["report_pending"] = 0
    counts["callback_active"] = 0
    counts["followup_emails"] = 0
    for row in all_rows:
        stage = row.get("pipeline_stage") or "new"
        if stage in counts:
            counts[stage] += 1
        offer = (row.get("offer_page") or "").lower()
        if offer in REPORT_ELIGIBLE_OFFERS and not row.get("report_sent"):
            counts["report_pending"] += 1
        if row.get("callback_status") == "active":
            counts["callback_active"] += 1
        if (row.get("followup_email_status") or "").lower() == "active":
            counts["followup_emails"] += 1

    if filter_by == "all":
        rows = all_rows
    else:
        rows = [r for r in all_rows if svc._matches_filter(r, filter_by)]

    return {"calls": rows, "count": len(rows), "stage_counts": counts}


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


@router.get("/calls/{row_key}/timeline")
async def get_call_timeline(row_key: str) -> dict:
    svc = _service()
    if not svc.get_call(row_key):
        raise HTTPException(status_code=404, detail="Call not found")
    events = svc.get_lead_timeline(row_key)
    return {"row_key": row_key, "events": events, "count": len(events)}


@router.post("/calls/{row_key}/cancel-followup-calls")
async def cancel_followup_calls(row_key: str, request: Request) -> dict:
    """Cancel pending follow-up (callback) calls for a lead."""
    dedup_store = getattr(request.app.state, "dedup_store", None)
    if not dedup_store:
        raise HTTPException(status_code=503, detail="Dedup store not configured")
    row = dedup_store.get_by_row_key(row_key)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    cancelled = dedup_store.cancel_pending_callbacks(row_key=row_key)
    from app.services.job_scheduler import cancel_pending_callback_jobs

    tasks_deleted = cancel_pending_callback_jobs(
        row_key, known_attempt=int(row.get("callback_attempt") or 0) or None
    )
    logger.info(
        "Admin cancelled follow-up calls row_key=%s cancelled=%s tasks_deleted=%s",
        row_key,
        cancelled,
        tasks_deleted,
    )
    return {
        "ok": True,
        "row_key": row_key,
        "cancelled": cancelled,
        "tasks_deleted": tasks_deleted,
        "callback_status": "cancelled" if cancelled else row.get("callback_status"),
    }


@router.post("/calls/{row_key}/cancel-followup-emails")
async def cancel_followup_emails(row_key: str, request: Request) -> dict:
    """Cancel pending follow-up emails for a lead."""
    dedup_store = getattr(request.app.state, "dedup_store", None)
    if not dedup_store:
        raise HTTPException(status_code=503, detail="Dedup store not configured")
    row = dedup_store.get_by_row_key(row_key)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    cancelled = dedup_store.cancel_followup_emails(row_key=row_key)
    from app.services.job_scheduler import cancel_pending_followup_jobs

    tasks_deleted = cancel_pending_followup_jobs(
        row_key, known_attempt=int(row.get("followup_email_attempt") or 0)
    )
    logger.info(
        "Admin cancelled follow-up emails row_key=%s cancelled=%s tasks_deleted=%s",
        row_key,
        cancelled,
        tasks_deleted,
    )
    return {
        "ok": True,
        "row_key": row_key,
        "cancelled": cancelled,
        "tasks_deleted": tasks_deleted,
        "followup_email_status": (
            "cancelled" if cancelled else row.get("followup_email_status")
        ),
    }


@router.get("/bills/{bill_id}/signed-url")
async def bill_signed_url(
    bill_id: int,
    download: bool = Query(False),
) -> dict:
    try:
        return _service().get_bill_signed_url(bill_id, download=download)
    except AdminServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
