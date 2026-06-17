"""
Twilio Programmable Messaging — send post-call SMS.

Uses Account SID / Auth Token from settings (same credentials as voice).
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class TwilioSmsError(Exception):
    """Raised when the Twilio Messages API returns an error."""


@dataclass(frozen=True)
class SmsSendResult:
    """Outcome of a single SMS send attempt."""

    success: bool
    message_sid: str = ""
    to_number: str = ""
    error: str = ""


def build_confirmation_sms_body(appointment_label: str) -> str:
    """SMS after customer uploads their bill (consultation confirmed + time)."""
    settings = get_settings()
    if settings.confirmation_sms_body:
        return settings.confirmation_sms_body.format(appointment=appointment_label)
    return (
        f"Your Lumi Energy consultation is confirmed for {appointment_label}. "
        "We received your bill — thank you!"
    )


def build_sms_body(upload_link: str | None = None) -> str:
    """
    SMS text from environment.

    Pass ``upload_link`` as the fully-formed URL (base + token).
    Falls back to SMS_BILL_UPLOAD_BASE_URL when not provided.
    Optional SMS_MESSAGE_BODY overrides the full text (use {link} placeholder).
    """
    settings = get_settings()
    link = upload_link or settings.sms_bill_upload_base_url
    if settings.sms_message_body:
        return settings.sms_message_body.format(link=link)
    return (
        "Thanks for speaking with Lumi Energy! To get your personalised savings "
        f"estimate, please upload a recent energy bill here: {link}"
    )


async def send_sms(*, to_number: str, body: str | None = None) -> SmsSendResult:
    """
    Send one SMS via Twilio Messages API.

    Returns SmsSendResult with success/failure — does not raise on HTTP errors
    (callers can still catch TwilioSmsError for missing configuration).
    """
    settings = get_settings()
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise TwilioSmsError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")
    if not settings.twilio_phone_number:
        raise TwilioSmsError("TWILIO_PHONE_NUMBER not set (used as SMS From)")

    text = body if body is not None else build_sms_body()
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}/Messages.json"
    )
    data = {
        "To": to_number,
        "From": settings.twilio_phone_number,
        "Body": text,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                data=data,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
    except httpx.HTTPError as exc:
        logger.error("SMS HTTP error to %s: %s", to_number, exc)
        return SmsSendResult(success=False, to_number=to_number, error=str(exc))

    if resp.status_code >= 400:
        err = f"Twilio SMS HTTP {resp.status_code}: {resp.text}"
        logger.error("SMS failed to %s: %s", to_number, err)
        return SmsSendResult(success=False, to_number=to_number, error=err)

    payload = resp.json()
    sid = payload.get("sid", "")
    logger.info("SMS sent successfully to=%s message_sid=%s", to_number, sid)
    return SmsSendResult(success=True, message_sid=sid, to_number=to_number)
