# Resy Bot

Queue restaurant reservations from a small local web page, and let a cron-driven
poller book them automatically on **Resy** — whether the table is already open
(grab it now / catch cancellations) or drops in the future.

**Resy only.** OpenTable is not supported; see
[Limitations](#limitations) for why.

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

# Gmail alerts (use a Gmail App Password: https://myaccount.google.com/apppasswords)
SENDER_EMAIL=your_gmail_email
SENDER_PASSWORD=your_16_character_app_password
RECEIVER_EMAIL=recipient_email_for_alerts

# Optional
# HEADLESS=1                 # run Chrome headless in the poller
# USE_UNDETECTED=1           # route Chrome through undetected-chromedriver
# WEB_PORT=5001
```

`.env`, `requests.json`, and the Chrome profile are gitignored.

> **First run:** launch the poller (or the CLI) once so Chrome logs into Resy
> using your credentials. The login is saved in the persistent Chrome profile
> (`.chrome-profile/`), so later runs skip login and are less likely to hit a
> CAPTCHA.

---

## Usage

### Manage requests (web UI)

```bash
python -m bot.web
```

Open **http://127.0.0.1:5001**, fill in the form (restaurant URL, date, guests,
desired time, window, optional start time, retry interval,
run-until-reservation), and click **Add request**. From the table you can
**Try now**, **Cancel**, or **Delete** any request.

**Restaurant name is optional and is only a label** — it appears in the table,
the logs, and the alert email's subject, and never touches the booking itself.
The **URL** is what identifies the restaurant. Leave the name blank and it's
inferred from the URL slug (`.../venues/the-duck-inn` → "The Duck Inn"); fill it
in only when you want a tidier label.

When a booking succeeds, the alert email links to **the reservation** — the
confirmation page if the provider redirected to one, otherwise your account's
reservations page — plus the confirmation number when one is on the page. The
same link shows up as *view reservation* in the table.

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

## Limitations

### OpenTable is not supported

Support was written and then removed, because it could not be made to work
reliably. Two independent blockers, either one sufficient:

**The browser is blocked before any booking logic runs.** OpenTable sits behind
Akamai bot management, which fingerprints the *browser*, not the IP. The same
machine that loads opentable.com fine in ordinary Chrome gets a bare
`Access Denied` page in a Selenium-driven one, so every attempt failed at the
first page load. The usual mitigations — stripping automation flags, a real user
agent, undetected-chromedriver, a hand-warmed Chrome profile — are an arms race
against a vendor whose job is to win it, and the failure mode is silent and
sudden.

**Sign-in can't be automated even when the page loads.** OpenTable's login is
two-step: you submit an email, and only then does it decide between showing a
password field and emailing you a one-time code. A bot cannot read that code.
Guest booking sidesteps the account but still requires clearing the same bot
wall, and it can't see or manage reservations afterward.

Resy has neither problem: it accepts Selenium, and it takes an email/password
login that persists in the Chrome profile. If you want OpenTable reservations,
book them by hand.

### Other caveats

- **CAPTCHA** on login can still appear; the persistent Chrome profile minimizes
  re-logins. If a run hits one, the poller emails you and retries next cycle.
- **Payment info** must already be saved on your Resy account — the bot confirms
  with whatever card is on file.

---

## What the bot verifies before claiming success

Both of these exist because earlier versions reported bookings that hadn't
happened, or had happened on the wrong day. The rule now is that nothing is
reported as booked unless Resy says so.

- **The date is checked twice.** Resy's date picker can silently fail to take,
  leaving the page showing another day's availability — which is how the bot
  once booked the wrong date. The date now goes through the URL (`?date=&seats=`),
  is read back off the date selector, and is checked again in the booking summary
  immediately before confirming. A contradiction aborts the attempt.
- **The booking is confirmed against Resy's own response.** The old flow clicked
  "Reserve Now", slept, and declared victory — so an attempt that stalled on a
  confirmation modal, or that Resy rejected, was still emailed to you as booked.
  There are now four outcomes:

  | What Resy does | Result |
  | --- | --- |
  | Shows a confirmation, even briefly | **Booked** |
  | Leaves checkout or closes, with no error | **Booked (unconfirmed)** — Resy dismisses the widget once a reservation is placed, so this is a real booking; the email flags it for a glance |
  | Shows an error (table gone, card needed) | Not booked, retries next cycle, no email |
  | Sits on the checkout screen saying nothing | Not booked, emails you what the widget showed |

  Getting this right took three passes, because the widget is a moving target.
  It is torn down on success, which leaves the bot reading the venue page
  underneath; and the confirmation can flash by in under a second before being
  replaced by another screen. So the widget is sampled several times a second
  and judged on the **whole transcript** rather than whatever is on screen when
  the clock runs out. Every distinct screen is printed to the log, so a run that
  still gets it wrong can be diagnosed from `cron.log`.

If Resy's markup changes, the worst case is a run that refuses to book and tells
you — not one that books the wrong thing or lies about it.
