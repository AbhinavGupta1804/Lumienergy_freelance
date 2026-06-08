"""
Twilio Voice Status Callback helpers.

How Status Callback works
-------------------------
When an outbound call is created (REST API or TwiML), you can set:
  - StatusCallback: HTTPS URL on your server
  - StatusCallbackMethod: POST (recommended)
  - StatusCallbackEvent: completed (and/or initiated, ringing, answered)

After the call ends, Twilio POSTs form fields (CallSid, CallStatus, To, From, …)
to that URL. Your app returns 200 OK quickly; Twilio may retry on failure.

Post-call SMS in this project is triggered when CallStatus=completed and the
agent previously called mark_bill_sms_ready (sms_eligible=1 in SQLite).
"""

import base64
import hashlib
import hmac
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_status_callback(form_data: dict[str, Any]) -> dict[str, str]:
    """
    Normalize Twilio Status Callback POST body.

    See: https://www.twilio.com/docs/voice/api/call-resource#statuscallback
    """
    return {
        "call_sid": str(form_data.get("CallSid", "")),
        "status": str(form_data.get("CallStatus", "")),
        "from": str(form_data.get("From", "")),
        "to": str(form_data.get("To", "")),
        "direction": str(form_data.get("Direction", "")),
        "duration": str(form_data.get("CallDuration", "") or form_data.get("Duration", "")),
        "account_sid": str(form_data.get("AccountSid", "")),
        "callback_source": str(form_data.get("CallbackSource", "")),
        "sequence_number": str(form_data.get("SequenceNumber", "")),
    }


def customer_phone_from_callback(data: dict[str, str]) -> str:
    """
    Customer handset for outbound-api calls is in ``To``.
    For inbound calls to your Twilio number, use ``From``.
    """
    direction = data.get("direction", "").lower()
    if "outbound" in direction:
        return data.get("to", "")
    return data.get("from", "")


def validate_twilio_signature(
    *,
    auth_token: str,
    url: str,
    params: dict[str, str],
    signature: str | None,
) -> bool:
    """
    Verify X-Twilio-Signature per Twilio security docs.

    ``url`` must be the full URL Twilio requested (including query string).
    """
    if not signature or not auth_token:
        return False

    sorted_items = sorted((k, v) for k, v in params.items())
    payload = url + "".join(f"{k}{v}" for k, v in sorted_items)
    digest = hmac.new(
        auth_token.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)
