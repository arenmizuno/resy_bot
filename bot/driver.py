"""Shared Selenium Chrome setup and common page helpers.

A persistent user-data-dir keeps you logged into Resy between runs and reduces
bot-detection friction, so the poller usually doesn't have to re-enter
credentials or solve a CAPTCHA every cycle.

Booking sites fingerprint the browser rather than the IP, so the same machine
that loads a site fine in normal Chrome can be blocked in a Selenium-driven one.
`make_driver` therefore strips the automation tells it can (notably the
AutomationControlled blink feature, which Chrome advertises by default under
Selenium) and can hand the whole job to undetected-chromedriver when installed:

    pip install undetected-chromedriver
    # then in .env
    USE_UNDETECTED=1
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from . import config

# A current desktop UA; the default under headless Chrome says "HeadlessChrome",
# which is an instant tell.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def _common_arguments(options, headless):
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,1000")
    # The big one: without this, Chrome under Selenium advertises itself as
    # automation-controlled, which is what bot-detection edges look for.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument(f"--user-agent={USER_AGENT}")
    # Persist cookies/session across runs.
    config.CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={config.CHROME_PROFILE_DIR}")
    if headless:
        options.add_argument("--headless=new")
    return options


def make_driver(headless=None):
    """Create a Chrome WebDriver using the persistent profile.

    Uses undetected-chromedriver when USE_UNDETECTED=1 and the package is
    installed, falling back to plain Selenium (with a warning) otherwise.
    """
    if headless is None:
        headless = config.HEADLESS

    if config.USE_UNDETECTED:
        driver = _make_undetected_driver(headless)
        if driver is not None:
            return driver

    options = _common_arguments(Options(), headless)
    # Trim the remaining obvious automation fingerprints.
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    _hide_webdriver_flag(driver)
    return driver


def _make_undetected_driver(headless):
    """Return an undetected-chromedriver instance, or None if unavailable."""
    try:
        import undetected_chromedriver as uc
    except ImportError:
        print(
            "[driver] USE_UNDETECTED=1 but undetected-chromedriver isn't installed "
            "(pip install undetected-chromedriver); using plain Selenium."
        )
        return None

    print("[driver] Using undetected-chromedriver.")
    options = _common_arguments(uc.ChromeOptions(), headless)
    driver = uc.Chrome(options=options, headless=headless)
    _hide_webdriver_flag(driver)
    return driver


def _hide_webdriver_flag(driver):
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
    except Exception:  # noqa: BLE001 - CDP not fatal
        pass


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
