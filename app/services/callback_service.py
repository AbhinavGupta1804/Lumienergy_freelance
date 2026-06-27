"""
Callback retry orchestration — Approach B (Twilio API lookup after ElevenLabs post-call).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.integrations.twilio_calls import TwilioCallError, fetch_call_status_terminal
from app.services.call_orchestrator import CallOrchestrator
from app.utils.callback_schedule import (
    compute_next_retry_at,
    is_call_answered,
    is_call_unanswered,
)
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class CallbackService:
    def __init__(self, store: DedupStore) -> None:
        self._store = store

    async def on_conversation_ended(self, conversation_id: str) -> dict:
        """
        After ElevenLabs post-call: fetch Twilio status, stop or schedule next retry.
        """
        settings = get_settings()
        if not settings.callback_enabled:
            return {"action": "skipped", "reason": "callback_disabled"}

        row = self._store.get_by_conversation_id(conversation_id)
        if not row:
            return {"action": "skipped", "reason": "unknown_conversation"}

        row_key = row.get("row_key") or ""
        call_sid = row.get("call_sid") or ""
        if not call_sid:
            self._store.release_call_in_progress(row_key)
            return {"action": "skipped", "reason": "missing_call_sid"}

        try:
            twilio = await fetch_call_status_terminal(call_sid)
        except TwilioCallError as exc:
            logger.error(
                "Twilio status fetch failed conversation_id=%s call_sid=%s: %s",
                conversation_id,
                call_sid,
                exc,
            )
            self._store.release_call_in_progress(row_key)
            return {"action": "failed", "error": str(exc)}

        status = str(twilio.get("status") or "")
        twilio_duration = int(twilio.get("duration") or 0)
        el_duration = int(row.get("call_duration_secs") or 0)
        duration = max(twilio_duration, el_duration)
        ended_at = _parse_iso(row.get("call_ended_at")) or datetime.now(timezone.utc)

        if el_duration > twilio_duration:
            logger.info(
                "Using ElevenLabs duration=%ss (Twilio=%ss) call_sid=%s",
                el_duration,
                twilio_duration,
                call_sid,
            )

        return self._apply_outcome(
            row_key=row_key,
            row=row,
            twilio_status=status,
            duration_secs=duration,
            ended_at=ended_at,
        )

    async def reconcile_stuck_call(self, row: dict) -> dict | None:
        """
        Fallback when ElevenLabs post-call webhook never arrived.

        Poll Twilio for terminal status and schedule (or stop) the callback chain.
        """
        row_key = row.get("row_key") or ""
        call_sid = row.get("call_sid") or ""
        if not row_key or not call_sid:
            return None

        try:
            twilio = await fetch_call_status_terminal(call_sid, max_wait_seconds=15)
        except TwilioCallError as exc:
            logger.error("Reconcile failed row_key=%s call_sid=%s: %s", row_key, call_sid, exc)
            return None

        status = str(twilio.get("status") or "")
        if status not in {"completed", "busy", "no-answer", "failed", "canceled"}:
            return None

        duration = int(twilio.get("duration") or 0)
        ended_at = datetime.now(timezone.utc)
        logger.info(
            "Reconciling stuck call row_key=%s call_sid=%s twilio_status=%s duration=%s",
            row_key,
            call_sid,
            status,
            duration,
        )
        return self._apply_outcome(
            row_key=row_key,
            row=row,
            twilio_status=status,
            duration_secs=duration,
            ended_at=ended_at,
        )

    def _apply_outcome(
        self,
        *,
        row_key: str,
        row: dict,
        twilio_status: str,
        duration_secs: int,
        ended_at: datetime,
    ) -> dict:
        prev_attempt = int(row.get("callback_attempt") or 0)
        new_attempt = prev_attempt + 1
        first_call_at = _parse_iso(row.get("first_call_at")) or _parse_iso(
            row.get("processed_at")
        ) or ended_at

        if is_call_answered(twilio_status, duration_secs):
            self._store.update_callback_outcome(
                row_key=row_key,
                callback_attempt=new_attempt,
                callback_status="answered",
                next_retry_at=None,
                last_twilio_status=twilio_status,
                call_in_progress=False,
            )
            logger.info(
                "Callback stopped — answered row_key=%s attempt=%s status=%s duration=%ss",
                row_key,
                new_attempt,
                twilio_status,
                duration_secs,
            )
            return {
                "action": "answered",
                "answered": True,
                "callback_attempt": new_attempt,
                "twilio_status": twilio_status,
                "duration_secs": duration_secs,
            }

        if not is_call_unanswered(twilio_status, duration_secs):
            self._store.update_callback_outcome(
                row_key=row_key,
                callback_attempt=new_attempt,
                callback_status=row.get("callback_status") or "active",
                next_retry_at=row.get("next_retry_at"),
                last_twilio_status=twilio_status,
                call_in_progress=False,
            )
            logger.info(
                "Callback not scheduled — non-retry status row_key=%s status=%s",
                row_key,
                twilio_status,
            )
            return {
                "action": "ignored",
                "answered": False,
                "reason": "non_retry_status",
                "twilio_status": twilio_status,
            }

        next_retry = compute_next_retry_at(
            completed_attempt=new_attempt,
            last_ended_at=ended_at,
            first_call_at=first_call_at,
        )
        if next_retry is None:
            self._store.update_callback_outcome(
                row_key=row_key,
                callback_attempt=new_attempt,
                callback_status="exhausted",
                next_retry_at=None,
                last_twilio_status=twilio_status,
                call_in_progress=False,
            )
            logger.info(
                "Callback exhausted row_key=%s after attempt=%s",
                row_key,
                new_attempt,
            )
            return {
                "action": "exhausted",
                "answered": False,
                "callback_attempt": new_attempt,
                "twilio_status": twilio_status,
            }

        next_iso = next_retry.astimezone(timezone.utc).isoformat()
        self._store.update_callback_outcome(
            row_key=row_key,
            callback_attempt=new_attempt,
            callback_status="active",
            next_retry_at=next_iso,
            last_twilio_status=twilio_status,
            call_in_progress=False,
        )
        logger.info(
            "Callback scheduled row_key=%s attempt=%s next_retry_at=%s status=%s",
            row_key,
            new_attempt,
            next_iso,
            twilio_status,
        )
        return {
            "action": "scheduled",
            "answered": False,
            "callback_attempt": new_attempt,
            "next_retry_at": next_iso,
            "twilio_status": twilio_status,
        }

    async def process_due_retries(self, orchestrator: CallOrchestrator) -> dict:
        """APScheduler tick — dial leads whose next_retry_at has passed."""
        settings = get_settings()
        if not settings.callback_enabled:
            return {"action": "skipped", "reason": "callback_disabled"}

        now = datetime.now(timezone.utc)
        before_iso = now.isoformat()

        reconcile_before = (
            now - timedelta(minutes=settings.callback_reconcile_after_minutes)
        ).isoformat()
        stuck = self._store.list_stuck_active_calls(
            stale_before_iso=reconcile_before, limit=20
        )
        for row in stuck:
            result = await self.reconcile_stuck_call(row)
            if result:
                logger.info("Stuck call reconciled row_key=%s: %s", row.get("row_key"), result)

        stale_before = (
            now - timedelta(minutes=settings.callback_stale_in_progress_minutes)
        ).isoformat()
        released = self._store.release_stale_in_progress(stale_before_iso=stale_before)
        if released:
            logger.warning("Released %s stale call_in_progress lock(s)", released)

        due = self._store.list_due_callbacks(before_iso=before_iso, limit=20)
        if not due:
            return {"action": "idle", "processed": 0}

        results: list[dict] = []
        for row in due:
            row_key = row.get("row_key") or ""
            if not row_key:
                continue
            if not self._store.claim_callback_dial(row_key, before_iso=before_iso):
                continue
            logger.info(
                "Callback dial starting row_key=%s phone=%s attempt=%s",
                row_key,
                row.get("dial_to") or row.get("phone_no"),
                row.get("callback_attempt"),
            )
            outcome = await orchestrator.retry_call_for_row(row)
            results.append({"row_key": row_key, **outcome})

        return {"action": "processed", "count": len(results), "results": results}
