"""
FastAPI application entry point.

Workflow:
  1. Google Apps Script POSTs new sheet rows to /webhooks/sheets/new-lead
  2. New rows trigger ElevenLabs outbound call API (Twilio + agent)
  3. Dynamic variables first_name + address are passed to the agent
  4. Dedup store prevents repeat calls for the same row

Run locally:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routes import (
    admin,
    calls,
    elevenlabs_webhooks,
    health,
    lumi_webhooks,
    scheduling,
    sheets_webhooks,
    webhooks,
)
from app.services.call_orchestrator import CallOrchestrator
from app.services.lead_processor import LeadProcessor
from app.services.post_call_sms import PostCallSmsService
from app.utils.dedup_store import DedupStore
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging and dedup store. Leads arrive via Sheets webhook."""
    settings = get_settings()
    setup_logging(settings.log_level)

    dedup_store = DedupStore(settings.dedup_db_path)
    lead_processor = LeadProcessor(dedup_store)
    call_orchestrator = CallOrchestrator(dedup_store)
    post_call_sms = PostCallSmsService(dedup_store)

    app.state.dedup_store = dedup_store
    app.state.lead_processor = lead_processor
    app.state.call_orchestrator = call_orchestrator
    app.state.post_call_sms_service = post_call_sms

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Google Sheets → ElevenLabs AI outbound calling",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(sheets_webhooks.router)
    app.include_router(webhooks.router)
    app.include_router(calls.router)
    app.include_router(scheduling.router)
    app.include_router(lumi_webhooks.router)
    app.include_router(elevenlabs_webhooks.router)
    app.include_router(admin.router)

    admin_static = Path(__file__).resolve().parent.parent / "admin_dashboard" / "public"
    if admin_static.is_dir():
        app.mount(
            "/admin",
            StaticFiles(directory=str(admin_static), html=True),
            name="admin_dashboard",
        )

    return app


app = create_app()
