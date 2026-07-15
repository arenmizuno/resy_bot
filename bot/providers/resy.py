"""Resy booking flow.

Refactored from the original resy_bot.run_resy_bot into a provider. The one
behavioral change: instead of a hardcoded ranked list of times, it collects the
available slots and picks the closest one within the request's ± window
(see matching.rank).
"""
import time
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .. import config, driver as driver_mod, matching
from .base import BookingProvider, BookingResult


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

        driver = driver_mod.make_driver()
        wait = WebDriverWait(driver, 20)
        try:
            self._login_if_needed(driver, wait)

            driver.get(url)
            print("[resy] Restaurant page loaded.")
            driver_mod.close_modal_if_present(driver, timeout=5)

            self._select_guests(wait, guests)
            self._select_date(driver, wait, target_date)

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

            self._finalize(driver, wait)
            return BookingResult.booked(slot_label)

        except TimeoutException as exc:
            return BookingResult.failed(f"Resy timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return BookingResult.failed(f"Resy error: {exc}")
        finally:
            driver.quit()

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
        print(f"[resy] Selecting {guests} guests...")
        dropdown = wait.until(EC.presence_of_element_located((By.ID, "party_size")))
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

        labels = [
            parsed.strftime("%B %-d, %Y."),
            parsed.strftime("%B %-d, %Y"),
            parsed.strftime("%A, %B %-d, %Y"),
            parsed.strftime("%a, %B %-d, %Y"),
        ]
        button = None
        for label in labels:
            try:
                button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, f"//button[@aria-label='{label}']"))
                )
                break
            except TimeoutException:
                continue
        if button is None:
            fallback = (
                f"//button[contains(@aria-label, '{parsed.strftime('%B')}') "
                f"and contains(@aria-label, '{parsed.day}') and not(@disabled)]"
            )
            button = wait.until(EC.element_to_be_clickable((By.XPATH, fallback)))

        driver.execute_script("arguments[0].scrollIntoView(true);", button)
        driver.execute_script("arguments[0].click();", button)
        print(f"[resy] Selected {parsed.strftime('%B %d, %Y')}")
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

    def _finalize(self, driver, wait):
        """Switch into the widget iframe and click Reserve / Confirm."""
        print("[resy] Switching to reservation iframe...")
        iframe = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'widgets.resy.com')]"))
        )
        driver.switch_to.frame(iframe)

        print("[resy] Clicking 'Reserve Now'...")
        reserve_btn = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[data-test-id='order_summary_page-button-book']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", reserve_btn)
        time.sleep(1)
        reserve_btn.click()

        # Optional secondary confirmation.
        try:
            confirm = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button//span[text()='Confirm']/.."))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", confirm)
            time.sleep(0.5)
            confirm.click()
            print("[resy] Secondary confirmation completed.")
        except TimeoutException:
            print("[resy] No secondary confirmation needed.")
        time.sleep(4)
