"""
SMS nurture: Stage 1 (appointment booked) + Stage 2 (10-touch no-answer).

Triggered by Zoho custom buttons → FastAPI webhooks.
Touch 1 sends on Stage 2 webhook; touches 2–10 via Cloud Tasks on cadence.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.content.nurture_sms_templates import (
    STAGE2_CADENCE_DAYS,
    render_stage1_sms,
    render_stage2_sms,
)
from app.integrations.twilio_sms import TwilioSmsError, send_sms
from app.services.job_scheduler import (
    cancel_pending_nurture_jobs,
    schedule_nurture_sms_job,
)
from app.services.message_logger import log_outbound_failure, log_outbound_message
from app.utils.dedup_store import DedupStore
from app.utils.message_store import CustomerMessageStore
from app.utils.phone import normalize_e164
from app.utils.sms_consent import is_sms_consent_granted

logger = logging.getLogger(__name__)

_STOP_RE = re.compile(
    r"^\s*(stop|stopall|unsubscribe|cancel|end|quit)\s*$",
    re.IGNORECASE,
)


def is_sms_stop_keyword(body: str) -> bool:
    return bool(_STOP_RE.match((body or "").strip()))


class SmsNurtureService:
    def __init__(
        self,
        store: DedupStore,
        message_store: CustomerMessageStore,
    ) -> None:
        self._store = store
        self._message_store = message_store

    def resolve_lead(
        self,
        *,
        phone: str = "",
        email: str = "",
        name: str = "",
        zoho_lead_id: str = "",
        address: str = "",
        row_key: str = "",
    ) -> dict | None:
        if row_key:
            row = self._store.get_by_row_key(row_key)
            if row:
                return row
        if zoho_lead_id or phone or email:
            return self._store.ensure_lead_for_nurture(
                phone=phone,
                email=email,
                name=name,
                zoho_lead_id=zoho_lead_id,
                address=address,
            )
        return None

    def _sms_block_reason(self, lead: dict) -> str | None:
        """Return skip reason if SMS must not send; None if allowed."""
        phone = (lead.get("phone_no") or lead.get("dial_to") or "").strip()
        if self._store.is_sms_opted_out(phone) or lead.get("sms_opt_out") in (
            True,
            1,
            "1",
            "true",
            "True",
        ):
            return "sms_opted_out"
        if not is_sms_consent_granted(lead.get("sms_eligible")):
            return "no_sms_consent"
        return None

    async def on_appointment_booked(self, lead: dict) -> dict:
        """Stage 1 — cancel Stage 2 sequence and send booked companion SMS."""
        settings = get_settings()
        if not settings.nurture_sms_enabled:
            return {"action": "skipped", "reason": "nurture_sms_disabled"}

        row_key = (lead.get("row_key") or "").strip()
        # Re-read so nurture_sms_attempt/status match DB (not a stale resolve payload).
        fresh = self._store.get_by_row_key(row_key) if row_key else None
        if fresh:
            lead = fresh

        # Soft-cancel Stage 2: flip status so the pending Cloud Task no-ops
        # when it fires (API delete needs cloudtasks.tasks.delete IAM).
        attempt = int(lead.get("nurture_sms_attempt") or 0)
        status = (lead.get("nurture_sms_status") or "").strip()
        cancelled = False
        if status == "active":
            cancelled = bool(
                self._store.cancel_nurture_sms(row_key=row_key, status="booked")
            )
            cancel_pending_nurture_jobs(row_key, known_attempt=attempt)
        logger.info(
            "Appointment booked row_key=%s nurture_status=%s attempt=%s "
            "nurture_soft_cancelled=%s (pending tasks skip on run)",
            row_key,
            status or "none",
            attempt,
            cancelled,
        )

        block = self._sms_block_reason(lead)
        if block:
            logger.info("Skip Stage 1 SMS — %s row_key=%s", block, row_key)
            return {
                "action": "skipped",
                "reason": block,
                "nurture_cancelled": cancelled,
                "cloud_task_deleted": 0,
            }

        if self._message_store.has_successful_outbound(
            lead_row_key=row_key,
            message_type="nurture_stage1",
        ):
            return {"action": "skipped", "reason": "stage1_already_sent"}

        result = await self._send_stage1(lead)
        return {
            **result,
            "nurture_cancelled": cancelled,
            "cloud_task_deleted": 0,
        }

    async def activate_stage2_followup(self, lead: dict) -> dict:
        """Stage 2 — send touch 1 immediately (pairs with Zoho email), schedule 2–10."""
        settings = get_settings()
        if not settings.nurture_sms_enabled:
            return {"action": "skipped", "reason": "nurture_sms_disabled"}

        row_key = (lead.get("row_key") or "").strip()
        # Prefer DB row so sms_eligible / opt-out match sheet ingest.
        fresh = self._store.get_by_row_key(row_key) if row_key else None
        if fresh:
            lead = fresh

        block = self._sms_block_reason(lead)
        if block:
            logger.info("Skip Stage 2 activate — %s row_key=%s", block, row_key)
            return {"action": "skipped", "reason": block}

        if (lead.get("nurture_sms_status") or "") == "active":
            return {"action": "skipped", "reason": "already_active"}

        # Mark active, then send touch 1 now so SMS lands with the Zoho email.
        # Touches 2–10 are scheduled from send_scheduled_touch on STAGE2_CADENCE_DAYS.
        now = datetime.now(timezone.utc)
        self._store.schedule_nurture_sms(
            row_key=row_key, next_at_iso=now.isoformat()
        )
        return await self.send_scheduled_touch(
            row_key=row_key, expected_attempt=1
        )

    async def send_scheduled_touch(
        self, *, row_key: str, expected_attempt: int
    ) -> dict:
        settings = get_settings()
        if not settings.nurture_sms_enabled:
            return {"action": "skipped", "reason": "nurture_sms_disabled"}

        lead = self._store.get_by_row_key(row_key)
        if not lead:
            return {"action": "skipped", "reason": "unknown_row"}

        status = (lead.get("nurture_sms_status") or "").strip()
        if status != "active":
            logger.info(
                "Nurture touch skipped (not active) row_key=%s attempt=%s "
                "status=%s",
                row_key,
                expected_attempt,
                status or "none",
            )
            return {"action": "skipped", "reason": f"status_{status or 'none'}"}

        block = self._sms_block_reason(lead)
        if block:
            cancel_status = "opted_out" if block == "sms_opted_out" else "no_consent"
            self._store.cancel_nurture_sms(row_key=row_key, status=cancel_status)
            logger.info(
                "Nurture touch skipped (%s) row_key=%s attempt=%s",
                block,
                row_key,
                expected_attempt,
            )
            return {"action": "skipped", "reason": block}

        current = int(lead.get("nurture_sms_attempt") or 0)
        if current >= expected_attempt:
            logger.info(
                "Nurture touch skipped (already sent) row_key=%s "
                "expected=%s current=%s",
                row_key,
                expected_attempt,
                current,
            )
            return {
                "action": "skipped",
                "reason": "already_sent",
                "attempt": current,
            }

        self._store.claim_nurture_sms(row_key)
        lead = self._store.get_by_row_key(row_key) or lead

        result = await self._send_stage2_touch(lead, touch=expected_attempt)
        if result.get("action") != "sent":
            # Restore schedule so a retry can happen
            self._store.update_nurture_sms_state(
                row_key=row_key,
                attempt=current,
                status="active",
                next_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            return result

        next_touch = expected_attempt + 1
        if next_touch > len(STAGE2_CADENCE_DAYS):
            self._store.update_nurture_sms_state(
                row_key=row_key,
                attempt=expected_attempt,
                status="completed",
                next_at_iso=None,
            )
            return {**result, "sequence": "completed"}

        next_at = self._touch_send_at(lead, next_touch)
        self._store.update_nurture_sms_state(
            row_key=row_key,
            attempt=expected_attempt,
            status="active",
            next_at_iso=next_at.isoformat(),
        )
        job = schedule_nurture_sms_job(
            row_key=row_key, attempt=next_touch, schedule_at=next_at
        )
        return {**result, "next_touch": next_touch, "next_at": next_at.isoformat(), "job": job}

    def on_inbound_sms(self, *, from_phone: str, body: str) -> dict:
        """Any reply cancels Stage 2; STOP also sets sms_opt_out."""
        phone = (from_phone or "").strip()
        if not phone:
            return {"action": "ignored", "reason": "no_phone"}

        stop = is_sms_stop_keyword(body)
        lead = self._store.find_lead_by_phone(phone)

        if stop:
            updated = self._store.set_sms_opt_out(phone=phone)
            if lead and (lead.get("nurture_sms_status") or "") == "active":
                cancel_pending_nurture_jobs(
                    lead["row_key"],
                    known_attempt=int(lead.get("nurture_sms_attempt") or 0),
                )
            return {
                "action": "opted_out",
                "rows_updated": updated,
                "row_key": (lead or {}).get("row_key"),
            }

        if not lead:
            return {"action": "ignored", "reason": "unknown_lead"}

        if (lead.get("nurture_sms_status") or "") != "active":
            return {"action": "ignored", "reason": "nurture_not_active"}

        cancel_pending_nurture_jobs(
            lead["row_key"],
            known_attempt=int(lead.get("nurture_sms_attempt") or 0),
        )
        self._store.cancel_nurture_sms(row_key=lead["row_key"], status="replied")
        return {
            "action": "cancelled_on_reply",
            "row_key": lead["row_key"],
        }

    async def _send_stage1(self, lead: dict) -> dict:
        settings = get_settings()
        row_key = lead["row_key"]
        to_number = normalize_e164(
            lead.get("phone_no") or lead.get("dial_to") or ""
        )
        if not to_number:
            return {"action": "failed", "error": "invalid_phone"}

        first_name = (lead.get("name") or "there").strip().split()[0]
        body = render_stage1_sms(
            first_name=first_name,
            company_phone=settings.nurture_company_phone,
            bill_upload_url=settings.nurture_bill_upload_base_url
            or settings.sms_bill_upload_base_url,
            calendar_url=settings.cal_booking_page_url or "",
            website_url=settings.nurture_website_url,
        )
        return await self._deliver(
            lead=lead,
            to_number=to_number,
            body=body,
            message_type="nurture_stage1",
        )

    async def _send_stage2_touch(self, lead: dict, *, touch: int) -> dict:
        settings = get_settings()
        to_number = normalize_e164(
            lead.get("phone_no") or lead.get("dial_to") or ""
        )
        if not to_number:
            return {"action": "failed", "error": "invalid_phone"}

        first_name = (lead.get("name") or "there").strip().split()[0]
        body = render_stage2_sms(
            touch,
            first_name=first_name,
            rep_name=settings.nurture_rep_name,
            company_phone=settings.nurture_company_phone,
            google_reviews_url=settings.nurture_google_reviews_url
            or settings.nurture_website_url,
            founder_video_url=settings.nurture_founder_video_url
            or settings.nurture_website_url,
            website_url=settings.nurture_website_url,
        )
        return await self._deliver(
            lead=lead,
            to_number=to_number,
            body=body,
            message_type=f"nurture_stage2_t{touch}",
        )

    async def _deliver(
        self,
        *,
        lead: dict,
        to_number: str,
        body: str,
        message_type: str,
    ) -> dict:
        row_key = lead["row_key"]
        block = self._sms_block_reason(lead)
        if block:
            logger.info(
                "Nurture SMS blocked at deliver — %s type=%s row_key=%s",
                block,
                message_type,
                row_key,
            )
            return {"action": "skipped", "reason": block}
        try:
            result = await send_sms(to_number=to_number, body=body)
        except TwilioSmsError as exc:
            logger.error("Nurture SMS config error row_key=%s: %s", row_key, exc)
            return {"action": "failed", "error": str(exc)}

        if not result.success:
            log_outbound_failure(
                message_store=self._message_store,
                dedup_store=self._store,
                channel="sms",
                message_type=message_type,
                body=body,
                to_address=to_number,
                error=result.error,
                customer_phone=to_number,
                lead_row_key=row_key,
                lead_name=lead.get("name") or "",
            )
            return {"action": "failed", "error": result.error}

        log_outbound_message(
            message_store=self._message_store,
            dedup_store=self._store,
            channel="sms",
            message_type=message_type,
            body=body,
            to_address=to_number,
            provider_id=result.message_sid,
            lead_row_key=row_key,
            lead_name=lead.get("name") or "",
            customer_phone=to_number,
        )
        logger.info(
            "Nurture SMS sent type=%s row_key=%s sid=%s",
            message_type,
            row_key,
            result.message_sid,
        )
        return {
            "action": "sent",
            "message_type": message_type,
            "to": to_number,
            "message_sid": result.message_sid,
        }

    def _touch_send_at(self, lead: dict, touch: int) -> datetime:
        """Send time for touch N: delta days from STAGE2_CADENCE_DAYS after last send."""
        # Cadence is days from sequence start (0,1,2,4,...). After each send we
        # schedule the next using the gap between consecutive entries.
        idx = touch - 1
        prev_idx = touch - 2
        days = STAGE2_CADENCE_DAYS[idx] - (
            STAGE2_CADENCE_DAYS[prev_idx] if prev_idx >= 0 else 0
        )
        base = datetime.now(timezone.utc) + timedelta(days=float(days))
        return self._quiet_hours_adjust(base)

    def _quiet_hours_adjust(self, when: datetime) -> datetime:
        settings = get_settings()
        tz = ZoneInfo(settings.business_timezone or "America/Phoenix")
        local = when.astimezone(tz)
        start = int(settings.nurture_sms_quiet_start_hour)
        end = int(settings.nurture_sms_quiet_end_hour)
        if start <= local.hour < end:
            return when.astimezone(timezone.utc)
        if local.hour >= end:
            next_day = (local + timedelta(days=1)).replace(
                hour=start, minute=0, second=0, microsecond=0
            )
            return next_day.astimezone(timezone.utc)
        # Before quiet start same day
        same = local.replace(hour=start, minute=0, second=0, microsecond=0)
        return same.astimezone(timezone.utc)
