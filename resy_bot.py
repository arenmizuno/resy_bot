import time
import smtplib
import os
from datetime import datetime
from email.message import EmailMessage
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from dotenv import load_dotenv

# ------------------- CONFIGURATION -------------------
load_dotenv() 
resy_email = os.getenv("RESY_EMAIL")
resy_password = os.getenv("RESY_PASSWORD")
sender_email = os.getenv("SENDER_EMAIL")
sender_password = os.getenv("SENDER_PASSWORD")
receiver_email = os.getenv("RECEIVER_EMAIL")

# change according to reservation preferences
restaurant_url = "https://resy.com/cities/chicago-il/venues/the-duck-inn"
target_date = "2025-08-05"
number_of_guests = 4
ranked_times = [
    "7:00 PM", "7:15 PM", "6:45 PM", "7:30 PM", "6:30 PM",
    "8:00 PM", "6:15 PM", "8:15 PM", "5:45 PM", "8:30 PM"
]

# ------------------- EMAIL ALERT FUNCTION -------------------
def send_alert(subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender_email, sender_password)
        smtp.send_message(msg)

# ------------------- MAIN BOT FUNCTION -------------------
def run_resy_bot():
    print("🚀 Starting Resy bot...")
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 20)

    try:
        # STEP 1: Login
        driver.get("https://resy.com")
        print("🔓 Opening login menu...")
        login_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//resy-menu-container[@on-login='vm.onLogin']")))
        login_menu.click()
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "ReactModal__Content")))

        print("✍️ Entering credentials...")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='email']"))).send_keys(resy_email)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='password']"))).send_keys(resy_password)

        continue_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue')]")))
        driver.execute_script("arguments[0].scrollIntoView(true);", continue_btn)
        continue_btn.click()

        print("⏳ Waiting for CAPTCHA or login redirect...")
        time.sleep(3)

        # STEP 2: Go to restaurant
        driver.get(restaurant_url)
        print("🍽 Navigated to restaurant page...")

        # STEP 3: Close "No Thanks" modal if it appears
        print("🔍 Checking for 'No Thanks' modal...")
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content")))
            no_thanks_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-test-id='announcement-button-secondary']")))
            driver.execute_script("arguments[0].click();", no_thanks_btn)
            print("❌ Clicked 'No Thanks' to dismiss modal.")
            WebDriverWait(driver, 10).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content")))
            print("✅ Modal dismissed successfully.")
        except TimeoutException:
            print("✅ No 'No Thanks' modal appeared.")

        # STEP 4: Select number of guests
        print(f"👥 Selecting {number_of_guests} guests...")
        guest_dropdown = wait.until(EC.presence_of_element_located((By.ID, "party_size")))
        Select(guest_dropdown).select_by_value(str(number_of_guests))
        time.sleep(2)

        # STEP 5: Select date
        print("📅 Selecting reservation date...")
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
        target_day = str(parsed_date.day)
        target_month_year = parsed_date.strftime("%B %Y")  # e.g., "July 2025"

        # Open the date selector first
        date_button = wait.until(EC.element_to_be_clickable((By.ID, "DropdownGroup__selector--date")))
        driver.execute_script("arguments[0].click();", date_button)

        # Navigate months if necessary
        max_attempts = 12
        for _ in range(max_attempts):
            try:
                # Check current month label (use class based on your HTML)
                month_label = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "CalendarMonth__Title")))
                current_month = month_label.text.strip()

                if current_month == target_month_year:
                    print(f"📆 Correct month '{current_month}' is visible.")
                    break

                # Click next month arrow (updated class)
                next_button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "ResyCalendar__nav_right")))
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(0.5)

            except TimeoutException:
                raise Exception("❌ Could not find month navigation or month label.")
        else:
            raise Exception(f"❌ Unable to reach month '{target_month_year}' after {max_attempts} attempts.")

        # Click the correct day
        # Format the target date for aria-label match
        aria_label = parsed_date.strftime("%B %-d, %Y.")  # e.g., "July 13, 2025."

        # XPath to find the matching <button>
        button_xpath = f"//button[@aria-label='{aria_label}']"
        calendar_button = wait.until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
        driver.execute_script("arguments[0].click();", calendar_button)
        print(f"✅ Selected {parsed_date.strftime('%B %d, %Y')}")


        # STEP 7: Wait for available slots to load
        print("⏱ Looking for available times...")
        time.sleep(3)
        slots = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button.ReservationButton.Button--primary")))

        selected = None
        for preferred_time in ranked_times:
            for button in slots:
                if preferred_time in button.get_attribute("innerText") or preferred_time in button.text:
                    selected = button
                    break
            if selected:
                break

        if not selected:
            raise Exception("No preferred times available.")

        print(f"🎯 Found time: {preferred_time}. Clicking...")
        driver.execute_script("arguments[0].scrollIntoView(true);", selected)
        driver.execute_script("arguments[0].click();", selected)
        time.sleep(10)

        # STEP 8: Switch to iframe that contains the reservation confirmation page
        try:
            print("🔁 Switching to iframe with reservation summary...")
            iframe = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'widgets.resy.com')]"))
            )
            driver.switch_to.frame(iframe)
        except TimeoutException:
            raise Exception("❌ Could not find or switch to iframe.")


        # STEP 9: Click "Reserve Now"
        print("📩 Clicking 'Reserve Now' to finalize reservation...")
        try:
            reserve_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-test-id='order_summary_page-button-book']")))
            driver.execute_script("arguments[0].scrollIntoView(true);", reserve_btn)
            time.sleep(1)
            reserve_btn.click()
            print("🎉 Reservation confirmed!")
            send_alert("✅ Reservation Completed", f"Successfully reserved {preferred_time} on {target_date}")
        except TimeoutException:
            raise Exception("❌ 'Reserve Now' button not found — reservation incomplete.")
        
        # Check for secondary confirmation modal
        try:
            print("🔍 Checking for secondary confirmation modal...")
            second_confirm = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button//span[text()='Confirm']/.."))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", second_confirm)
            time.sleep(0.5)
            second_confirm.click()
            print("✅ Secondary confirmation completed.")
        except TimeoutException:
            print("✅ No secondary confirmation needed.")
    
        time.sleep(5)

    except TimeoutException as te:
        send_alert("❌ Timeout on Resy Bot", f"A timeout occurred: {str(te)}")
        print("Timeout occurred.")
    except Exception as e:
        send_alert("❌ Error in Resy Bot", str(e))
        print(f"Error occurred: {e}")
    finally:
        driver.quit()
        print("🛑 Bot finished.")

# ------------------- RUN -------------------
if __name__ == "__main__":
    run_resy_bot()
