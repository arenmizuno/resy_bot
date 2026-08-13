# Resy Bot

Queues Resy reservations and books them automatically when a table opens.

## Problem

I use Beli constantly and I am always working through a list of restaurants I want to
try. The hard part is never picking the place, it is getting the table. Reservations
drop at a fixed time weeks ahead, sell out in seconds, and the only other way in is
catching a cancellation at a random hour.

Doing that by hand means setting alarms and refreshing Resy all day. This bot does it
instead. I queue the restaurant, date, time and party size once, and a poller keeps
trying on a schedule until it books or gives up.

## Repo Structure

```
resy-bot/
├── bot/
│   ├── config.py         # env vars, paths, defaults
│   ├── store.py          # JSON request store, file-locked, shared by web + poller
│   ├── timing.py         # when to attempt, when to give up
│   ├── matching.py       # parse slot times and dates, pick closest within window
│   ├── driver.py         # Selenium Chrome setup, persistent profile
│   ├── notify.py         # Gmail alerts
│   ├── web.py            # local web UI to add and manage requests
│   ├── poller.py         # cron entrypoint, attempts every due request
│   └── providers/
│       ├── base.py       # provider interface and BookingResult
│       └── resy.py       # the Resy booking flow
├── resy_bot.py           # one-off CLI for a single booking
└── requirements.txt
```

The web UI and the poller share `requests.json`, so anything added in the browser is
picked up by the next cron run.

## Tech Stack

Python 3.11, Selenium 4 driving real Chrome, Flask for the local UI, python-dotenv for
config, and smtplib for Gmail alerts. Scheduling is plain cron. No database, the queue
is a JSON file.

## Setup

```bash
pip install -r requirements.txt
```

You also need Google Chrome installed. Selenium 4 manages the driver itself.

Create `.env` in the project root:

```env
RESY_EMAIL=your_resy_login_email
RESY_PASSWORD=your_resy_password

# Gmail alerts, use an app password: https://myaccount.google.com/apppasswords
SENDER_EMAIL=your_gmail_email
SENDER_PASSWORD=your_16_character_app_password
RECEIVER_EMAIL=where_alerts_should_go

# Optional
# HEADLESS=1          # run Chrome headless in the poller
# USE_UNDETECTED=1    # route through undetected-chromedriver if Resy blocks Selenium
# WEB_PORT=5001
```

Run the poller once by hand first so Chrome logs in and saves the session to
`.chrome-profile/`. Later runs reuse it and skip the login. That folder, `.env` and
`requests.json` are all gitignored.

## Usage

Start the UI, add a request, and let cron do the rest.

```bash
python -m bot.web
```

Open http://127.0.0.1:5001 and paste the restaurant URL, date, time, party size, and
how far off your desired time you will accept. Restaurant name is optional, it is only
a label and is filled in from the URL if you leave it blank.

Then run the poller on a schedule. It does one pass and exits, so run it every minute
and let the per-request retry interval control the actual pace.

```bash
( crontab -l 2>/dev/null; \
  echo "* * * * * cd /Users/aren/Desktop/resy-bot && /opt/anaconda3/bin/python -m bot.poller >> /Users/aren/Desktop/resy-bot/cron.log 2>&1" ) | crontab -
```

To force one request immediately, or to book a single table without the queue:

```bash
python -m bot.poller --id <request_id>
python resy_bot.py --restaurant-url "https://resy.com/cities/new-york-ny/venues/the-tyger" \
  --date 2026-08-26 --guests 2 --time "7:00 PM" --window-hours 2
```

You get an email when a booking lands, and when an attempt fails for a real reason.
Routine "nothing available yet" attempts stay quiet.

## Future Steps

- Text or push alerts instead of just email
- Retry pacing that tightens as the reservation date gets close
- A dry-run mode that reports what it would book without booking it
- Tests around the date and confirmation logic, which is where the real bugs have been

## Limitations

Resy only. OpenTable support was written and removed because it could not be made to
work. OpenTable sits behind Akamai bot management that blocks the automated browser
before any booking logic runs, and its login can fall back to a one-time emailed code
that a bot cannot read. Resy has neither problem.

It assumes a payment card is already on file with Resy, since it confirms with whatever
is saved. It needs a machine that is awake with Chrome installed, so it is a laptop or
home server tool, not something that runs in the cloud as written. A CAPTCHA can still
appear on login, which the persistent Chrome profile mostly avoids but cannot rule out.
On macOS, cron needs Full Disk or Automation permission to launch Chrome, so run the
poller once in Terminal and grant the prompt before trusting the schedule.

Everything depends on Resy's page markup, so a redesign will break it. That is why the
bot is careful about what counts as success. After clicking Reserve Now:

| What Resy does | Result |
| --- | --- |
| Shows a confirmation, even briefly | Booked |
| Leaves checkout or closes with no error | Booked, flagged unconfirmed in the email |
| Shows an error, table gone or card needed | Not booked, retries next cycle, no email |
| Sits on the checkout screen | Not booked, emails you what the widget showed |

The unconfirmed case is normal, not a bug. Resy tears the widget down the moment a
reservation is placed, so there is often nothing left to read. It books, and the email
tells you to glance at your account.
