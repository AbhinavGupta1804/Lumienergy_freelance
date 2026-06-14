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
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

CAL_SLOTS_URL = "https://api.cal.com/v2/slots"
CAL_BOOKINGS_URL = "https://api.cal.com/v2/bookings"
CAL_API_VERSION = "2024-08-13"


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

    async def _fetch_slots_raw(self, start_day: date, end_day: date) -> list[dict[str, Any]]:
        """
        Fetch slots from Cal.com for an inclusive date range.

        Returns a flat list of {start: iso} from every bucket in the response.
        Caller must filter by local date — Cal.com may bucket evening slots under
        an adjacent date key even when the slot is local-time evening on start_day.
        """
        params = {
            "eventTypeId": self._event_type_id,
            "start": start_day.isoformat(),
            "end": end_day.isoformat(),
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
        try:
            buckets = data.get("data", {}) or {}
        except AttributeError:
            buckets = {}

        slots: list[dict[str, Any]] = []
        for _day_key, items in buckets.items():
            for item in items or []:
                if isinstance(item, dict) and "start" in item:
                    slots.append(item)
                elif isinstance(item, str):
                    slots.append({"start": item})
        logger.info(
            "Cal.com returned %s slot(s) for range %s → %s",
            len(slots),
            start_day,
            end_day,
        )
        return slots

    async def fetch_slots_for_day(self, target_day: date) -> list[dict[str, Any]]:
        """
        Return raw slots whose local time falls on target_day.

        We request through the next calendar day so late-evening slots that Cal.com
        buckets under the following date key are still included.
        """
        end_day = target_day + timedelta(days=1)
        return await self._fetch_slots_raw(target_day, end_day)

    async def fetch_slots_range(self, start_day: date, end_day: date) -> list[dict[str, Any]]:
        """Fetch all raw slots for an inclusive start_day … end_day window."""
        return await self._fetch_slots_raw(start_day, end_day)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "cal-api-version": CAL_API_VERSION,
        }

    @staticmethod
    def phone_to_attendee_email(phone: str) -> str:
        """Cal.com SMS-style placeholder email used for phone-only attendees."""
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            raise CalComError(f"Invalid phone for Cal.com attendee email: {phone!r}")
        return f"{digits}@sms.cal.com"

    async def create_booking(
        self,
        *,
        start: str,
        full_name: str,
        phone: str,
        address: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a Cal.com booking with full customer name and home address.

        Returns the booking ``uid`` and Google Calendar ``eventUid`` when available.
        """
        if not full_name.strip():
            raise CalComError("full_name is required for booking")
        if not address.strip():
            raise CalComError("address is required for booking")

        payload: dict[str, Any] = {
            "eventTypeId": int(self._event_type_id),
            "start": start,
            "attendee": {
                "name": full_name.strip(),
                "email": self.phone_to_attendee_email(phone),
                "timeZone": self._timezone,
                "phoneNumber": phone,
            },
            "location": {
                "type": "attendeeAddress",
                "address": address.strip(),
            },
        }
        if metadata:
            payload["metadata"] = metadata

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                CAL_BOOKINGS_URL,
                headers=self._headers(),
                json=payload,
            )

        if resp.status_code >= 400:
            raise CalComError(f"Cal.com booking HTTP {resp.status_code}: {resp.text}")

        body = resp.json()
        data = body.get("data") or {}
        booking_uid = data.get("uid")
        if not booking_uid:
            raise CalComError(f"Cal.com booking missing uid: {body}")

        google_event_uid = await self._google_event_uid_for_booking(str(booking_uid))
        logger.info(
            "Cal.com booking created uid=%s attendee=%r address=%r",
            booking_uid,
            full_name,
            address[:60],
        )
        return {
            "booking_uid": str(booking_uid),
            "google_event_uid": google_event_uid,
            "title": data.get("title"),
            "start": data.get("start"),
        }

    async def google_event_uid_for_booking(self, booking_uid: str) -> str | None:
        """Resolve the linked Google Calendar event UID for a Cal.com booking."""
        return await self._google_event_uid_for_booking(booking_uid)

    async def _google_event_uid_for_booking(self, booking_uid: str) -> str | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{CAL_BOOKINGS_URL}/{booking_uid}/references",
                headers=self._headers(),
            )
        if resp.status_code >= 400:
            logger.warning(
                "Cal.com booking references failed uid=%s: %s",
                booking_uid,
                resp.text[:300],
            )
            return None

        for ref in (resp.json().get("data") or []):
            if ref.get("type") == "google_calendar" and ref.get("eventUid"):
                return str(ref["eventUid"])
        return None

    async def update_google_calendar_description(
        self,
        *,
        google_event_uid: str,
        description: str,
    ) -> None:
        """Patch the linked Google Calendar event description via Cal.com."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"https://api.cal.com/v2/calendars/google/events/{google_event_uid}",
                headers=self._headers(),
                json={"description": description},
            )
        if resp.status_code >= 400:
            raise CalComError(
                f"Cal.com calendar update HTTP {resp.status_code}: {resp.text}"
            )
        logger.info("Updated Google Calendar description eventUid=%s", google_event_uid)
