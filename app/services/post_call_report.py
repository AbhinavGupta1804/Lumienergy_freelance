"""
Post-call report email service for eligible landing-page leads.

After a call ends (or if the dial fails before a conversation starts), generates
a personalized preliminary solar analysis PDF and emails it to the customer.
The email conditionally includes a Cal.com self-scheduling link depending on
whether an appointment was booked during the call.

Eligible Offer Page values (sheet):
  aps-hike, zero-down, solar-roi-calculator, getquote

Cases:
  1. Picked + booked  --> report WITHOUT calendar link
  2. Picked + not booked --> report WITH calendar link
  3. Not picked        --> report WITH calendar link
  4. Error / wrong # / dial failed --> report WITH calendar link
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.integrations.resend_email import send_email_resend
from app.integrations.sheet_columns import parse_monthly_bill
from app.services.job_scheduler import schedule_followup_email_job
from app.services.message_logger import log_outbound_message, log_outbound_failure
from app.services.report_generator import ReportGenerator, ReportInput
from app.utils.dedup_store import DedupStore
from app.utils.message_store import CustomerMessageStore

logger = logging.getLogger(__name__)

REPORT_ELIGIBLE_OFFERS = frozenset({
    "aps-hike",
    "zero-down",
    "solar-roi-calculator",
    "getquote",
})

_CAL_LINK_LABEL = "Book your free home consult"


def _escape_html(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _html_from_text(body_text: str, *, calendar_url: str = "") -> str:
    """Turn plain-text email into simple HTML; hide ugly query strings behind a label."""
    clean = _calendar_url_clean(calendar_url) if calendar_url else ""
    parts: list[str] = []
    lines = body_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            parts.append("<br>")
            i += 1
            continue

        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ""
        is_label = stripped == _CAL_LINK_LABEL
        is_url_line = bool(
            calendar_url
            and (stripped == calendar_url or (clean and stripped == clean))
        )
        next_is_url = bool(
            calendar_url
            and (next_stripped == calendar_url or (clean and next_stripped == clean))
        )

        # "Book your free home consult" + URL line → one clean HTML link (prefilled href)
        if calendar_url and is_label and next_is_url:
            parts.append(
                f'<a href="{_escape_html(calendar_url)}" '
                f'style="color:#2563eb;font-weight:600;text-decoration:underline;">'
                f"{_escape_html(_CAL_LINK_LABEL)}</a><br>"
            )
            i += 2
            continue

        if is_url_line:
            parts.append(
                f'<a href="{_escape_html(calendar_url)}" '
                f'style="color:#2563eb;font-weight:600;text-decoration:underline;">'
                f"{_escape_html(_CAL_LINK_LABEL)}</a><br>"
            )
            i += 1
            continue

        if is_label and calendar_url:
            i += 1
            continue

        parts.append(f"{_escape_html(line)}<br>")
        i += 1

    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;'
        'line-height:1.55;color:#111827;">'
        + "".join(parts)
        + "</div>"
    )


def _calendar_url_clean(base_url: str) -> str:
    """Public-facing Cal URL without prefill query params (for plain-text emails)."""
    from urllib.parse import urlparse, urlunparse

    base = (base_url or "").strip()
    if not base:
        return ""
    parsed = urlparse(base)
    return urlunparse(parsed._replace(query="", fragment=""))


def _build_email_body(
    *,
    first_name: str,
    include_calendar_link: bool,
    calendar_url: str,
) -> str:
    greeting = f"Hey {first_name}," if first_name else "Hey,"
    # Plain text shows the clean URL; HTML uses the prefilled calendar_url behind a label.
    visible_url = _calendar_url_clean(calendar_url) or calendar_url
    if include_calendar_link and calendar_url:
        take_a_look = (
            "Take a look, if the math makes sense and you want to see how we actually "
            "guarantee those numbers on your next bill, you can grab 10 minutes on our "
            f"calendar here:\n{_CAL_LINK_LABEL}\n{visible_url}"
        )
    else:
        take_a_look = (
            "Take a look, if the math makes sense and you want to see how we actually "
            "guarantee those numbers on your next bill, we'll walk you through everything "
            "at your upcoming appointment."
        )
    lines = [
        greeting,
        "",
        "Just finished running the numbers through our calculator based on the info you dropped.",
        "",
        "Long story short: your property actually qualifies for a higher monthly savings tier "
        "than average because of the current Arizona utility rates.",
        "",
        "I put the full ROI report together in the attachment below",
        "",
        take_a_look,
        "",
        "Or contact our technician Ivan, directly on 4802526872",
        "",
        "Talk soon,",
        "Ayden",
    ]
    return "\n".join(lines)


def _build_followup_email_body(
    *,
    first_name: str,
    calendar_url: str,
) -> str:
    greeting = f"Hey {first_name}," if first_name else "Hey,"
    visible_url = _calendar_url_clean(calendar_url) or calendar_url
    lines = [
        greeting,
        "",
        "Ayden here from Lumi — just floating your solar report back to the top of your inbox.",
        "",
        "The numbers I ran for your property still stand, and with where Arizona utility "
        "rates are headed, the savings tier you qualify for is worth locking in sooner "
        "rather than later.",
        "",
        "If the math made sense to you, you can grab 10 minutes on our calendar here:",
        _CAL_LINK_LABEL,
        visible_url,
        "",
        "Or contact our technician Ivan, directly on 4802526872",
        "",
        "Talk soon,",
        "Ayden",
    ]
    return "\n".join(lines)


def _calendar_url_with_lead(
    base_url: str,
    *,
    email: str = "",
    first_name: str = "",
    last_name: str = "",
) -> str:
    """Prefill Cal.com booking form so self-book webhooks can match CRM email."""
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

    base = (base_url or "").strip()
    if not base:
        return ""
    params: dict[str, str] = {}
    if email and "@" in email:
        params["email"] = email.strip()
    name = " ".join(p for p in (first_name, last_name) if p).strip()
    if name:
        params["name"] = name
    if not params:
        return base
    parsed = urlparse(base)
    existing = parse_qs(parsed.query)
    flat = {k: v[0] for k, v in existing.items() if v}
    flat.update(params)
    return urlunparse(parsed._replace(query=urlencode(flat)))


def compute_next_followup_at(days_ahead: int) -> str:
    """
    UTC ISO timestamp for `days_ahead` calendar days from today at the
    configured send time (08:30) in the business timezone.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.business_timezone)
    local_now = datetime.now(tz)
    target = (local_now + timedelta(days=days_ahead)).replace(
        hour=settings.followup_email_send_hour,
        minute=settings.followup_email_send_minute,
        second=0,
        microsecond=0,
    )
    return target.astimezone(timezone.utc).isoformat()


