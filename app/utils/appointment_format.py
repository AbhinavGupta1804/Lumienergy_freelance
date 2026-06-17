"""Human-readable appointment labels for SMS (Arizona / business timezone)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def format_appointment_label(start_iso: str) -> str:
    """
  e.g. "Saturday, June 20 at 8 AM" in business_timezone.
    """
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
    return f"{weekday}, {month_day} at {time_part}"
