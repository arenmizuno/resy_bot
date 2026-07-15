"""Slot-time parsing and ranking.

Both providers need to turn a restaurant's available-time buttons into the best
match for the user's desired time, restricted to a ± window. This replaces the
original bot's hardcoded ranked list of times with proximity ranking around a
single desired time.
"""
import re
from datetime import time

# "7:15 PM", "7 PM", "11:00am"
_AMPM_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([APap][Mm])\b")
# 24-hour "19:00"
_24H_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def parse_time(text):
    """Extract the first clock time from `text` as a datetime.time, or None."""
    if not text:
        return None
    m = _AMPM_RE.search(text)
    if m:
        hour = int(m.group(1)) % 12
        minute = int(m.group(2) or 0)
        if m.group(3).lower() == "pm":
            hour += 12
        return time(hour, minute)
    m = _24H_RE.search(text)
    if m:
        return time(int(m.group(1)), int(m.group(2)))
    return None


def _minutes(t):
    return t.hour * 60 + t.minute


def diff_minutes(a, b):
    """Absolute difference between two times, in minutes."""
    return abs(_minutes(a) - _minutes(b))


def rank(items, desired_time, window_hours, label=lambda x: x):
    """Return `items` whose parsed time is within ±window of desired, closest first.

    `label` maps an item to the text to parse (default: the item itself), so a
    provider can pass a list of (element, text) tuples or raw strings.
    """
    desired = parse_time(desired_time) if isinstance(desired_time, str) else desired_time
    if desired is None:
        # Can't rank without a target — hand items back untouched.
        return list(items)

    window_min = float(window_hours) * 60.0
    scored = []
    for item in items:
        t = parse_time(label(item))
        if t is None:
            continue
        delta = diff_minutes(t, desired)
        if delta <= window_min:
            scored.append((delta, item))
    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored]
