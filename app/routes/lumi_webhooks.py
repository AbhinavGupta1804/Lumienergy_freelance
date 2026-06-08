"""
Lumi-specific webhooks called by the ElevenLabs agent during a live call.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.post_call_sms import PostCallSmsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/lumi", tags=["lumi-webhooks"])


class MarkBillSmsReadyBody(BaseModel):
    """JSON body sent by ElevenLabs mark_bill_sms_ready tool."""

    phone_no: str = Field(..., description="Customer phone from {{phone_no}}")
    conversation_id: str | None = Field(
        default=None,
        description="Current call ID — use {{system__conversation_id}} in ElevenLabs tool",
    )


def _check_tool_auth(provided: str | None) -> None:
    expected = get_settings().sms_tool_api_key or get_settings().scheduling_tool_api_key
    if not expected:
        return
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid tool API key")


@router.post("/mark-bill-sms-ready")
async def mark_bill_sms_ready(
    request: Request,
    body: MarkBillSmsReadyBody,
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
) -> JSONResponse:
    """
    ElevenLabs tool webhook — call after Step 6 (attendance), before Step 7 (closing).

    Sets sms_eligible=1. SMS is sent when Twilio POSTs CallStatus=completed to
    /webhooks/twilio/status (status callback attached when the outbound call starts).
    """
    _check_tool_auth(x_tool_api_key)

    service: PostCallSmsService = request.app.state.post_call_sms_service
    result = service.mark_ready_by_phone(
        body.phone_no,
        conversation_id=body.conversation_id,
    )
    return JSONResponse(result)
