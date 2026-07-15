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
  <title>Reservation Bot</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: -apple-system, system-ui, sans-serif; margin: 0; background: #f5f5f7; color: #1d1d1f; }
    .wrap { max-width: 1050px; margin: 0 auto; padding: 24px 18px 60px; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .sub { color: #6e6e73; margin: 0 0 24px; font-size: 13px; }
    .card { background: #fff; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 22px; }
    label { display: block; font-size: 12px; font-weight: 600; margin: 10px 0 4px; }
    input, select { width: 100%; padding: 8px 10px; border: 1px solid #d2d2d7; border-radius: 8px; font-size: 14px; box-sizing: border-box; background: #fff; }
    .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px 16px; }
    .check { display: flex; align-items: center; gap: 8px; margin-top: 16px; }
    .check input { width: auto; }
    button { background: #0071e3; color: #fff; border: 0; border-radius: 20px; padding: 9px 20px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 16px; }
    button.secondary { background: #e8e8ed; color: #1d1d1f; padding: 5px 12px; margin: 0; font-size: 12px; }
    button.danger { background: #ffe5e5; color: #c00; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; vertical-align: top; }
    th { font-size: 11px; text-transform: uppercase; color: #6e6e73; letter-spacing: .04em; }
    .tag { display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 11px; font-weight: 600; }
    .pending { background: #fff3cd; color: #856404; }
    .booked { background: #d4edda; color: #155724; }
    .failed, .expired { background: #f8d7da; color: #721c24; }
    .cancelled { background: #e2e3e5; color: #383d41; }
    .muted { color: #6e6e73; font-size: 12px; }
    .actions { display: flex; gap: 6px; }
    form.inline { margin: 0; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>🍽️ Reservation Bot</h1>
  <p class="sub">Queue a Resy or OpenTable booking. The poller starts at your <b>start time</b> (or immediately if blank),
     retries every <b>retry interval</b> hours, books any slot within <b>± window</b> of your time, and stops
     2 days before the reservation unless you check <b>run until reservation</b>.</p>

  <div class="card">
    <form method="post" action="{{ url_for('add') }}">
      <div class="grid">
        <div>
          <label>Platform</label>
          <select name="platform">
            <option value="resy">Resy</option>
            <option value="opentable">OpenTable</option>
          </select>
        </div>
        <div><label>Restaurant name</label><input name="restaurant_name" required placeholder="The Duck Inn"></div>
        <div><label>Guests</label><input name="guests" type="number" min="1" value="2" required></div>
      </div>
      <label>Restaurant URL</label>
      <input name="restaurant_url" required placeholder="https://resy.com/cities/chicago-il/venues/the-duck-inn">
      <div class="grid">
        <div><label>Date</label><input name="date" type="date" required></div>
        <div><label>Desired time</label><input name="desired_time" required placeholder="7:00 PM" value="7:00 PM"></div>
        <div><label>± Window (hours)</label><input name="window_hours" type="number" step="0.25" min="0" value="2"></div>
      </div>
      <div class="grid">
        <div><label>Start trying at (optional)</label><input name="start_time" type="datetime-local"></div>
        <div><label>Retry interval (hours)</label><input name="retry_interval_hours" type="number" step="0.25" min="0.05" value="2"></div>
        <div class="check">
          <input type="checkbox" id="rur" name="run_until_reservation" value="1">
          <label for="rur" style="margin:0;">Run until reservation<br><span class="muted">(else stop 2 days before)</span></label>
        </div>
      </div>
      <button type="submit">Add request</button>
    </form>
  </div>

  <div class="card">
    <table>
      <thead>
        <tr>
          <th>Restaurant</th><th>When</th><th>Party</th><th>Status</th>
          <th>Attempts</th><th>Next attempt</th><th>Stops</th><th></th>
        </tr>
      </thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td>
            <b>{{ r.req.restaurant_name }}</b><br>
            <span class="muted">{{ r.req.platform }} · ±{{ r.req.window_hours }}h</span>
            {% if r.req.last_error %}<br><span class="muted">last: {{ r.req.last_error[:70] }}</span>{% endif %}
          </td>
          <td>{{ r.req.date }}<br><span class="muted">{{ r.req.desired_time }}</span>
              {% if r.req.booked_slot %}<br><b>booked {{ r.req.booked_slot }}</b>{% endif %}</td>
          <td>{{ r.req.guests }}</td>
          <td><span class="tag {{ r.req.status }}">{{ r.req.status }}</span></td>
          <td>{{ r.req.attempts }}</td>
          <td class="muted">{{ r.next_attempt if r.req.status == 'pending' else '—' }}</td>
          <td class="muted">{{ r.deadline }}</td>
          <td class="actions">
            {% if r.req.status == 'pending' %}
              <form class="inline" method="post" action="{{ url_for('attempt', request_id=r.req.id) }}">
                <button class="secondary" type="submit">Try now</button>
              </form>
              <form class="inline" method="post" action="{{ url_for('cancel', request_id=r.req.id) }}">
                <button class="secondary" type="submit">Cancel</button>
              </form>
            {% endif %}
            <form class="inline" method="post" action="{{ url_for('delete', request_id=r.req.id) }}">
              <button class="secondary danger" type="submit">Delete</button>
            </form>
          </td>
        </tr>
      {% else %}
        <tr><td colspan="8" class="muted">No requests yet. Add one above.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
</body>
</html>
"""


def _fmt(dt):
    return dt.strftime("%b %-d, %-I:%M %p")


@app.route("/")
def index():
    now = datetime.now()
    rows = []
    for req in store.list_all():
        rows.append(
            {
                "req": req,
                "next_attempt": _fmt(timing.next_attempt_at(req, now)),
                "deadline": _fmt(timing.deadline(req)),
            }
        )
    return render_template_string(TEMPLATE, rows=rows)


@app.route("/add", methods=["POST"])
def add():
    f = request.form
    try:
        req = new_request(
            platform=f.get("platform"),
            restaurant_name=f.get("restaurant_name"),
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
    print(f"Reservation Bot UI → http://{config.WEB_HOST}:{config.WEB_PORT}")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)


if __name__ == "__main__":
    main()
