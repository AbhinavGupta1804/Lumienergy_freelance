"""Human-readable appointment labels for SMS (Arizona / business timezone)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

# Cloud Tasks rejects a schedule more than 30 days out. Stay inside that window.
_CLOUD_TASKS_HORIZON = timedelta(days=29)
_MIN_SCHEDULE_LEAD = timedelta(seconds=30)


def format_appointment_label(start_iso: str) -> str:
    """
    e.g. "Saturday, June 20 at 8 AM" in business_timezone.
    """
    date_part, time_part = format_appointment_parts(start_iso)
    return f"{date_part} at {time_part}"


def parse_appointment_datetime(start_value: str) -> datetime:
    """Parse a Zoho or Cal.com start value into an aware datetime."""
    text = (start_value or "").strip()
    if not text or text.lower() == "null":
        raise ValueError("missing appointment start")
    settings = get_settings()
    tz = ZoneInfo(settings.business_timezone)
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        for fmt in (
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %I:%M:%S %p",
            "%d-%b-%Y %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise ValueError(f"unrecognized appointment start: {text}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def format_booked_appointment(start_value: str) -> tuple[str, str]:
    """Parse a Zoho or Cal.com start value and return (date, time) in business TZ."""
    dt = parse_appointment_datetime(start_value)
    return format_appointment_parts(dt.isoformat())


def plan_reminder(start: datetime, now: datetime, delta: timedelta) -> tuple[str, datetime | None]:
    """
    Decide whether a reminder at ``start - delta`` can be scheduled.

    Returns (status, when). status is schedule, too_soon, or too_far.
    too_soon covers a booking made inside the reminder window — that text is skipped.
    """
    when = start - delta
    if when <= now + _MIN_SCHEDULE_LEAD:
        return "too_soon", None
    if when > now + _CLOUD_TASKS_HORIZON:
        return "too_far", None
    return "schedule", when


def format_appointment_parts(start_iso: str) -> tuple[str, str]:
    """Return (date, time) e.g. ('Saturday, June 20', '8 AM')."""
    settings = get_settings()
    tz = ZoneInfo(settings.business_timezone)
    dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    local = dt.astimezone(tz)
    weekday = local.strftime("%A")
    month_day = f"{local.strftime('%B')} {local.day}"
    hour = local.strftime("%I").lstrip("0") or "12"
    minute = local.minute
    suffix = local.strftime("%p")
    if minute == 0:
        time_part = f"{hour} {suffix}"
    else:
        time_part = f"{hour}:{minute:02d} {suffix}"
    return f"{weekday}, {month_day}", time_part
