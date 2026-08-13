"""Slot-time parsing, ranking, and date verification.

Both providers need to turn a restaurant's available-time buttons into the best
match for the user's desired time, restricted to a ± window. This replaces the
original bot's hardcoded ranked list of times with proximity ranking around a
single desired time.

The date helpers exist because a booking site's date picker can silently fail to
take effect, leaving the page showing another date's availability — so providers
read the date back off the page and compare it here before booking anything.
"""
import re
from datetime import time

# "7:15 PM", "7 PM", "11:00am"
_AMPM_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([APap][Mm])\b")
# 24-hour "19:00"
_24H_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# "Dec. 25", "December 25, 2026", "Sat, Dec 25"
_MONTH_DAY_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
    re.IGNORECASE,
)
# "2026-12-25"
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


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


def find_dates(text):
    """Return every (month, day) pair mentioned in `text`.

    Deliberately ignores the year: the surfaces we read back (a "Dec. 25" picker
    button, a widget's booking summary) usually omit it, and month+day is enough
    to catch a picker that landed on the wrong day.
    """
    if not text:
        return []
    found = [
        (int(m.group(2)), int(m.group(3)))
        for m in _ISO_RE.finditer(text)
    ]
    found += [
        (_MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        for m in _MONTH_DAY_RE.finditer(text)
    ]
    return found


def date_verdict(text, target):
    """Compare a page's rendered date text against a target `datetime.date`.

    Returns "match" (the target date is named), "mismatch" (dates are named and
    none of them is the target), or "unknown" (no date found — the caller should
    log loudly but not treat it as proof of a wrong date).
    """
    dates = find_dates(text)
    if not dates:
        return "unknown"
    return "match" if (target.month, target.day) in dates else "mismatch"


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
