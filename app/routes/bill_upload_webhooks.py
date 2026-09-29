"""
Webhooks called after a successful bill upload (website or Vercel uploader).

POST /webhooks/bill-upload/complete
  → attach bill file to Zoho CRM Lead
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app.services.zoho_bill_attachment import ZohoBillAttachmentService

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
    Called by LUMI SOLAR WEBSITE (or legacy Vercel upload.js) after storage + DB succeed.

    Attaches the uploaded bill image/PDF to the matching Zoho Lead.
    """
    _check_secret(x_bill_upload_webhook_secret)

    if not hasattr(request.app.state, "dedup_store"):
        raise HTTPException(status_code=500, detail="Service not configured")

    zoho_result: dict = {"action": "skipped", "reason": "service_unavailable"}
    try:
        store = request.app.state.dedup_store
        zoho_service = ZohoBillAttachmentService(store)
        zoho_result = await zoho_service.attach_for_upload_token(body.upload_token)
        logger.info("Bill-upload Zoho attach: %s", zoho_result)
    except Exception:
        logger.exception("Bill-upload Zoho attach crashed token=%s", body.upload_token)
        zoho_result = {"action": "failed", "error": "unexpected_exception"}

    return JSONResponse(
        {
            "ok": True,
            "zoho_attach": zoho_result,
        }
    )