class PostCallReportService:
    """Generate and email the preliminary PDF report after the call ends."""

    def __init__(
        self,
        store: DedupStore,
        message_store: CustomerMessageStore,
    ) -> None:
        self._store = store
        self._message_store = message_store
        self._report_gen = ReportGenerator()

    async def on_conversation_ended(
        self,
        conversation_id: str,
        *,
        answered: bool = False,
        webhook_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self._store.get_by_conversation_id(conversation_id)
        if not row:
            return {"action": "skipped", "reason": "unknown_conversation"}
        return await self._send_for_row(row, context=f"conversation_id={conversation_id}")

    async def on_dial_failed(self, row_key: str) -> dict[str, Any]:
        """
        Send report when the outbound dial never starts (invalid phone,
        ElevenLabs API error, etc.). Always includes calendar link.
        """
        row = self._store.get_by_row_key(row_key)
        if not row:
            return {"action": "skipped", "reason": "unknown_row"}
        return await self._send_for_row(row, context=f"dial_failed row_key={row_key}")

    async def on_call_reconciled(self, row_key: str) -> dict[str, Any]:
        """
        Send report when the call outcome was resolved via Twilio reconciliation
        (no ElevenLabs post-call webhook — typically unanswered calls, Case 3).
        """
        row = self._store.get_by_row_key(row_key)
        if not row:
            return {"action": "skipped", "reason": "unknown_row"}
        return await self._send_for_row(row, context=f"reconciled row_key={row_key}")

    async def _send_for_row(
        self,
        row: dict[str, Any],
        *,
        context: str = "",
    ) -> dict[str, Any]:
        from app.integrations.sheet_columns import normalize_offer_page

        offer_page = normalize_offer_page(row.get("offer_page"))
        if offer_page not in REPORT_ELIGIBLE_OFFERS:
            logger.info(
                "Report skipped not_report_eligible row_key=%s offer_page=%r eligible=%s",
                row.get("row_key"),
                offer_page,
                sorted(REPORT_ELIGIBLE_OFFERS),
            )
            return {
                "action": "skipped",
                "reason": "not_report_eligible",
                "offer_page": offer_page,
            }

        email = (row.get("email") or "").strip()
        if not email or "@" not in email:
            return {"action": "skipped", "reason": "no_email"}

        if row.get("report_sent"):
            return {"action": "skipped", "reason": "already_sent"}

        has_booking = bool(row.get("cal_booking_uid"))
        include_calendar_link = not has_booking
        email_type = "without_calendar" if has_booking else "with_calendar"

        row_key = row.get("row_key") or ""
        name = row.get("name") or ""
        first_name = name.split()[0] if name.strip() else "Customer"
        last_name = " ".join(name.split()[1:]) if len(name.split()) > 1 else ""
        address = row.get("address") or ""
        monthly_bill = parse_monthly_bill(row.get("monthly_bill")) or 250.0

        settings = get_settings()
        calendar_url = _calendar_url_with_lead(
            (settings.cal_booking_page_url or "").strip(),
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        try:
            report_input = ReportInput(
                first_name=first_name,
                last_name=last_name,
                address=address,
                email=email,
                monthly_bill=monthly_bill,
                calendar_url=calendar_url,
                include_calendar_link=include_calendar_link,
            )
            pdf_bytes = await asyncio.to_thread(
                self._report_gen.generate_pdf_bytes, report_input
            )
        except Exception:
            logger.exception("Report PDF generation failed %s", context or row_key)
            return {"action": "error", "reason": "pdf_generation_failed"}

        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
        report_name = " ".join(part for part in (first_name, last_name) if part)
        filename = f"{report_name}.pdf"

        body_text = _build_email_body(
            first_name=first_name,
            include_calendar_link=include_calendar_link,
            calendar_url=calendar_url,
        )
        body_html = _html_from_text(
            body_text,
            calendar_url=calendar_url if include_calendar_link else "",
        )
        subject = "quick update on your solar report"

        try:
            result = await send_email_resend(
                to_email=email,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                attachments=[{
                    "filename": filename,
                    "content": pdf_b64,
                    "content_type": "application/pdf",
                }],
            )
        except Exception:
            logger.exception("Report email send failed %s email=%s", context, email)
            log_outbound_failure(
                message_store=self._message_store,
                dedup_store=self._store,
                channel="email",
                message_type="report_email",
                body=body_text[:200],
                to_address=email,
                error="send_exception",
                lead_row_key=row_key,
                lead_name=name,
            )
            return {"action": "error", "reason": "email_send_failed"}

        if not result.success:
            logger.warning(
                "Report email rejected %s email=%s error=%s",
                context,
                email,
                result.error,
            )
            log_outbound_failure(
                message_store=self._message_store,
                dedup_store=self._store,
                channel="email",
                message_type="report_email",
                body=body_text[:200],
                to_address=email,
                error=result.error,
                lead_row_key=row_key,
                lead_name=name,
            )
            return {"action": "error", "reason": "email_rejected", "error": result.error}

        self._store.mark_report_sent(row_key=row_key, report_email_type=email_type)

        # Not booked --> start the 4-step follow-up email chain (every 2 days, 08:30)
        if include_calendar_link and settings.followup_email_enabled:
            next_at = compute_next_followup_at(settings.followup_email_interval_days)
            self._store.schedule_followup_email(row_key=row_key, next_at_iso=next_at)
            job = schedule_followup_email_job(
                row_key=row_key,
                attempt=1,
                schedule_at=next_at,
            )
            logger.info(
                "Follow-up email chain scheduled row_key=%s first_at=%s job=%s",
                row_key,
                next_at,
                job,
            )

        log_outbound_message(
            message_store=self._message_store,
            dedup_store=self._store,
            channel="email",
            message_type="report_email",
            body=f"Preliminary Solar Analysis report ({email_type.replace('_', ' ')})",
            to_address=email,
            provider_id=result.provider_id,
            lead_row_key=row_key,
            lead_name=name,
        )

        logger.info(
            "Report email sent %s email=%s type=%s provider_id=%s",
            context or row_key,
            email,
            email_type,
            result.provider_id,
        )
        return {
            "action": "sent",
            "email": email,
            "email_type": email_type,
            "include_calendar_link": include_calendar_link,
            "provider_id": result.provider_id,
        }

    async def process_due_followups(self) -> dict[str, Any]:
        """
        Scheduler tick — send follow-up emails whose next_followup_email_at has
        passed. 4 attempts max, every 2 calendar days at 08:30 business time.
        Stops early if the lead booked (agent booking or Cal.com self-booking).
        """
        settings = get_settings()
        if not settings.followup_email_enabled:
            return {"action": "skipped", "reason": "followup_disabled"}

        now_iso = datetime.now(timezone.utc).isoformat()
        due = self._store.list_due_followup_emails(before_iso=now_iso, limit=20)
        if not due:
            return {"action": "idle", "processed": 0}

        results: list[dict[str, Any]] = []
        for row in due:
            row_key = row.get("row_key") or ""
            if not row_key:
                continue
            if not self._store.claim_followup_email(row_key, before_iso=now_iso):
                continue
            result = await self._send_followup_for_row(row)
            logger.info("Follow-up email row_key=%s: %s", row_key, result)
            results.append({"row_key": row_key, **result})

        return {"action": "processed", "count": len(results), "results": results}

    async def _send_followup_for_row(self, row: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        row_key = row.get("row_key") or ""
        attempt = int(row.get("followup_email_attempt") or 0) + 1

        # Lead booked since the last email --> stop the chain
        if row.get("cal_booking_uid") or row.get("self_booked"):
            self._store.update_followup_email_state(
                row_key=row_key,
                attempt=attempt - 1,
                status="booked",
                next_at_iso=None,
            )
            return {"action": "stopped", "reason": "booked"}

        email = (row.get("email") or "").strip()
        if not email or "@" not in email:
            self._store.update_followup_email_state(
                row_key=row_key,
                attempt=attempt - 1,
                status="cancelled",
                next_at_iso=None,
            )
            return {"action": "stopped", "reason": "no_email"}

        name = row.get("name") or ""
        first_name = name.split()[0] if name.strip() else "Customer"
        calendar_url = _calendar_url_with_lead(
            (settings.cal_booking_page_url or "").strip(),
            email=email,
            first_name=first_name,
        )
        body_text = _build_followup_email_body(
            first_name=first_name,
            calendar_url=calendar_url,
        )
        body_html = _html_from_text(body_text, calendar_url=calendar_url)
        subject = "following up on your solar report"

        try:
            result = await send_email_resend(
                to_email=email,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
            )
        except Exception:
            logger.exception("Follow-up email send crashed row_key=%s", row_key)
            result = None

        if not result or not result.success:
            error = result.error if result else "send_exception"
            log_outbound_failure(
                message_store=self._message_store,
                dedup_store=self._store,
                channel="email",
                message_type="followup_email",
                body=body_text[:200],
                to_address=email,
                error=error,
                lead_row_key=row_key,
                lead_name=name,
            )
            # Keep the chain alive: retry this attempt at the next slot
            next_at = compute_next_followup_at(settings.followup_email_interval_days)
            self._store.update_followup_email_state(
                row_key=row_key,
                attempt=attempt - 1,
                status="active",
                next_at_iso=next_at,
            )
            schedule_followup_email_job(
                row_key=row_key,
                attempt=attempt,  # retry same attempt number
                schedule_at=next_at,
            )
            return {
                "action": "error",
                "reason": "send_failed",
                "error": error,
                "next_followup_email_at": next_at,
            }

        exhausted = attempt >= settings.followup_email_max_attempts
        next_at = (
            None
            if exhausted
            else compute_next_followup_at(settings.followup_email_interval_days)
        )
        self._store.update_followup_email_state(
            row_key=row_key,
            attempt=attempt,
            status="exhausted" if exhausted else "active",
            next_at_iso=next_at,
        )

        if next_at:
            schedule_followup_email_job(
                row_key=row_key,
                attempt=attempt + 1,
                schedule_at=next_at,
            )

        log_outbound_message(
            message_store=self._message_store,
            dedup_store=self._store,
            channel="email",
            message_type="followup_email",
            body=f"Follow-up email {attempt}/{settings.followup_email_max_attempts}",
            to_address=email,
            provider_id=result.provider_id,
            lead_row_key=row_key,
            lead_name=name,
        )

        return {
            "action": "sent",
            "attempt": attempt,
            "next_followup_email_at": next_at,
            "provider_id": result.provider_id,
        }
