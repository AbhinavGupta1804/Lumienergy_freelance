"""
Webhooks called by the Vercel bill-upload app after a successful upload.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app.services.bill_upload_confirmation_sms import BillUploadConfirmationSmsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/bill-upload", tags=["bill-upload-webhooks"])


class BillUploadCompleteBody(BaseModel):
    upload_token: str


def _check_secret(provided: str | None) -> None:
    expected = get_settings().bill_upload_webhook_secret
    if not expected:
        logger.warning("BILL_UPLOAD_WEBHOOK_SECRET not set — rejecting bill-upload webhook")
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/complete")
async def bill_upload_complete(
    body: BillUploadCompleteBody,
    request: Request,
    x_bill_upload_webhook_secret: str | None = Header(
        default=None, alias="X-Bill-Upload-Webhook-Secret"
    ),
) -> JSONResponse:
    """
    Called by bill_upload/api/upload.js after storage + DB update succeed.

    Sends consultation confirmation SMS with appointment time.
    """
    _check_secret(x_bill_upload_webhook_secret)

    if not hasattr(request.app.state, "bill_upload_confirmation_sms_service"):
        raise HTTPException(status_code=500, detail="Service not configured")

    service: BillUploadConfirmationSmsService = (
        request.app.state.bill_upload_confirmation_sms_service
    )
    result = await service.on_bill_uploaded(body.upload_token)
    logger.info("Bill-upload confirmation SMS: %s", result)
    return JSONResponse({"ok": True, **result})
