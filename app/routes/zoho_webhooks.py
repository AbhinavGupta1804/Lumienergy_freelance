"""
Zoho CRM custom-button webhooks → SMS nurture.

Auth: X-Zoho-Webhook-Secret (or ?secret=) must match ZOHO_WEBHOOK_SECRET.

Buttons:
  POST /webhooks/zoho/book-appointment  → Stage 1 SMS + cancel Stage 2
  POST /webhooks/zoho/activate-followup → Stage 2 10-touch sequence
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/zoho", tags=["zoho-webhooks"])


class ZohoLeadBody(BaseModel):
    phone: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    name: str = ""
    address: str = ""
    # Zoho Deluge often sends id as Int — coerce so large CRM ids stay exact as text
    zoho_lead_id: str = Field(default="", alias="id")
    row_key: str = ""
    appointment_start: str = ""
    sms_consent: str = ""
    meet_link: str = ""
    cal_booking_uid: str = ""
    appointment_cancelled: str = ""
    business_unit: str = Field(default="", alias="Business_unit")

    model_config = {"populate_by_name": True}

    @field_validator(
        "zoho_lead_id",
        "phone",
        "email",
        "first_name",
        "last_name",
        "name",
        "address",
        "row_key",
        "appointment_start",
        "sms_consent",
        "meet_link",
        "cal_booking_uid",
        "appointment_cancelled",
        "business_unit",
        mode="before",
    )
    @classmethod
    def _stringify(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


def _verify_zoho_secret(
    header_value: str | None,
    query_secret: str | None,
) -> None:
    settings = get_settings()
    expected = (settings.zoho_webhook_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503, detail="ZOHO_WEBHOOK_SECRET not configured"
        )
    provided = (header_value or query_secret or "").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid Zoho webhook secret")


def _is_cancelled(body: ZohoLeadBody) -> bool:
    return (body.appointment_cancelled or "").strip().lower() in {"1", "true", "yes"}


def _display_name(body: ZohoLeadBody) -> str:
    if (body.name or "").strip():
        return body.name.strip()
    parts = [body.first_name.strip(), body.last_name.strip()]
    return " ".join(p for p in parts if p) or "Lead"


@router.post("/book-appointment")
async def zoho_book_appointment(
    body: ZohoLeadBody,
    request: Request,
    x_zoho_webhook_secret: str | None = Header(default=None),
    secret: str | None = Query(default=None),
) -> JSONResponse:
    _verify_zoho_secret(x_zoho_webhook_secret, secret)
    nurture = request.app.state.sms_nurture_service

    lead = nurture.resolve_lead(
        phone=body.phone,
        email=body.email,
        name=_display_name(body),
        zoho_lead_id=body.zoho_lead_id,
        address=body.address,
        row_key=body.row_key,
        business_unit=body.business_unit or "Lumi Energy",
    )
    if not lead:
        raise HTTPException(
            status_code=400,
            detail="Need Zoho id, phone, email, or row_key to identify the lead",
        )

    if _is_cancelled(body):
        logger.info(
            "Zoho book-appointment cancel ignored for reminders lead=%s",
            lead.get("row_key"),
        )
        return JSONResponse(
            {
                "ok": True,
                "row_key": lead.get("row_key"),
                "action": "ignored",
                "reason": "energy_reminders_disabled",
            }
        )

    result = await nurture.on_appointment_booked(lead)
    logger.info(
        "Zoho book-appointment lead=%s business_unit=%r result=%s",
        lead.get("row_key"),
        lead.get("business_unit"),
        result,
    )
    return JSONResponse({"ok": True, "row_key": lead.get("row_key"), **result})


@router.post("/lights/book-appointment")
async def zoho_lights_book_appointment(
    body: ZohoLeadBody,
    request: Request,
    x_zoho_webhook_secret: str | None = Header(default=None),
    secret: str | None = Query(default=None),
) -> JSONResponse:
    """Lumi Lights consultation booked — stop the text sequence and send confirmation SMS."""
    _verify_zoho_secret(x_zoho_webhook_secret, secret)
    nurture = request.app.state.sms_nurture_service

    lead = nurture.resolve_lights_lead(
        phone=body.phone,
        email=body.email,
        name=_display_name(body),
        zoho_lead_id=body.zoho_lead_id,
        address=body.address,
        sms_consent=body.sms_consent,
        business_unit=body.business_unit or "Lumi Lights",
    )
    if not lead:
        raise HTTPException(
            status_code=400,
            detail="Need Zoho id, phone, email, or row_key to identify the lead",
        )
    cancelled = _is_cancelled(body)
    if not cancelled and not (body.appointment_start or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Appointment_Booked is empty",
        )
    if cancelled:
        reminders = nurture.cancel_appointment_reminders(lead)
        logger.info(
            "Zoho Lights book-appointment cancelled lead=%s reminders=%s",
            lead.get("row_key"),
            reminders,
        )
        return JSONResponse(
            {"ok": True, "row_key": lead.get("row_key"), "reminders": reminders}
        )

    result = await nurture.on_lights_appointment_booked(
        lead,
        appointment_start=body.appointment_start,
        first_name=body.first_name,
        sms_consent=body.sms_consent,
        meet_link=body.meet_link,
        cal_booking_uid=body.cal_booking_uid,
    )
    reminders = nurture.schedule_appointment_reminders(
        lead,
        appointment_start=body.appointment_start,
        meet_link=body.meet_link,
        cal_booking_uid=body.cal_booking_uid,
    )
    logger.info(
        "Zoho Lights book-appointment lead=%s result=%s reminders=%s",
        lead.get("row_key"),
        result,
        reminders,
    )
    return JSONResponse(
        {"ok": True, "row_key": lead.get("row_key"), "reminders": reminders, **result}
    )


@router.post("/lights/activate-followup")
async def zoho_lights_activate_followup(
    body: ZohoLeadBody,
    request: Request,
    x_zoho_webhook_secret: str | None = Header(default=None),
    secret: str | None = Query(default=None),
) -> JSONResponse:
    """Lumi Lights 10-touch follow-up. Does not send the Energy solar texts."""
    _verify_zoho_secret(x_zoho_webhook_secret, secret)
    nurture = request.app.state.sms_nurture_service
    lead = nurture.resolve_lights_lead(
        phone=body.phone,
        email=body.email,
        name=_display_name(body),
        zoho_lead_id=body.zoho_lead_id,
        address=body.address,
        sms_consent=body.sms_consent,
        business_unit=body.business_unit or "Lumi Lights",
    )
    if not lead:
        raise HTTPException(
            status_code=400,
            detail="Need Zoho id, phone, email, or row_key to identify the lead",
        )
    result = await nurture.activate_stage2_followup(lead)
    logger.info(
        "Zoho Lights activate-followup lead=%s business_unit=%r result=%s",
        lead.get("row_key"),
        lead.get("business_unit"),
        result,
    )
    return JSONResponse({"ok": True, "row_key": lead.get("row_key"), **result})


@router.post("/activate-followup")
async def zoho_activate_followup(
    body: ZohoLeadBody,
    request: Request,
    x_zoho_webhook_secret: str | None = Header(default=None),
    secret: str | None = Query(default=None),
) -> JSONResponse:
    _verify_zoho_secret(x_zoho_webhook_secret, secret)
    nurture = request.app.state.sms_nurture_service

    lead = nurture.resolve_lead(
        phone=body.phone,
        email=body.email,
        name=_display_name(body),
        zoho_lead_id=body.zoho_lead_id,
        address=body.address,
        row_key=body.row_key,
        business_unit=body.business_unit or "Lumi Energy",
    )
    if not lead:
        raise HTTPException(
            status_code=400,
            detail="Need Zoho id, phone, email, or row_key to identify the lead",
        )

    result = await nurture.activate_stage2_followup(lead)
    logger.info(
        "Zoho activate-followup lead=%s business_unit=%r result=%s",
        lead.get("row_key"),
        lead.get("business_unit"),
        result,
    )
    return JSONResponse({"ok": True, "row_key": lead.get("row_key"), **result})
