"""
Twilio Programmable Voice — attach Status Callback URLs to live calls.

ElevenLabs initiates outbound calls and normally registers its own callbacks.
After each call starts, we PATCH the Twilio Call resource so Twilio also POSTs
to our FastAPI /webhooks/twilio/status when CallStatus=completed.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class TwilioCallError(Exception):
    pass


def status_callback_url() -> str | None:
    """Public URL Twilio will POST to when the call ends."""
    base = (get_settings().public_base_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/webhooks/twilio/status"


async def attach_status_callback(call_sid: str) -> bool:
    """
    Register status_callback on an in-progress outbound call.

    Twilio will POST application/x-www-form-urlencoded data to our endpoint
    when the call reaches the subscribed events (we request only "completed").
    """
    settings = get_settings()
    callback = status_callback_url()
    if not callback:
        logger.warning(
            "PUBLIC_BASE_URL not set — cannot attach Twilio status callback for %s",
            call_sid,
        )
        return False
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.warning("Twilio credentials missing — cannot attach status callback")
        return False

    api = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}/Calls/{call_sid}.json"
    )
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)

    async with httpx.AsyncClient(timeout=15.0) as client:
        get_resp = await client.get(api, auth=auth)
        if get_resp.status_code >= 400:
            raise TwilioCallError(
                f"Could not read call {call_sid}: HTTP {get_resp.status_code}"
            )
        current = get_resp.json()
        # Twilio may require Url when updating StatusCallback on active calls.
        form: dict[str, str] = {
            "StatusCallback": callback,
            "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": "completed",
        }
        if current.get("url"):
            form["Url"] = current["url"]

        post_resp = await client.post(api, data=form, auth=auth)

    if post_resp.status_code >= 400:
        logger.error(
            "Failed to attach status callback to %s: HTTP %s %s",
            call_sid,
            post_resp.status_code,
            post_resp.text,
        )
        return False

    # Verify Twilio stored the callback (ElevenLabs calls often ignore this update).
    async with httpx.AsyncClient(timeout=15.0) as client:
        verify = await client.get(api, auth=auth)
    verified_url = (verify.json().get("status_callback") or "") if verify.status_code < 400 else ""

    if verified_url.rstrip("/") == callback.rstrip("/"):
        logger.info(
            "Twilio status callback active for %s → %s",
            call_sid,
            callback,
        )
        return True

    logger.warning(
        "Twilio status callback NOT active for %s (ElevenLabs calls use EL webhooks). "
        "Configure ElevenLabs post-call webhook → %s/webhooks/elevenlabs/post-call",
        call_sid,
        (get_settings().public_base_url or "").rstrip("/"),
    )
    return False
