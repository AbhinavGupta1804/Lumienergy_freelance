"""
Compute next callback dial time for unanswered outbound calls.

Day 1 (same calendar day as first call, America/Phoenix):
  attempt 1 ends → +30 min
  attempt 2 ends → +1 hour
  attempt 3 ends → +2 hours

After that (or when day-1 slots fall past 8 PM): 9:00 AM and 7:00 PM daily
until 7 days after the first call. No dials at or after 8:00 PM.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

UNANSWERED_TWILIO_STATUSES = frozenset({"no-answer", "busy"})


def is_call_answered(twilio_status: str, duration_secs: int | None) -> bool:
    """Customer picked up — real conversation (duration > 0)."""
    return (duration_secs or 0) > 0


def is_call_unanswered(twilio_status: str, duration_secs: int | None) -> bool:
    """Schedule a callback: no-answer, busy, or completed with zero duration."""
    status = (twilio_status or "").lower()
    if status in UNANSWERED_TWILIO_STATUSES:
        return True
    return status == "completed" and (duration_secs or 0) == 0


def compute_next_retry_at(
    *,
    completed_attempt: int,
    last_ended_at: datetime,
    first_call_at: datetime,
) -> datetime | None:
    """
    Return UTC datetime for the next dial, or None if the 7-day window is over.

    ``completed_attempt`` is how many calls have finished (1 = first call just ended).
    """
    settings = get_settings()
    tz = ZoneInfo(settings.business_timezone)
    max_days = settings.callback_max_days

    if last_ended_at.tzinfo is None:
        last_ended_at = last_ended_at.replace(tzinfo=ZoneInfo("UTC"))
    if first_call_at.tzinfo is None:
        first_call_at = first_call_at.replace(tzinfo=ZoneInfo("UTC"))

    window_end = first_call_at + timedelta(days=max_days)
    if last_ended_at >= window_end:
        return None

    local_ended = last_ended_at.astimezone(tz)
    first_day = first_call_at.astimezone(tz).date()

    candidate: datetime | None = None

    if completed_attempt <= 3:
        offsets = {
            1: timedelta(minutes=30),
            2: timedelta(hours=1),
            3: timedelta(hours=2),
        }
        raw = last_ended_at + offsets[completed_attempt]
        raw = _clamp_to_calling_hours(raw, tz)
        if raw.astimezone(tz).date() == first_day:
            candidate = raw

    if candidate is None:
        candidate = _next_daily_slot(last_ended_at, tz)

    if candidate >= window_end:
        return None

    candidate = _enforce_minimum_delay(
        candidate=candidate,
        completed_attempt=completed_attempt,
        last_ended_at=last_ended_at,
        tz=tz,
    )
    return candidate.astimezone(ZoneInfo("UTC"))


def _enforce_minimum_delay(
    *,
    candidate: datetime,
    completed_attempt: int,
    last_ended_at: datetime,
    tz: ZoneInfo,
) -> datetime:
    """Never schedule in the past; honor minimum gaps (30m / 1h / 2h)."""
    now_utc = datetime.now(ZoneInfo("UTC"))
    min_offsets = {
        1: timedelta(minutes=30),
        2: timedelta(hours=1),
        3: timedelta(hours=2),
    }
    floor = last_ended_at + min_offsets.get(completed_attempt, timedelta(minutes=5))
    if candidate < floor:
        candidate = floor
        candidate = _clamp_to_calling_hours(candidate, tz)
    # Safety: never fire on the next scheduler tick due to clock / TZ skew.
    if candidate <= now_utc + timedelta(minutes=2):
        candidate = now_utc + timedelta(minutes=2)
        candidate = _clamp_to_calling_hours(candidate, tz)
    return candidate


def _clamp_to_calling_hours(dt: datetime, tz: ZoneInfo) -> datetime:
    """Earliest 9 AM; if at/after 8 PM → next day 9 AM."""
    settings = get_settings()
    local = dt.astimezone(tz)
    morning = local.replace(
        hour=settings.callback_morning_hour, minute=0, second=0, microsecond=0
    )
    cutoff = local.replace(
        hour=settings.callback_evening_cutoff_hour, minute=0, second=0, microsecond=0
    )

    if local < morning:
        return morning.astimezone(ZoneInfo("UTC"))
    if local >= cutoff:
        next_morning = (local.date() + timedelta(days=1))
        return datetime(
            next_morning.year,
            next_morning.month,
            next_morning.day,
            settings.callback_morning_hour,
            0,
            0,
            tzinfo=tz,
        ).astimezone(ZoneInfo("UTC"))
    return dt


def _next_daily_slot(after: datetime, tz: ZoneInfo) -> datetime:
    """9 AM or 7 PM Phoenix — two attempts per day after day-1 rapid retries."""
    settings = get_settings()
    local = after.astimezone(tz)
    morning = local.replace(
        hour=settings.callback_morning_hour, minute=0, second=0, microsecond=0
    )
    evening = local.replace(
        hour=settings.callback_evening_hour, minute=0, second=0, microsecond=0
    )

    if local < morning:
        return morning.astimezone(ZoneInfo("UTC"))
    if local < evening:
        return evening.astimezone(ZoneInfo("UTC"))

    next_day: date = local.date() + timedelta(days=1)
    next_morning = datetime(
        next_day.year,
        next_day.month,
        next_day.day,
        settings.callback_morning_hour,
        0,
        0,
        tzinfo=tz,
    )
    return next_morning.astimezone(ZoneInfo("UTC"))
