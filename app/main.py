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

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routes import (
    admin,
    bill_upload_webhooks,
    calls,
    elevenlabs_webhooks,
    health,
    lumi_webhooks,
    scheduling,
    sheets_webhooks,
    webhooks,
)
from app.services.bill_upload_confirmation_sms import BillUploadConfirmationSmsService
from app.services.call_orchestrator import CallOrchestrator
from app.services.callback_scheduler import create_callback_scheduler
from app.services.callback_service import CallbackService
from app.services.lead_processor import LeadProcessor
from app.services.post_call_sms import PostCallSmsService
from app.utils.dedup_store import DedupStore
from app.utils.logging import setup_logging
from app.utils.message_store import CustomerMessageStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging and dedup store. Leads arrive via Sheets webhook."""
    settings = get_settings()
    setup_logging(settings.log_level)

    dedup_store = DedupStore(settings.dedup_db_path)
    message_store = CustomerMessageStore(settings.dedup_db_path)
    lead_processor = LeadProcessor(dedup_store)
    call_orchestrator = CallOrchestrator(dedup_store)
    post_call_sms = PostCallSmsService(dedup_store, message_store)
    bill_upload_confirmation_sms = BillUploadConfirmationSmsService(
        dedup_store, message_store
    )
    callback_service = CallbackService(dedup_store)

    app.state.dedup_store = dedup_store
    app.state.message_store = message_store
    app.state.lead_processor = lead_processor
    app.state.call_orchestrator = call_orchestrator
    app.state.post_call_sms_service = post_call_sms
    app.state.bill_upload_confirmation_sms_service = bill_upload_confirmation_sms
    app.state.callback_service = callback_service

    scheduler = None
    scheduler = create_callback_scheduler(dedup_store, call_orchestrator)
    if scheduler:
        scheduler.start()
        logger.info(
            "Callback scheduler started (every %ss)",
            settings.callback_scheduler_interval_seconds,
        )

    yield

    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Google Sheets → ElevenLabs AI outbound calling",
        version="1.0.0",
        lifespan=lifespan,
    )
    origins = [
        o.strip()
        for o in (settings.cors_origins or "").split(",")
        if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(sheets_webhooks.router)
    app.include_router(webhooks.router)
    app.include_router(calls.router)
    app.include_router(scheduling.router)
    app.include_router(lumi_webhooks.router)
    app.include_router(elevenlabs_webhooks.router)
    app.include_router(bill_upload_webhooks.router)
    app.include_router(admin.router)

    # Legacy static admin (optional) — Next.js runs on :3000
    legacy_static = (
        Path(__file__).resolve().parent.parent / "admin_dashboard" / "_legacy" / "public"
    )
    if legacy_static.is_dir():
        app.mount(
            "/admin-legacy",
            StaticFiles(directory=str(legacy_static), html=True),
            name="admin_dashboard_legacy",
        )

    return app


app = create_app()
