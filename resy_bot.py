import time
import smtplib
import os
import argparse
from datetime import datetime
from email.message import EmailMessage

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from dotenv import load_dotenv

# ------------------- CONFIGURATION -------------------
load_dotenv()

RESY_EMAIL = os.getenv("RESY_EMAIL")
RESY_PASSWORD = os.getenv("RESY_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")


# ------------------- ARG PARSE FUNCTION -------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Run Resy reservation bot")

    parser.add_argument(
        "--restaurant-url",
        required=True,
        help="Full Resy restaurant URL"
    )
    parser.add_argument(
        "--restaurant-name",
        required=True,
        help="Restaurant name for alerts"
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target reservation date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--guests",
        type=int,
        required=True,
        help="Number of guests"
    )
    parser.add_argument(
        "--times",
        nargs="+",
        default=[
            "7:00 PM", "7:15 PM", "6:45 PM", "7:30 PM", "6:30 PM",
            "8:00 PM", "6:15 PM", "8:15 PM", "5:45 PM", "8:30 PM"
        ],
        help="Preferred reservation times in priority order"
    )

    return parser.parse_args()


# ------------------- EMAIL ALERT FUNCTION -------------------
def send_alert(subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.send_message(msg)


# ------------------- HELPER FUNCTION -------------------
def close_initial_modal_if_present(driver, timeout=5):
    try:
        wait = WebDriverWait(driver, timeout)

        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content"))
        )

        possible_selectors = [
            (By.CSS_SELECTOR, "button[data-test-id='announcement-button-secondary']"),
            (By.CSS_SELECTOR, "button[aria-label='Close']"),
            (By.CSS_SELECTOR, "button.close"),
            (By.XPATH, "//button[contains(text(), 'No Thanks')]"),
            (By.XPATH, "//button[contains(text(), 'Close')]"),
            (By.XPATH, "//button[contains(text(), 'Not now')]"),
        ]

        for by, selector in possible_selectors:
            try:
                btn = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((by, selector))
                )
                driver.execute_script("arguments[0].click();", btn)
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content"))
                )
                print("Initial modal closed.")
                return
            except TimeoutException:
                continue

        print("Modal appeared, but no close button was found.")

    except TimeoutException:
        print("No initial modal appeared.")


