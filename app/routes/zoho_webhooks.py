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
    )
    if not lead:
        raise HTTPException(
            status_code=400,
            detail="Need Zoho id, phone, email, or row_key to identify the lead",
        )

    result = await nurture.on_appointment_booked(lead)
    logger.info(
        "Zoho book-appointment lead=%s result=%s",
        lead.get("row_key"),
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
    )
    if not lead:
        raise HTTPException(
            status_code=400,
            detail="Need Zoho id, phone, email, or row_key to identify the lead",
        )

    result = await nurture.activate_stage2_followup(lead)
    logger.info(
        "Zoho activate-followup lead=%s result=%s",
        lead.get("row_key"),
        result,
    )
    return JSONResponse({"ok": True, "row_key": lead.get("row_key"), **result})
