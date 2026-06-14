"""
Lumi-specific webhooks called by the ElevenLabs agent during a live call.

DEPRECATED: mark_bill_sms_ready endpoint has been removed.
SMS is now sent automatically to all customers after call completion.
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/lumi", tags=["lumi-webhooks"])
