"""Resy booking flow.

Refactored from the original resy_bot.run_resy_bot into a provider. Two
behavioral changes from that script:

* instead of a hardcoded ranked list of times, it collects the available slots
  and picks the closest one within the request's ± window (see matching.rank);

* **the date is set through the URL and then verified twice.** Resy venue pages
  accept `?date=YYYY-MM-DD&seats=N`, which avoids driving the calendar widget
  entirely. The calendar remains as a fallback, but a picker click that doesn't
  land leaves the page showing *another date's* availability, and the old code
  booked whatever it found there. So the date is read back off the page before a
  slot is chosen, and off the booking summary before the reservation is
  confirmed; a contradiction aborts the attempt instead of booking.
"""
import re
import time
from datetime import datetime
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from .. import config, driver as driver_mod, matching
from .base import BookingProvider, BookingResult

# Fallback link for the alert email when the confirmation view doesn't expose a
# direct reservation URL. This is Resy's signed-in reservations page; it 404s
# when signed out, so if Resy moves it, change it here.
RESERVATIONS_URL = "https://resy.com/account/upcoming"


class DateMismatch(RuntimeError):
    """The page is showing a different date than the one requested."""


class NotConfirmed(RuntimeError):
    """Resy never confirmed the reservation, so it must not be reported booked.

    `retryable` separates the two cases: Resy explicitly refusing (the table went
    while we were checking out) is routine and just retries on the next cycle,
    whereas an unreadable outcome is worth an email — the reservation may or may
    not exist, and only you can check.
    """

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class ResyProvider(BookingProvider):
    name = "resy"

    def book(self, request) -> BookingResult:
        url = request["restaurant_url"]
        name = request["restaurant_name"]
        target_date = request["date"]
        guests = int(request["guests"])
        desired_time = request["desired_time"]
        window_hours = float(request.get("window_hours", config.DEFAULT_WINDOW_HOURS))

        print(f"[resy] Booking {name} on {target_date} for {guests} near {desired_time} (±{window_hours}h)")

        wanted = datetime.strptime(target_date, "%Y-%m-%d").date()

        driver = driver_mod.make_driver()
        wait = WebDriverWait(driver, 20)
        try:
            self._login_if_needed(driver, wait)

            search_url = self._build_search_url(url, guests, target_date)
            print(f"[resy] Opening availability: {search_url}")
            driver.get(search_url)
            driver_mod.close_modal_if_present(driver, timeout=5)
            time.sleep(3)

            self._select_guests(wait, guests)
            # The URL params usually do it; fall back to the widgets if not.
            if not self._date_ok(driver, wanted):
                print("[resy] URL date didn't take — falling back to the calendar.")
                self._select_date(driver, wait, target_date)
            self._require_date(driver, wanted)

            slot = self._pick_slot(driver, wait, desired_time, window_hours)
            if slot is None:
                return BookingResult.unavailable(
                    f"No Resy slots within ±{window_hours}h of {desired_time}."
                )

            slot_element, slot_label = slot
            print(f"[resy] Selecting slot {slot_label}...")
            driver.execute_script("arguments[0].scrollIntoView(true);", slot_element)
            driver.execute_script("arguments[0].click();", slot_element)
            time.sleep(8)

            outcome = self._finalize(driver, wait, wanted)
            url, code = self._capture_confirmation(driver)
            return BookingResult.booked(
                slot_label,
                confirmation_url=url,
                confirmation_code=code,
                verified=(outcome == "confirmed"),
            )

        except DateMismatch as exc:
            # Never fall through into booking the wrong day.
            return BookingResult.failed(str(exc))
        except NotConfirmed as exc:
            if exc.retryable:
                return BookingResult.unavailable(str(exc))
            return BookingResult.failed(str(exc))
        except TimeoutException as exc:
            return BookingResult.failed(f"Resy timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return BookingResult.failed(f"Resy error: {exc}")
        finally:
            driver.quit()

    # ------------------- date handling -------------------
    @staticmethod
    def _build_search_url(restaurant_url, guests, target_date):
        """Append ?date=&seats= so Resy renders the right day's availability.

        Verified against a live venue page: these params drive both the date
        selector and the party-size select, which is far more reliable than
        clicking through the calendar.
        """
        parts = urlparse(restaurant_url)
        query = parse_qs(parts.query)
        query.update({"date": [target_date], "seats": [str(guests)]})
        new_query = urlencode({k: v[0] for k, v in query.items()})
        return urlunparse(parts._replace(query=new_query))

    @staticmethod
    def _date_button_text(driver):
        for by, selector in [
            (By.ID, "DropdownGroup__selector--date"),
            (By.CSS_SELECTOR, "[id*='selector--date']"),
        ]:
            try:
                text = driver.find_element(by, selector).text.strip()
                if text:
                    return text
            except WebDriverException:
                continue
        return ""

    def _date_ok(self, driver, wanted):
        """True when the date selector clearly shows the target date."""
        text = self._date_button_text(driver)
        verdict = matching.date_verdict(text, wanted)
        print(f"[resy] Date selector reads {text!r} -> {verdict}")
        return verdict == "match"

    def _require_date(self, driver, wanted):
        """Abort the attempt unless the page is showing the target date."""
        text = self._date_button_text(driver)
        verdict = matching.date_verdict(text, wanted)
        if verdict == "mismatch":
            raise DateMismatch(
                f"Resy is showing {text!r} but the request is for "
                f"{wanted.isoformat()} — aborting instead of booking the wrong date."
            )
        if verdict == "unknown":
            print(
                f"[resy] WARNING: could not read the date selector ({text!r}); "
                "relying on the booking-summary check before confirming."
            )
        else:
            print(f"[resy] Confirmed the page is on {wanted.isoformat()}.")

    # ------------------- steps -------------------
    def _login_if_needed(self, driver, wait):
        """Log in only if we're not already authenticated (persistent profile)."""
        driver.get("https://resy.com")
        driver_mod.close_modal_if_present(driver, timeout=5)

        try:
            login_btn = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[data-test-id='menu_container-button-log_in']")
                )
            )
        except TimeoutException:
            print("[resy] Already logged in (no login button).")
            return

        if not (config.RESY_EMAIL and config.RESY_PASSWORD):
            raise RuntimeError("RESY_EMAIL / RESY_PASSWORD not configured.")

        print("[resy] Logging in...")
        login_btn.click()
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "ReactModal__Content")))

        email_login_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Log in with email & password')]")
            )
        )
        driver.execute_script("arguments[0].click();", email_login_btn)

        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='email']"))).send_keys(
            config.RESY_EMAIL
        )
        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='password']"))).send_keys(
            config.RESY_PASSWORD
        )
        continue_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", continue_btn)
        continue_btn.click()
        print("[resy] Submitted credentials; waiting for redirect/CAPTCHA...")
        time.sleep(3)

    def _select_guests(self, wait, guests):
        dropdown = wait.until(EC.presence_of_element_located((By.ID, "party_size")))
        if dropdown.get_attribute("value") == str(guests):
            print(f"[resy] Party size already {guests}.")
            return
        print(f"[resy] Selecting {guests} guests...")
        Select(dropdown).select_by_value(str(guests))
        time.sleep(2)

    def _select_date(self, driver, wait, target_date):
        print("[resy] Selecting date...")
        parsed = datetime.strptime(target_date, "%Y-%m-%d")
        target_month_year = parsed.strftime("%B %Y")

        date_button = wait.until(
            EC.element_to_be_clickable((By.ID, "DropdownGroup__selector--date"))
        )
        driver.execute_script("arguments[0].click();", date_button)

        for _ in range(12):
            try:
                month_label = wait.until(
                    EC.visibility_of_element_located((By.CLASS_NAME, "CalendarMonth__Title"))
                )
                if month_label.text.strip() == target_month_year:
                    break
                next_button = wait.until(
                    EC.element_to_be_clickable((By.CLASS_NAME, "ResyCalendar__nav_right"))
                )
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(0.5)
            except TimeoutException:
                raise RuntimeError("Could not navigate Resy calendar.")
        else:
            raise RuntimeError(f"Could not reach month '{target_month_year}'.")

        # Live aria-label format is "Tuesday, September 1, 2026." — weekday, and
        # a trailing period. The selected day gets " Selected date." appended, so
        # match on the prefix rather than the whole string. The old code's
        # variants all missed the trailing period, which is why every run fell
        # through to a loose contains() match and could click the wrong day.
        prefix = parsed.strftime("%A, %B %-d, %Y.")
        labels = [
            prefix,
            parsed.strftime("%B %-d, %Y."),
            parsed.strftime("%A, %B %-d, %Y"),
            parsed.strftime("%B %-d, %Y"),
        ]
        button = None
        for label in labels:
            try:
                button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, f"//button[starts-with(@aria-label, '{label}')]")
                    )
                )
                print(f"[resy] Matched calendar day via {label!r}")
                break
            except TimeoutException:
                continue
        if button is None:
            # No substring-on-the-day fallback: contains(@aria-label,'2') also
            # matches the 12th, 20th–29th, and would happily book another day.
            raise DateMismatch(
                f"Could not find a calendar button for {parsed.strftime('%A, %B %-d, %Y')} "
                "(Resy's aria-label format may have changed)."
            )

        driver.execute_script("arguments[0].scrollIntoView(true);", button)
        driver.execute_script("arguments[0].click();", button)
        print(f"[resy] Clicked {parsed.strftime('%B %d, %Y')}")
        time.sleep(3)

    def _pick_slot(self, driver, wait, desired_time, window_hours):
        """Return (element, label) of the closest available slot within window."""
        try:
            slots = wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "button.ReservationButton.Button--primary")
                )
            )
        except TimeoutException:
            return None

        pairs = []
        for btn in slots:
            label_text = btn.get_attribute("innerText") or btn.text or ""
            pairs.append((btn, label_text))

        ranked = matching.rank(pairs, desired_time, window_hours, label=lambda p: p[1])
        if not ranked:
            return None
        element, label_text = ranked[0]
        parsed = matching.parse_time(label_text)
        pretty = parsed.strftime("%-I:%M %p") if parsed else label_text.strip()
        return element, pretty

    def _finalize(self, driver, wait, wanted):
        """Switch into the widget iframe, re-check the date, then Reserve / Confirm.

        Raises NotConfirmed unless Resy actually says the booking went through.
        """
        print("[resy] Switching to reservation iframe...")
        iframe = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'widgets.resy.com')]"))
        )
        driver.switch_to.frame(iframe)

        self._require_summary_date(driver, wanted)

        print("[resy] Clicking 'Reserve Now'...")
        clicked = self._click_first(
            driver,
            [
                (By.CSS_SELECTOR, "button[data-test-id='order_summary_page-button-book']"),
                (By.CSS_SELECTOR, "button[data-test-id*='button-book']"),
                (By.XPATH, "//button[contains(., 'Reserve Now')]"),
                (By.XPATH, "//button[contains(., 'Reserve')]"),
                (By.XPATH, "//button[contains(., 'Complete Reservation')]"),
            ],
            timeout=20,
        )
        if not clicked:
            raise NotConfirmed("Could not find Resy's 'Reserve Now' button.")

        time.sleep(2)
        # Secondary confirmation. The old code matched exactly one markup shape
        # and silently skipped when it didn't match — which is how a run could
        # stop here, never confirm, and still be reported as booked.
        if self._click_first(driver, self.CONFIRM_LOCATORS, timeout=6):
            print("[resy] Secondary confirmation clicked.")
        else:
            print("[resy] No secondary confirmation button matched.")

        return self._await_confirmation(driver)

    # Broad set, because this modal's markup is the piece that changed under the
    # old bot and the failure was silent.
    CONFIRM_LOCATORS = [
        (By.XPATH, "//button//span[text()='Confirm']/.."),
        (By.XPATH, "//button[normalize-space()='Confirm']"),
        (By.XPATH, "//button[contains(., 'Confirm')]"),
        (By.CSS_SELECTOR, "button[data-test-id*='confirm']"),
        (By.CSS_SELECTOR, "button[data-test-id*='button-book']"),
        (By.XPATH, "//button[contains(., 'Yes')]"),
    ]

    # Phrases Resy shows once a reservation really exists. "Add to calendar" and
    # "Cancel reservation" are here deliberately: they are affordances that only
    # make sense on a reservation that already exists, so they survive wording
    # changes to the headline.
    SUCCESS_PATTERNS = re.compile(
        r"you'?re all set|all set|reservation confirmed|confirmed|"
        r"see you on|see you soon|booking confirmed|added to your|"
        r"add to calendar|cancel reservation|modify reservation|"
        r"reservation details|thank you|enjoy your|upcoming reservation",
        re.IGNORECASE,
    )
    # Phrases that mean it definitively did not happen.
    FAILURE_PATTERNS = re.compile(
        r"no longer available|not available|unable to|couldn'?t complete|"
        r"something went wrong|please try again|has expired|sold out|"
        r"add a (credit )?card|payment method (is )?required",
        re.IGNORECASE,
    )
    # The checkout screen we start on. Leaving it without an error means the
    # booking advanced.
    SUMMARY_PATTERNS = re.compile(
        r"reserve now|order summary|cancellation policy|payment method",
        re.IGNORECASE,
    )

    WIDGET_IFRAME = "//iframe[contains(@src, 'widgets.resy.com')]"
    # Fast enough to catch a confirmation screen that flashes past. The old 2s
    # cadence could miss it entirely, and only ever looked at the current
    # screen, so a confirmation that came and went was never seen at all.
    POLL_INTERVAL = 0.4

    def _await_confirmation(self, driver, timeout=45):
        """Wait for Resy's verdict. Returns "confirmed" or "closed".

        The widget is a moving target: after Reserve Now it can flash a
        confirmation for under a second and then swap itself for another screen
        or vanish entirely. So this samples it several times a second and judges
        the **whole transcript**, not whatever happens to be on screen at the
        end — an earlier version polled every two seconds, looked only at the
        current screen, and reported a confirmed booking as a failure because
        the confirmation had already been replaced.

        Outcomes:

        * a success phrase appears at any point -> "confirmed";
        * an error phrase appears -> NotConfirmed (retryable);
        * the widget leaves the checkout screen, or disappears, without ever
          showing an error -> "closed", i.e. booked but not confirmed in words;
        * it sits on checkout the whole time -> NotConfirmed (hard failure).

        Every read re-enters the iframe from the top, since the frame handle
        goes stale the moment Resy swaps or removes it.
        """
        deadline = time.time() + timeout
        confirm_clicks = 0
        screens = []          # distinct widget screens, in the order seen
        saw_summary = False   # have we seen the checkout screen at all?
        left_summary_at = None

        while time.time() < deadline:
            text, iframe_present = self._read_widget(driver)

            if not iframe_present:
                return self._verdict_after_widget_closed(driver, screens)

            if text and (not screens or screens[-1] != text):
                screens.append(text)

            failure = self.FAILURE_PATTERNS.search(text)
            if failure:
                raise NotConfirmed(
                    f"Resy refused the booking: {failure.group(0)!r}", retryable=True
                )
            # Judge the transcript, so a confirmation that flashed past counts.
            if self.SUCCESS_PATTERNS.search("\n".join(screens)):
                print("[resy] Resy confirmed the reservation.")
                self._log_screens(screens)
                return "confirmed"

            on_summary = bool(self.SUMMARY_PATTERNS.search(text))
            if on_summary:
                saw_summary = True
                left_summary_at = None
                # A late confirm modal is worth clicking, but only while we're
                # still on checkout, and only a couple of times.
                if confirm_clicks < 2 and self._click_first(
                    driver, self.CONFIRM_LOCATORS, timeout=0
                ):
                    confirm_clicks += 1
                    print("[resy] Clicked a late confirmation button.")
            elif saw_summary and text:
                # Moved past checkout with no error. Give the confirmation a
                # moment to render before calling it.
                if left_summary_at is None:
                    left_summary_at = time.time()
                elif time.time() - left_summary_at > 5:
                    print("[resy] Widget advanced past checkout with no error.")
                    self._log_screens(screens)
                    return "closed"

            time.sleep(self.POLL_INTERVAL)

        self._log_screens(screens)
        last_text = screens[-1] if screens else ""
        snippet = " ".join(last_text.split())[:200] or "(the widget had no readable text)"
        raise NotConfirmed(
            "Clicked 'Reserve Now' but Resy never confirmed the reservation — "
            "check your Resy account, it may or may not have gone through. "
            f"Widget showed: {snippet}"
        )

    def _read_widget(self, driver):
        """Return (widget_text, iframe_present), tolerating a frame swap."""
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.XPATH, self.WIDGET_IFRAME)
        except WebDriverException:
            return "", False
        if not frames:
            return "", False
        try:
            driver.switch_to.frame(frames[0])
            return driver.find_element(By.TAG_NAME, "body").text, True
        except WebDriverException:
            # Swapped underneath us mid-read; treat as present-but-unreadable so
            # the next pass re-resolves the frame.
            return "", True

    @staticmethod
    def _log_screens(screens):
        """Print each distinct widget screen, so a failure is diagnosable."""
        if not screens:
            print("[resy] Widget transcript: (nothing readable)")
            return
        print(f"[resy] Widget transcript ({len(screens)} screen(s)):")
        for i, screen in enumerate(screens, 1):
            print(f"[resy]   {i}. {' '.join(screen.split())[:300]}")

    def _verdict_after_widget_closed(self, driver, screens=()):
        """The widget is gone. Decide what that means from what we saw."""
        try:
            driver.switch_to.default_content()
            page = driver.find_element(By.TAG_NAME, "body").text
        except WebDriverException:
            page = ""

        self._log_screens(list(screens))

        failure = self.FAILURE_PATTERNS.search(page)
        if failure:
            raise NotConfirmed(
                f"Resy refused the booking: {failure.group(0)!r}", retryable=True
            )
        # A confirmation seen before the widget closed still counts.
        if self.SUCCESS_PATTERNS.search("\n".join(screens)) or self.SUCCESS_PATTERNS.search(page):
            print("[resy] Resy confirmed the reservation.")
            return "confirmed"

        print(
            "[resy] Widget closed with no error — treating as booked but "
            "unverified (Resy dismisses it once the reservation is placed)."
        )
        return "closed"

    @staticmethod
    def _click_first(driver, locators, timeout=5):
        for by, selector in locators:
            try:
                el = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((by, selector))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", el)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", el)
                return True
            except (TimeoutException, WebDriverException):
                continue
        return False

    @staticmethod
    def _require_summary_date(driver, wanted):
        """Last line of defense: the order summary must not name another date.

        Called from inside the widget iframe, immediately before the booking is
        confirmed. A summary that names no date at all ("unknown") is not proof
        of anything, so it only warns — but a summary naming a *different* date
        aborts the attempt.
        """
        try:
            summary = driver.find_element(By.TAG_NAME, "body").text
        except WebDriverException:
            summary = ""

        verdict = matching.date_verdict(summary, wanted)
        if verdict == "mismatch":
            named = matching.find_dates(summary)
            raise DateMismatch(
                f"Resy's booking summary is for {named} but the request is for "
                f"{wanted.isoformat()} — refused to confirm."
            )
        if verdict == "unknown":
            print("[resy] WARNING: no date found in the booking summary; confirming anyway.")
        else:
            print(f"[resy] Booking summary confirms {wanted.isoformat()}.")

    @staticmethod
    def _capture_confirmation(driver):
        """Return (reservation_url, confirmation_code) after a successful booking.

        Resy books inside the widget iframe and leaves the top-level URL on the
        restaurant page, so look for a reservation link in the confirmation view
        first and fall back to the account's reservations page. Either way the
        alert links to the reservation, not the restaurant listing.

        Runs from the top-level document: by this point the widget has usually
        dismissed itself, and a stale frame handle would make every lookup throw.
        """
        try:
            driver.switch_to.default_content()
        except WebDriverException:
            pass

        url, code = None, None

        # Only accept a link that identifies a *specific* reservation. A looser
        # match picked up the widget's own nav link
        # (widgets.resy.com/#/account/reservations-and-notify), which is useless
        # in an email.
        try:
            for anchor in driver.find_elements(By.CSS_SELECTOR, "a[href*='/reservations/']"):
                href = anchor.get_attribute("href") or ""
                tail = href.split("/reservations/", 1)[-1].strip("/")
                if tail and "-and-" not in tail:
                    url = href
                    break
        except WebDriverException:
            pass

        for by, selector in [
            (By.CSS_SELECTOR, "[data-test-id*='confirmation']"),
            (By.XPATH, "//*[contains(text(), 'Confirmation')]"),
        ]:
            try:
                text = driver.find_element(by, selector).text.strip()
                if text:
                    code = text
                    break
            except WebDriverException:
                continue

        return url or RESERVATIONS_URL, code
