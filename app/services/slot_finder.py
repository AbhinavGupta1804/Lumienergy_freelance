
"""
Slot lookup service used by the ElevenLabs `get_available_slots` tool.

Pipeline:
  1. Resolve `day_query` (free text) -> exact date in business timezone.
  2. Fetch slots from Cal.com for that single date.
  3. Filter by time_period (morning / afternoon / evening / any).
  4. Optionally filter by time_preference ("around 2 PM", "between 10 and 12", …).
  5. Return the first two slots with speech-friendly labels.

The agent must read `offer_speech` / slot `local` values and pass `start` verbatim to book_slot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import re

import dateparser

from app.config import get_settings
from app.integrations.cal_com import CalComClient, CalComError

logger = logging.getLogger(__name__)

VALID_PERIODS = {"any", "morning", "afternoon", "evening"}
SCHEDULING_WINDOW_DAYS = 3  # tomorrow, day after tomorrow, two days after tomorrow

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

PERIOD_WORDS = ("morning", "afternoon", "evening", "night", "tonight")

NEXT_DAY_QUERIES: dict[int, str] = {
    1: "day after tomorrow",
    2: "two days after tomorrow",
}

DAY_LABELS: dict[int, str] = {
    1: "tomorrow",
    2: "day after tomorrow",
    3: "two days after tomorrow",
}

# Longest / most specific first — "tomorrow" is a substring of the other phrases.
_SCHEDULING_DAY_OFFSETS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^two\s+days?\s+after\s+tomorrow$", re.I), 3),
    (re.compile(r"^(?:the\s+)?day\s+after\s+tomorrow$", re.I), 2),
    (re.compile(r"^tomorrow$", re.I), 1),
]


class SlotFinderError(Exception):
    pass


@dataclass(frozen=True)
class TimeWindow:
    """Inclusive local-time window for filtering slots."""

    start: datetime | None
    end: datetime | None
    sort_by_proximity_to: datetime | None = None


def _today_in_business_tz() -> date:
    settings = get_settings()
    tz = ZoneInfo(settings.business_timezone)
    return datetime.now(tz).date()


def _next_weekday(today: date, target_weekday: int, *, skip_this_week: bool = False) -> date:
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    if skip_this_week and days_ahead < 7:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _normalize_day_query_text(text: str) -> str:
    norm = (text or "").lower().strip()
    for word in PERIOD_WORDS:
        norm = norm.replace(word, "")
    return re.sub(r"\s+", " ", norm).strip()


def _try_scheduling_day_offset(day_query: str) -> int | None:
    """
    Map agent scheduling phrases to days ahead of today.

    dateparser mishandles ``two days after tomorrow`` (resolves to tomorrow
    because it anchors on the word ``tomorrow``). These three phrases are
    fixed in the ElevenLabs prompt — resolve them explicitly.
    """
    norm = _normalize_day_query_text(day_query)
    if not norm:
        return None
    for pattern, offset in _SCHEDULING_DAY_OFFSETS:
        if pattern.fullmatch(norm):
            return offset
    return None


def _try_weekday_phrase(text: str, today: date) -> date | None:
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
    """Convert natural-language day text to a future date in the business timezone."""
    settings = get_settings()
    tz_name = settings.business_timezone
    today = _today_in_business_tz()

    cleaned = (day_query or "").strip()
    if not cleaned:
        return today + timedelta(days=1)

    scheduling_offset = _try_scheduling_day_offset(cleaned)
    if scheduling_offset is not None:
        result = today + timedelta(days=scheduling_offset)
    elif weekday_hit := _try_weekday_phrase(cleaned, today):
        result = weekday_hit
    else:
        stripped = _normalize_day_query_text(cleaned) or cleaned

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
    hour_12 = dt_local.strftime("%I").lstrip("0") or "12"
    minute = dt_local.minute
    suffix = dt_local.strftime("%p")
    if minute == 0:
        return f"{hour_12} {suffix}"
    return f"{hour_12}:{minute:02d} {suffix}"


def _to_local(iso_z: str, tz_name: str) -> datetime:
    s = iso_z.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(ZoneInfo(tz_name))


def _day_bounds(target_day: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(target_day, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(minutes=1)
    return start, end


def _parse_clock_fragment(fragment: str, target_day: date, tz_name: str) -> datetime | None:
    tz = ZoneInfo(tz_name)
    day_start, _ = _day_bounds(target_day, tz_name)
    parsed = dateparser.parse(
        fragment.strip(),
        settings={
            "TIMEZONE": tz_name,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": day_start.replace(tzinfo=None),
        },
    )
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def parse_time_preference(text: str, target_day: date, tz_name: str) -> TimeWindow | None:
    """
    Parse customer time frames such as:
      - around 2 PM / about 10
      - between 10 and 12 / from 2 to 4
      - after 3 / before noon
      - early afternoon / late morning
    Returns None when the phrase cannot be parsed (caller skips preference filter).
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None

    day_start, day_end = _day_bounds(target_day, tz_name)

    qualitative: dict[str, tuple[int, int]] = {
        "early morning": (7, 10),
        "late morning": (10, 12),
        "early afternoon": (12, 14),
        "late afternoon": (15, 17),
        "early evening": (17, 19),
        "late evening": (19, 21),
        "noon": (11, 13),
        "lunch": (11, 13),
        "lunchtime": (11, 13),
        "midday": (11, 13),
    }
    for phrase, (h1, h2) in qualitative.items():
        if phrase in raw:
            return TimeWindow(
                day_start.replace(hour=h1, minute=0),
                day_start.replace(hour=h2, minute=0),
            )

    between = re.search(r"(?:between|from)\s+(.+?)\s+(?:and|to)\s+(.+)", raw)
    if between:
        t1 = _parse_clock_fragment(between.group(1), target_day, tz_name)
        t2 = _parse_clock_fragment(between.group(2), target_day, tz_name)
        if t1 and t2:
            return TimeWindow(min(t1, t2), max(t1, t2))

    after = re.search(r"(?:after|past)\s+(.+)", raw)
    if after:
        t = _parse_clock_fragment(after.group(1), target_day, tz_name)
        if t:
            return TimeWindow(t, day_end)

    before = re.search(r"before\s+(.+)", raw)
    if before:
        t = _parse_clock_fragment(before.group(1), target_day, tz_name)
        if t:
            return TimeWindow(day_start, t)

    around = re.search(r"(?:around|about|like|roughly|ish|near)\s+(.+)", raw)
    if around:
        center = _parse_clock_fragment(around.group(1), target_day, tz_name)
        if center:
            return TimeWindow(
                center - timedelta(minutes=75),
                center + timedelta(minutes=75),
                sort_by_proximity_to=center,
            )

    center = _parse_clock_fragment(raw, target_day, tz_name)
    if center:
        return TimeWindow(
            center - timedelta(minutes=75),
            center + timedelta(minutes=75),
            sort_by_proximity_to=center,
        )

    return None


