"""
Google Sheets webhook — called by Apps Script when a new lead row is added.

Install scripts/sheets_webhook.gs in the spreadsheet and point it at:
  POST {PUBLIC_BASE_URL}/webhooks/sheets/new-lead
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.integrations.customer_notifications import notification_channel
from app.integrations.google_sheets import build_row_key
from app.integrations.sheet_columns import (
    normalize_offer_page,
    parse_monthly_bill,
    parse_yes_no_consent,
)
from app.models.lead import Lead
from app.integrations.twilio_sms import build_lights_welcome_sms_body
from app.services.instant_lead_sms import InstantLeadSmsService
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/sheets", tags=["sheets-webhooks"])


class NewLeadBody(BaseModel):
    """Payload sent by Google Apps Script on new row."""

    row_number: int = Field(..., ge=2, description="Sheet row number (2 = first data row)")
    first_name: str = ""
    last_name: str = ""
    address: str = ""
    phone_no: str = ""
    email: str = ""
    transactional_sms_consent: str = ""
    offer_page: str = ""
    monthly_bill: str = ""
    zoho_lead_id: str = ""
    # Personalized website upload link (written by LUMI SOLAR WEBSITE on form submit)
    bill_upload_url: str = ""

    def to_lead(self) -> Lead:
        from datetime import datetime, timezone

        first_name = self.first_name.strip()
        last_name = self.last_name.strip()
        address = self.address.strip()
        phone_no = self.phone_no.strip()
        email = self.email.strip()
        offer_page = normalize_offer_page(self.offer_page)
        monthly_bill = parse_monthly_bill(self.monthly_bill)
        row_key = build_row_key(
            self.row_number, first_name, last_name, address, phone_no
        )
        return Lead(
            row_number=self.row_number,
            first_name=first_name,
            last_name=last_name,
            address=address,
            phone_no=phone_no,
            email=email,
            row_key=row_key,
            detected_at=datetime.now(timezone.utc),
            transactional_sms_consent=parse_yes_no_consent(
                self.transactional_sms_consent
            ),
            offer_page=offer_page,
            monthly_bill=monthly_bill,
            zoho_lead_id=(self.zoho_lead_id or "").strip(),
        )


def _store_sheet_lead(request: Request, body: NewLeadBody) -> Lead:
    """Save the sheet row, consent, and Zoho id. Does not text or dial."""
    lead = body.to_lead()
    store = request.app.state.dedup_store
    phone_e164 = normalize_e164(lead.phone_no) or lead.phone_no.strip()
    store.upsert_lead_from_sheet(
        row_key=lead.row_key,
        row_number=lead.row_number,
        name=lead.full_name,
        address=lead.address,
        phone=phone_e164,
        email=lead.email,
        sms_eligible=lead.transactional_sms_consent,
        offer_page=lead.offer_page,
        monthly_bill=lead.monthly_bill,
    )
    logger.info(
        "Stored sheet consent row=%s row_key=%s sms_eligible=%s (raw=%r)",
        lead.row_number,
        lead.row_key,
        lead.transactional_sms_consent,
        body.transactional_sms_consent,
    )
    if lead.zoho_lead_id:
        store.bind_zoho_lead_id(
            row_key=lead.row_key,
            row_number=lead.row_number,
            name=lead.full_name,
            address=lead.address,
            phone=lead.phone_no,
            email=lead.email,
            zoho_lead_id=lead.zoho_lead_id,
        )
    if not lead.first_name and not lead.last_name and not lead.address and not lead.phone_no:
        raise HTTPException(status_code=400, detail="Row is empty")
    return lead


def _check_webhook_secret(provided: str | None) -> None:
    expected = get_settings().sheets_webhook_secret
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SHEETS_WEBHOOK_SECRET is not configured on the server",
        )
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/new-lead")
async def sheets_new_lead(
    request: Request,
    body: NewLeadBody,
    x_sheets_webhook_secret: str | None = Header(default=None, alias="X-Sheets-Webhook-Secret"),
) -> dict:
    """
    Receive a new Lumi Energy lead from Google Apps Script.

    Saves the row and sends the Energy welcome SMS. Does not place a call.
    """
    _check_webhook_secret(x_sheets_webhook_secret)

    lead = _store_sheet_lead(request, body)

    if notification_channel() == "email" and not lead.email.strip():
        logger.warning(
            "Row %s has no Email — post-call notification will be skipped (NOTIFICATION_CHANNEL=email)",
            lead.row_number,
        )

    # Stage 0 runs even if the dial job was already processed for this row_key.
    # (Previously we returned early on already_processed with no logs — looked like
    # Stage 0 "never triggered".)
    instant_sms: InstantLeadSmsService = request.app.state.instant_lead_sms_service
    welcome_result = await instant_sms.on_new_lead(lead)
    logger.info(
        "Welcome SMS row %s: %s",
        lead.row_number,
        welcome_result,
    )

    logger.info(
        "Energy lead stored row=%s row_key=%s — voice dial disabled, welcome_sms=%s",
        lead.row_number,
        lead.row_key,
        welcome_result,
    )
    return {
        "accepted": True,
        "company": "lumi_energy",
        "voice_call": False,
        "row_number": lead.row_number,
        "row_key": lead.row_key,
        "welcome_sms": welcome_result,
    }


class LightsLeadBody(BaseModel):
    """Lumi Lights sheet: Name, Address, Email, Phone, Offer Page, SMS Consent, T&C Consent, Submitted."""

    row_number: int = Field(..., ge=2)
    name: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    phone_no: str = ""
    offer_page: str = ""
    sms_consent: str = ""
    tc_consent: str = ""
    submitted: str = ""
    zoho_lead_id: str = ""

    def to_energy_body(self) -> NewLeadBody:
        full = self.name.strip()
        first, _, last = full.partition(" ")
        phone = (self.phone or self.phone_no).strip()
        return NewLeadBody(
            row_number=self.row_number,
            first_name=first.strip(),
            last_name=last.strip(),
            address=self.address.strip(),
            phone_no=phone,
            email=self.email.strip(),
            transactional_sms_consent=self.sms_consent,
            offer_page=self.offer_page,
            zoho_lead_id=(self.zoho_lead_id or "").strip(),
        )


@router.post("/lights/new-lead")
async def sheets_lights_new_lead(
    request: Request,
    body: LightsLeadBody,
    x_sheets_webhook_secret: str | None = Header(default=None, alias="X-Sheets-Webhook-Secret"),
) -> dict:
    """
    Lumi Lights sheet row.

    Stores Name, Address, Email, Phone, Offer Page, and SMS Consent.
    Sends the Lights welcome SMS. Does not place a call.
    """
    _check_webhook_secret(x_sheets_webhook_secret)
    incoming = body.to_energy_body()
    lead = incoming.to_lead()
    lead = Lead(
        row_number=lead.row_number,
        first_name=lead.first_name,
        last_name=lead.last_name,
        address=lead.address,
        phone_no=lead.phone_no,
        email=lead.email,
        row_key=f"lights_{lead.row_key}",
        detected_at=lead.detected_at,
        transactional_sms_consent=lead.transactional_sms_consent,
        offer_page=lead.offer_page,
    )
    if not lead.full_name and not lead.address and not lead.phone_no:
        raise HTTPException(status_code=400, detail="Row is empty")
    store = request.app.state.dedup_store
    store.upsert_lead_from_sheet(
        row_key=lead.row_key,
        row_number=lead.row_number,
        name=lead.full_name,
        address=lead.address,
        phone=normalize_e164(lead.phone_no) or lead.phone_no.strip(),
        email=lead.email,
        sms_eligible=lead.transactional_sms_consent,
        offer_page=lead.offer_page,
    )
    store.set_business_unit(row_key=lead.row_key, business_unit="lumi_lights")
    if lead.zoho_lead_id:
        store.bind_zoho_lead_id(
            row_key=lead.row_key,
            row_number=lead.row_number,
            name=lead.full_name,
            address=lead.address,
            phone=lead.phone_no,
            email=lead.email,
            zoho_lead_id=lead.zoho_lead_id,
        )
    instant_sms: InstantLeadSmsService = request.app.state.instant_lead_sms_service
    welcome_result = await instant_sms.on_new_lead(
        lead,
        body=build_lights_welcome_sms_body(),
    )
    streetview: dict = {"ok": False, "skipped": True}
    address = (lead.address or "").strip()
    if address:
        try:
            from app.services.home_streetview import capture_home_streetview
            from app.utils.streetview import StreetViewError

            streetview = capture_home_streetview(
                store, row_key=lead.row_key, address=address
            )
        except StreetViewError as exc:
            logger.warning(
                "Lumi Lights street view skipped row_key=%s error=%s",
                lead.row_key,
                exc,
            )
            streetview = {"ok": False, "error": str(exc)}
        except Exception:
            logger.exception(
                "Lumi Lights street view failed row_key=%s", lead.row_key
            )
            streetview = {"ok": False, "error": "Street View fetch failed"}
    logger.info(
        "Lumi Lights lead stored row=%s row_key=%s tc_consent=%r submitted=%r welcome_sms=%s streetview=%s",
        lead.row_number,
        lead.row_key,
        body.tc_consent,
        body.submitted,
        welcome_result,
        streetview.get("ok"),
    )
    return {
        "accepted": True,
        "company": "lumi_lights",
        "voice_call": False,
        "row_number": lead.row_number,
        "row_key": lead.row_key,
        "welcome_sms": welcome_result,
        "streetview": {"ok": bool(streetview.get("ok"))},
    }
