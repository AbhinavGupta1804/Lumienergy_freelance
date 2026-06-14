"""
Scheduling proxy endpoint used by the ElevenLabs `get_available_slots` tool.

The agent calls THIS endpoint instead of Cal.com directly so we can:
  - parse natural-language dates ("tomorrow", "Tuesday evening")
  - apply the correct business timezone (Arizona / America/Phoenix)
  - filter by time period (morning / afternoon / evening)
  - return both raw ISO `start` (for booking) and a human label (for speech)

Auth: a shared API key header keeps the public ngrok URL gated.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.integrations.cal_com import CalComError
from app.services.calendar_booking import book_appointment
from app.services.slot_finder import SlotFinderError, find_3day_slots, find_slots
from app.utils.dedup_store import DedupStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


def _check_auth(provided: str | None) -> None:
    expected = get_settings().scheduling_tool_api_key
    if not expected:
        return  # auth disabled if env var empty
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid tool API key")


@router.get("/slots")
async def slots(
    day_query: str = Query(..., description="Natural language day, e.g. 'tomorrow', 'day after tomorrow'"),
    time_period: str = Query("any", description="any | morning | afternoon | evening"),
    time_preference: str | None = Query(
        None,
        description="Customer time frame, e.g. 'around 2 PM', 'between 10 and 12', 'after 3'",
    ),
    limit: str = Query("first_two", description="first_two | all"),
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
):
    """Return up to two slots for one resolved date."""
    _check_auth(x_tool_api_key)

    try:
        result = await find_slots(
            day_query=day_query,
            time_period=time_period,
            time_preference=time_preference,
            limit=limit,
        )
    except SlotFinderError as exc:
        logger.warning("Slot lookup failed for %r: %s", day_query, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected slot lookup error")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return result


@router.get("/3day-slots")
async def three_day_slots(
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
):
    """
    Deprecated: bulk 3-day fetch. Prefer GET /scheduling/slots with one day_query per call.
    """
    _check_auth(x_tool_api_key)

    try:
        result = await find_3day_slots()
    except SlotFinderError as exc:
        logger.warning("3day slot lookup failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected 3day slot lookup error")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return result


class BookAttendeeBody(BaseModel):
    name: str = ""
    phoneNumber: str = Field(..., description="E.164 phone from {{phone_no}}")
    timeZone: str = "America/Phoenix"


class CalBookProxyBody(BaseModel):
    """Same shape as Cal.com POST /v2/bookings — drop-in for the ElevenLabs tool."""

    eventTypeId: int | None = None
    start: str
    attendee: BookAttendeeBody


def _dedup_store(request: Request) -> DedupStore:
    if not hasattr(request.app.state, "dedup_store"):
        raise HTTPException(status_code=500, detail="Dedup store not configured")
    return request.app.state.dedup_store


async def _book_from_phone(
    *,
    store: DedupStore,
    start: str,
    phone_no: str,
) -> dict:
    try:
        return await book_appointment(
            store=store,
            start=start.strip(),
            phone_no=phone_no.strip(),
        )
    except CalComError as exc:
        logger.warning("Booking failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected booking error")
        raise HTTPException(status_code=500, detail="Internal error") from exc


@router.post("/book")
async def book_slot_post(
    body: CalBookProxyBody,
    request: Request,
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
):
    """
    Drop-in proxy for the existing ElevenLabs ``book_slot`` Cal.com POST tool.

    The agent still sends ``start`` + ``attendee.phoneNumber`` (from {{phone_no}}).
    Full name and address are loaded from the lead DB row — ``attendee.name`` is
    ignored so first_name-only dynamic vars do not leak into the calendar.
    """
    _check_auth(x_tool_api_key)
    store = _dedup_store(request)
    result = await _book_from_phone(
        store=store,
        start=body.start,
        phone_no=body.attendee.phoneNumber,
    )
    return {
        "status": "success",
        "data": {
            "uid": result["booking_uid"],
            "title": result.get("title"),
            "start": result.get("start"),
        },
    }


@router.get("/book")
async def book_slot_get(
    request: Request,
    start: str = Query(..., description="Exact ISO start from get_available_slots"),
    phone_no: str = Query(..., description="Customer phone E.164 — use exact {{phone_no}}"),
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
):
    """Alternate GET book endpoint (same DB lookup by phone)."""
    _check_auth(x_tool_api_key)
    store = _dedup_store(request)
    return await _book_from_phone(store=store, start=start, phone_no=phone_no)