def _filter_by_time_preference(
    slots: list[dict[str, Any]],
    preference: str,
    target_day: date,
    tz_name: str,
) -> list[dict[str, Any]]:
    window = parse_time_preference(preference, target_day, tz_name)
    if window is None:
        logger.warning("Could not parse time_preference %r — skipping preference filter", preference)
        return slots

    filtered: list[dict[str, Any]] = []
    for slot in slots:
        dt = slot["local_dt"]
        if window.start and dt < window.start:
            continue
        if window.end and dt > window.end:
            continue
        filtered.append(slot)

    if window.sort_by_proximity_to:
        center = window.sort_by_proximity_to
        filtered.sort(key=lambda s: abs((s["local_dt"] - center).total_seconds()))
    else:
        filtered.sort(key=lambda s: s["start"])
    return filtered


def _format_two_slot_offer(slots: list[dict[str, Any]]) -> str:
    """Speech label for exactly two offered times: '10 AM or 11 AM'."""
    if not slots:
        return ""
    if len(slots) == 1:
        return slots[0]["local"]
    return f"{slots[0]['local']} or {slots[1]['local']}"


def _scheduling_meta(target_day: date, day_has_no_slots: bool) -> dict[str, Any]:
    """Meta for day-level emptiness — use has_any_slots, not period-level has_slots."""
    today = _today_in_business_tz()
    days_from_today = (target_day - today).days
    exhausted = day_has_no_slots and days_from_today >= SCHEDULING_WINDOW_DAYS
    next_day_query = None
    if day_has_no_slots and days_from_today < SCHEDULING_WINDOW_DAYS:
        next_day_query = NEXT_DAY_QUERIES.get(days_from_today)
    return {
        "days_from_today": days_from_today,
        "day_label": DAY_LABELS.get(days_from_today, ""),
        "next_day_query": next_day_query,
        "scheduling_window_exhausted": exhausted,
    }


