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


def _format_template(template: str, **kwargs: str) -> str:
    """Format SMS template; missing keys are left as empty strings."""
    safe = {k: (v or "") for k, v in kwargs.items()}
    return template.format(**safe)


def build_confirmation_sms_body(
    appointment_label: str,
    *,
    appointment_date: str = "",
    appointment_time: str = "",
) -> str:
    """SMS after customer uploads their bill (consultation confirmed + time)."""
    settings = get_settings()
    if settings.confirmation_sms_body:
        return _format_template(
            settings.confirmation_sms_body,
            appointment=appointment_label,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
        )
    date_part = appointment_date or appointment_label
    time_part = appointment_time
    if date_part and time_part:
        when = f"{date_part} at {time_part}"
    else:
        when = appointment_label
    return (
        f"Lumi Energy: Your consultation is confirmed for {when}. "
        "Thank you for uploading your energy bill. Reply STOP to opt out."
    )


def build_sms_body(upload_link: str | None = None, *, first_name: str = "") -> str:
    """
    Post-call bill upload SMS.

    Placeholders in SMS_MESSAGE_BODY: {link}, {first_name}, {support_phone}
    """
    settings = get_settings()
    link = upload_link or settings.sms_bill_upload_base_url
    name = (first_name or "").strip() or "there"
    support = (settings.sms_support_phone or "+1 (480) 252-6872").strip()
    if settings.sms_message_body:
        return _format_template(
            settings.sms_message_body,
            link=link,
            first_name=name,
            support_phone=support,
        )
    return (
        f"Lumi Energy: Hi {name}, thanks for speaking with Lumi Energy. "
        "To prepare your personalized solar savings analysis, please upload a recent "
        f"energy bill here: {link} For questions, contact us at {support}. "
        "Reply STOP to opt out."
    )


async def send_sms(*, to_number: str, body: str | None = None) -> SmsSendResult:
    """
    Send one SMS via Twilio Messages API.

    Uses TWILIO_MESSAGING_SERVICE_SID when set (required for US A2P 10DLC).
    Falls back to TWILIO_PHONE_NUMBER as From only when no service SID is configured.

    Returns SmsSendResult with success/failure — does not raise on HTTP errors
    (callers can still catch TwilioSmsError for missing configuration).
    """
    settings = get_settings()
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise TwilioSmsError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")

    messaging_sid = (settings.twilio_messaging_service_sid or "").strip()
    from_number = (settings.twilio_phone_number or "").strip()
    if not messaging_sid and not from_number:
        raise TwilioSmsError(
            "Set TWILIO_MESSAGING_SERVICE_SID (recommended for A2P 10DLC) "
            "or TWILIO_PHONE_NUMBER"
        )

    text = body if body is not None else build_sms_body()
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}/Messages.json"
    )
    if messaging_sid:
        data = {
            "To": to_number,
            "MessagingServiceSid": messaging_sid,
            "Body": text,
        }
        sender_label = f"MessagingServiceSid={messaging_sid}"
    else:
        logger.warning(
            "Sending SMS via From=%s without Messaging Service — "
            "US A2P 10DLC may block delivery (error 30034). "
            "Set TWILIO_MESSAGING_SERVICE_SID in .env",
            from_number,
        )
        data = {
            "To": to_number,
            "From": from_number,
            "Body": text,
        }
        sender_label = f"From={from_number}"

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
        logger.error("SMS failed to %s via %s: %s", to_number, sender_label, err)
        return SmsSendResult(success=False, to_number=to_number, error=err)

    payload = resp.json()
    sid = payload.get("sid", "")
    logger.info(
        "SMS sent successfully to=%s message_sid=%s via %s",
        to_number,
        sid,
        sender_label,
    )
    return SmsSendResult(success=True, message_sid=sid, to_number=to_number)
