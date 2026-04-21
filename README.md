# Resy Reservation Bot

## Overview

This project is an automated reservation bot for Resy. It logs into a user account, navigates to a restaurant page, selects a date, number of guests, and preferred times, and attempts to book a reservation. If successful (or if an error occurs), the bot sends an email notification.

I built this because I enjoy trying new restaurants and optimizing the process of getting reservations. I am active on Beli (username: **zuno**), and this project was a way to combine that interest with automation and practical engineering.

---

## Setup Instructions

### 1. Install Requirements

```bash
pip install -r requirements.txt
```

---

### 2. Generate a Gmail App Password

1. Go to: https://myaccount.google.com/apppasswords  
2. Generate a new App Password  
3. Copy the 16-character password  

---

### 3. Create and Configure `.env` File

```bash
touch .env
open -a TextEdit .env
```

Add:

```env
RESY_EMAIL=your_resy_login_email
RESY_PASSWORD=your_resy_password

SENDER_EMAIL=your_gmail_email
SENDER_PASSWORD=your_16_character_app_password

RECEIVER_EMAIL=recipient_email_for_alerts
```

Do not commit this file. Add `.env` to `.gitignore`.

---

## Scheduling a One-Time Run with cron

### Cron Format

```
MINUTE HOUR DAY MONTH DAY_OF_WEEK
```

| Field | Meaning | Example |
|------|--------|--------|
| MINUTE | 0–59 | 57 |
| HOUR | 0–23 | 11 (11 AM) |
| DAY | 1–31 | 21 |
| MONTH | 1–12 | 4 (April) |
| DAY_OF_WEEK | 0–7 (`*` = any) | * |

---

### Example Schedule

```
57 11 21 4 *
```

Runs at:

**11:57 AM on April 21**

---

### Full Cron Command (with All Parameters)

```bash
echo '57 11 21 4 * cd /Users/aren/Desktop/resy-bot && /opt/anaconda3/bin/python resy_bot.py \
--restaurant-name "The Duck Inn" \
--restaurant-url "https://resy.com/cities/chicago-il/venues/the-duck-inn" \
--date 2026-04-28 \
--guests 4 \
--times "7:00 PM" "7:15 PM" "6:45 PM" \
>> /Users/aren/Desktop/resy-bot/cron.log 2>&1 ; \
crontab -l | grep -v "resy_bot.py" | crontab -' | crontab -
```

---

### Explanation of the Cron Command

- `57 11 21 4 *` → Run at 11:57 AM on April 21  
- `cd /Users/aren/Desktop/resy-bot` → Navigate to project directory  
- `/opt/anaconda3/bin/python` → Full Python path (required for cron)  
- `resy_bot.py` → Script to run  

#### Script Arguments:
- `--restaurant-name` → Used in email alerts  
- `--restaurant-url` → Restaurant page to book  
- `--date` → Reservation date  
- `--guests` → Number of guests  
- `--times` → Preferred reservation times in order  

#### Logging:
- `>> cron.log 2>&1` → Saves output and errors to `cron.log`

#### Cleanup:
- `crontab -l | grep -v "resy_bot.py" | crontab -`  
  → Removes the job after it runs once

---

### Important Notes

- Your computer must be **awake** at runtime  
- Cron runs jobs within the specified minute (not exact to the second)  
- Use full paths (Python + project directory)  

---

## Project Structure

- `resy_bot.py` – main automation script  
- `.env` – credentials (not committed)  
- `requirements.txt` – dependencies  
- `cron.log` – runtime logs  

---

## Skills and Concepts Demonstrated

- Web automation using Selenium  
- Handling dynamic front-end behavior (React modals, delays)  
- XPath and CSS selector design  
- Reliable browser interaction (scrolling, waits, fallbacks)  
- Environment variable management  
- Email automation via SMTP  
- CLI design with argparse  
- Task scheduling with cron  
- Debugging timing-sensitive workflows  

---
