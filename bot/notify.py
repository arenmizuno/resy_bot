"""Email alerts.

Extracted from the original resy_bot.send_alert so both the poller and the web
app can notify on success/failure. Failing to send an alert never raises into
the caller — a booking that succeeded shouldn't be reported as failed just
because Gmail was unreachable.
"""
import smtplib
from email.message import EmailMessage

from . import config


def send_alert(subject, body):
    """Send a plain-text email alert. Returns True on success, False otherwise."""
    missing = config.missing_email_config()
    if missing:
        print(f"[notify] Skipping email (missing config: {', '.join(missing)}).")
        return False

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = config.SENDER_EMAIL
    msg["To"] = config.RECEIVER_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
            smtp.send_message(msg)
        print(f"[notify] Sent: {subject}")
        return True
    except Exception as exc:  # noqa: BLE001 - never let alerting crash the bot
        print(f"[notify] Failed to send email: {exc}")
        return False
