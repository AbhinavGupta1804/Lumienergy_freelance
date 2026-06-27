"""APScheduler job — dial due callback retries every minute."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.services.callback_service import CallbackService
from app.services.call_orchestrator import CallOrchestrator
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


def create_callback_scheduler(
    store: DedupStore,
    orchestrator: CallOrchestrator,
) -> AsyncIOScheduler | None:
    settings = get_settings()
    if not settings.callback_enabled:
        logger.info("Callback scheduler disabled (CALLBACK_ENABLED=false)")
        return None

    service = CallbackService(store)
    tz = ZoneInfo(settings.business_timezone)
    scheduler = AsyncIOScheduler(timezone=tz)
    logger.info(
        "Callback scheduler uses business timezone %s (retry slots 9 AM / 7 PM local); "
        "tick interval %ss on server clock",
        settings.business_timezone,
        settings.callback_scheduler_interval_seconds,
    )

    async def _tick() -> None:
        try:
            result = await service.process_due_retries(orchestrator)
            if result.get("action") == "processed":
                logger.info("Callback scheduler tick: %s", result)
        except Exception:
            logger.exception("Callback scheduler tick failed")

    scheduler.add_job(
        _tick,
        "interval",
        seconds=settings.callback_scheduler_interval_seconds,
        id="callback_retries",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
