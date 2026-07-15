"""Shared Selenium Chrome setup and common page helpers.

A persistent user-data-dir keeps you logged into Resy/OpenTable between runs and
reduces bot-detection friction, so the poller usually doesn't have to re-enter
credentials or solve a CAPTCHA every cycle.
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from . import config


def make_driver(headless=None):
    """Create a Chrome WebDriver using the persistent profile."""
    if headless is None:
        headless = config.HEADLESS

    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,1000")
    # Persist cookies/session across runs.
    config.CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={config.CHROME_PROFILE_DIR}")
    # Trim the most obvious automation fingerprints.
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
    except Exception:  # noqa: BLE001 - CDP not fatal
        pass
    return driver


def close_modal_if_present(driver, timeout=5):
    """Dismiss a Resy-style ReactModal announcement if one pops up."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content"))
        )
    except TimeoutException:
        return

    candidates = [
        (By.CSS_SELECTOR, "button[data-test-id='announcement-button-secondary']"),
        (By.CSS_SELECTOR, "button[aria-label='Close']"),
        (By.CSS_SELECTOR, "button.close"),
        (By.XPATH, "//button[contains(text(), 'No Thanks')]"),
        (By.XPATH, "//button[contains(text(), 'Close')]"),
        (By.XPATH, "//button[contains(text(), 'Not now')]"),
    ]
    for by, selector in candidates:
        try:
            btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((by, selector)))
            driver.execute_script("arguments[0].click();", btn)
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.ReactModal__Content"))
            )
            print("[driver] Closed modal.")
            return
        except TimeoutException:
            continue
    print("[driver] Modal present but no known close button matched.")
