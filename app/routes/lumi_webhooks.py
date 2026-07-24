"""
Lumi-specific webhooks called by the ElevenLabs agent during a live call.

mark_bill_sms_ready — Step 6b: send bill-upload SMS immediately when booking flow
completed and sheet transactional SMS consent is Yes.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.post_call_sms import PostCallSmsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/lumi", tags=["lumi-webhooks"])


def _check_tool_auth(provided: str | None) -> None:
    expected = get_settings().scheduling_tool_api_key
    if not expected:
        return
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid tool API key")


class MarkBillSmsReadyBody(BaseModel):
    phone_no: str = Field("", description="Customer phone — use exact {{phone_no}}")


@router.post("/mark-bill-sms-ready")
async def mark_bill_sms_ready(
    request: Request,
    body: MarkBillSmsReadyBody,
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
) -> dict[str, Any]:
    """
    ElevenLabs Step 6b tool — send bill-upload link SMS now (not post-call).

    Requires:
      - Latest call row for phone_no
      - sms_eligible=true (Transactional SMS Consent = Yes on sheet)
    """
    _check_tool_auth(x_tool_api_key)

    phone_no = (body.phone_no or "").strip()
    if not phone_no:
        raise HTTPException(status_code=400, detail="phone_no is required")

    if not hasattr(request.app.state, "post_call_sms_service"):
        raise HTTPException(status_code=500, detail="SMS service not configured")

    sms_service: PostCallSmsService = request.app.state.post_call_sms_service
    result = await sms_service.send_bill_upload_at_step_6b(phone_no=phone_no)
    logger.info("mark_bill_sms_ready phone=%s result=%s", phone_no, result)
    return {"ok": True, **result}
