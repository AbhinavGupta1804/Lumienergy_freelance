"""
Send transactional email via SMTP (Gmail, Google Workspace, SendGrid SMTP, etc.).
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings

logger = logging.getLogger(__name__)


class SmtpEmailError(Exception):
    """SMTP is not configured or send failed."""


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    to_email: str = ""
    error: str = ""


def _send_smtp_sync(
    *,
    to_email: str,
    subject: str,
    body_text: str,
) -> EmailSendResult:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        raise SmtpEmailError("SMTP_HOST and SMTP_FROM_EMAIL must be set for email notifications")
    if not settings.smtp_username or not settings.smtp_password:
        raise SmtpEmailError("SMTP_USERNAME and SMTP_PASSWORD must be set for email notifications")

    from_addr = settings.smtp_from_email.strip()
    from_name = (settings.smtp_from_name or "Lumi Energy").strip()
    from_header = f"{from_name} <{from_addr}>" if from_name else from_addr

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.sendmail(from_addr, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.sendmail(from_addr, [to_email], msg.as_string())
    except smtplib.SMTPException as exc:
        logger.error("SMTP send failed to=%s: %s", to_email, exc)
        return EmailSendResult(success=False, to_email=to_email, error=str(exc))
    except OSError as exc:
        logger.error("SMTP connection failed to=%s: %s", to_email, exc)
        return EmailSendResult(success=False, to_email=to_email, error=str(exc))

    logger.info("Email sent successfully to=%s subject=%s", to_email, subject[:60])
    return EmailSendResult(success=True, to_email=to_email)


async def send_email(
    *,
    to_email: str,
    subject: str,
    body_text: str,
) -> EmailSendResult:
    """Send one plain-text email (runs SMTP in a thread — smtplib is blocking)."""
    import asyncio

    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return EmailSendResult(success=False, to_email=to_email, error="invalid_email")

    return await asyncio.to_thread(
        _send_smtp_sync,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
    )
