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

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import get_settings
from app.services.slot_finder import SlotFinderError, find_slots

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
    day_query: str = Query(..., description="Natural language day, e.g. 'tomorrow', 'Tuesday', '2026-06-02'"),
    time_period: str = Query("any", description="any | morning | afternoon | evening"),
    limit: str = Query("first_two", description="first_two | all"),
    x_tool_api_key: str | None = Header(default=None, alias="X-Tool-Api-Key"),
):
    """Return slots for one resolved date, filtered by time period."""
    _check_auth(x_tool_api_key)

    try:
        result = await find_slots(
            day_query=day_query,
            time_period=time_period,
            limit=limit,
        )
    except SlotFinderError as exc:
        logger.warning("Slot lookup failed for %r: %s", day_query, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected slot lookup error")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return result
