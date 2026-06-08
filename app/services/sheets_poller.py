"""
Background asyncio task that polls Google Sheets every N seconds.

Started on FastAPI startup; cancelled cleanly on shutdown.
"""

import asyncio
import logging

from app.config import get_settings
from app.services.lead_processor import LeadProcessor
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


class SheetsPoller:
    """Runs LeadProcessor.run_once() on a fixed interval."""

    def __init__(self, dedup_store: DedupStore) -> None:
        self._processor = LeadProcessor(dedup_store)
        self._task: asyncio.Task | None = None
        self._running = False

    async def _poll_loop(self) -> None:
        settings = get_settings()
        interval = settings.sheets_poll_interval_seconds
        logger.info("Sheets poller started (interval=%ss)", interval)

        while self._running:
            try:
                await self._processor.run_once()
            except Exception:
                logger.exception("Error during sheets poll cycle")
            await asyncio.sleep(interval)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="sheets_poller")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Sheets poller stopped")
