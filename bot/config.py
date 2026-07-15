"""Central configuration and paths.

Credentials and tunables come from the .env file (loaded here once). Filesystem
paths are all anchored to the project root so the web app and the cron poller
agree on where the request store lives regardless of the working directory.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the directory that contains this package.
ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

# ------------------- Credentials -------------------
RESY_EMAIL = os.getenv("RESY_EMAIL")
RESY_PASSWORD = os.getenv("RESY_PASSWORD")

OPENTABLE_EMAIL = os.getenv("OPENTABLE_EMAIL")
OPENTABLE_PASSWORD = os.getenv("OPENTABLE_PASSWORD")

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

# ------------------- Paths -------------------
# The request store shared by the web UI and the poller.
STORE_PATH = Path(os.getenv("STORE_PATH", ROOT / "requests.json"))
LOCK_PATH = Path(str(STORE_PATH) + ".lock")

# Persistent Chrome profile keeps you logged in between runs and reduces
# bot-detection friction (especially on OpenTable).
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", ROOT / ".chrome-profile"))

# ------------------- Web app -------------------
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "5001"))

# ------------------- Behavior defaults -------------------
# How long before the reservation the poller gives up (unless the request opts
# into running all the way to the reservation time).
DEFAULT_STOP_BEFORE_DAYS = 2
DEFAULT_WINDOW_HOURS = 2.0
DEFAULT_RETRY_INTERVAL_HOURS = 2.0

# Whether Selenium runs headless. Booking flows are more reliable non-headless,
# so default to visible; override with HEADLESS=1 for the cron poller if desired.
HEADLESS = os.getenv("HEADLESS", "0") in ("1", "true", "True")


def missing_email_config():
    """Return a list of missing email-alert env vars (empty if all present)."""
    required = {
        "SENDER_EMAIL": SENDER_EMAIL,
        "SENDER_PASSWORD": SENDER_PASSWORD,
        "RECEIVER_EMAIL": RECEIVER_EMAIL,
    }
    return [name for name, value in required.items() if not value]
