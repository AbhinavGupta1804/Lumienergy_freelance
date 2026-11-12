"""
Admin dashboard API — calls, bills, SMS conversations, WebSocket.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.integrations.twilio_sms import TwilioSmsError, send_sms
from app.services.admin_service import AdminServiceError, get_admin_service, lead_is_lights
from app.integrations.openai_images import (
    DEFAULT_IMAGE_MODEL,
    OpenAIImageError,
    image_model_options,
    resolve_image_model,
)
from app.services.home_streetview import (
    capture_home_streetview,
    load_streetview_bytes,
    render_lighting_preview,
)
from app.utils.streetview import StreetViewError
from app.services.message_logger import log_outbound_failure, log_outbound_message
from app.services.post_call_report import REPORT_ELIGIBLE_OFFERS
from app.utils.phone import normalize_e164
from app.utils.sms_consent import lead_allows_transactional_sms
from app.utils.ws_hub import admin_ws_hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class LightingPreviewBody(BaseModel):
    extra_prompt: str = Field(default="", max_length=1000)
    model: str = Field(default="", max_length=80)


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
    reads: str = Query(
        "",
        description='JSON map of phone → last-read ISO timestamp, e.g. {"+15551212":"2026-01-01T00:00:00Z"}',
    ),
    company: str = Query("", description="energy or lights"),
) -> dict:
    last_read_by_phone: dict[str, str] = {}
    if reads.strip():
        try:
            raw = json.loads(reads)
            if isinstance(raw, dict):
                for phone, ts in raw.items():
                    if not phone or not ts:
                        continue
                    normalized = normalize_e164(str(phone)) or str(phone).strip()
                    if normalized:
                        last_read_by_phone[normalized] = str(ts)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("Ignoring invalid conversations reads JSON")
    company_filter = (company or "").strip().lower()
    if company_filter not in {"", "energy", "lights"}:
        raise HTTPException(status_code=400, detail="company must be energy or lights")
    rows = _service().list_conversations(
        q=q,
        limit=limit,
        last_read_by_phone=last_read_by_phone,
        company=company_filter,
    )
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
    if not dedup_store:
        raise HTTPException(
            status_code=503,
            detail="Lead store unavailable — cannot verify SMS consent",
        )

    lead_row = dedup_store.find_lead_by_phone(
        to_number
    ) or dedup_store.get_latest_called_by_phone(to_number)
    if not lead_allows_transactional_sms(lead_row):
        raise HTTPException(
            status_code=403,
            detail="Transactional SMS consent is not Yes for this customer",
        )
    if dedup_store.is_sms_opted_out(to_number):
        raise HTTPException(
            status_code=403,
            detail="Customer has opted out of SMS (STOP)",
        )

    try:
        result = await send_sms(to_number=to_number, body=body)
    except TwilioSmsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    message_store = getattr(request.app.state, "message_store", None)

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
    company: str = Query("", description="energy or lights"),
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
    company_filter = (company or "").strip().lower()
    if company_filter not in {"", "energy", "lights"}:
        raise HTTPException(status_code=400, detail="company must be energy or lights")

    svc = _service()
    # Unfiltered (search only) for stage counts; then apply pipeline filter
    all_rows = svc.list_calls(
        q=q, filter_by="all", limit=limit, company=company_filter
    )
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


def _lights_lead_or_404(row_key: str) -> dict:
    row = _service().get_call(row_key)
    if not row or not lead_is_lights(row):
        raise HTTPException(status_code=404, detail="Lead not found")
    return row


@router.get("/calls/{row_key}/streetview")
async def get_lead_streetview(row_key: str) -> Response:
    row = _lights_lead_or_404(row_key)
    path = (row.get("streetview_storage_path") or "").strip()
    if not path:
        raise HTTPException(status_code=404, detail="No home image yet")
    try:
        data = load_streetview_bytes(path)
    except StreetViewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/calls/{row_key}/streetview/render")
async def get_lead_lighting_preview(row_key: str) -> Response:
    row = _lights_lead_or_404(row_key)
    path = (row.get("streetview_render_path") or "").strip()
    if not path:
        raise HTTPException(status_code=404, detail="No lighting preview yet")
    try:
        data = load_streetview_bytes(path)
    except StreetViewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/image-models")
async def list_image_models() -> dict:
    return {"default": DEFAULT_IMAGE_MODEL, "models": image_model_options()}


@router.post("/calls/{row_key}/streetview/render")
async def create_lead_lighting_preview(
    row_key: str,
    request: Request,
    body: LightingPreviewBody | None = None,
) -> dict:
    row = _lights_lead_or_404(row_key)
    source = (row.get("streetview_storage_path") or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="Fetch the Street View photo first")
    store = getattr(request.app.state, "dedup_store", None)
    if not store:
        raise HTTPException(status_code=503, detail="Lead store is not configured")
    try:
        model = resolve_image_model(body.model if body else "")
    except OpenAIImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        result = render_lighting_preview(
            store,
            row_key=row_key,
            source_path=source,
            extra_prompt=(body.extra_prompt if body else ""),
            model=model,
        )
    except (StreetViewError, OpenAIImageError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "row_key": row_key,
        "fetched_at": result.get("fetched_at"),
    }


@router.post("/calls/{row_key}/streetview")
async def fetch_lead_streetview(row_key: str, request: Request) -> dict:
    row = _lights_lead_or_404(row_key)
    address = (row.get("address") or "").strip()
    if not address:
        raise HTTPException(status_code=400, detail="This lead has no address")
    store = getattr(request.app.state, "dedup_store", None)
    if not store:
        raise HTTPException(status_code=503, detail="Lead store is not configured")
    try:
        result = capture_home_streetview(store, row_key=row_key, address=address)
    except StreetViewError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "row_key": row_key,
        "fetched_at": result.get("fetched_at"),
    }


@router.post("/lights/streetview/backfill")
async def backfill_lights_streetview(
    request: Request,
    limit: int = Query(15, ge=1, le=40),
) -> dict:
    """Fetch home photos for Lights leads that do not have one yet."""
    store = getattr(request.app.state, "dedup_store", None)
    if not store:
        raise HTTPException(status_code=503, detail="Lead store is not configured")
    rows = _service().list_calls(filter_by="all", limit=500, company="lights")
    pending = [
        row
        for row in rows
        if not (row.get("streetview_storage_path") or "").strip()
        and (row.get("address") or "").strip()
    ]
    fetched = 0
    failed: list[dict] = []
    for row in pending[:limit]:
        try:
            capture_home_streetview(
                store,
                row_key=row["row_key"],
                address=row.get("address") or "",
            )
            fetched += 1
        except StreetViewError as exc:
            failed.append({"row_key": row.get("row_key"), "error": str(exc)})
    return {
        "ok": True,
        "fetched": fetched,
        "failed": len(failed),
        "remaining": max(len(pending) - fetched, 0),
        "errors": failed[:8],
    }


@router.get("/calls/{row_key}/timeline")
async def get_call_timeline(row_key: str) -> dict:
    svc = _service()
    if not svc.get_call(row_key):
        raise HTTPException(status_code=404, detail="Call not found")
    events = svc.get_lead_timeline(row_key)
    return {"row_key": row_key, "events": events, "count": len(events)}


@router.post("/calls/{row_key}/start-voice-call")
async def start_voice_call(row_key: str, request: Request) -> dict:
    """Call now is turned off for every lead."""
    raise HTTPException(status_code=409, detail="Call now is turned off")


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


class SalesCloseBody(BaseModel):
    row_key: str = Field(..., min_length=1)
    note: str = Field("", max_length=32000)
    note_title: str = Field("Admin sale note", max_length=100)
    sale_revenue: float | None = None
    pre_sight_profit: float | None = None
    post_inspection_profit: float | None = None
    sale_date: str | None = Field(
        None,
        description="ISO date or datetime, e.g. 2026-09-30 or 2026-09-30T12:00:00",
    )


@router.get("/sales/leads")
async def list_sales_leads(
    q: str = Query("", description="Search name, phone, email"),
    limit: int = Query(500, ge=1, le=1000),
    zoho_only: bool = Query(False, description="Only leads with zoho_lead_id"),
    company: str = Query("", description="energy or lights"),
) -> dict:
    company_filter = (company or "").strip().lower()
    if company_filter not in {"", "energy", "lights"}:
        raise HTTPException(status_code=400, detail="company must be energy or lights")
    rows = _service().list_sales_leads(
        q=q, limit=limit, zoho_only=zoho_only, company=company_filter
    )
    return {"leads": rows, "count": len(rows)}


@router.post("/sales/close")
async def close_sale(payload: SalesCloseBody) -> dict:
    """
    Push sale fields + optional note to Zoho CRM for a lead in our DB.
    """
    from datetime import datetime

    from app.integrations.zoho_crm import (
        ZOHO_FIELD_POST_INSPECTION_PROFIT,
        ZOHO_FIELD_PRE_SIGHT_PROFIT,
        ZOHO_FIELD_SALE_DATE,
        ZOHO_FIELD_SALE_REVENUE,
        ZohoCrmError,
        create_lead_note,
        find_lead_id_by_email_or_phone,
        get_lead,
        normalize_zoho_lead_id,
        update_lead_fields,
        zoho_crm_configured,
    )

    if not zoho_crm_configured():
        raise HTTPException(status_code=503, detail="Zoho CRM is not configured")

    row_key = payload.row_key.strip()
    lead = _service().get_call(row_key)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    zoho_id = normalize_zoho_lead_id(str(lead.get("zoho_lead_id") or ""))

    # Stored id may be from an old duplicate lead — verify, else resolve by email/phone
    if zoho_id:
        existing = await get_lead(zoho_id)
        if not existing:
            logger.warning(
                "Stale zoho_lead_id=%s for row_key=%s — resolving via email/phone",
                zoho_id,
                row_key,
            )
            zoho_id = ""

    if not zoho_id:
        resolved = await find_lead_id_by_email_or_phone(
            email=str(lead.get("email") or ""),
            phone=str(lead.get("dial_to") or lead.get("phone_no") or ""),
            business_unit="Lumi Lights" if lead_is_lights(lead) else "Lumi Energy",
        )
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No valid Zoho Lead found for this record. "
                    "Stored zoho_lead_id is invalid/missing and email/phone search returned nothing."
                ),
            )
        zoho_id = resolved
        # Best-effort: refresh DB binding if unique constraint allows
        try:
            from app.config import get_settings
            from supabase import create_client

            settings = get_settings()
            if settings.supabase_url and settings.supabase_service_role_key:
                sb = create_client(
                    settings.supabase_url, settings.supabase_service_role_key
                )
                sb.table("processed_leads").update({"zoho_lead_id": None}).eq(
                    "row_key", row_key
                ).execute()
                owned = (
                    sb.table("processed_leads")
                    .select("row_key")
                    .eq("zoho_lead_id", zoho_id)
                    .limit(1)
                    .execute()
                )
                if not (owned.data or []):
                    sb.table("processed_leads").update({"zoho_lead_id": zoho_id}).eq(
                        "row_key", row_key
                    ).execute()
        except Exception:
            logger.exception("Could not refresh zoho_lead_id for row_key=%s", row_key)

    note = (payload.note or "").strip()
    fields: dict = {}

    if payload.sale_revenue is not None:
        fields[ZOHO_FIELD_SALE_REVENUE] = float(payload.sale_revenue)
    if payload.pre_sight_profit is not None:
        fields[ZOHO_FIELD_PRE_SIGHT_PROFIT] = float(payload.pre_sight_profit)
    if payload.post_inspection_profit is not None:
        fields[ZOHO_FIELD_POST_INSPECTION_PROFIT] = float(
            payload.post_inspection_profit
        )

    if payload.sale_date and payload.sale_date.strip():
        raw = payload.sale_date.strip()
        # Accept YYYY-MM-DD or full ISO; Zoho DateTime wants ISO-like string
        try:
            if "T" in raw:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(f"{raw}T12:00:00")
            fields[ZOHO_FIELD_SALE_DATE] = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="sale_date must be YYYY-MM-DD or ISO datetime",
            ) from exc

    if not fields and not note:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: note, sale_revenue, pre_sight_profit, post_inspection_profit, sale_date",
        )

    updated_fields: list[str] = []
    note_created = False
    note_title_used = ""
    try:
        if fields:
            await update_lead_fields(zoho_lead_id=zoho_id, fields=fields)
            updated_fields = list(fields.keys())
        if note:
            note_title_used = (payload.note_title or "Admin sale note").strip() or (
                "Admin sale note"
            )
            await create_lead_note(
                zoho_lead_id=zoho_id,
                note_content=note,
                note_title=note_title_used,
            )
            note_created = True
    except ZohoCrmError as exc:
        logger.exception("Sales close Zoho error row_key=%s", row_key)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Discord — sales channel (non-blocking for the CRM write)
    discord_sent = False
    try:
        from app.config import get_settings
        from app.integrations.discord_notify import send_discord_embed

        settings = get_settings()
        sales_hook = (settings.discord_sales_webhook_url or "").strip()
        money = lambda v: f"${v:,.2f}" if v is not None else "—"
        discord_fields = [
            {"name": "Lead", "value": str(lead.get("name") or "—"), "inline": True},
            {
                "name": "Phone",
                "value": str(lead.get("dial_to") or lead.get("phone_no") or "—"),
                "inline": True,
            },
            {"name": "Email", "value": str(lead.get("email") or "—"), "inline": True},
            {
                "name": "Sale Revenue",
                "value": money(payload.sale_revenue),
                "inline": True,
            },
            {
                "name": "Pre Sight Profit",
                "value": money(payload.pre_sight_profit),
                "inline": True,
            },
            {
                "name": "Post Inspection Profit",
                "value": money(payload.post_inspection_profit),
                "inline": True,
            },
            {
                "name": "Sale Date",
                "value": (payload.sale_date or "—").strip() or "—",
                "inline": True,
            },
        ]
        if note_created:
            discord_fields.append(
                {
                    "name": "Note title",
                    "value": note_title_used or "—",
                    "inline": False,
                }
            )
            discord_fields.append(
                {
                    "name": "Note",
                    "value": note[:900] + ("…" if len(note) > 900 else ""),
                    "inline": False,
                }
            )

        brand = "Lumi Lights" if lead_is_lights(lead) else "Lumi Energy"
        discord_sent = await send_discord_embed(
            title=f"{brand} sales update → Zoho",
            description=f"**{lead.get('name') or 'Lead'}** was updated from the admin Sales page.",
            fields=discord_fields,
            color=0x2563EB,
            webhook_url=sales_hook or None,
            username="Lumi Sales",
        )
    except Exception:
        logger.exception("Sales Discord notify failed row_key=%s", row_key)

    logger.info(
        "Sales close ok row_key=%s zoho=%s fields=%s note=%s discord=%s",
        row_key,
        zoho_id,
        updated_fields,
        note_created,
        discord_sent,
    )
    return {
        "ok": True,
        "row_key": row_key,
        "zoho_lead_id": zoho_id,
        "lead_name": lead.get("name") or "",
        "updated_fields": updated_fields,
        "note_created": note_created,
        "discord_sent": discord_sent,
    }