def _spoken_day_label(weekday: str, pretty_date: str) -> str:
    return f"{weekday} {pretty_date}"


def _enrich_day_slots(
    raw_slots: list[dict[str, Any]],
    target_day: date,
    tz_name: str,
) -> dict[str, Any]:
    """
    Given raw Cal.com slots for one day, return a dict with:
      - per-period blocks (morning/afternoon/evening), each with slots + offer_speech
      - all_slots (sorted, all periods)
      - has_any_slots
    """
    all_enriched: list[dict[str, Any]] = []
    for slot in raw_slots:
        start_iso = slot.get("start")
        if not start_iso:
            continue
        try:
            local_dt = _to_local(start_iso, tz_name)
        except ValueError:
            continue
        # Cal.com may return slots from adjacent day buckets — keep only this day.
        if local_dt.date() != target_day:
            continue
        all_enriched.append({
            "start": start_iso,
            "local": _format_local(local_dt),
            "local_dt": local_dt,
            "period": _period_for_local_hour(local_dt.hour),
        })
    all_enriched.sort(key=lambda s: s["start"])

    def _build_period_block(period: str) -> dict[str, Any]:
        filtered = [s for s in all_enriched if s["period"] == period]
        first_two = filtered[:2]
        return {
            "slots": [{"start": s["start"], "local": s["local"], "period": s["period"]} for s in first_two],
            "all_slots": [{"start": s["start"], "local": s["local"], "period": s["period"]} for s in filtered],
            "offer_speech": _format_two_slot_offer(first_two),
            "has_slots": bool(first_two),
        }

    weekday = target_day.strftime("%A")
    pretty_date = f"{target_day.strftime('%B')} {target_day.day}"

    return {
        "date": target_day.isoformat(),
        "weekday": weekday,
        "pretty_date": pretty_date,
        "morning": _build_period_block("morning"),
        "afternoon": _build_period_block("afternoon"),
        "evening": _build_period_block("evening"),
        "all_slots": [
            {"start": s["start"], "local": s["local"], "period": s["period"]}
            for s in all_enriched
        ],
        "has_any_slots": bool(all_enriched),
    }


async def find_3day_slots() -> dict[str, Any]:
    """
    Fetch all slots for tomorrow, day after tomorrow, and two days after tomorrow
    in a single Cal.com request, then partition by local date.

    Returns:
    {
      "timezone": "America/Phoenix",
      "days": [
        {
          "label": "tomorrow",
          "date": "2026-06-13",
          "weekday": "Saturday",
          "pretty_date": "June 13",
          "morning":   {"has_slots": true, "offer_speech": "10 AM or 11 AM", "slots": [...], "all_slots": [...]},
          "afternoon": {"has_slots": true, "offer_speech": "2 PM or 3 PM",   "slots": [...], "all_slots": [...]},
          "evening":   {"has_slots": false,"offer_speech": "",               "slots": [], "all_slots": []},
          "all_slots": [...],
          "has_any_slots": true
        },
        { "label": "day after tomorrow", ... },
        { "label": "two days after tomorrow", ... }
      ],
      "any_slots_in_window": true,
      "scheduling_window_exhausted": false
    }
    """
    settings = get_settings()
    tz_name = settings.business_timezone
    today = _today_in_business_tz()

    day_labels = [
        (today + timedelta(days=1), "tomorrow"),
        (today + timedelta(days=2), "day after tomorrow"),
        (today + timedelta(days=3), "two days after tomorrow"),
    ]
    start_day = day_labels[0][0]
    # Extend one day past the window so late-evening slots bucketed on the next
    # date key are still returned by Cal.com.
    api_end_day = day_labels[-1][0] + timedelta(days=1)

    client = CalComClient()
    try:
        raw_slots = await client.fetch_slots_range(start_day, api_end_day)
    except CalComError as exc:
        raise SlotFinderError(str(exc)) from exc

    target_dates = {target_day for target_day, _ in day_labels}
    slots_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in target_dates}
    for slot in raw_slots:
        start_iso = slot.get("start")
        if not start_iso:
            continue
        try:
            local_dt = _to_local(start_iso, tz_name)
        except ValueError:
            continue
        local_date = local_dt.date()
        if local_date in slots_by_date:
            slots_by_date[local_date].append(slot)

    days: list[dict[str, Any]] = []
    for target_day, label in day_labels:
        day_data = _enrich_day_slots(slots_by_date[target_day], target_day, tz_name)
        day_data["label"] = label
        days.append(day_data)

    any_slots = any(d["has_any_slots"] for d in days)

    return {
        "timezone": tz_name,
        "days": list(days),
        "any_slots_in_window": any_slots,
        "scheduling_window_exhausted": not any_slots,
    }


