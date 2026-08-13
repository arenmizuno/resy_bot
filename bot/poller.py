"""Cron entrypoint: attempt every due reservation request, once per invocation.

Run this frequently (every minute is recommended); the per-request retry cadence
and start-time gating live in `timing`, so a frequent cron just makes the bot
responsive without over-attempting any single request.

    python -m bot.poller            # process all due requests
    python -m bot.poller --id <id>  # force one request now (ignores cadence)
"""
import argparse
from datetime import datetime

from . import store, notify, timing
from .providers import get_provider


def _attempt(request):
    """Run one booking attempt and persist the outcome. Returns the result."""
    rid = request["id"]
    label = f"{request['platform']}:{request['restaurant_name']} {request['date']} {request['desired_time']}"
    print(f"[poller] Attempting {label} (attempt #{request.get('attempts', 0) + 1})")

    try:
        provider = get_provider(request["platform"])
    except ValueError:
        # e.g. an OpenTable request queued before that platform was removed.
        # Retire it rather than crashing every later request in the cycle.
        store.update(rid, status="cancelled", last_error=f"Unsupported platform: {request['platform']}")
        print(f"[poller] Cancelled {rid} — unsupported platform {request['platform']!r}")
        return None

    result = provider.book(request)

    now = datetime.now().isoformat(timespec="seconds")
    if result.success:
        store.update(
            rid,
            status="booked",
            last_attempt=now,
            last_error=None,
            attempts=request.get("attempts", 0) + 1,
            booked_slot=result.slot,
            confirmation_url=result.confirmation_url,
            confirmation_code=result.confirmation_code,
            verified=result.verified,
        )
        body = (
            f"Reserved {request['restaurant_name']} ({request['platform']}) for "
            f"{request['guests']} at {result.slot} on {request['date']}.\n"
        )
        if result.confirmation_code:
            body += f"Confirmation: {result.confirmation_code}\n"
        # Link to the reservation itself, not the restaurant's listing page.
        body += f"Your reservation: {result.confirmation_url}\n"
        if not result.verified:
            body += (
                "\nNote: Resy closed its booking widget without printing a "
                "confirmation, which is what it does once a reservation is "
                "placed — but it was not confirmed in words. Worth a glance at "
                "your Resy account.\n"
            )
        subject = "✅ Booked" if result.verified else "✅ Booked (unconfirmed)"
        notify.send_alert(f"{subject} — {request['restaurant_name']}", body)
        print(f"[poller] BOOKED {label} at {result.slot}")
    else:
        store.update(
            rid,
            last_attempt=now,
            last_error=result.error,
            attempts=request.get("attempts", 0) + 1,
        )
        # Only email on hard failures, not routine "nothing available yet".
        if not result.no_availability:
            notify.send_alert(
                f"⚠️ Booking attempt failed — {request['restaurant_name']}",
                f"{request['platform']} attempt for {request['restaurant_name']} on "
                f"{request['date']} failed:\n{result.error}\nWill retry per schedule.",
            )
        print(f"[poller] Not booked ({'no availability' if result.no_availability else 'error'}): {result.error}")
    return result


def _expire(request):
    store.update(request["id"], status="expired")
    notify.send_alert(
        f"⏰ Stopped trying — {request['restaurant_name']}",
        f"Gave up on {request['restaurant_name']} ({request['platform']}) for "
        f"{request['date']} at {request['desired_time']}: reached the cutoff "
        f"({'reservation time' if request.get('run_until_reservation') else '2 days before'}).",
    )
    print(f"[poller] Expired {request['id']} ({request['restaurant_name']})")


def run_once(force_id=None):
    now = datetime.now()
    requests = store.list_all()
    pending = [r for r in requests if r.get("status") == "pending"]

    if force_id:
        target = next((r for r in requests if r["id"] == force_id), None)
        if target is None:
            print(f"[poller] No request with id {force_id}")
            return
        print(f"[poller] Forcing attempt for {force_id} (ignoring cadence).")
        _attempt(target)
        return

    if not pending:
        print("[poller] No pending requests.")
        return

    print(f"[poller] {len(pending)} pending request(s) at {now.isoformat(timespec='seconds')}")
    for request in pending:
        if timing.is_past_deadline(request, now):
            _expire(request)
        elif timing.is_due(request, now):
            _attempt(request)
        else:
            when = timing.next_attempt_at(request, now)
            print(f"[poller] Skipping {request['restaurant_name']} — next attempt at {when.isoformat(timespec='minutes')}")


def main():
    parser = argparse.ArgumentParser(description="Run one poll cycle over queued booking requests.")
    parser.add_argument("--id", dest="force_id", help="Force one attempt for this request id, ignoring cadence.")
    args = parser.parse_args()
    run_once(force_id=args.force_id)


if __name__ == "__main__":
    main()
