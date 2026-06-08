"""
Health and status routes.
"""

from fastapi import APIRouter, Request

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Liveness probe — confirms API is running."""
    return {"status": "ok"}


@router.get("/status")
async def status(request: Request) -> dict:
    """Show poller state and recent processed leads."""
    dedup = request.app.state.dedup_store
    poller_running = (
        request.app.state.sheets_poller.is_running
        if hasattr(request.app.state, "sheets_poller")
        else False
    )
    settings = get_settings()
    return {
        "poller_running": poller_running,
        "database_backend": settings.database_backend,
        "processed_leads": dedup.list_processed(limit=20),
    }