async def find_slots(
    *,
    day_query: str,
    time_period: str = "any",
    time_preference: str | None = None,
    limit: str = "first_two",
) -> dict[str, Any]:
    """
    Fetch slots for ONE day. Call once per day/period the agent is offering.

    Returns spoken_offer with weekday + date baked in, e.g.
    "Monday June 15 — 8 AM or 10 AM"
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

    day_data = _enrich_day_slots(raw_slots, target_day, tz_name)
    weekday = day_data["weekday"]
    pretty_date = day_data["pretty_date"]
    day_spoken = _spoken_day_label(weekday, pretty_date)
    has_any_slots = day_data["has_any_slots"]
    meta = _scheduling_meta(target_day, not has_any_slots)

    # Build full enriched list for time_preference filtering.
    enriched: list[dict[str, Any]] = []
    for slot in raw_slots:
        start_iso = slot.get("start")
        if not start_iso:
            continue
        try:
            local_dt = _to_local(start_iso, tz_name)
        except ValueError:
            continue
        if local_dt.date() != target_day:
            continue
        enriched.append({
            "start": start_iso,
            "local": _format_local(local_dt),
            "local_dt": local_dt,
            "period": _period_for_local_hour(local_dt.hour),
        })
    enriched.sort(key=lambda s: s["start"])

    pref = (time_preference or "").strip() or None
    if pref:
        filtered = _filter_by_time_preference(enriched, pref, target_day, tz_name)
        slots_out = filtered[:2]
        offer_inner = _format_two_slot_offer(slots_out)
        has_slots = bool(slots_out)
    elif period in ("morning", "afternoon", "evening"):
        block = day_data[period]
        slots_out = block["slots"]
        offer_inner = block["offer_speech"]
        has_slots = block["has_slots"]
    else:
        slots_out = day_data["all_slots"][:2]
        offer_inner = _format_two_slot_offer(slots_out)
        has_slots = bool(slots_out)

    spoken_offer = f"{day_spoken} — {offer_inner}" if has_slots else ""
    no_slots_message = f"No availability on {day_spoken}." if not has_any_slots else ""

    if has_slots:
        if pref:
            summary = f"{day_spoken} ({pref}): {offer_inner}"
        elif period != "any":
            summary = f"{day_spoken} {period}: {offer_inner}"
        else:
            summary = f"{day_spoken}: {offer_inner}"
    elif not has_any_slots:
        summary = no_slots_message
    else:
        summary = f"No {period} slots on {day_spoken}."

    return {
        "resolved_date": day_data["date"],
        "weekday": weekday,
        "pretty_date": pretty_date,
        "day_spoken": day_spoken,
        "timezone": tz_name,
        "time_period": period,
        "time_preference": pref,
        "has_any_slots": has_any_slots,
        "has_slots": has_slots,
        "bookable": has_slots,
        "slots": slots_out,
        "offer_speech": offer_inner,
        "spoken_offer": spoken_offer,
        "no_slots_message": no_slots_message,
        "summary": summary,
        "morning": day_data["morning"],
        "afternoon": day_data["afternoon"],
        "evening": day_data["evening"],
        "all_slots": day_data["all_slots"],
        **meta,
    }
