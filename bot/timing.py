"""Pure scheduling math shared by the poller and the web UI.

No Selenium imports here, so the web app can compute "next attempt" / "deadline"
labels cheaply. All functions take/return naive local datetimes.
"""
from datetime import datetime, timedelta

from . import config, matching


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def reservation_datetime(request):
    """The actual dining moment: request date + desired time (defaults to 19:00)."""
    day = datetime.strptime(request["date"], "%Y-%m-%d")
    t = matching.parse_time(request.get("desired_time", ""))
    if t is None:
        return day.replace(hour=19, minute=0)
    return day.replace(hour=t.hour, minute=t.minute)


def deadline(request):
    """When the poller gives up.

    Default: stop 2 days before the reservation. If run_until_reservation is set,
    keep going right up to the reservation time.
    """
    reservation = reservation_datetime(request)
    if request.get("run_until_reservation"):
        return reservation
    return reservation - timedelta(days=config.DEFAULT_STOP_BEFORE_DAYS)


def next_attempt_at(request, now=None):
    """Earliest time the next attempt is allowed."""
    now = now or datetime.now()
    last = _parse_dt(request.get("last_attempt"))
    interval = timedelta(hours=float(request.get("retry_interval_hours", config.DEFAULT_RETRY_INTERVAL_HOURS)))

    if last is not None:
        return last + interval
    start = _parse_dt(request.get("start_time"))
    if start is not None:
        return start
    # No start time and never attempted → try right away.
    return now


def is_due(request, now=None):
    """True if this pending request should be attempted at `now`."""
    if request.get("status") != "pending":
        return False
    now = now or datetime.now()
    if now >= deadline(request):
        return False
    return now >= next_attempt_at(request, now)


def is_past_deadline(request, now=None):
    now = now or datetime.now()
    return now >= deadline(request)
