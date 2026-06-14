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
    """Show webhook config and recent processed leads."""
    dedup = request.app.state.dedup_store
    settings = get_settings()
    return {
        "sheets_webhook_configured": bool(settings.sheets_webhook_secret),
        "public_base_url": settings.public_base_url or None,
        "database_backend": settings.database_backend,
        "processed_leads": dedup.list_processed(limit=20),
    }
