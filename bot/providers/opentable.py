"""OpenTable booking flow.

OpenTable has stronger bot detection than Resy, so this flow:
  * reuses the persistent Chrome profile (keeps you signed in),
  * prefills availability via URL query params (?covers=&dateTime=) instead of
    driving the fiddly widget dropdowns, and
  * isolates every selector here with verbose logging + fallbacks, because
    OpenTable's DOM changes often and these are the most likely thing to need
    re-tuning against the live site.

If plain Selenium starts getting blocked, install `undetected-chromedriver` and
swap `driver.make_driver()` for it (see README).
"""
import time
from datetime import datetime
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .. import config, driver as driver_mod, matching
from .base import BookingProvider, BookingResult


class OpenTableProvider(BookingProvider):
    name = "opentable"

    def book(self, request) -> BookingResult:
        name = request["restaurant_name"]
        target_date = request["date"]
        guests = int(request["guests"])
        desired_time = request["desired_time"]
        window_hours = float(request.get("window_hours", config.DEFAULT_WINDOW_HOURS))

        print(f"[opentable] Booking {name} on {target_date} for {guests} near {desired_time} (±{window_hours}h)")

        driver = driver_mod.make_driver()
        wait = WebDriverWait(driver, 20)
        try:
            self._login_if_needed(driver, wait)

            search_url = self._build_search_url(
                request["restaurant_url"], guests, target_date, desired_time
            )
            print(f"[opentable] Opening availability: {search_url}")
            driver.get(search_url)
            time.sleep(4)

            slot = self._pick_slot(driver, wait, desired_time, window_hours)
            if slot is None:
                return BookingResult.unavailable(
                    f"No OpenTable slots within ±{window_hours}h of {desired_time}."
                )

            slot_element, slot_label = slot
            print(f"[opentable] Selecting slot {slot_label}...")
            driver.execute_script("arguments[0].scrollIntoView(true);", slot_element)
            driver.execute_script("arguments[0].click();", slot_element)
            time.sleep(6)

            self._complete_reservation(driver, wait)
            return BookingResult.booked(slot_label)

        except TimeoutException as exc:
            return BookingResult.failed(f"OpenTable timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return BookingResult.failed(f"OpenTable error: {exc}")
        finally:
            driver.quit()

    # ------------------- helpers -------------------
    @staticmethod
    def _build_search_url(restaurant_url, guests, target_date, desired_time):
        """Append ?covers=&dateTime= so OpenTable renders availability directly."""
        parsed_time = matching.parse_time(desired_time) or datetime.strptime("19:00", "%H:%M").time()
        date_time = f"{target_date}T{parsed_time.strftime('%H:%M')}"

        parts = urlparse(restaurant_url)
        query = parse_qs(parts.query)
        query.update({"covers": [str(guests)], "dateTime": [date_time]})
        new_query = urlencode({k: v[0] for k, v in query.items()})
        return urlunparse(parts._replace(query=new_query))

    def _login_if_needed(self, driver, wait):
        driver.get("https://www.opentable.com/")
        time.sleep(3)

        # If a "Sign in" affordance is absent, assume we're already authenticated.
        sign_in = self._first_present(
            driver,
            [
                (By.CSS_SELECTOR, "[data-test='sign-in-link']"),
                (By.CSS_SELECTOR, "a[href*='sign-in']"),
                (By.XPATH, "//button[contains(., 'Sign in')]"),
                (By.XPATH, "//a[contains(., 'Sign in')]"),
            ],
            timeout=5,
        )
        if sign_in is None:
            print("[opentable] Already signed in (no sign-in link).")
            return

        if not (config.OPENTABLE_EMAIL and config.OPENTABLE_PASSWORD):
            raise RuntimeError("OPENTABLE_EMAIL / OPENTABLE_PASSWORD not configured.")

        print("[opentable] Signing in...")
        driver.execute_script("arguments[0].click();", sign_in)
        time.sleep(2)

        email = self._first_present(
            driver,
            [
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.ID, "emailInput"),
                (By.CSS_SELECTOR, "input[name='email']"),
            ],
            timeout=10,
        )
        if email is None:
            raise RuntimeError("Could not find OpenTable email field (selectors need tuning).")
        email.send_keys(config.OPENTABLE_EMAIL)

        # Some flows require submitting the email before the password appears.
        pwd = self._first_present(
            driver,
            [
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.ID, "passwordInput"),
                (By.CSS_SELECTOR, "input[name='password']"),
            ],
            timeout=4,
        )
        if pwd is None:
            self._click_first(
                driver,
                [
                    (By.XPATH, "//button[contains(., 'Continue')]"),
                    (By.XPATH, "//button[contains(., 'Next')]"),
                ],
            )
            time.sleep(2)
            pwd = self._first_present(
                driver, [(By.CSS_SELECTOR, "input[type='password']")], timeout=8
            )
        if pwd is None:
            raise RuntimeError("Could not find OpenTable password field (selectors need tuning).")
        pwd.send_keys(config.OPENTABLE_PASSWORD)

        self._click_first(
            driver,
            [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(., 'Sign in')]"),
                (By.XPATH, "//button[contains(., 'Continue')]"),
            ],
        )
        print("[opentable] Submitted credentials; waiting for redirect/CAPTCHA...")
        time.sleep(4)

    def _pick_slot(self, driver, wait, desired_time, window_hours):
        """Return (element, label) of the closest available slot within window."""
        slot_selectors = [
            (By.CSS_SELECTOR, "[data-test='time-slot']"),
            (By.CSS_SELECTOR, "a[href*='/booking/']"),
            (By.CSS_SELECTOR, "button[id^='ReservationButton']"),
            (By.XPATH, "//*[@data-test='times-list']//a | //*[@data-test='times-list']//button"),
        ]
        elements = []
        for by, selector in slot_selectors:
            try:
                found = WebDriverWait(driver, 8).until(
                    EC.presence_of_all_elements_located((by, selector))
                )
                if found:
                    print(f"[opentable] Found {len(found)} slot(s) via {selector}")
                    elements = found
                    break
            except TimeoutException:
                continue

        if not elements:
            return None

        pairs = []
        for el in elements:
            label_text = (
                el.get_attribute("aria-label")
                or el.get_attribute("innerText")
                or el.text
                or ""
            )
            pairs.append((el, label_text))

        ranked = matching.rank(pairs, desired_time, window_hours, label=lambda p: p[1])
        if not ranked:
            return None
        element, label_text = ranked[0]
        parsed = matching.parse_time(label_text)
        pretty = parsed.strftime("%-I:%M %p") if parsed else label_text.strip()
        return element, pretty

    def _complete_reservation(self, driver, wait):
        """Click through the booking-details page to finalize."""
        print("[opentable] Completing reservation...")
        clicked = self._click_first(
            driver,
            [
                (By.CSS_SELECTOR, "[data-test='complete-reservation-button']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(., 'Complete reservation')]"),
                (By.XPATH, "//button[contains(., 'Reserve Now')]"),
                (By.XPATH, "//button[contains(., 'Confirm')]"),
            ],
            timeout=20,
        )
        if not clicked:
            raise RuntimeError("Could not find OpenTable 'Complete reservation' button.")
        time.sleep(5)

    # ------------------- selector utilities -------------------
    @staticmethod
    def _first_present(driver, locators, timeout=5):
        for by, selector in locators:
            try:
                return WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((by, selector))
                )
            except TimeoutException:
                continue
        return None

    @staticmethod
    def _click_first(driver, locators, timeout=5):
        for by, selector in locators:
            try:
                el = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((by, selector))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", el)
                driver.execute_script("arguments[0].click();", el)
                return True
            except TimeoutException:
                continue
        return False
