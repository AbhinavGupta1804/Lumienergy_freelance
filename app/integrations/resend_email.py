"""
Send transactional email via Resend HTTP API.
https://resend.com/docs/api-reference/emails/send-email
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailError(Exception):
    """Resend is not configured or send failed."""


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    to_email: str = ""
    error: str = ""
    provider_id: str = ""


def _from_header() -> tuple[str, str]:
    """Return (from_email, from_display_header)."""
    settings = get_settings()
    from_addr = (
        (settings.resend_from_email or settings.smtp_from_email or "support@lumienergy.us")
        .strip()
    )
    from_name = (settings.smtp_from_name or "Lumi Energy").strip()
    header = f"{from_name} <{from_addr}>" if from_name else from_addr
    return from_addr, header


async def send_email_resend(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    attachments: list[dict] | None = None,
) -> EmailSendResult:
    """
    Send one email via Resend.

    attachments: optional list of
      {"filename": "report.pdf", "content": "<base64>", "content_type": "application/pdf"}
    """
    settings = get_settings()
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        raise ResendEmailError("RESEND_API_KEY is not set")

    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return EmailSendResult(success=False, to_email=to_email, error="invalid_email")

    _, from_header = _from_header()
    payload: dict = {
        "from": from_header,
        "to": [to_email],
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        payload["html"] = body_html
    if attachments:
        payload["attachments"] = attachments

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        logger.error("Resend request failed to=%s: %s", to_email, exc)
        return EmailSendResult(success=False, to_email=to_email, error=str(exc))

    if response.status_code >= 400:
        detail = response.text[:400]
        logger.error(
            "Resend send failed status=%s to=%s body=%s",
            response.status_code,
            to_email,
            detail,
        )
        return EmailSendResult(
            success=False,
            to_email=to_email,
            error=f"resend_{response.status_code}: {detail}",
        )

    email_id = ""
    try:
        email_id = str((response.json() or {}).get("id") or "")
    except ValueError:
        pass

    logger.info(
        "Email sent via Resend to=%s subject=%s id=%s",
        to_email,
        subject[:60],
        email_id,
    )
    return EmailSendResult(
        success=True,
        to_email=to_email,
        provider_id=email_id,
    )
