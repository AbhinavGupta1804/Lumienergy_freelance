"""
Google Sheets webhook — called by Apps Script when a new lead row is added.

Install scripts/sheets_webhook.gs in the spreadsheet and point it at:
  POST {PUBLIC_BASE_URL}/webhooks/sheets/new-lead
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.integrations.customer_notifications import notification_channel
from app.integrations.google_sheets import build_row_key
from app.models.lead import Lead
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

    def to_lead(self) -> Lead:
        from datetime import datetime, timezone

        first_name = self.first_name.strip()
        last_name = self.last_name.strip()
        address = self.address.strip()
        phone_no = self.phone_no.strip()
        email = self.email.strip()
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


async def _process_lead_task(processor: LeadProcessor, lead: Lead) -> None:
    try:
        result = await processor.process_incoming(lead)
        logger.info("Sheets webhook processed row %s: %s", lead.row_number, result)
    except Exception:
        logger.exception("Sheets webhook failed for row %s", lead.row_number)


@router.post("/new-lead")
async def sheets_new_lead(
    request: Request,
    body: NewLeadBody,
    background_tasks: BackgroundTasks,
    x_sheets_webhook_secret: str | None = Header(default=None, alias="X-Sheets-Webhook-Secret"),
) -> dict:
    """
    Receive a new lead from Google Apps Script and place an outbound call.

    Returns immediately; the call is initiated in a background task.
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

    processor: LeadProcessor = request.app.state.lead_processor
    background_tasks.add_task(_process_lead_task, processor, lead)
    logger.info("Sheets webhook accepted row %s (%s) email=%s", lead.row_number, lead.full_name, lead.email or "(empty)")

    return {
        "accepted": True,
        "queued": True,
        "row_number": lead.row_number,
        "row_key": lead.row_key,
    }
