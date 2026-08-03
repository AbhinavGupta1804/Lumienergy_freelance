"""
Job scheduling facade — Google Cloud Tasks.

DB columns (next_retry_at / next_followup_email_at) remain the source of truth.
Cloud Tasks is the timer that wakes the app at the right moment.
Handlers always re-check booked/cancelled before acting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.integrations.cloud_tasks import (
    create_http_task,
    delete_task_by_id,
    use_cloud_tasks,
)

logger = logging.getLogger(__name__)


def followup_task_id(row_key: str, attempt: int) -> str:
    return f"fu-{row_key}-a{attempt}"


def callback_task_id(row_key: str, attempt: int) -> str:
    return f"cb-{row_key}-a{attempt}"


def process_lead_task_id(row_key: str) -> str:
    return f"pl-{row_key}"


def schedule_process_lead_job(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Enqueue outbound dial (+ dial-fail report) as its own Cloud Run request.

    Sheets webhooks must not rely on FastAPI BackgroundTasks under request-based
    Cloud Run billing — CPU stops after the HTTP response and PDF/email dies.
    """
    from datetime import datetime, timezone

    row_number = payload.get("row_number")
    row_key = str(payload.get("row_key") or f"row-{row_number}")
    if not use_cloud_tasks():
        logger.warning(
            "Process-lead not enqueued — Cloud Tasks not configured row_key=%s",
            row_key,
        )
        return {"backend": "none", "scheduled": False}

    name = create_http_task(
        relative_url="/internal/jobs/process-lead",
        payload=payload,
        schedule_time=datetime.now(timezone.utc),
        task_id=process_lead_task_id(row_key),
    )
    return {
        "backend": "cloud_tasks",
        "scheduled": bool(name),
        "task_name": name,
        "row_key": row_key,
    }


def schedule_followup_email_job(
    *,
    row_key: str,
    attempt: int,
    schedule_at: datetime | str,
) -> dict[str, Any]:
    """
    Schedule follow-up email #attempt for this lead.
    ``attempt`` is 1-based (the attempt about to be sent).
    """
    if not use_cloud_tasks():
        logger.warning(
            "Follow-up email not enqueued — Cloud Tasks not configured row_key=%s",
            row_key,
        )
        return {"backend": "none", "scheduled": False}

    name = create_http_task(
        relative_url="/internal/jobs/followup-email",
        payload={"row_key": row_key, "expected_attempt": attempt},
        schedule_time=schedule_at,
        task_id=followup_task_id(row_key, attempt),
    )
    return {
        "backend": "cloud_tasks",
        "scheduled": bool(name),
        "task_name": name,
        "attempt": attempt,
    }


def schedule_callback_dial_job(
    *,
    row_key: str,
    attempt: int,
    schedule_at: datetime | str,
) -> dict[str, Any]:
    """
    Schedule the next callback dial.
    ``attempt`` is the completed_attempt count after the last call (matches
    what compute_next_retry_at used), used only for a stable task id.
    """
    if not use_cloud_tasks():
        logger.warning(
            "Callback dial not enqueued — Cloud Tasks not configured row_key=%s",
            row_key,
        )
        return {"backend": "none", "scheduled": False}

    name = create_http_task(
        relative_url="/internal/jobs/callback-dial",
        payload={"row_key": row_key, "expected_attempt": attempt},
        schedule_time=schedule_at,
        task_id=callback_task_id(row_key, attempt),
    )
    return {
        "backend": "cloud_tasks",
        "scheduled": bool(name),
        "task_name": name,
        "attempt": attempt,
    }


def cancel_pending_followup_jobs(
    row_key: str,
    *,
    known_attempt: int | None = None,
) -> int:
    """
    Delete the one pending follow-up Cloud Task for this lead.

    Task ids are ``fu-{row_key}-a{N}`` where N is the *next* email to send
    (followup_email_attempt + 1). We only ever create one at a time, so we
    only delete that one.
    """
    if not use_cloud_tasks():
        return 0
    if known_attempt is None or known_attempt < 0:
        return 0

    settings = get_settings()
    max_a = max(1, int(settings.followup_email_max_attempts or 4))
    # Row stores last completed attempt; pending task is the next one.
    next_attempt = known_attempt + 1
    if next_attempt < 1 or next_attempt > max_a:
        return 0
    return 1 if delete_task_by_id(followup_task_id(row_key, next_attempt)) else 0


def cancel_pending_callback_jobs(
    row_key: str,
    *,
    known_attempt: int | None = None,
) -> int:
    """
    Delete the one pending callback Cloud Task for this lead.

    Task ids are ``cb-{row_key}-a{N}`` with the same N used at schedule time
    (stored as ``callback_attempt`` on the row). One create → one delete.
    """
    if not use_cloud_tasks():
        return 0
    if known_attempt is None or known_attempt <= 0:
        return 0
    return (
        1
        if delete_task_by_id(callback_task_id(row_key, known_attempt))
        else 0
    )


def cancel_jobs_for_lead(row: dict[str, Any]) -> dict[str, int]:
    """Cancel callback + follow-up Cloud Tasks using attempt counters on the row."""
    row_key = (row.get("row_key") or "").strip()
    if not row_key:
        return {"callbacks": 0, "followups": 0}
    cb_attempt = int(row.get("callback_attempt") or 0)
    fu_attempt = int(row.get("followup_email_attempt") or 0)
    return {
        "callbacks": cancel_pending_callback_jobs(
            row_key, known_attempt=cb_attempt or None
        ),
        "followups": cancel_pending_followup_jobs(
            row_key, known_attempt=fu_attempt
        ),
    }
