
"""
Slot lookup service used by the ElevenLabs `get_available_slots` tool.

Pipeline:
  1. Resolve `day_query` (free text) -> exact date in business timezone.
  2. Fetch slots from Cal.com for that single date.
  3. Filter by time_period (morning / afternoon / evening / any).
  4. Format response with:
        - start  : the EXACT ISO string Cal.com returned (used by book_slot)
        - local  : human label like "11 AM" or "4:30 PM" (what the agent speaks)
        - period : "morning" | "afternoon" | "evening"

The agent must read `local` and pass `start` verbatim to book_slot.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import re

import dateparser

from app.config import get_settings
from app.integrations.cal_com import CalComClient, CalComError

logger = logging.getLogger(__name__)

VALID_PERIODS = {"any", "morning", "afternoon", "evening"}

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Drop period words so "tuesday evening" still resolves to Tuesday
PERIOD_WORDS = ("morning", "afternoon", "evening", "night", "tonight")


class SlotFinderError(Exception):
    pass


def _today_in_business_tz() -> date:
    settings = get_settings()
    tz = ZoneInfo(settings.business_timezone)
    return datetime.now(tz).date()


def _next_weekday(today: date, target_weekday: int, *, skip_this_week: bool = False) -> date:
    """Next occurrence of target_weekday (0=Mon). If today is the target, return today+7."""
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # always future
    if skip_this_week and days_ahead < 7:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _try_weekday_phrase(text: str, today: date) -> date | None:
    """
    Handle 'monday', 'tuesday', 'this wednesday', 'next friday', 'coming saturday'.
    Returns None if the phrase doesn't match a weekday.
    """
    norm = text.lower()
    for word in PERIOD_WORDS:
        norm = norm.replace(word, "")
    norm = re.sub(r"\s+", " ", norm).strip()

    modifier_match = re.match(r"^(this|next|coming|upcoming)\s+([a-z]+)$", norm)
    if modifier_match:
        modifier, weekday_name = modifier_match.group(1), modifier_match.group(2)
        wd = WEEKDAYS.get(weekday_name)
        if wd is None:
            return None
        return _next_weekday(today, wd, skip_this_week=(modifier == "next"))

    wd = WEEKDAYS.get(norm)
    if wd is not None:
        return _next_weekday(today, wd)
    return None


def resolve_day(day_query: str) -> date:
    """
    Convert "tomorrow", "Tuesday", "next Friday", "Tuesday evening", "June 3",
    "2026-06-02" to a date in the business timezone. Never returns a past date.
    """
    settings = get_settings()
    tz_name = settings.business_timezone
    today = _today_in_business_tz()

    cleaned = (day_query or "").strip()
    if not cleaned:
        return today + timedelta(days=1)

    # 1) Explicit weekday phrases (most reliable)
    weekday_hit = _try_weekday_phrase(cleaned, today)
    if weekday_hit:
        result = weekday_hit
    else:
        # 2) Strip trailing period words for dateparser ("June 3 evening" -> "June 3")
        stripped = cleaned.lower()
        for word in PERIOD_WORDS:
            stripped = stripped.replace(word, "")
        stripped = re.sub(r"\s+", " ", stripped).strip() or cleaned

        parsed = dateparser.parse(
            stripped,
            settings={
                "TIMEZONE": tz_name,
                "RETURN_AS_TIMEZONE_AWARE": False,
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.combine(today, datetime.min.time()),
            },
        )
        if not parsed:
            raise SlotFinderError(f"Could not understand day '{day_query}'")
        result = parsed.date()

    # Force into the future and within a sane window.
    if result <= today:
        result = today + timedelta(days=1)
    max_ahead = today + timedelta(days=settings.scheduling_max_days_ahead)
    if result > max_ahead:
        raise SlotFinderError(
            f"'{day_query}' resolves to {result}, beyond {settings.scheduling_max_days_ahead} days ahead"
        )
    return result


def _period_for_local_hour(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def _format_local(dt_local: datetime) -> str:
    """Format like '11 AM', '4:30 PM' (drop ':00' for whole hours)."""
    hour_12 = dt_local.strftime("%I").lstrip("0") or "12"
    minute = dt_local.minute
    suffix = dt_local.strftime("%p")
    if minute == 0:
        return f"{hour_12} {suffix}"
    return f"{hour_12}:{minute:02d} {suffix}"


def _to_local(iso_z: str, tz_name: str) -> datetime:
    """Parse ISO 8601 (with Z) to a datetime in business timezone."""
    s = iso_z.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(ZoneInfo(tz_name))


async def find_slots(
    *,
    day_query: str,
    time_period: str = "any",
    limit: str = "first_two",
) -> dict[str, Any]:
    """
    Returns:
      {
        "resolved_date": "2026-06-02",
        "weekday": "Tuesday",
        "timezone": "America/Phoenix",
        "time_period": "evening",
        "slots": [{"start": "...Z", "local": "5 PM", "period": "evening"}, ...],
        "summary": "Tuesday June 2 evening: 5 PM, 6 PM",
        "has_slots": true
      }
    """
    period = (time_period or "any").lower().strip()
    if period not in VALID_PERIODS:
        period = "any"

    target_day = resolve_day(day_query)
    settings = get_settings()
    tz_name = settings.business_timezone

    client = CalComClient()
    try:
        raw_slots = await client.fetch_slots_for_day(target_day)
    except CalComError as exc:
        raise SlotFinderError(str(exc)) from exc

    enriched: list[dict[str, Any]] = []
    for slot in raw_slots:
        start_iso = slot.get("start")
        if not start_iso:
            continue
        try:
            local_dt = _to_local(start_iso, tz_name)
        except ValueError:
            continue
        slot_period = _period_for_local_hour(local_dt.hour)
        if period != "any" and slot_period != period:
            continue
        enriched.append(
            {
                "start": start_iso,
                "local": _format_local(local_dt),
                "period": slot_period,
                "hour_24": local_dt.hour,
            }
        )

    enriched.sort(key=lambda s: s["start"])

    limit_norm = (limit or "first_two").lower().strip()
    if limit_norm == "first_two":
        slots_out = enriched[:2]
    elif limit_norm == "all":
        slots_out = enriched
    else:
        slots_out = enriched[:2]

    weekday = target_day.strftime("%A")
    # Cross-platform day formatting (Windows does not support "%-d").
    pretty_date = f"{target_day.strftime('%B')} {target_day.day}"

    if slots_out:
        labels = ", ".join(s["local"] for s in slots_out)
        suffix = "" if period == "any" else f" {period}"
        summary = f"{weekday} {pretty_date}{suffix}: {labels}"
    else:
        suffix = "" if period == "any" else f" {period}"
        summary = f"No availability on {weekday} {pretty_date}{suffix}."

    return {
        "resolved_date": target_day.isoformat(),
        "weekday": weekday,
        "timezone": tz_name,
        "time_period": period,
        "slots": [
            {"start": s["start"], "local": s["local"], "period": s["period"]}
            for s in slots_out
        ],
        "summary": summary,
        "has_slots": bool(slots_out),
    }
