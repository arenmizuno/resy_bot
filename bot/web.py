"""Local web UI for managing booking requests.

    python -m bot.web

Then open http://127.0.0.1:5001 to add / view / cancel requests. The cron poller
reads the same store, so anything added here is picked up automatically.
"""
import threading
from datetime import datetime

from flask import Flask, redirect, render_template_string, request, url_for

from . import config, store, timing
from .store import new_request

app = Flask(__name__)

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Resy Bot</title>
  <style>
    :root {
      /* OLED-first palette. There is no light variant on purpose — the whole
         look depends on true black, and a washed-out light mode would read as
         a different product. */
      color-scheme: dark;

      --bg:        #000000;
      --surface:   #0c0d0f;
      --surface-2: #15171a;
      --surface-3: #1e2126;
      --line:      rgba(255, 255, 255, 0.09);
      --line-firm: rgba(255, 255, 255, 0.18);

      /* Against the card surface: text 20:1, dim 7.5:1, faint 4.9:1 — the two
         greys are as dark as they can go and still clear AA for body text. */
      --text:      #ffffff;
      --text-dim:  #9ba1a8;
      --text-faint:#7a8087;

      /* Accents are nudged off the source hues so each clears 4.5:1 on black
         as text — the stock signal red is only 4:1. */
      --go:     #00f19f;
      --go-ink: #00110a;
      --wait:   #ffde00;
      --stop:   #ff3b4e;
      --idle:   #7a8087;

      --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
      --space-4: 16px; --space-5: 24px; --space-6: 32px;

      --radius:  10px;
      --radius-sm: 6px;
      --ease: cubic-bezier(0.2, 0.8, 0.3, 1);

      /* The `font` shorthand has no valid `inherit` family keyword — writing one
         invalidates the whole declaration — so every shorthand names this. */
      --sans: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
      --mono: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, monospace;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 400 14px/1.5 var(--sans);
      -webkit-font-smoothing: antialiased;
      font-variant-numeric: tabular-nums;
    }

    /* The one typographic move the whole layout leans on: micro labels in
       heavy uppercase with wide tracking, data in mono underneath. */
    .label {
      font: 700 10px/1.4 var(--sans);
      text-transform: uppercase;
      letter-spacing: 0.16em;
      color: var(--text-faint);
    }

    .wrap { max-width: 1080px; margin: 0 auto; padding: 0 var(--space-5) 96px; }

    @keyframes rise {
      from { opacity: 0; transform: translateY(12px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes breathe { 50% { opacity: 0.25; } }
    @media (prefers-reduced-motion: reduce) {
      * { animation: none !important; transition: none !important; }
    }

    /* ---------- top bar ---------- */
    .topbar {
      position: sticky; top: 0; z-index: 40;
      display: flex; align-items: center; gap: var(--space-3);
      height: 56px;
      padding: 0 var(--space-5);
      /* Opaque rather than blurred — the page behind it is already pure black,
         so a backdrop-filter buys nothing and costs a compositing layer. */
      background: var(--bg);
      border-bottom: 1px solid var(--line);
    }
    .topbar-inner {
      display: flex; align-items: center; gap: var(--space-3);
      width: 100%; max-width: 1080px; margin: 0 auto;
    }
    .mark {
      font: 800 13px/1 var(--sans);
      text-transform: uppercase;
      letter-spacing: 0.22em;
    }
    .pulse {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--idle); flex: none;
    }
    .pulse.live { background: var(--go); animation: breathe 2.4s ease-in-out infinite; }
    .topbar .label { margin-left: auto; }

    /* ---------- page head ---------- */
    header { padding: var(--space-6) 0 var(--space-5); }
    h1 {
      font: 800 34px/1.05 var(--sans);
      letter-spacing: -0.03em;
      margin: var(--space-2) 0 var(--space-3);
    }
    .lede { font-size: 14px; color: var(--text-dim); margin: 0; max-width: 60ch; }

    /* ---------- panels ---------- */
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-5);
      margin-bottom: var(--space-5);
      animation: rise 0.4s var(--ease) 0.06s both;
    }
    .panel-head {
      display: flex; align-items: baseline; gap: var(--space-3);
      margin-bottom: var(--space-4);
      padding-bottom: var(--space-3);
      border-bottom: 1px solid var(--line);
    }
    h2 { font: 700 12px/1.4 var(--sans); text-transform: uppercase; letter-spacing: 0.16em; margin: 0; }
    .count { font: 700 11px/1 var(--mono); color: var(--text-faint); margin-left: auto; }

    /* ---------- form ---------- */
    .field { margin-bottom: var(--space-4); }
    label { display: block; margin-bottom: 6px; }
    .field > label {
      font: 700 10px/1.4 var(--sans);
      text-transform: uppercase;
      letter-spacing: 0.16em;
      color: var(--text-dim);
    }
    .field > label .hint { color: var(--text-faint); letter-spacing: 0.1em; }

    input, select {
      width: 100%;
      min-height: 44px;
      padding: 0 12px;
      font: 400 15px/1.4 var(--sans);
      color: var(--text);
      background: var(--surface-2);
      border: 1px solid var(--line-firm);
      border-radius: var(--radius-sm);
      transition: border-color 0.18s var(--ease), background 0.18s var(--ease);
    }
    /* Under 16px iOS zooms the page on focus. */
    @media (max-width: 760px) { input, select { font-size: 16px; } }
    input:hover, select:hover { border-color: rgba(255, 255, 255, 0.3); }
    input:focus, select:focus {
      outline: 2px solid var(--go);
      outline-offset: 2px;
      border-color: var(--go);
      background: var(--surface-3);
    }
    input::placeholder { color: var(--text-faint); }
    input[type="date"], input[type="datetime-local"] { font-family: var(--mono); font-size: 14px; }

    .row { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-4); margin-bottom: var(--space-4); }
    /* The grid gap already spaces these; leaving the field margin on would
       double it once the columns stack. */
    .row > .field { margin-bottom: 0; }
    @media (max-width: 760px) { .row { grid-template-columns: 1fr; } }

    /* A 20px checkbox is well under the 44px touch target, so the whole row is
       the label — click anywhere on it to toggle. */
    .switch {
      display: flex; align-items: center; gap: 10px;
      min-height: 44px; margin: 0;
      align-self: end;
      font: 600 13px/1.3 var(--sans);
      cursor: pointer;
    }
    .switch input { width: 20px; height: 20px; min-height: 0; accent-color: var(--go); cursor: pointer; }

    .actions-bar {
      display: flex; justify-content: flex-end;
      margin-top: var(--space-5); padding-top: var(--space-4);
      border-top: 1px solid var(--line);
    }

    /* ---------- buttons ---------- */
    button {
      font: 700 11px/1 var(--sans);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      border: 1px solid transparent;
      border-radius: var(--radius-sm);
      cursor: pointer;
      min-height: 40px;
      padding: 0 18px;
      white-space: nowrap;
      transition: background 0.18s var(--ease), color 0.18s var(--ease),
                  border-color 0.18s var(--ease), transform 0.12s var(--ease);
    }
    @media (max-width: 760px) { button { min-height: 44px; } }
    button:active { transform: scale(0.97); }
    button:focus-visible { outline: 2px solid var(--go); outline-offset: 2px; }

    .btn-primary { background: var(--go); color: var(--go-ink); padding: 0 28px; }
    .btn-primary:hover { background: #4dffc0; }

    .btn-quiet {
      background: transparent;
      color: var(--text-dim);
      border-color: var(--line-firm);
      padding: 0 12px;
    }
    .btn-quiet:hover { background: var(--surface-3); color: var(--text); border-color: var(--line-firm); }
    .btn-quiet.danger { color: var(--stop); }
    .btn-quiet.danger:hover { background: rgba(255, 59, 78, 0.12); border-color: var(--stop); }

    /* ---------- queue ---------- */
    .table-scroll { overflow-x: auto; margin: 0 calc(-1 * var(--space-5)); padding: 0 var(--space-5); }
    table { width: 100%; border-collapse: collapse; }
    th {
      font: 700 10px/1.4 var(--sans);
      text-transform: uppercase;
      letter-spacing: 0.16em;
      color: var(--text-faint);
      text-align: left;
      padding: 0 var(--space-4) var(--space-3) 0;
      white-space: nowrap;
    }
    td {
      padding: var(--space-3) var(--space-4) var(--space-3) 0;
      border-top: 1px solid var(--line);
      vertical-align: top;
    }
    tbody tr { transition: background 0.18s var(--ease); }
    tbody tr:hover { background: var(--surface-2); }
    /* Status reads twice: as a colored edge for scanning and as a labelled
       chip for anyone who can't use the color. */
    tbody tr td:first-child { box-shadow: inset 3px 0 0 var(--edge, transparent); padding-left: var(--space-3); }
    tr.pending   { --edge: var(--wait); }
    tr.booked    { --edge: var(--go); }
    tr.failed,
    tr.expired   { --edge: var(--stop); }
    tr.cancelled { --edge: var(--idle); }
    td:last-child, th:last-child { padding-right: 0; text-align: right; }
    /* Enough room that dates, booked slots and countdowns never wrap; the
       wrapper scrolls horizontally before any of them break. */
    th:nth-child(1) { min-width: 170px; }
    th:nth-child(2) { min-width: 132px; }
    th:nth-child(5) { min-width: 150px; }

    .name { font: 700 15px/1.3 var(--sans); letter-spacing: -0.01em; }
    .meta { font-size: 12px; color: var(--text-dim); line-height: 1.5; }
    .meta.err { color: var(--stop); }
    .mono { font-family: var(--mono); font-size: 13px; }
    .date { font: 600 14px/1.3 var(--mono); }
    .booked-slot { font: 700 13px/1.4 var(--sans); color: var(--go); margin-top: 2px; white-space: nowrap; }
    .guests { font: 700 16px/1.2 var(--mono); }
    a { color: var(--go); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .sched { display: grid; grid-template-columns: auto auto; gap: 3px var(--space-2); align-items: baseline; justify-content: start; }
    .sched .label { font-size: 9px; }
    .sched .v { font: 600 12px/1.4 var(--mono); color: var(--text-dim); white-space: nowrap; }
    .sched .v.now { color: var(--wait); }

    .tag {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 9px 4px 7px;
      border-radius: 999px;
      border: 1px solid currentColor;
      font: 700 10px/1.3 var(--sans);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      white-space: nowrap;
    }
    .tag::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .tag.pending   { color: var(--wait); }
    .tag.booked    { color: var(--go); }
    .tag.failed,
    .tag.expired   { color: var(--stop); }
    .tag.cancelled { color: var(--idle); }

    .row-actions { display: flex; gap: var(--space-2); justify-content: flex-end; }
    form.inline { margin: 0; }

    .empty { padding: var(--space-6) 0; text-align: center; color: var(--text-faint); }

    /* Below 760px the grid collapses to stacked cards — a 6-column table can't
       stay readable at 375px, and each row carries its own header labels. */
    @media (max-width: 760px) {
      h1 { font-size: 28px; }

      .table-scroll { overflow-x: visible; }
      thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
      table, tbody, tr, td { display: block; width: 100%; }
      tbody tr {
        border: 1px solid var(--line);
        border-left: 3px solid var(--edge, var(--line));
        border-radius: var(--radius-sm);
        padding: var(--space-3);
        margin-bottom: var(--space-3);
      }
      tbody tr td:first-child { box-shadow: none; padding-left: 0; }
      td { border-top: 0; padding: var(--space-2) 0; }
      td + td { border-top: 1px solid var(--line); }
      td::before {
        content: attr(data-label);
        display: block;
        font: 700 9px/1.4 var(--sans);
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: var(--text-faint);
        margin-bottom: 4px;
      }
      td:last-child { text-align: left; }
      td:last-child::before { content: none; }
      .row-actions { justify-content: flex-start; flex-wrap: wrap; }
    }
  </style>
</head>
<body>

<div class="topbar">
  <div class="topbar-inner">
    <span class="pulse {{ 'live' if pending else '' }}" aria-hidden="true"></span>
    <span class="mark">Resy Bot</span>
    <span class="label">{{ 'Polling' if pending else 'Idle' }}</span>
  </div>
</div>

<div class="wrap">

  <header>
    <span class="label">Reservation engine</span>
    <h1>Resy Bot</h1>
    <p class="lede">
      Queue a table and the poller keeps trying — from your start time, every retry interval,
      booking anything within your window. It stops two days out unless you tell it not to.
    </p>
  </header>

  <form class="panel" method="post" action="{{ url_for('add') }}">
    <div class="panel-head"><h2>New request</h2></div>

    <div class="field">
      <label for="restaurant_url">Restaurant URL</label>
      <input id="restaurant_url" name="restaurant_url" required
             placeholder="https://resy.com/cities/new-york-ny/venues/the-tyger">
    </div>

    <div class="row">
      <div class="field">
        <label for="date">Date</label>
        <input id="date" name="date" type="date" required>
      </div>
      <div class="field">
        <label for="desired_time">Time</label>
        <input id="desired_time" name="desired_time" required placeholder="7:00 PM" value="7:00 PM">
      </div>
      <div class="field">
        <label for="guests">Guests</label>
        <input id="guests" name="guests" type="number" min="1" value="2" required>
      </div>
    </div>

    <div class="row">
      <div class="field">
        <label for="window_hours">Window <span class="hint">± hours</span></label>
        <input id="window_hours" name="window_hours" type="number" step="0.25" min="0" value="2">
      </div>
      <div class="field">
        <label for="retry_interval_hours">Retry every <span class="hint">hours</span></label>
        <input id="retry_interval_hours" name="retry_interval_hours" type="number" step="0.25" min="0.05" value="2">
      </div>
      <div class="field">
        <label for="start_time">Start trying <span class="hint">optional</span></label>
        <input id="start_time" name="start_time" type="datetime-local">
      </div>
    </div>

    <div class="row">
      <div class="field">
        <label for="restaurant_name">Name <span class="hint">label only, optional</span></label>
        <input id="restaurant_name" name="restaurant_name" placeholder="From the URL">
      </div>
      <label class="field switch" for="rur">
        <input type="checkbox" id="rur" name="run_until_reservation" value="1">
        Run until reservation
      </label>
    </div>

    <div class="actions-bar">
      <button class="btn-primary" type="submit">Add request</button>
    </div>
  </form>

  <div class="panel">
    <div class="panel-head">
      <h2>Queue</h2>
      <span class="count">{{ total }} total</span>
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Restaurant</th>
            <th>Reservation</th>
            <th>Party</th>
            <th>Status</th>
            <th>Schedule</th>
            <th><span class="label">Actions</span></th>
          </tr>
        </thead>
        <tbody>
        {% for r in rows %}
          <tr class="{{ r.req.status }}">
            <td data-label="Restaurant">
              <div class="name">{{ r.req.restaurant_name }}</div>
              <div class="meta mono">±{{ r.window }}h · every {{ r.interval }}h</div>
              {% if r.req.last_error %}<div class="meta err">{{ r.req.last_error[:90] }}</div>{% endif %}
            </td>
            <td data-label="Reservation">
              <div class="date">{{ r.date_label }}</div>
              <div class="meta mono">{{ r.req.desired_time }}</div>
              {% if r.req.booked_slot %}
                <div class="booked-slot">Booked {{ r.req.booked_slot }}</div>
                {% if r.req.verified is false %}<div class="meta">Unconfirmed — check Resy</div>{% endif %}
                {% if r.req.confirmation_url %}
                  <div class="meta"><a href="{{ r.req.confirmation_url }}" target="_blank" rel="noopener">View reservation</a></div>
                {% endif %}
              {% endif %}
            </td>
            <td data-label="Party"><span class="guests">{{ r.req.guests }}</span></td>
            <td data-label="Status">
              <span class="tag {{ r.req.status }}">{{ r.req.status }}</span>
              <div class="meta mono">{{ r.req.attempts }} attempt{{ '' if r.req.attempts == 1 else 's' }}</div>
            </td>
            <td data-label="Schedule">
              {% if r.req.status == 'pending' %}
                <div class="sched">
                  <span class="label">Next</span>
                  <span class="v {{ 'now' if r.next_in == 'Due now' else '' }}">{{ r.next_in }}</span>
                  <span class="label">Stops</span>
                  <span class="v">{{ r.deadline }}</span>
                </div>
              {% elif r.last_attempt %}
                <div class="sched">
                  <span class="label">Tried</span>
                  <span class="v">{{ r.last_attempt }}</span>
                </div>
              {% else %}
                <span class="meta">&mdash;</span>
              {% endif %}
            </td>
            <td data-label="Actions">
              <div class="row-actions">
                {% if r.req.status == 'pending' %}
                  <form class="inline" method="post" action="{{ url_for('attempt', request_id=r.req.id) }}">
                    <button class="btn-quiet" type="submit">Try now</button>
                  </form>
                  <form class="inline" method="post" action="{{ url_for('cancel', request_id=r.req.id) }}">
                    <button class="btn-quiet" type="submit">Cancel</button>
                  </form>
                {% endif %}
                <form class="inline" method="post" action="{{ url_for('delete', request_id=r.req.id) }}"
                      onsubmit="return confirm('Delete this request? This cannot be undone.');">
                  <button class="btn-quiet danger" type="submit">Delete</button>
                </form>
              </div>
            </td>
          </tr>
        {% else %}
          <tr><td colspan="6" class="empty">Nothing queued yet.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

</div>
</body>
</html>
"""


def _fmt(dt):
    return dt.strftime("%b %-d, %-I:%M %p")


def _fmt_date(iso):
    """2026-08-26 -> 'Wed, Aug 26'. Falls back to the raw value."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%a, %b %-d")
    except (ValueError, TypeError):
        return iso


def _num(value):
    """Drop a pointless trailing '.0' so the UI reads '2h', not '2.0h'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else round(number, 2)


def _countdown(dt, now):
    """A countdown reads better than a timestamp for something imminent:
    '14m', '3h 06m', '2d 4h'."""
    seconds = (dt - now).total_seconds()
    if seconds <= 0:
        return "Due now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


@app.route("/")
def index():
    now = datetime.now()
    rows = []
    for req in store.list_all():
        last = req.get("last_attempt")
        rows.append(
            {
                "req": req,
                "date_label": _fmt_date(req.get("date")),
                "window": _num(req.get("window_hours")),
                "interval": _num(req.get("retry_interval_hours")),
                "next_in": _countdown(timing.next_attempt_at(req, now), now),
                "deadline": _fmt(timing.deadline(req)),
                "last_attempt": _fmt(datetime.fromisoformat(last)) if last else None,
            }
        )

    return render_template_string(
        TEMPLATE,
        rows=rows,
        total=len(rows),
        pending=sum(1 for row in rows if row["req"].get("status") == "pending"),
    )


@app.route("/add", methods=["POST"])
def add():
    f = request.form
    try:
        req = new_request(
            platform="resy",
            restaurant_name=f.get("restaurant_name") or None,
            restaurant_url=f.get("restaurant_url"),
            date=f.get("date"),
            guests=f.get("guests"),
            desired_time=f.get("desired_time"),
            window_hours=f.get("window_hours") or config.DEFAULT_WINDOW_HOURS,
            start_time=f.get("start_time") or None,
            retry_interval_hours=f.get("retry_interval_hours") or config.DEFAULT_RETRY_INTERVAL_HOURS,
            run_until_reservation=bool(f.get("run_until_reservation")),
        )
    except (ValueError, TypeError) as exc:
        return f"Invalid request: {exc}", 400
    store.add(req)
    return redirect(url_for("index"))


@app.route("/cancel/<request_id>", methods=["POST"])
def cancel(request_id):
    store.cancel(request_id)
    return redirect(url_for("index"))


@app.route("/delete/<request_id>", methods=["POST"])
def delete(request_id):
    store.delete(request_id)
    return redirect(url_for("index"))


@app.route("/attempt/<request_id>", methods=["POST"])
def attempt(request_id):
    # Run the (slow, Selenium-driven) attempt in a background thread so the page
    # returns immediately. Imported here to keep Selenium out of the web import
    # path unless actually used.
    from . import poller

    threading.Thread(target=poller.run_once, kwargs={"force_id": request_id}, daemon=True).start()
    return redirect(url_for("index"))


def main():
    print(f"Resy Bot UI → http://{config.WEB_HOST}:{config.WEB_PORT}")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)


if __name__ == "__main__":
    main()
