"""
Google Cloud Tasks client — schedule HTTP callbacks at exact times.

Auth (preferred — no JSON key):
  Application Default Credentials
  - Local: gcloud auth application-default login (your user with Enqueuer/Editor)
  - Cloud Run: runtime service account with roles/cloudtasks.enqueuer

Optional:
  CLOUD_TASKS_SERVICE_ACCOUNT_JSON — only if you explicitly want a dedicated key.
  Never reuse the Sheets GOOGLE_SERVICE_ACCOUNT_JSON here (different project/SA).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_TASK_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def cloud_tasks_configured() -> bool:
    """True when Cloud Tasks env is set. JSON key is optional (ADC on Cloud Run)."""
    settings = get_settings()
    return bool(
        settings.gcp_project_id
        and settings.gcp_location
        and settings.cloud_tasks_queue
        and settings.public_base_url
        and settings.internal_jobs_secret
    )


def use_cloud_tasks() -> bool:
    """True when jobs should be dispatched via Cloud Tasks."""
    settings = get_settings()
    backend = (settings.job_scheduler_backend or "auto").strip().lower()
    if backend in ("off", "disabled", "none", "apscheduler"):
        return False
    if backend == "cloud_tasks":
        return cloud_tasks_configured()
    # auto
    return cloud_tasks_configured()


def _sanitize_task_id(task_id: str) -> str:
    cleaned = _TASK_ID_SAFE.sub("-", task_id).strip("-")
    return cleaned[:500] or "task"


def _queue_path() -> str:
    settings = get_settings()
    return (
        f"projects/{settings.gcp_project_id}"
        f"/locations/{settings.gcp_location}"
        f"/queues/{settings.cloud_tasks_queue}"
    )


def _key_file_path() -> str | None:
    """
    Optional JSON key for Cloud Tasks only.

    Do NOT fall back to GOOGLE_SERVICE_ACCOUNT_JSON (Sheets SA) — that is often
    a different project and will cause cloudtasks.tasks.create PERMISSION_DENIED.
    On Cloud Run / local ADC, leave CLOUD_TASKS_SERVICE_ACCOUNT_JSON unset.
    """
    settings = get_settings()
    path = (settings.cloud_tasks_service_account_json or "").strip()
    if path and Path(path).is_file():
        return path
    return None


def _client():
    from google.cloud import tasks_v2

    key_path = _key_file_path()
    if key_path:
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        logger.debug("Cloud Tasks client using key file %s", key_path)
        return tasks_v2.CloudTasksClient(credentials=creds)

    # Cloud Run / GCE: metadata server credentials (no downloaded key)
    logger.debug("Cloud Tasks client using Application Default Credentials")
    return tasks_v2.CloudTasksClient()


def create_http_task(
    *,
    relative_url: str,
    payload: dict[str, Any],
    schedule_time: datetime | str,
    task_id: str,
) -> str | None:
    """
    Create (or replace) a delayed HTTP POST task.

    Returns the full task name, or None if Cloud Tasks is not configured /
    creation failed.
    """
    if not cloud_tasks_configured():
        return None

    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    url = f"{base}{relative_url}"

    if isinstance(schedule_time, str):
        when = datetime.fromisoformat(schedule_time.replace("Z", "+00:00"))
    else:
        when = schedule_time
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)

    # Cloud Tasks rejects schedule_time in the past — clamp to ~now+5s
    now = datetime.now(timezone.utc)
    if when <= now:
        when = now + timedelta(seconds=5)

    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(when)

    headers = {
        "Content-Type": "application/json",
        "X-Internal-Jobs-Secret": settings.internal_jobs_secret,
    }
    http_request: dict[str, Any] = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": url,
        "headers": headers,
        "body": json.dumps(payload).encode("utf-8"),
    }
    # OIDC: Cloud Tasks presents as this SA when calling Cloud Run
    invoker = (settings.cloud_tasks_invoker_sa or "").strip()
    if invoker:
        http_request["oidc_token"] = {
            "service_account_email": invoker,
            "audience": base,
        }

    safe_id = _sanitize_task_id(task_id)
    parent = _queue_path()
    task_name = f"{parent}/tasks/{safe_id}"
    task: dict[str, Any] = {
        "name": task_name,
        "http_request": http_request,
        "schedule_time": ts,
    }

    client = _client()
    try:
        # Replace if a prior task with this id still exists
        try:
            client.delete_task(name=task_name)
        except Exception:
            pass
        response = client.create_task(request={"parent": parent, "task": task})
        logger.info(
            "Cloud Task created name=%s schedule=%s url=%s",
            response.name,
            when.isoformat(),
            url,
        )
        return response.name
    except Exception:
        logger.exception(
            "Cloud Task create failed task_id=%s url=%s schedule=%s",
            safe_id,
            url,
            when.isoformat(),
        )
        return None


def delete_task_by_id(task_id: str) -> bool:
    """Best-effort delete of a pending task. Returns True if deleted."""
    if not cloud_tasks_configured():
        return False
    safe_id = _sanitize_task_id(task_id)
    name = f"{_queue_path()}/tasks/{safe_id}"
    try:
        _client().delete_task(name=name)
        logger.info("Cloud Task deleted name=%s", name)
        return True
    except Exception:
        logger.debug("Cloud Task delete skipped/failed name=%s", name, exc_info=True)
        return False
