"""
Processes all new leads from a single poll cycle.

Filters out rows already in the dedup store, then triggers calls sequentially
to avoid hammering APIs (simple and safe for initial version).
"""

import logging

from app.integrations.google_sheets import GoogleSheetsClient
from app.models.lead import Lead
from app.services.call_orchestrator import CallOrchestrator
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class LeadProcessor:
    """Poll sheet → find new rows → place outbound calls."""

    def __init__(self, dedup_store: DedupStore) -> None:
        self._dedup = dedup_store
        self._sheets: GoogleSheetsClient | None = None
        self._orchestrator = CallOrchestrator(dedup_store)

    def _get_sheets(self) -> GoogleSheetsClient:
        if self._sheets is None:
            self._sheets = GoogleSheetsClient()
        return self._sheets

    def _new_leads(self, leads: list[Lead]) -> list[Lead]:
        return [lead for lead in leads if not self._dedup.is_processed(lead.row_key)]

    async def run_once(self) -> dict:
        """
        One processing cycle: read sheet and call each new lead.

        Returns summary statistics.
        """
        leads = self._get_sheets().fetch_leads()
        new_leads = self._new_leads(leads)

        results = []
        for lead in new_leads:
            outcome = await self._orchestrator.process_lead(lead)
            results.append({"row_number": lead.row_number, **outcome})

        summary = {
            "total_rows": len(leads),
            "new_leads": len(new_leads),
            "results": results,
        }
        if new_leads:
            logger.info("Poll cycle complete: %s new lead(s) processed", len(new_leads))
        else:
            logger.debug("Poll cycle: no new leads")
        return summary
