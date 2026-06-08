"""
Manual call triggers — useful for testing without waiting for the poller.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.integrations.google_sheets import GoogleSheetsClient
from app.services.lead_processor import LeadProcessor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["calls"])


class ManualCallRequest(BaseModel):
    """Trigger a call by sheet row number."""

    row_number: int = Field(..., ge=2, description="Sheet row number (2 = first data row)")


@router.post("/trigger-poll")
async def trigger_poll(request: Request) -> dict:
    """
    Force one Google Sheets poll cycle immediately.

    Same logic as the background poller — useful for testing after adding a row.
    """
    processor: LeadProcessor = request.app.state.lead_processor
    try:
        return await processor.run_once()
    except Exception as exc:
        logger.exception("Manual poll failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/trigger-row")
async def trigger_row(request: Request, body: ManualCallRequest) -> dict:
    """
    Call a specific sheet row by row number (bypasses waiting for poller).

    Still respects dedup unless you clear the SQLite store.
    """
    dedup = request.app.state.dedup_store
    orchestrator = request.app.state.call_orchestrator

    sheets = GoogleSheetsClient()
    leads = sheets.fetch_leads()
    lead = next((l for l in leads if l.row_number == body.row_number), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Row {body.row_number} not found")

    if dedup.is_processed(lead.row_key):
        return {
            "message": "Row already processed",
            "row_key": lead.row_key,
            "hint": "Delete entry from data/processed_leads.db to retry",
        }

    result = await orchestrator.process_lead(lead)
    return {"row_number": body.row_number, **result}
