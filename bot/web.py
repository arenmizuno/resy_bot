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
      color-scheme: light dark;

      --bg-page: #f5f5f7;
      --bg-card: rgba(255, 255, 255, 0.8);
      --bg-inset: #ffffff;
      --bg-hover: rgba(0, 0, 0, 0.03);
      --text-primary: #1d1d1f;
      /* Apple's own #86868b / #0071e3 measure 3.3:1 and 4.3:1 on this
         background — under WCAG AA for text. Nudged darker to clear 4.5:1
         while keeping the same character. */
      --text-secondary: #6e6e73;
      --accent-text: #0066cc;
      --accent-fill: #0071e3;
      --accent: #0071e3;
      --accent-contrast: #ffffff;
      --hairline: rgba(0, 0, 0, 0.08);
      --field-border: rgba(0, 0, 0, 0.16);
      --shadow-card: 0 4px 24px rgba(0, 0, 0, 0.06);

      --tag-pending-bg: #fff4e5;   --tag-pending-fg: #8a5300;
      --tag-booked-bg:  #e4f7e9;   --tag-booked-fg:  #14713a;
      --tag-bad-bg:     #fdeaea;   --tag-bad-fg:     #b42318;
      --tag-off-bg:     #eeeef0;   --tag-off-fg:     #66666b;

      --space-xs: 4px;  --space-sm: 8px;  --space-md: 16px;
      --space-lg: 24px; --space-xl: 48px;

      --radius-card: 18px;
      --radius-field: 12px;
      --ease: cubic-bezier(0.25, 0.1, 0.25, 1);
    }

    @media (prefers-color-scheme: dark) {
      :root {
        --bg-page: #000000;
        --bg-card: rgba(29, 29, 31, 0.72);
        --bg-inset: #1d1d1f;
        --bg-hover: rgba(255, 255, 255, 0.04);
        --text-primary: #f5f5f7;
        --text-secondary: #98989d;
        --accent-text: #4da2ff;
        /* White on #0a84ff is only 3.65:1; the fill is darkened so the primary
           button's label clears AA. The ring/checkbox keep the brighter blue. */
        --accent-fill: #0f6fdd;
        --accent: #0a84ff;
        --hairline: rgba(255, 255, 255, 0.12);
        --field-border: rgba(255, 255, 255, 0.2);
        --shadow-card: 0 4px 24px rgba(0, 0, 0, 0.5);

        --tag-pending-bg: rgba(255, 159, 10, 0.16); --tag-pending-fg: #ffb340;
        --tag-booked-bg:  rgba(48, 209, 88, 0.16);  --tag-booked-fg:  #30d158;
        --tag-bad-bg:     rgba(255, 69, 58, 0.16);  --tag-bad-fg:     #ff6961;
        --tag-off-bg:     rgba(255, 255, 255, 0.1); --tag-off-fg:     #98989d;
      }
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg-page);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
      font: 400 17px/1.5 -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
      -webkit-font-smoothing: antialiased;
    }

    .wrap {
      max-width: 980px;
      margin: 0 auto;
      padding: var(--space-xl) var(--space-lg) 96px;
      animation: fadeUp 0.5s var(--ease) both;
    }

    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(20px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      * { animation: none !important; transition: none !important; }
    }

    header { margin-bottom: var(--space-xl); }
    h1 { font: 600 32px/1.2 inherit; letter-spacing: -0.02em; margin: 0 0 var(--space-sm); }
    .lede { font-size: 17px; color: var(--text-secondary); margin: 0; max-width: 620px; }

    .card {
      background: var(--bg-card);
      -webkit-backdrop-filter: blur(20px);
      backdrop-filter: blur(20px);
      border: 1px solid var(--hairline);
      border-radius: var(--radius-card);
      box-shadow: var(--shadow-card);
      padding: var(--space-lg);
      margin-bottom: var(--space-lg);
    }
    .card + .card { margin-top: var(--space-lg); }

    h2 {
      font: 600 13px/1.4 inherit;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-secondary);
      margin: 0 0 var(--space-md);
    }

    /* ---------- form ---------- */
    .field { margin-bottom: var(--space-md); }
    .field:last-of-type { margin-bottom: 0; }
    label {
      display: block;
      font: 600 13px/1.4 inherit;
      margin-bottom: 6px;
    }
    label .hint { font-weight: 400; color: var(--text-secondary); }

    input, select {
      width: 100%;
      min-height: 44px;
      padding: 0 14px;
      font: 400 17px/1.4 inherit;
      color: var(--text-primary);
      background: var(--bg-inset);
      border: 1px solid var(--field-border);
      border-radius: var(--radius-field);
      transition: border-color 0.2s var(--ease), box-shadow 0.2s var(--ease);
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent);
    }
    input::placeholder { color: var(--text-secondary); }

    .row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: var(--space-md);
    }
    @media (max-width: 700px) { .row { grid-template-columns: 1fr; } }

    /* A 20px checkbox is well under the 44px touch target, so the whole row is
       the label — click anywhere on it to toggle. */
    .switch {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 44px;
      margin: 0;
      font-weight: 400;
      cursor: pointer;
    }
    .switch input { width: 20px; height: 20px; min-height: 0; accent-color: var(--accent); cursor: pointer; }

    .actions-bar {
      display: flex;
      justify-content: flex-end;
      margin-top: var(--space-lg);
      padding-top: var(--space-lg);
      border-top: 1px solid var(--hairline);
    }

    /* ---------- buttons ---------- */
    button {
      font: 500 15px/1 inherit;
      border: 0;
      border-radius: 980px;
      cursor: pointer;
      min-height: 44px;
      padding: 0 24px;
      white-space: nowrap;
      transition: transform 0.2s var(--ease), filter 0.2s var(--ease), background 0.2s var(--ease);
    }
    button:active { transform: scale(0.98); }
    button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }

    .btn-primary { background: var(--accent-fill); color: var(--accent-contrast); }
    .btn-primary:hover { transform: scale(1.02); filter: brightness(1.08); }

    .btn-quiet {
      background: transparent;
      color: var(--accent-text);
      padding: 0 12px;
      min-height: 44px;
    }
    .btn-quiet:hover { background: var(--bg-hover); }
    .btn-quiet.danger { color: var(--tag-bad-fg); }

    /* ---------- table ---------- */
    .table-scroll { overflow-x: auto; margin: 0 calc(-1 * var(--space-lg)); padding: 0 var(--space-lg); }
    table { width: 100%; border-collapse: collapse; }
    th {
      font: 600 11px/1.4 inherit;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-secondary);
      text-align: left;
      padding: 0 var(--space-md) var(--space-sm) 0;
      white-space: nowrap;
    }
    td {
      padding: var(--space-md) var(--space-md) var(--space-md) 0;
      border-top: 1px solid var(--hairline);
      vertical-align: top;
      font-size: 15px;
    }
    tbody tr { transition: background 0.2s var(--ease); }
    tbody tr:hover { background: var(--bg-hover); }
    td:last-child, th:last-child { padding-right: 0; text-align: right; }

    .name { font-weight: 600; }
    .meta { font-size: 13px; color: var(--text-secondary); line-height: 1.4; }
    .meta.err { color: var(--tag-bad-fg); }
    .booked-slot { font-weight: 600; }
    a { color: var(--accent-text); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .tag {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 980px;
      font: 600 12px/1.3 inherit;
      white-space: nowrap;
    }
    .tag.pending   { background: var(--tag-pending-bg); color: var(--tag-pending-fg); }
    .tag.booked    { background: var(--tag-booked-bg);  color: var(--tag-booked-fg); }
    .tag.failed,
    .tag.expired   { background: var(--tag-bad-bg);     color: var(--tag-bad-fg); }
    .tag.cancelled { background: var(--tag-off-bg);     color: var(--tag-off-fg); }

    .row-actions { display: flex; gap: var(--space-xs); justify-content: flex-end; }
    form.inline { margin: 0; }

    .empty { padding: var(--space-xl) 0; text-align: center; color: var(--text-secondary); }
  </style>
</head>
<body>
<div class="wrap">

  <header>
    <h1>Resy Bot</h1>
    <p class="lede">
      Queue a table and the poller keeps trying — from your start time, every retry interval,
      booking anything within your window. It stops two days out unless you tell it not to.
    </p>
  </header>

  <form class="card" method="post" action="{{ url_for('add') }}">
    <h2>New request</h2>

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

  <div class="card">
    <h2>Queue</h2>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Restaurant</th>
            <th>Reservation</th>
            <th>Party</th>
            <th>Status</th>
            <th>Schedule</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
        {% for r in rows %}
          <tr>
            <td>
              <div class="name">{{ r.req.restaurant_name }}</div>
              <div class="meta">±{{ r.window }}h · every {{ r.interval }}h</div>
              {% if r.req.last_error %}<div class="meta err">{{ r.req.last_error[:90] }}</div>{% endif %}
            </td>
            <td>
              {{ r.date_label }}
              <div class="meta">{{ r.req.desired_time }}</div>
              {% if r.req.booked_slot %}
                <div class="booked-slot">Booked {{ r.req.booked_slot }}</div>
                {% if r.req.verified is false %}<div class="meta">Unconfirmed — check Resy</div>{% endif %}
                {% if r.req.confirmation_url %}
                  <div class="meta"><a href="{{ r.req.confirmation_url }}" target="_blank" rel="noopener">View reservation</a></div>
                {% endif %}
              {% endif %}
            </td>
            <td>{{ r.req.guests }}</td>
            <td>
              <span class="tag {{ r.req.status }}">{{ r.req.status }}</span>
              <div class="meta">{{ r.req.attempts }} attempt{{ '' if r.req.attempts == 1 else 's' }}</div>
            </td>
            <td class="meta">
              {% if r.req.status == 'pending' %}
                Next {{ r.next_attempt }}<br>Stops {{ r.deadline }}
              {% elif r.last_attempt %}
                Tried {{ r.last_attempt }}
              {% else %}
                &mdash;
              {% endif %}
            </td>
            <td>
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
                "next_attempt": _fmt(timing.next_attempt_at(req, now)),
                "deadline": _fmt(timing.deadline(req)),
                "last_attempt": _fmt(datetime.fromisoformat(last)) if last else None,
            }
        )
    return render_template_string(TEMPLATE, rows=rows)


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
