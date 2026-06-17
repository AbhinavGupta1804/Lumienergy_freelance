"""Scheduling weekday helpers — kept separate from services to avoid circular imports."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

SUNDAY_WEEKDAY = 6
BOOKABLE_WINDOW_SIZE = 3

# Agent day_query phrases → 1-based index in the bookable window (Mon–Sat only).
WINDOW_DAY_QUERIES: dict[int, str] = {
    1: "tomorrow",
    2: "day after tomorrow",
    3: "two days after tomorrow",
}

WINDOW_DAY_LABELS: dict[int, str] = WINDOW_DAY_QUERIES.copy()


def today_in_business_tz() -> date:
    settings = get_settings()
    return datetime.now(ZoneInfo(settings.business_timezone)).date()


def is_bookable_day(d: date) -> bool:
    """Lumi does not book home visits on Sundays."""
    return d.weekday() != SUNDAY_WEEKDAY


def bookable_days_window(today: date) -> list[date]:
    """Next N bookable days after today, skipping Sundays."""
    days: list[date] = []
    cursor = today
    while len(days) < BOOKABLE_WINDOW_SIZE:
        cursor += timedelta(days=1)
        if is_bookable_day(cursor):
            days.append(cursor)
    return days


def resolve_window_day(today: date, window_index: int) -> date:
    """Map window position 1–3 ('tomorrow', etc.) to a concrete date."""
    window = bookable_days_window(today)
    if window_index < 1 or window_index > len(window):
        raise ValueError(f"window_index {window_index} out of range")
    return window[window_index - 1]


def scheduling_window_index(today: date, target: date) -> int | None:
    """1-based window position for target, or None if outside the window."""
    try:
        return bookable_days_window(today).index(target) + 1
    except ValueError:
        return None


def next_bookable_day_in_window(today: date, target: date) -> date | None:
    window = bookable_days_window(today)
    try:
        idx = window.index(target)
    except ValueError:
        return None
    if idx + 1 < len(window):
        return window[idx + 1]
    return None


def scheduling_call_dynamic_vars() -> dict[str, str]:
    """Weekday names for the 3-day bookable window — pass to ElevenLabs at call start."""
    today = today_in_business_tz()
    window = bookable_days_window(today)
    calendar_tomorrow = today + timedelta(days=1)
    # First scheduling ask says "tomorrow" when that day is bookable; else weekday (e.g. Monday after Saturday).
    if is_bookable_day(calendar_tomorrow) and window[0] == calendar_tomorrow:
        day_1_speech = "tomorrow"
    else:
        day_1_speech = window[0].strftime("%A")
    return {
        "sched_day_1": window[0].strftime("%A"),
        "sched_day_1_speech": day_1_speech,
        "sched_day_2": window[1].strftime("%A"),
        "sched_day_3": window[2].strftime("%A"),
    }
