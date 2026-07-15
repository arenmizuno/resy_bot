"""JSON-backed request store shared by the web UI and the cron poller.

Both processes read-modify-write the same file, so every mutation happens under
an exclusive file lock (fcntl) to avoid clobbering. Requests are plain dicts;
see `new_request` for the schema.
"""
import fcntl
import json
import uuid
from contextlib import contextmanager
from datetime import datetime

from . import config

VALID_PLATFORMS = ("resy", "opentable")
VALID_STATUSES = ("pending", "booked", "failed", "expired", "cancelled")


@contextmanager
def _locked():
    """Hold an exclusive lock for the duration of a read-modify-write."""
    config.LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _read():
    if not config.STORE_PATH.exists():
        return []
    try:
        with open(config.STORE_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(requests):
    config.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.STORE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(requests, fh, indent=2)
    tmp.replace(config.STORE_PATH)


def new_request(
    platform,
    restaurant_name,
    restaurant_url,
    date,
    guests,
    desired_time,
    window_hours=config.DEFAULT_WINDOW_HOURS,
    start_time=None,
    retry_interval_hours=config.DEFAULT_RETRY_INTERVAL_HOURS,
    run_until_reservation=False,
):
    """Build a request dict with defaults, a fresh id, and a created_at stamp.

    Raises ValueError on invalid platform/date so bad input is rejected at the
    web layer rather than surfacing later in the poller.
    """
    platform = (platform or "").strip().lower()
    if platform not in VALID_PLATFORMS:
        raise ValueError(f"platform must be one of {VALID_PLATFORMS}")

    # Validate date format early.
    datetime.strptime(date, "%Y-%m-%d")

    return {
        "id": uuid.uuid4().hex,
        "platform": platform,
        "restaurant_name": restaurant_name.strip(),
        "restaurant_url": restaurant_url.strip(),
        "date": date,
        "guests": int(guests),
        "desired_time": desired_time.strip(),
        "window_hours": float(window_hours),
        "start_time": start_time or None,
        "retry_interval_hours": float(retry_interval_hours),
        "run_until_reservation": bool(run_until_reservation),
        "status": "pending",
        "attempts": 0,
        "last_attempt": None,
        "last_error": None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def list_all():
    """Return all requests (newest first)."""
    with _locked():
        requests = _read()
    return sorted(requests, key=lambda r: r.get("created_at", ""), reverse=True)


def add(request):
    with _locked():
        requests = _read()
        requests.append(request)
        _write(requests)
    return request


def get(request_id):
    with _locked():
        for req in _read():
            if req.get("id") == request_id:
                return req
    return None


def update(request_id, **fields):
    """Merge `fields` into the request with the given id. Returns updated dict."""
    with _locked():
        requests = _read()
        updated = None
        for req in requests:
            if req.get("id") == request_id:
                req.update(fields)
                updated = req
                break
        if updated is not None:
            _write(requests)
    return updated


def cancel(request_id):
    return update(request_id, status="cancelled")


def delete(request_id):
    with _locked():
        requests = _read()
        remaining = [r for r in requests if r.get("id") != request_id]
        _write(remaining)
    return len(remaining) != len(requests)
