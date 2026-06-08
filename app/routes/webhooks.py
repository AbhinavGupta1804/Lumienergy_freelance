"""
Twilio Voice webhook routes.

Status Callback (POST /webhooks/twilio/status)
----------------------------------------------
Twilio POSTs when call progress events occur. We subscribe to ``completed`` only.
On completed + sms_eligible, PostCallSmsService sends the bill-upload SMS.

Configure per-call via attach_status_callback() after ElevenLabs starts the call,
and/or set the same URL on your Twilio phone number in Console for redundancy.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.integrations.twilio_webhooks import (
    parse_status_callback,
    validate_twilio_signature,
)
from app.services.post_call_sms import PostCallSmsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio-webhooks"])


@router.post("/status")
async def twilio_status_callback(request: Request) -> PlainTextResponse:
    """
    Twilio Status Callback endpoint.

    Twilio sends application/x-www-form-urlencoded fields including:
      CallSid, CallStatus, From, To, Direction, CallDuration, ...

    Return 200 OK so Twilio does not retry. Duplicate ``completed`` posts are
    ignored when sms_sent is already set in the database.
    """
    form = await request.form()
    raw_params = {k: str(v) for k, v in form.items()}
    data = parse_status_callback(raw_params)

    settings = get_settings()
    if settings.twilio_validate_webhook_signatures:
        signature = request.headers.get("X-Twilio-Signature")
        url = str(request.url)
        if not validate_twilio_signature(
            auth_token=settings.twilio_auth_token,
            url=url,
            params=raw_params,
            signature=signature,
        ):
            logger.warning("Invalid Twilio signature for status callback call_sid=%s", data.get("call_sid"))
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    logger.info(
        "Twilio status callback call_sid=%s status=%s to=%s from=%s",
        data.get("call_sid"),
        data.get("status"),
        data.get("to"),
        data.get("from"),
    )

    if hasattr(request.app.state, "post_call_sms_service"):
        sms_service: PostCallSmsService = request.app.state.post_call_sms_service
        result = await sms_service.on_status_callback(data)
        logger.info("Post-call SMS handler result: %s", result)

    return PlainTextResponse("OK")


@router.post("/voice")
async def twilio_voice_fallback(request: Request) -> PlainTextResponse:
    """
    Fallback voice webhook — not used when ElevenLabs initiates outbound calls.

    Returns minimal TwiML so Twilio does not error if this URL is hit accidentally.
    """
    form = await request.form()
    logger.warning(
        "Unexpected hit on /webhooks/twilio/voice CallSid=%s From=%s To=%s",
        form.get("CallSid"),
        form.get("From"),
        form.get("To"),
    )
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
    return PlainTextResponse(twiml, media_type="application/xml")
