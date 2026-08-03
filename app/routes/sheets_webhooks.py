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
from app.services.job_scheduler import schedule_process_lead_job
from app.services.lead_processor import LeadProcessor

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
        )


def _check_webhook_secret(provided: str | None) -> None:
    expected = get_settings().sheets_webhook_secret
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SHEETS_WEBHOOK_SECRET is not configured on the server",
        )
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


async def _process_lead_inline(processor: LeadProcessor, lead: Lead) -> None:
    try:
        result = await processor.process_incoming(lead)
        logger.info("Sheets webhook processed row %s: %s", lead.row_number, result)
    except Exception:
        logger.exception("Sheets webhook failed for row %s", lead.row_number)


@router.post("/new-lead")
async def sheets_new_lead(
    request: Request,
    body: NewLeadBody,
    x_sheets_webhook_secret: str | None = Header(default=None, alias="X-Sheets-Webhook-Secret"),
) -> dict:
    """
    Receive a new lead from Google Apps Script and place an outbound call.

    Prefer Cloud Tasks so dial + dial-fail PDF/email run in a dedicated request
    (request-based Cloud Run kills FastAPI BackgroundTasks after 200 OK).
    Falls back to awaiting inline when Cloud Tasks is not configured.
    """
    _check_webhook_secret(x_sheets_webhook_secret)

    lead = body.to_lead()
    if not lead.first_name and not lead.last_name and not lead.address and not lead.phone_no:
        raise HTTPException(status_code=400, detail="Row is empty")

    if notification_channel() == "email" and not lead.email.strip():
        logger.warning(
            "Row %s has no Email — post-call notification will be skipped (NOTIFICATION_CHANNEL=email)",
            lead.row_number,
        )

    dedup = request.app.state.dedup_store
    if dedup.is_processed(lead.row_key):
        return {
            "accepted": True,
            "skipped": True,
            "reason": "already_processed",
            "row_key": lead.row_key,
        }

    job_payload = {
        "row_number": lead.row_number,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "address": lead.address,
        "phone_no": lead.phone_no,
        "email": lead.email,
        "transactional_sms_consent": body.transactional_sms_consent,
        "offer_page": lead.offer_page,
        "monthly_bill": body.monthly_bill,
        "row_key": lead.row_key,
    }
    job = schedule_process_lead_job(job_payload)

    logger.info(
        "Sheets webhook accepted row %s (%s) email=%s offer_page=%r sms_consent=%s enqueue=%s",
        lead.row_number,
        lead.full_name,
        lead.email or "(empty)",
        lead.offer_page,
        "yes" if lead.transactional_sms_consent else "no",
        job,
    )

    if job.get("scheduled"):
        return {
            "accepted": True,
            "queued": True,
            "via": "cloud_tasks",
            "row_number": lead.row_number,
            "row_key": lead.row_key,
        }

    # Local / CT not configured: keep the HTTP request alive for dial + report.
    processor: LeadProcessor = request.app.state.lead_processor
    await _process_lead_inline(processor, lead)
    return {
        "accepted": True,
        "queued": False,
        "via": "inline",
        "row_number": lead.row_number,
        "row_key": lead.row_key,
    }
