"""
ElevenLabs post-call webhooks.

ElevenLabs-owned Twilio calls do NOT deliver Status Callbacks to your server
(Twilio only notifies ElevenLabs). Use this endpoint for call analytics and
callback scheduling. Bill-upload SMS is sent during the call via the
mark_bill_sms_ready tool (Step 6b), not here.

Dashboard setup (required once):
  ElevenLabs → Settings / ElevenAgents → Webhooks → Create webhook
  URL: {PUBLIC_BASE_URL}/webhooks/elevenlabs/post-call
  Enable:
    - post_call_transcription (or post_call_audio)
    - call_initiation_failure  ← missed / declined / busy (no conversation)
  Assign webhook to your agent
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.calendar_booking import append_transcript_to_calendar
from app.services.call_analytics import extract_post_call_analytics
from app.services.callback_service import CallbackService
from app.services.discord_call_summary import notify_call_ended_discord
from app.services.post_call_report import PostCallReportService
from app.services.post_call_sms import PostCallSmsService
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/elevenlabs", tags=["elevenlabs-webhooks"])

# Conversation finished with analysis / audio
_CALL_ENDED_TYPES = frozenset({"post_call_transcription", "post_call_audio"})
# Never connected — no-answer, busy, declined
_INITIATION_FAILURE_TYPE = "call_initiation_failure"


def _verify_elevenlabs_signature(
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """
    Verify ElevenLabs-Signature header (format: t=<unix>,v0=<hex hmac>).
    """
    if not signature_header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        timestamp = parts.get("t", "")
        received = parts.get("v0", "")
        if not timestamp or not received:
            return False
        # Reject stale timestamps (> 30 minutes)
        if abs(time.time() - int(timestamp)) > 1800:
            return False
        signed = f"{timestamp}.{raw_body.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received)
    except (ValueError, TypeError):
        return False


async def _handle_initiation_failure(
    request: Request,
    payload: dict[str, Any],
) -> JSONResponse:
    """
    Missed / declined / busy — no live conversation.

    Reuses existing unanswered flow:
      - schedule callback retries
      - send report email WITH calendar link + follow-up email chain
    Self-book via that link cancels callbacks + follow-ups (calcom webhook).
    """
    data = payload.get("data") or {}
    conversation_id = (data.get("conversation_id") or "").strip()
    agent_id = data.get("agent_id", "")
    failure_reason = (data.get("failure_reason") or "no-answer").strip()

    logger.info(
        "ElevenLabs call_initiation_failure conversation_id=%s agent_id=%s reason=%s",
        conversation_id,
        agent_id,
        failure_reason,
    )

    if not conversation_id:
        return JSONResponse({"ok": False, "reason": "missing_conversation_id"})

    callback_result: dict | None = None
    if hasattr(request.app.state, "callback_service"):
        callback_service: CallbackService = request.app.state.callback_service
        callback_result = await callback_service.on_initiation_failure(
            conversation_id,
            failure_reason=failure_reason,
        )
        logger.info("Initiation-failure callback result: %s", callback_result)

    report_result: dict | None = None
    if hasattr(request.app.state, "post_call_report_service"):
        report_service: PostCallReportService = request.app.state.post_call_report_service
        # Same path as Twilio reconcile (Case 3: not picked → report + calendar)
        report_result = await report_service.on_conversation_ended(
            conversation_id,
            answered=False,
            webhook_payload=payload,
        )
        logger.info("Initiation-failure report email result: %s", report_result)

    discord_sent = False
    if hasattr(request.app.state, "dedup_store"):
        store: DedupStore = request.app.state.dedup_store
        discord_sent = await notify_call_ended_discord(
            payload=payload,
            store=store,
            sms_result=None,
        )

    return JSONResponse(
        {
            "ok": True,
            "event": _INITIATION_FAILURE_TYPE,
            "failure_reason": failure_reason,
            "callback": callback_result,
            "report": report_result,
            "discord_sent": discord_sent,
        }
    )


@router.post("/post-call")
async def elevenlabs_post_call(request: Request) -> JSONResponse:
    """
    Receives ElevenLabs post-call webhooks when a conversation finishes,
    or call_initiation_failure when the customer never connected.
    """
    raw = await request.body()
    settings = get_settings()

    if settings.elevenlabs_webhook_secret:
        sig = request.headers.get("elevenlabs-signature")
        if not _verify_elevenlabs_signature(raw, sig, settings.elevenlabs_webhook_secret):
            logger.warning("Invalid ElevenLabs webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
    else:
        logger.debug("ELEVENLABS_WEBHOOK_SECRET not set — skipping signature check")

    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    event_type = payload.get("type", "")

    if event_type == _INITIATION_FAILURE_TYPE:
        return await _handle_initiation_failure(request, payload)

    if event_type not in _CALL_ENDED_TYPES:
        logger.debug("Ignoring ElevenLabs event type=%s", event_type)
        return JSONResponse({"ok": True, "ignored": event_type})

    data = payload.get("data") or {}
    conversation_id = data.get("conversation_id", "")
    agent_id = data.get("agent_id", "")

    logger.info(
        "ElevenLabs call ended event=%s conversation_id=%s agent_id=%s",
        event_type,
        conversation_id,
        agent_id,
    )

    if not conversation_id:
        return JSONResponse({"ok": False, "reason": "missing_conversation_id"})

    analytics_saved = False
    analytics_fields = extract_post_call_analytics(payload)
    if analytics_fields and hasattr(request.app.state, "dedup_store"):
        store: DedupStore = request.app.state.dedup_store
        analytics_saved = store.update_post_call_analytics(**analytics_fields)

    sms_result: dict | None = None
    callback_result: dict | None = None
    answered = False

    if hasattr(request.app.state, "callback_service"):
        callback_service: CallbackService = request.app.state.callback_service
        callback_result = await callback_service.on_conversation_ended(
            conversation_id,
            webhook_payload=payload,
        )
        answered = bool(callback_result.get("answered"))
        logger.info("Post-call callback result: %s", callback_result)

    if hasattr(request.app.state, "post_call_sms_service"):
        sms_service: PostCallSmsService = request.app.state.post_call_sms_service
        sms_result = await sms_service.on_conversation_ended(
            conversation_id,
            answered=answered,
            webhook_payload=payload,
        )
        logger.info("Post-call SMS (ElevenLabs webhook) result: %s", sms_result)

    calendar_result: dict | None = None
    discord_sent = False
    if hasattr(request.app.state, "dedup_store"):
        store: DedupStore = request.app.state.dedup_store
        if event_type == "post_call_transcription":
            calendar_result = await append_transcript_to_calendar(
                store=store,
                conversation_id=conversation_id,
                webhook_data=data,
            )
            logger.info("Post-call calendar update: %s", calendar_result)
        discord_sent = await notify_call_ended_discord(
            payload=payload,
            store=store,
            sms_result=sms_result,
        )

    report_result: dict | None = None
    if hasattr(request.app.state, "post_call_report_service"):
        report_service: PostCallReportService = request.app.state.post_call_report_service
        report_result = await report_service.on_conversation_ended(
            conversation_id,
            answered=answered,
            webhook_payload=payload,
        )
        logger.info("Post-call report email result: %s", report_result)

    return JSONResponse(
        {
            "ok": True,
            "analytics_saved": analytics_saved,
            "callback": callback_result,
            "sms": sms_result,
            "calendar": calendar_result,
            "discord_sent": discord_sent,
            "report": report_result,
        }
    )
