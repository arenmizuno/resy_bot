# Reservation Bot (Resy + OpenTable)

Queue restaurant reservations from a small local web page, and let a cron-driven
poller book them automatically on **Resy** or **OpenTable** — whether the table
is already open (grab it now / catch cancellations) or drops in the future.

For each request you set:

- **Start time** *(optional)* — when to begin trying. Blank = start immediately.
- **Retry interval** — how often to re-attempt (default every 2 hours), so it keeps
  trying to catch cancellations.
- **± Window** — book any open slot within this many hours of your desired time
  (e.g. desired 7:00 PM, window 2h → anything 5:00–9:00 PM).
- **Run until reservation** — by default the bot **stops trying 2 days before**
  the reservation; check this to keep trying right up to the reservation time.

---

## How it works

```
bot/
  config.py        env + paths + defaults
  store.py         JSON request store (file-locked) shared by web + poller
  timing.py        when to attempt / when to give up (pure datetime math)
  matching.py      parse slot times, pick closest within ± window
  driver.py        shared Selenium Chrome (persistent profile)
  notify.py        email alerts
  providers/
    base.py        BookingProvider interface
    resy.py        Resy flow
    opentable.py   OpenTable flow
  web.py           local web UI (add/view/cancel/try-now)
  poller.py        cron entrypoint — attempts all due requests
resy_bot.py        legacy one-off CLI (still works)
requests.json      your queued requests (gitignored)
```

The **web UI** and the **poller** both read/write `requests.json`. You add
requests in the browser; cron runs the poller every minute; the poller attempts
only the requests that are due (start time reached, retry interval elapsed, and
before the give-up deadline).

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

You also need Google Chrome installed (Selenium 4 auto-manages the driver).

### 2. Configure `.env`

```env
# Resy login
RESY_EMAIL=your_resy_login_email
RESY_PASSWORD=your_resy_password

# OpenTable login
OPENTABLE_EMAIL=your_opentable_email
OPENTABLE_PASSWORD=your_opentable_password

# Gmail alerts (use a Gmail App Password: https://myaccount.google.com/apppasswords)
SENDER_EMAIL=your_gmail_email
SENDER_PASSWORD=your_16_character_app_password
RECEIVER_EMAIL=recipient_email_for_alerts

# Optional
# HEADLESS=1                 # run Chrome headless in the poller
# WEB_PORT=5001
```

`.env`, `requests.json`, and the Chrome profile are gitignored.

> **First run:** launch the poller (or the CLI) once so Chrome logs into Resy /
> OpenTable using your credentials. The login is saved in the persistent Chrome
> profile (`.chrome-profile/`), so later runs skip login and are less likely to
> hit a CAPTCHA.

---

## Usage

### Manage requests (web UI)

```bash
python -m bot.web
```

Open **http://127.0.0.1:5001**, fill in the form (platform, restaurant name +
URL, date, guests, desired time, window, optional start time, retry interval,
run-until-reservation), and click **Add request**. From the table you can
**Try now**, **Cancel**, or **Delete** any request.

### Run the poller

The poller does one pass and exits — it's meant to be run on a schedule:

```bash
python -m bot.poller            # attempt all due requests
python -m bot.poller --id <id>  # force one request now, ignoring cadence
```

### Legacy one-off CLI (Resy only)

```bash
python resy_bot.py \
  --restaurant-name "The Duck Inn" \
  --restaurant-url "https://resy.com/cities/chicago-il/venues/the-duck-inn" \
  --date 2026-04-28 --guests 4 --time "7:00 PM" --window-hours 2
```

---

## Scheduling with cron

**Run the poller every minute.** A frequent cron makes the bot react quickly when
a start time passes or a table opens; the per-request 2-hour retry cadence is
enforced inside the poller, so a fast cron does *not* over-attempt any request.

> Why not a 2-hour cron? It can only act on 2-hour boundaries — enough to miss a
> reservation drop by up to ~2 hours and too coarse to catch fast cancellations.

Add the job (this appends without wiping other crontab entries):

```bash
( crontab -l 2>/dev/null; \
  echo "* * * * * cd /Users/aren/Desktop/resy-bot && /opt/anaconda3/bin/python -m bot.poller >> /Users/aren/Desktop/resy-bot/cron.log 2>&1" ) | crontab -
```

Check it: `crontab -l` · Watch it: `tail -f cron.log` · Remove it:
`crontab -l | grep -v "bot.poller" | crontab -`

> On macOS the process running `cron` needs Full Disk / Automation permissions to
> launch Chrome. If the poller can't open Chrome from cron, run
> `python -m bot.poller` once in Terminal and grant the prompt.

---

## Notes & caveats

- **OpenTable** has stronger bot detection and its page markup changes often. The
  flow lives entirely in `bot/providers/opentable.py` with verbose logging and
  fallback selectors, so it's easy to re-tune. If plain Selenium gets blocked,
  `pip install undetected-chromedriver` and swap it into `bot/driver.make_driver`.
- **CAPTCHA** on login can still appear; the persistent Chrome profile minimizes
  re-logins. If a run hits one, the poller emails you and retries next cycle.
- **Payment info** must already be saved on your Resy / OpenTable account — the
  bot confirms with whatever card is on file.
