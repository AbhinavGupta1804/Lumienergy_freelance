"""
ElevenLabs Conversational AI — Twilio outbound call integration.

ElevenLabs owns the telephony bridge: one API call starts the outbound call
and connects the callee to your existing Conversational AI agent.

API: POST https://api.elevenlabs.io/v1/convai/twilio/outbound-call
"""

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.utils.scheduling_days import scheduling_call_dynamic_vars
from app.utils.retry import retry_async

logger = logging.getLogger(__name__)

OUTBOUND_CALL_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"


class ElevenLabsCallError(Exception):
    """Raised when ElevenLabs outbound call API returns an error."""


class ElevenLabsClient:
    """
    Initiates outbound calls via ElevenLabs + Twilio integration.

    Your Twilio number must already be linked in the ElevenLabs dashboard
    (Conversational AI → Phone Numbers). Use agent_phone_number_id from there.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.elevenlabs_api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set")
        if not settings.elevenlabs_agent_id:
            raise ValueError("ELEVENLABS_AGENT_ID is not set")
        if not settings.elevenlabs_agent_phone_number_id:
            raise ValueError("ELEVENLABS_AGENT_PHONE_NUMBER_ID is not set")

        self._api_key = settings.elevenlabs_api_key
        self._agent_id = settings.elevenlabs_agent_id
        self._agent_phone_number_id = settings.elevenlabs_agent_phone_number_id
        self._max_retries = settings.max_call_retries
        self._retry_delay = settings.retry_base_delay_seconds

    async def initiate_outbound_call(
        self,
        *,
        to_number: str,
        first_name: str,
        last_name: str,
        address: str,
        phone_no: str,
    ) -> dict[str, Any]:
        """
        Start an outbound call to to_number and pass dynamic variables to the agent.

        dynamic_variables map to agent prompt / tool placeholders:
          {{first_name}}, {{last_name}}, {{full_name}}, {{address}}, {{phone_no}}
          {{sched_day_1}}, {{sched_day_1_speech}}, {{sched_day_2}}, {{sched_day_3}} (scheduling weekdays)
        """
        first = first_name.strip()
        last = last_name.strip()
        full_name = " ".join(p for p in (first, last) if p).strip() or first or last

        payload = {
            "agent_id": self._agent_id,
            "agent_phone_number_id": self._agent_phone_number_id,
            "to_number": to_number,
            "conversation_initiation_client_data": {
                "dynamic_variables": {
                    "first_name": first,
                    "last_name": last,
                    "full_name": full_name,
                    "address": address,
                    "phone_no": phone_no,
                    **scheduling_call_dynamic_vars(),
                },
            },
            "call_recording_enabled": False,
        }

        logger.info(
            "Initiating ElevenLabs outbound call to %s (full_name=%s, phone_no=%s)",
            to_number,
            full_name,
            phone_no or "(empty)",
        )

        async def _post() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    OUTBOUND_CALL_URL,
                    headers={
                        "xi-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code >= 400:
                raise ElevenLabsCallError(
                    f"ElevenLabs API error {response.status_code}: {response.text}"
                )
            data = response.json()
            if not data.get("success"):
                raise ElevenLabsCallError(
                    f"ElevenLabs call failed: {data.get('message', data)}"
                )
            return data

        return await retry_async(
            _post,
            max_attempts=self._max_retries,
            base_delay=self._retry_delay,
            exceptions=(ElevenLabsCallError, httpx.HTTPError),
        )
