"""Backwards-compatible CLI for a single one-off Resy booking.

The bot's logic now lives in the `bot/` package. This wrapper preserves the old
command-line interface so existing cron lines / muscle memory keep working:

    python resy_bot.py --restaurant-name "The Duck Inn" \
        --restaurant-url "https://resy.com/.../the-duck-inn" \
        --date 2026-04-28 --guests 4 --time "7:00 PM" --window-hours 2

For queuing multiple requests and OpenTable support, use the web UI instead:
    python -m bot.web         # add/manage requests
    python -m bot.poller      # run one poll cycle (schedule via cron)
"""
import argparse

from bot import notify
from bot.providers import ResyProvider


def parse_args():
    parser = argparse.ArgumentParser(description="Book a single Resy reservation now.")
    parser.add_argument("--restaurant-url", required=True, help="Full Resy restaurant URL")
    parser.add_argument("--restaurant-name", required=True, help="Restaurant name for alerts")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--guests", type=int, required=True, help="Number of guests")
    parser.add_argument("--time", dest="desired_time", default="7:00 PM", help="Desired time, e.g. '7:00 PM'")
    parser.add_argument("--window-hours", type=float, default=2.0, help="± window around desired time")
    # Accept the legacy --times list too; first entry becomes the desired time.
    parser.add_argument("--times", nargs="+", help="(legacy) list of times; first is used as desired time")
    return parser.parse_args()


def main():
    args = parse_args()
    desired_time = args.times[0] if args.times else args.desired_time

    request = {
        "platform": "resy",
        "restaurant_url": args.restaurant_url,
        "restaurant_name": args.restaurant_name,
        "date": args.date,
        "guests": args.guests,
        "desired_time": desired_time,
        "window_hours": args.window_hours,
    }

    result = ResyProvider().book(request)
    if result.success:
        print(f"Booked {args.restaurant_name} at {result.slot} on {args.date}.")
        notify.send_alert(
            f"✅ Booked — {args.restaurant_name}",
            f"Reserved {args.restaurant_name} for {args.guests} at {result.slot} on {args.date}.\n"
            f"URL: {args.restaurant_url}",
        )
    else:
        print(f"Not booked: {result.error}")
        notify.send_alert(f"⚠️ Resy booking failed — {args.restaurant_name}", result.error or "Unknown error")


if __name__ == "__main__":
    main()
