"""
Download Maker x Vehicle Class data from the Vahan Parivahan dashboard - Headless Version.
Downloads monthly totals (Y-Axis: Maker, X-Axis: Vehicle Class).
Designed to run on UI-less servers (no display required).

Usage:
    python download_maker_vehicle_class_v2.py --year 2026 --month 1
    python download_maker_vehicle_class_v2.py --legacy   # downloads Jan-Dec 2025 + Jan 2026
"""

import os
import time
import shutil
import argparse
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd

DASHBOARD_URL = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"

MONTH_ABBRS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "monthly_maker_vehicle_class_data")


def setup_headless_driver(download_dir):
    """Setup Chrome driver in headless mode for UI-less servers."""
    chrome_options = Options()

    # Headless mode settings
    chrome_options.add_argument("--headless=new")  # New headless mode (Chrome 109+)
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--disable-software-rasterizer")

    # User agent to avoid detection
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Download preferences
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Enable downloads in headless mode (required for Chrome headless)
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": download_dir},
    )

    # Hide webdriver property
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return driver


def wait_for_page_load(driver, timeout=30):
    """Wait for page to fully load."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def select_dropdown_by_id(driver, dropdown_id, option_text, retry=3):
    """Select an option from a PrimeFaces dropdown by ID with retry logic."""
    for attempt in range(retry):
        try:
            # Wait for dropdown to be present
            dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, dropdown_id))
            )
            label = dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
            print(f"   Current value: {label.text}")

            # Scroll element into view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", dropdown)
            time.sleep(0.5)

            # Click using JavaScript (more reliable in headless mode)
            driver.execute_script("arguments[0].click();", label)
            time.sleep(1.5)

            # Wait for panel to appear
            panel_id = f"{dropdown_id}_panel"
            panel = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.ID, panel_id))
            )

            # Wait for options to load
            time.sleep(0.5)
            options = panel.find_elements(By.TAG_NAME, "li")
            print(f"   Found {len(options)} options")

            for opt in options:
                opt_text = opt.text.strip()
                if option_text.lower() in opt_text.lower():
                    # Scroll option into view within panel
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", opt)
                    time.sleep(0.3)
                    driver.execute_script("arguments[0].click();", opt)
                    print(f"   Selected: {opt_text}")
                    time.sleep(1.5)

                    # Verify selection
                    new_label = dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
                    print(f"   New value: {new_label.text}")
                    return True

            print(f"   Option '{option_text}' not found in: {[o.text for o in options[:10]]}")
            return False

        except Exception as e:
            print(f"   Attempt {attempt + 1} failed: {e}")
            if attempt < retry - 1:
                time.sleep(2)
                # Click elsewhere to close any open panel
                try:
                    driver.find_element(By.TAG_NAME, "body").click()
                    time.sleep(0.5)
                except:
                    pass
            else:
                return False
    return False


def _click_refresh(driver):
    """Click the Refresh button on the dashboard using JavaScript."""
    try:
        refresh_btn = driver.find_element(
            By.XPATH,
            "//button[contains(@id, 'refresh') or .//span[contains(text(), 'Refresh')]]",
        )
        driver.execute_script("arguments[0].click();", refresh_btn)
        print("   Clicked refresh button")
        time.sleep(5)
    except Exception:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if "Refresh" in btn.text:
                driver.execute_script("arguments[0].click();", btn)
                print("   Clicked refresh button")
                time.sleep(5)
                break


def _select_month(driver, month_abbr):
    """Select a month from the groupingTable:selectMonth dropdown."""
    try:
        month_dropdown_id = "groupingTable:selectMonth"
        month_dropdown = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, month_dropdown_id))
        )
        label = month_dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
        print(f"   Found month dropdown, current value: '{label.text}'")

        # Use JavaScript click for headless mode
        driver.execute_script("arguments[0].click();", label)
        time.sleep(1)

        panel = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.ID, f"{month_dropdown_id}_panel"))
        )
        options = panel.find_elements(By.TAG_NAME, "li")
        option_texts = [opt.text for opt in options]
        print(f"   Available options: {option_texts}")

        month_selected = False
        for opt in options:
            if month_abbr in opt.text.upper():
                driver.execute_script("arguments[0].click();", opt)
                print(f"   Selected month: {opt.text}")
                month_selected = True
                time.sleep(2)
                break

        if not month_selected:
            print(f"   Month '{month_abbr}' not found in options")
            driver.find_element(By.TAG_NAME, "body").click()
            time.sleep(0.5)

    except Exception as e:
        print(f"   Error selecting month: {e}")


def _click_download(driver):
    """Find and click the CSV/Excel download icon using JavaScript. Returns True if clicked."""
    csv_selectors = [
        "//img[contains(@src, 'csv') or contains(@alt, 'csv') or contains(@alt, 'CSV')]",
        "//a[contains(@href, 'csv') or contains(@title, 'csv') or contains(@title, 'CSV')]",
        "//img[contains(@src, 'green') or contains(@class, 'csv')]",
        "//*[contains(@onclick, 'csv') or contains(@onclick, 'CSV')]",
        "//a[contains(@id, 'csv') or contains(@class, 'csv')]",
        "//button[contains(@id, 'csv') or contains(@title, 'CSV')]",
        "//span[contains(@class, 'csv')]/parent::*",
        "//img[contains(@title, 'Excel') or contains(@title, 'Download')]",
        "//a[.//img]",
    ]

    for selector in csv_selectors:
        try:
            elements = driver.find_elements(By.XPATH, selector)
            for elem in elements:
                if elem.is_displayed():
                    elem_src = elem.get_attribute("src") or ""
                    elem_alt = elem.get_attribute("alt") or ""
                    elem_title = elem.get_attribute("title") or ""
                    combined = (elem_src + elem_alt + elem_title).lower()
                    if any(x in combined for x in ["csv", "download", "excel", "export"]):
                        driver.execute_script("arguments[0].click();", elem)
                        print("   Download icon clicked!")
                        time.sleep(10)
                        return True
        except Exception:
            continue

    # Fallback: look for any download/export images or links
    print("   Looking for any download/export icons...")
    for img in driver.find_elements(By.TAG_NAME, "img"):
        src = img.get_attribute("src") or ""
        alt = img.get_attribute("alt") or ""
        title = img.get_attribute("title") or ""
        combined = (src + alt + title).lower()
        if img.is_displayed() and any(
            x in combined for x in ["csv", "xls", "excel", "download", "export"]
        ):
            print(f"   Found image: src={src}, alt={alt}")
            driver.execute_script("arguments[0].click();", img)
            time.sleep(10)
            return True

    for link in driver.find_elements(By.TAG_NAME, "a"):
        href = link.get_attribute("href") or ""
        title = link.get_attribute("title") or ""
        onclick = link.get_attribute("onclick") or ""
        combined = (href + title + onclick).lower()
        if link.is_displayed() and any(
            x in combined for x in ["csv", "xls", "excel", "download", "export"]
        ):
            print(f"   Found link: href={href}, title={title}")
            driver.execute_script("arguments[0].click();", link)
            time.sleep(10)
            return True

    return False


def _wait_and_move_file(temp_download_dir, year, month):
    """Wait for a file to appear in temp dir and move it to OUTPUT_DIR."""
    max_wait = 60
    waited = 0
    while waited < max_wait:
        files = os.listdir(temp_download_dir)
        ready_files = [
            f
            for f in files
            if f.endswith((".csv", ".xlsx", ".xls")) and not f.endswith(".crdownload")
        ]
        if ready_files:
            print(f"   Download complete: {ready_files[0]}")
            break
        time.sleep(1)
        waited += 1

    if waited >= max_wait:
        print("   Download may still be in progress...")
        return

    dest_name = f"maker_vehicle_class_{year}_{month:02d}"

    for file in os.listdir(temp_download_dir):
        if file.endswith((".xlsx", ".xls", ".csv")):
            src_path = os.path.join(temp_download_dir, file)
            _, ext = os.path.splitext(file)

            if ext in (".xlsx", ".xls"):
                # Convert to CSV
                df = pd.read_excel(src_path, header=None)
                csv_path = os.path.join(OUTPUT_DIR, f"{dest_name}.csv")
                df.to_csv(csv_path, index=False, header=False)
                print(f"   Converted and saved to: {csv_path}")
                os.remove(src_path)
            else:
                dest_path = os.path.join(OUTPUT_DIR, f"{dest_name}.csv")
                shutil.move(src_path, dest_path)
                print(f"   Saved to: {dest_path}")


def download_month(year, month):
    """Download Maker x Vehicle Class data for a single month in headless mode.

    Args:
        year: int, e.g. 2026
        month: int, 1-12
    """
    month_abbr = MONTH_ABBRS[month - 1]
    print(f"\n{'='*60}")
    print(f"Downloading Maker x Vehicle Class data for {month_abbr} {year}")
    print(f"Running in headless mode (no browser window)")
    print(f"{'='*60}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    temp_download_dir = os.path.join(SCRIPT_DIR, "temp_downloads_mvc")
    os.makedirs(temp_download_dir, exist_ok=True)

    # Clean temp directory
    for f in os.listdir(temp_download_dir):
        os.remove(os.path.join(temp_download_dir, f))

    driver = setup_headless_driver(temp_download_dir)

    try:
        # 1. Navigate to dashboard
        print(f"\nNavigating to: {DASHBOARD_URL}")
        driver.get(DASHBOARD_URL)
        print("Waiting for page to load...")
        time.sleep(10)  # Extra time for headless mode
        wait_for_page_load(driver)

        # Save debug screenshot
        screenshot_path = os.path.join(SCRIPT_DIR, "debug_mvc_screenshot.png")
        driver.save_screenshot(screenshot_path)
        print(f"Debug screenshot saved: {screenshot_path}")

        # 2. Set Y-Axis to Maker
        print("\n1. Setting Y-Axis to 'Maker'...")
        if not select_dropdown_by_id(driver, "yaxisVar", "Maker"):
            print("   WARNING: Failed to set Y-Axis")
        time.sleep(1)

        # 3. Set X-Axis to Vehicle Class
        print("\n2. Setting X-Axis to 'Vehicle Class'...")
        if not select_dropdown_by_id(driver, "xaxisVar", "Vehicle Class"):
            print("   WARNING: Failed to set X-Axis")
        time.sleep(1)

        # Save screenshot after axis selection
        driver.save_screenshot(os.path.join(SCRIPT_DIR, "debug_mvc_after_axis.png"))

        # 4. Set Year Type to Calendar Year
        print("\n3. Setting Year Type to 'Calendar Year'...")
        select_dropdown_by_id(driver, "selectedYearType", "Calendar")
        time.sleep(1)

        # 5. Set Year
        print(f"\n4. Setting Year to '{year}'...")
        select_dropdown_by_id(driver, "selectedYear", str(year))
        time.sleep(1)

        # 6. Click Refresh button
        print("\n5. Clicking Refresh button...")
        _click_refresh(driver)

        # 7. Wait for data to load
        print("\nWaiting for data to load...")
        time.sleep(5)

        # Save screenshot after refresh
        driver.save_screenshot(os.path.join(SCRIPT_DIR, "debug_mvc_after_refresh.png"))

        # 8. Select month from groupingTable:selectMonth
        print(f"\n6. Selecting month '{month_abbr}' from table dropdown...")
        _select_month(driver, month_abbr)

        # 9. Click download icon
        print("\n7. Looking for download icon...")
        download_found = _click_download(driver)

        # 10. Wait for download and move file
        if download_found:
            print("\n8. Waiting for download to complete...")
            _wait_and_move_file(temp_download_dir, year, month)
        else:
            print("\n8. No download icon found.")
            driver.save_screenshot(os.path.join(SCRIPT_DIR, "debug_mvc_no_download.png"))

    except Exception as e:
        print(f"\nError: {e}")
        try:
            driver.save_screenshot(os.path.join(SCRIPT_DIR, "debug_mvc_error.png"))
            print("Error screenshot saved")
        except:
            pass
        raise

    finally:
        driver.quit()
        if os.path.exists(temp_download_dir):
            shutil.rmtree(temp_download_dir)
        print("\nBrowser closed")


def download_legacy():
    """Download data for Jan 2025 through Jan 2026 (13 months)."""
    months_to_download = []
    # Jan 2025 - Dec 2025
    for m in range(1, 13):
        months_to_download.append((2025, m))
    # Jan 2026
    months_to_download.append((2026, 1))

    print(f"Legacy download (headless): {len(months_to_download)} months")
    for year, month in months_to_download:
        print(f"\n>>> {MONTH_ABBRS[month - 1]} {year} <<<")
        download_month(year, month)
        # Pause between downloads to avoid rate limiting
        print("Pausing before next download...")
        time.sleep(5)

    print(f"\nLegacy download complete. Files saved to: {OUTPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Download Maker x Vehicle Class data from Vahan dashboard (headless mode)."
    )
    parser.add_argument("--year", type=int, help="Year to download (e.g. 2026)")
    parser.add_argument("--month", type=int, help="Month to download (1-12)")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Download Jan-Dec 2025 + Jan 2026 (13 months)",
    )
    args = parser.parse_args()

    if args.legacy:
        download_legacy()
    elif args.year and args.month:
        if not 1 <= args.month <= 12:
            print("Error: month must be between 1 and 12")
            return
        download_month(args.year, args.month)
    else:
        parser.print_help()
        print("\nError: provide --year and --month, or --legacy")


if __name__ == "__main__":
    main()
