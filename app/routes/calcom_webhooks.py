"""
Cal.com booking webhook — detects when a customer self-books via the calendar link.

Setup:
  Cal.com → Settings → Webhooks → Add subscriber
  URL: {PUBLIC_BASE_URL}/webhooks/calcom/booking-created
  Event: BOOKING_CREATED
  Secret: set CALCOM_WEBHOOK_SECRET in .env (optional)
"""

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.utils.dedup_store import DedupStore
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/calcom", tags=["calcom-webhooks"])


def _verify_calcom_signature(
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    if not signature_header:
        return False
    try:
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)
    except (ValueError, TypeError):
        return False


def _extract_attendee_info(payload: dict[str, Any]) -> dict[str, str]:
    """Pull phone and email from Cal.com BOOKING_CREATED payload."""

    def _unwrap(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("value", "optionValue", "email", "phone", "phoneNumber"):
                inner = value.get(key)
                if inner is not None and not isinstance(inner, (dict, list)):
                    return str(inner).strip()
            return ""
        if isinstance(value, list):
            for item in value:
                got = _unwrap(item)
                if got:
                    return got
            return ""
        return str(value).strip()

    def _is_usable_email(addr: str) -> bool:
        addr = (addr or "").strip().lower()
        if not addr or "@" not in addr:
            return False
        # Cal.com SMS-reminder placeholder — not the lead's real email
        if addr.endswith("@sms.cal.com"):
            return False
        return True

    booking = payload.get("payload") or payload
    attendees = booking.get("attendees") or []
    phones: list[str] = []
    emails: list[str] = []

    for att in attendees:
        if not isinstance(att, dict):
            continue
        for key in ("phoneNumber", "phone", "attendeePhoneNumber"):
            p = _unwrap(att.get(key))
            if p:
                phones.append(p)
        e = _unwrap(att.get("email"))
        if _is_usable_email(e):
            emails.append(e)

    metadata = booking.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("phoneNumber", "phone"):
            p = _unwrap(metadata.get(key))
            if p:
                phones.append(p)

    sms_reminder = _unwrap(booking.get("smsReminderNumber"))
    if sms_reminder:
        phones.append(sms_reminder)

    responses = booking.get("responses") or {}
    if isinstance(responses, dict):
        for key in ("phone", "phoneNumber", "smsReminderNumber", "attendeePhoneNumber"):
            p = _unwrap(responses.get(key))
            if p:
                phones.append(p)
        for key in ("email", "attendeeEmail"):
            e = _unwrap(responses.get(key))
            if _is_usable_email(e):
                emails.append(e)

    user_fields = booking.get("userFieldsResponses") or {}
    if isinstance(user_fields, dict):
        for key, val in user_fields.items():
            kl = str(key).lower()
            unwrapped = _unwrap(val)
            if "email" in kl and _is_usable_email(unwrapped):
                emails.append(unwrapped)
            if "phone" in kl and unwrapped:
                phones.append(unwrapped)

    phone = next((p for p in phones if p), "")
    email = next((e for e in emails if e), "")
    return {"phone": phone, "email": email}


def _extract_booking_uid(payload: dict[str, Any]) -> str:
    booking = payload.get("payload") or payload
    return str(
        booking.get("uid")
        or booking.get("bookingUid")
        or booking.get("bookingId")
        or ""
    ).strip()


def _resolve_self_book_lead(
    store: DedupStore,
    *,
    phone: str,
    email: str,
) -> dict[str, Any] | None:
    """
    Match a Cal.com self-book to a CRM lead.

    Prefer active callback retries, then active follow-up email chains.
    Phone match covers TEST_MODE dials where dial_to is the test number.
    """
    row = None
    if phone:
        row = store.find_active_callback_by_phone(phone)
    if not row and email:
        row = store.find_active_callback_by_email(email)
    if not row and email:
        row = store.find_active_followup_by_email(email)
    if not row and phone:
        row = store.find_active_followup_by_phone(phone)
    return row


@router.post("/booking-created")
async def calcom_booking_created(request: Request) -> JSONResponse:
    """
    When a customer books via the public calendar link, mark them as
    self-booked and cancel their callback retries.

    Agent on-call bookings also fire BOOKING_CREATED from Cal.com — those are
    ignored here because /scheduling/book already persisted cal_booking_uid.
    """
    import asyncio

    raw = await request.body()
    settings = get_settings()

    if settings.calcom_webhook_secret:
        sig = request.headers.get("x-cal-signature-256")
        if not _verify_calcom_signature(raw, sig, settings.calcom_webhook_secret):
            logger.warning("Invalid Cal.com webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    trigger_event = payload.get("triggerEvent", "")
    if trigger_event not in ("BOOKING_CREATED", ""):
        logger.debug("Ignoring Cal.com event type=%s", trigger_event)
        return JSONResponse({"ok": True, "ignored": trigger_event})

    if not hasattr(request.app.state, "dedup_store"):
        raise HTTPException(status_code=500, detail="Dedup store not configured")

    store: DedupStore = request.app.state.dedup_store
    info = _extract_attendee_info(payload)
    phone = normalize_e164(info["phone"]) or info["phone"]
    email = (info["email"] or "").strip()
    booking_uid = _extract_booking_uid(payload)

    logger.info(
        "Cal.com booking webhook phone=%s email=%s uid=%s",
        phone or "(none)",
        email or "(none)",
        booking_uid or "(none)",
    )

    row = _resolve_self_book_lead(store, phone=phone, email=email)

    if not row:
        logger.info(
            "Cal.com booking webhook: no matching lead for phone=%s email=%s",
            phone,
            email,
        )
        return JSONResponse({"ok": True, "action": "no_match"})

    row_key = row.get("row_key") or ""
    existing_uid = (row.get("cal_booking_uid") or "").strip()

    # On-call agent booking already saved cal_booking_uid via /scheduling/book.
    # Skip heavy self-book + Cloud Tasks cancel — that blocked live-call tools.
    if existing_uid:
        logger.info(
            "Cal.com webhook skipped — agent/CRM already booked row_key=%s uid=%s",
            row_key,
            existing_uid,
        )
        return JSONResponse({
            "ok": True,
            "action": "already_agent_booked",
            "row_key": row_key,
            "cal_booking_uid": existing_uid,
        })

    if row.get("self_booked"):
        return JSONResponse({
            "ok": True,
            "action": "already_self_booked",
            "row_key": row_key,
        })

    marked = store.mark_self_booked(row_key=row_key)

    # Refresh row for attempt counters, then cancel Cloud Tasks in the background
    # so this HTTP response returns immediately (Cal + live tools stay fast).
    row_after = store.get_by_row_key(row_key) or row

    async def _cleanup_jobs() -> None:
        from app.services.job_scheduler import cancel_jobs_for_lead

        try:
            result = await asyncio.to_thread(cancel_jobs_for_lead, row_after)
            phone_for_cancel = normalize_e164(
                row_after.get("dial_to") or row_after.get("phone_no") or ""
            )
            if phone_for_cancel:
                await asyncio.to_thread(
                    lambda: store.cancel_active_callbacks_for_phone(
                        phone_for_cancel, except_row_key=row_key
                    )
                )
            logger.info(
                "Cal.com self-book cleanup done row_key=%s tasks=%s",
                row_key,
                result,
            )
        except Exception:
            logger.exception("Cal.com self-book cleanup failed row_key=%s", row_key)

    asyncio.create_task(_cleanup_jobs())

    logger.info(
        "Cal.com self-booking accepted row_key=%s marked=%s uid=%s (cleanup async)",
        row_key,
        marked,
        booking_uid or "(none)",
    )
    return JSONResponse({
        "ok": True,
        "action": "self_booked",
        "row_key": row_key,
        "marked": marked,
    })
