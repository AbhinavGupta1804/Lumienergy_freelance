"""
Processes incoming leads from the Google Sheets webhook (or manual triggers).
"""

import logging

from app.models.lead import Lead
from app.services.call_orchestrator import CallOrchestrator
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class LeadProcessor:
    """Webhook lead → outbound call."""

    def __init__(self, dedup_store: DedupStore) -> None:
        self._dedup = dedup_store
        self._orchestrator = CallOrchestrator(dedup_store)

    async def process_incoming(self, lead: Lead) -> dict:
        """Process one lead pushed from Apps Script or a manual trigger."""
        if self._dedup.is_processed(lead.row_key):
            logger.info("Skipping row %s — already processed", lead.row_number)
            return {
                "skipped": True,
                "reason": "already_processed",
                "row_key": lead.row_key,
            }

        outcome = await self._orchestrator.process_lead(lead)
        return {"row_number": lead.row_number, **outcome}
