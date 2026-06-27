"""
Bill-upload link + consultation confirmation — SMS or email based on NOTIFICATION_CHANNEL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.integrations.smtp_email import EmailSendResult, SmtpEmailError, send_email
from app.integrations.twilio_sms import (
    SmsSendResult,
    TwilioSmsError,
    build_confirmation_sms_body,
    build_sms_body,
    send_sms,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationResult:
    success: bool
    channel: str
    to: str = ""
    provider_id: str = ""
    error: str = ""
    body: str = ""
    subject: str = ""


def notification_channel() -> str:
    return (get_settings().notification_channel or "sms").strip().lower()


def _greeting_name(first_name: str, full_name: str) -> str:
    name = (first_name or "").strip() or (full_name or "").strip()
    return name or "there"


def build_bill_upload_email_subject(first_name: str = "") -> str:
    settings = get_settings()
    if settings.email_bill_upload_subject:
        return settings.email_bill_upload_subject.format(
            first_name=first_name or "there",
        )
    return "Upload your energy bill — Lumi Energy"


def build_bill_upload_email_body(
    upload_link: str,
    *,
    first_name: str = "",
    full_name: str = "",
) -> str:
    settings = get_settings()
    greeting = _greeting_name(first_name, full_name)
    if settings.email_bill_upload_body:
        return settings.email_bill_upload_body.format(
            link=upload_link,
            first_name=greeting,
        )
    return (
        f"Hi {greeting},\n\n"
        "Thanks for speaking with Lumi Energy! To prepare your personalised savings "
        "estimate, please upload a recent energy bill using this secure link:\n\n"
        f"{upload_link}\n\n"
        "— Lumi Energy"
    )


def build_confirmation_email_subject(appointment_label: str) -> str:
    settings = get_settings()
    if settings.email_confirmation_subject:
        return settings.email_confirmation_subject.format(appointment=appointment_label)
    return "Your Lumi Energy consultation is confirmed"


def build_confirmation_email_body(
    appointment_label: str,
    *,
    first_name: str = "",
    full_name: str = "",
) -> str:
    settings = get_settings()
    greeting = _greeting_name(first_name, full_name)
    if settings.email_confirmation_body:
        return settings.email_confirmation_body.format(
            appointment=appointment_label,
            first_name=greeting,
        )
    return (
        f"Hi {greeting},\n\n"
        f"Your consultation is confirmed for {appointment_label}.\n"
        "We received your bill — thank you!\n\n"
        "— Lumi Energy"
    )


async def send_bill_upload_notification(
    *,
    phone: str | None,
    email: str | None,
    upload_link: str,
    first_name: str = "",
    full_name: str = "",
) -> NotificationResult:
    channel = notification_channel()
    if channel == "email":
        to_email = (email or "").strip()
        if not to_email:
            return NotificationResult(
                success=False,
                channel="email",
                error="no_email",
            )
        subject = build_bill_upload_email_subject(first_name)
        body = build_bill_upload_email_body(
            upload_link,
            first_name=first_name,
            full_name=full_name,
        )
        try:
            result: EmailSendResult = await send_email(
                to_email=to_email,
                subject=subject,
                body_text=body,
            )
        except SmtpEmailError as exc:
            return NotificationResult(success=False, channel="email", error=str(exc))
        return NotificationResult(
            success=result.success,
            channel="email",
            to=result.to_email,
            error=result.error,
            body=body,
            subject=subject,
        )

    to_number = (phone or "").strip()
    if not to_number:
        return NotificationResult(success=False, channel="sms", error="no_phone")
    body = build_sms_body(upload_link, first_name=first_name)
    try:
        result: SmsSendResult = await send_sms(to_number=to_number, body=body)
    except TwilioSmsError as exc:
        return NotificationResult(
            success=False, channel="sms", error=str(exc), body=body
        )
    return NotificationResult(
        success=result.success,
        channel="sms",
        to=result.to_number,
        provider_id=result.message_sid,
        error=result.error,
        body=body,
    )


async def send_confirmation_notification(
    *,
    phone: str | None,
    email: str | None,
    appointment_label: str,
    first_name: str = "",
    full_name: str = "",
    appointment_date: str = "",
    appointment_time: str = "",
) -> NotificationResult:
    channel = notification_channel()
    if channel == "email":
        to_email = (email or "").strip()
        if not to_email:
            return NotificationResult(
                success=False,
                channel="email",
                error="no_email",
            )
        subject = build_confirmation_email_subject(appointment_label)
        body = build_confirmation_email_body(
            appointment_label,
            first_name=first_name,
            full_name=full_name,
        )
        try:
            result: EmailSendResult = await send_email(
                to_email=to_email,
                subject=subject,
                body_text=body,
            )
        except SmtpEmailError as exc:
            return NotificationResult(success=False, channel="email", error=str(exc))
        return NotificationResult(
            success=result.success,
            channel="email",
            to=result.to_email,
            error=result.error,
            body=body,
            subject=subject,
        )

    to_number = (phone or "").strip()
    if not to_number:
        return NotificationResult(success=False, channel="sms", error="no_phone")
    body = build_confirmation_sms_body(
        appointment_label,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
    )
    try:
        result: SmsSendResult = await send_sms(to_number=to_number, body=body)
    except TwilioSmsError as exc:
        return NotificationResult(
            success=False, channel="sms", error=str(exc), body=body
        )
    return NotificationResult(
        success=result.success,
        channel="sms",
        to=result.to_number,
        provider_id=result.message_sid,
        error=result.error,
        body=body,
    )