# ------------------- MAIN BOT FUNCTION -------------------
def run_resy_bot(restaurant_url, restaurant_name, target_date, number_of_guests, ranked_times):
    print("Starting Resy bot...")

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 20)

    try:
        # STEP 1: LOGIN
        driver.get("https://resy.com")
        close_initial_modal_if_present(driver)

        print("Opening login menu...")
        login_btn = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[data-test-id='menu_container-button-log_in']")
            )
        )
        login_btn.click()

        wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "ReactModal__Content"))
        )

        email_login_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Log in with email & password')]")
            )
        )
        driver.execute_script("arguments[0].click();", email_login_btn)

        print("Entering credentials...")
        wait.until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='email']"))
        ).send_keys(RESY_EMAIL)

        wait.until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='password']"))
        ).send_keys(RESY_PASSWORD)

        continue_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", continue_btn)
        continue_btn.click()

        print("Waiting for CAPTCHA or login redirect...")
        time.sleep(3)

        # STEP 2: GO TO RESTAURANT
        driver.get(restaurant_url)
        print("Navigated to restaurant page...")

        # STEP 3: CLOSE "NO THANKS" MODAL IF IT APPEARS
        print("Checking for 'No Thanks' modal...")
        try:
            modal_wait = WebDriverWait(driver, 5)
            modal_wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content"))
            )
            no_thanks_btn = modal_wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[data-test-id='announcement-button-secondary']")
                )
            )
            driver.execute_script("arguments[0].click();", no_thanks_btn)
            print("Clicked 'No Thanks' to dismiss modal.")
            WebDriverWait(driver, 3).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content"))
            )
            print("Modal dismissed successfully.")
        except TimeoutException:
            print("No 'No Thanks' modal appeared.")

        # STEP 4: SELECT NUMBER OF GUESTS
        print(f"Selecting {number_of_guests} guests...")
        guest_dropdown = wait.until(
            EC.presence_of_element_located((By.ID, "party_size"))
        )
        Select(guest_dropdown).select_by_value(str(number_of_guests))
        time.sleep(2)

        # STEP 5: SELECT DATE
        print("Selecting reservation date...")
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
        target_month_year = parsed_date.strftime("%B %Y")

        date_button = wait.until(
            EC.element_to_be_clickable((By.ID, "DropdownGroup__selector--date"))
        )
        driver.execute_script("arguments[0].click();", date_button)

        max_attempts = 12
        for _ in range(max_attempts):
            try:
                month_label = wait.until(
                    EC.visibility_of_element_located((By.CLASS_NAME, "CalendarMonth__Title"))
                )
                current_month = month_label.text.strip()

                if current_month == target_month_year:
                    print(f"Correct month '{current_month}' is visible.")
                    break

                next_button = wait.until(
                    EC.element_to_be_clickable((By.CLASS_NAME, "ResyCalendar__nav_right"))
                )
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(0.5)

            except TimeoutException:
                raise Exception("Could not find month navigation or month label.")
        else:
            raise Exception(f"Unable to reach month '{target_month_year}' after {max_attempts} attempts.")

        possible_labels = [
            parsed_date.strftime("%B %-d, %Y."),
            parsed_date.strftime("%B %-d, %Y"),
            parsed_date.strftime("%A, %B %-d, %Y"),
            parsed_date.strftime("%a, %B %-d, %Y"),
        ]

        calendar_button = None

        for label in possible_labels:
            try:
                print(f"Trying date label: {label}")
                xpath = f"//button[@aria-label='{label}']"
                calendar_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                break
            except TimeoutException:
                continue

        if calendar_button is None:
            day_num = parsed_date.day
            fallback_xpath = (
                f"//button[contains(@aria-label, '{parsed_date.strftime('%B')}') "
                f"and contains(@aria-label, '{day_num}') and not(@disabled)]"
            )
            print(f"Falling back to broader xpath: {fallback_xpath}")
            calendar_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, fallback_xpath))
            )

        driver.execute_script("arguments[0].scrollIntoView(true);", calendar_button)
        driver.execute_script("arguments[0].click();", calendar_button)
        print(f"Selected {parsed_date.strftime('%B %d, %Y')}")

        # STEP 6: WAIT FOR AVAILABLE SLOTS
        print("Looking for available times...")
        time.sleep(3)

        slots = wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "button.ReservationButton.Button--primary")
            )
        )

        selected = None
        selected_time = None

        for preferred_time in ranked_times:
            for button in slots:
                button_text = button.get_attribute("innerText") or button.text
                if preferred_time in button_text:
                    selected = button
                    selected_time = preferred_time
                    break
            if selected:
                break

        if not selected:
            raise Exception("No preferred times available.")

        print(f"Found time: {selected_time}. Clicking...")
        driver.execute_script("arguments[0].scrollIntoView(true);", selected)
        driver.execute_script("arguments[0].click();", selected)
        time.sleep(10)

        # STEP 7: SWITCH TO IFRAME
        try:
            print("Switching to iframe with reservation summary...")
            iframe = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'widgets.resy.com')]"))
            )
            driver.switch_to.frame(iframe)
        except TimeoutException:
            raise Exception("Could not find or switch to iframe.")

        # STEP 8: CLICK "RESERVE NOW"
        print("Clicking 'Reserve Now' to finalize reservation...")
        try:
            reserve_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[data-test-id='order_summary_page-button-book']")
                )
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", reserve_btn)
            time.sleep(1)
            reserve_btn.click()
            print("Reservation confirmed!")

            send_alert(
                f"Reservation Completed - {restaurant_name}",
                f"Successfully reserved {restaurant_name} for {number_of_guests} guests at {selected_time} on {target_date}.\nURL: {restaurant_url}"
            )
        except TimeoutException:
            raise Exception("'Reserve Now' button not found — reservation incomplete.")

        # STEP 9: CHECK FOR SECONDARY CONFIRMATION
        try:
            print("Checking for secondary confirmation modal...")
            second_confirm = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button//span[text()='Confirm']/.."))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", second_confirm)
            time.sleep(0.5)
            second_confirm.click()
            print("Secondary confirmation completed.")
        except TimeoutException:
            print("No secondary confirmation needed.")

        time.sleep(5)

    except TimeoutException as te:
        send_alert("Timeout on Resy Bot", f"A timeout occurred: {str(te)}")
        print("Timeout occurred.")

    except Exception as e:
        send_alert("Error in Resy Bot", str(e))
        print(f"Error occurred: {e}")

    finally:
        driver.quit()
        print("Bot finished.")


# ------------------- RUN -------------------
if __name__ == "__main__":
    args = parse_args()
    run_resy_bot(
        restaurant_url=args.restaurant_url,
        restaurant_name=args.restaurant_name,
        target_date=args.date,
        number_of_guests=args.guests,
        ranked_times=args.times,
    )