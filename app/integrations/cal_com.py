"""
Cal.com API client — slots lookup for a single date in the business timezone.

Why this file:
  The ElevenLabs agent must NEVER do date math or timezone math. We hide both
  here, fetch slots for one local date, and return them with both:
    - the raw `start` ISO string (used verbatim by book_slot) AND
    - a human label like "11 AM" the agent reads to the customer.

Reference: https://cal.com/docs/api-reference/v2/slots
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

CAL_SLOTS_URL = "https://api.cal.com/v2/slots"


class CalComError(Exception):
    """Cal.com API failure."""


class CalComClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.cal_api_key:
            raise ValueError("CAL_API_KEY is not set")
        if not settings.cal_event_type_id:
            raise ValueError("CAL_EVENT_TYPE_ID is not set")
        self._api_key = settings.cal_api_key
        self._event_type_id = settings.cal_event_type_id
        self._timezone = settings.business_timezone

    async def fetch_slots_for_day(self, target_day: date) -> list[dict[str, Any]]:
        """
        Return raw slot start ISO strings for the given local day.

        We pass timeZone so Cal.com returns availability honoring the
        business's local working hours.
        """
        params = {
            "eventTypeId": self._event_type_id,
            "start": target_day.isoformat(),
            "end": target_day.isoformat(),  # inclusive single-day window
            "timeZone": self._timezone,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "cal-api-version": "2024-09-04",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(CAL_SLOTS_URL, params=params, headers=headers)

        if resp.status_code >= 400:
            raise CalComError(f"Cal.com slots HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        # Cal.com response shape: { "status": "success", "data": { "YYYY-MM-DD": [ {start: "..."}, ... ] } }
        try:
            buckets = data.get("data", {}) or {}
        except AttributeError:
            buckets = {}

        slots: list[dict[str, Any]] = []
        for day_key, items in buckets.items():
            for item in items or []:
                if isinstance(item, dict) and "start" in item:
                    slots.append(item)
                elif isinstance(item, str):
                    slots.append({"start": item})
        logger.info("Cal.com returned %s slot(s) for %s", len(slots), target_day)
        return slots
