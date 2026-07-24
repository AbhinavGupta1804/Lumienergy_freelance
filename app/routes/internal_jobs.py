"""
Internal job endpoints — invoked by Google Cloud Tasks at the scheduled time.

Auth: X-Internal-Jobs-Secret must match INTERNAL_JOBS_SECRET.
Handlers always re-check lead state (booked / cancelled) before acting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.call_orchestrator import CallOrchestrator
from app.services.post_call_report import PostCallReportService
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/jobs", tags=["internal-jobs"])


class FollowupEmailBody(BaseModel):
    row_key: str = Field(..., min_length=1)
    expected_attempt: int = Field(..., ge=1)


class CallbackDialBody(BaseModel):
    row_key: str = Field(..., min_length=1)
    expected_attempt: int = Field(1, ge=0)


def _verify_secret(header_value: str | None) -> None:
    settings = get_settings()
    expected = (settings.internal_jobs_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_JOBS_SECRET not configured")
    if not header_value or header_value.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid job secret")


@router.post("/followup-email")
async def run_followup_email(
    body: FollowupEmailBody,
    request: Request,
    x_internal_jobs_secret: str | None = Header(default=None),
) -> JSONResponse:
    _verify_secret(x_internal_jobs_secret)

    store: DedupStore = request.app.state.dedup_store
    report: PostCallReportService = request.app.state.post_call_report_service
    row = store.get_by_row_key(body.row_key)
    if not row:
        return JSONResponse({"ok": True, "action": "skipped", "reason": "unknown_row"})

    status = (row.get("followup_email_status") or "").strip()
    if status != "active":
        return JSONResponse(
            {"ok": True, "action": "skipped", "reason": f"status_{status or 'none'}"}
        )

    current = int(row.get("followup_email_attempt") or 0)
    if current >= body.expected_attempt:
        return JSONResponse(
            {
                "ok": True,
                "action": "skipped",
                "reason": "already_sent",
                "attempt": current,
            }
        )
    if current + 1 != body.expected_attempt:
        logger.warning(
            "Follow-up attempt mismatch row_key=%s expected=%s current=%s",
            body.row_key,
            body.expected_attempt,
            current,
        )
        # Still allow if we're behind (missed a task) — only block if ahead
        if current + 1 > body.expected_attempt:
            return JSONResponse(
                {"ok": True, "action": "skipped", "reason": "attempt_mismatch"}
            )

    # Claim so a concurrent task delivery won't double-send
    store.claim_followup_email(
        body.row_key, before_iso="9999-12-31T00:00:00+00:00"
    )

    # Re-load after claim
    row = store.get_by_row_key(body.row_key) or row
    result = await report._send_followup_for_row(row)

    logger.info("Cloud Tasks follow-up email row_key=%s result=%s", body.row_key, result)
    return JSONResponse({"ok": True, **result})


@router.post("/callback-dial")
async def run_callback_dial(
    body: CallbackDialBody,
    request: Request,
    x_internal_jobs_secret: str | None = Header(default=None),
) -> JSONResponse:
    _verify_secret(x_internal_jobs_secret)

    store: DedupStore = request.app.state.dedup_store
    orchestrator: CallOrchestrator = request.app.state.call_orchestrator
    row = store.get_by_row_key(body.row_key)
    if not row:
        return JSONResponse({"ok": True, "action": "skipped", "reason": "unknown_row"})

    if row.get("self_booked") or (row.get("callback_status") or "") == "self_booked":
        store.update_callback_outcome(
            row_key=body.row_key,
            callback_attempt=int(row.get("callback_attempt") or 0),
            callback_status="self_booked",
            next_retry_at=None,
            last_twilio_status=row.get("last_twilio_status"),
            call_in_progress=False,
        )
        return JSONResponse({"ok": True, "action": "self_booked"})

    if (row.get("callback_status") or "") != "active":
        return JSONResponse(
            {
                "ok": True,
                "action": "skipped",
                "reason": f"status_{row.get('callback_status') or 'none'}",
            }
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    # Allow claim even if next_retry_at was cleared somehow — force due
    if row.get("next_retry_at"):
        claimed = store.claim_callback_dial(body.row_key, before_iso=now_iso)
        if not claimed:
            # Maybe clock skew: try claiming with a far-future before_iso
            claimed = store.claim_callback_dial(
                body.row_key, before_iso="9999-12-31T00:00:00+00:00"
            )
        if not claimed:
            return JSONResponse(
                {"ok": True, "action": "skipped", "reason": "claim_failed"}
            )
    else:
        # next_retry_at already cleared — set in-progress manually via claim path
        # Update call_in_progress by claiming with future bound after restoring next_retry
        store.update_callback_outcome(
            row_key=body.row_key,
            callback_attempt=int(row.get("callback_attempt") or 0),
            callback_status="active",
            next_retry_at=now_iso,
            last_twilio_status=row.get("last_twilio_status"),
            call_in_progress=False,
        )
        if not store.claim_callback_dial(body.row_key, before_iso=now_iso):
            return JSONResponse(
                {"ok": True, "action": "skipped", "reason": "claim_failed"}
            )

    row = store.get_by_row_key(body.row_key) or row
    logger.info(
        "Cloud Tasks callback dial starting row_key=%s attempt=%s",
        body.row_key,
        row.get("callback_attempt"),
    )
    outcome = await orchestrator.retry_call_for_row(row)
    return JSONResponse({"ok": True, "action": "dialed", **outcome})
