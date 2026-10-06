"""
Vahan Dashboard Data Downloader - Headless Version
Downloads Maker-wise Fuel data from the Vahan Parivahan dashboard
Designed to run on UI-less servers (no display required)
"""

import os
import time
import shutil
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd


def setup_headless_driver(download_dir):
    """Setup Chrome driver in headless mode for UI-less servers"""
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
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Download preferences
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Enable downloads in headless mode (required for Chrome headless)
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": download_dir
    })

    # Hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver


def wait_for_page_load(driver, timeout=30):
    """Wait for page to fully load"""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def select_dropdown_by_id(driver, dropdown_id, option_text, retry=3):
    """Select an option from a PrimeFaces dropdown by ID"""
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


def wait_for_download(download_dir, timeout=60):
    """Wait for a file to be downloaded"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files = os.listdir(download_dir)
        # Filter out partial downloads
        completed_files = [f for f in files
                         if (f.endswith('.csv') or f.endswith('.xlsx') or f.endswith('.xls'))
                         and not f.endswith('.crdownload')
                         and not f.endswith('.tmp')]
        if completed_files:
            # Wait a bit more to ensure file is completely written
            time.sleep(2)
            return completed_files[0]
        time.sleep(1)
    return None


def download_vahan_data_headless():
    """Main function to download Vahan data in headless mode"""

    # Calculate date for filters (current_date - 1 day)
    yesterday = datetime.now() - timedelta(days=1)
    target_year = str(yesterday.year)
    target_month_abbr = yesterday.strftime("%b").upper()  # Abbreviated month (e.g., JAN)

    print(f"=" * 60)
    print(f"Vahan Data Downloader - Headless Mode")
    print(f"=" * 60)
    print(f"Target date: {target_month_abbr} {target_year}")
    print(f"Running in headless mode (no browser window)")

    # Setup paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    download_dir = os.path.join(script_dir, "vahan_data")
    temp_download_dir = os.path.join(script_dir, "temp_downloads")

    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(temp_download_dir, exist_ok=True)

    # Clean temp directory
    for f in os.listdir(temp_download_dir):
        os.remove(os.path.join(temp_download_dir, f))

    driver = setup_headless_driver(temp_download_dir)

    try:
        # Navigate to the Vahan dashboard
        url = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"
        print(f"\nNavigating to: {url}")
        driver.get(url)

        print("Waiting for page to load...")
        time.sleep(10)  # Give extra time in headless mode
        wait_for_page_load(driver)

        # Take a screenshot for debugging (optional)
        screenshot_path = os.path.join(script_dir, "debug_screenshot.png")
        driver.save_screenshot(screenshot_path)
        print(f"Debug screenshot saved: {screenshot_path}")

        print("\n--- Setting Filters ---")

        # 1. Set Y-Axis to Maker
        print("\n1. Setting Y-Axis to 'Maker'...")
        if not select_dropdown_by_id(driver, "yaxisVar", "Maker"):
            print("   WARNING: Failed to set Y-Axis")
        time.sleep(1)

        # 2. Set X-Axis to Fuel
        print("\n2. Setting X-Axis to 'Fuel'...")
        if not select_dropdown_by_id(driver, "xaxisVar", "Fuel"):
            print("   WARNING: Failed to set X-Axis")
        time.sleep(1)

        # Take screenshot after axis selection
        driver.save_screenshot(os.path.join(script_dir, "debug_after_axis.png"))

        # 3. Year Type should already be Calendar Year, but let's confirm
        print("\n3. Verifying Year Type is 'Calendar Year'...")
        select_dropdown_by_id(driver, "selectedYearType", "Calendar")
        time.sleep(1)

        # 4. Set Year
        print(f"\n4. Setting Year to '{target_year}'...")
        select_dropdown_by_id(driver, "selectedYear", target_year)
        time.sleep(1)

        # 5. Click Refresh button
        print("\n5. Clicking Refresh button...")
        try:
            refresh_btn = driver.find_element(By.XPATH, "//button[contains(@id, 'refresh') or .//span[contains(text(), 'Refresh')]]")
            driver.execute_script("arguments[0].click();", refresh_btn)
            print("   Clicked refresh button")
            time.sleep(5)
        except:
            # Try finding by text
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if "Refresh" in btn.text:
                    driver.execute_script("arguments[0].click();", btn)
                    print("   Clicked refresh button")
                    time.sleep(5)
                    break

        # Wait for data to load
        print("\nWaiting for data to load...")
        time.sleep(5)

        # Take another screenshot after refresh
        driver.save_screenshot(os.path.join(script_dir, "debug_after_refresh.png"))

        # 6. Select month from dropdown near the table
        print(f"\n6. Selecting month '{target_month_abbr}' from table dropdown...")
        try:
            month_dropdown_id = "groupingTable:selectMonth"
            month_dropdown = driver.find_element(By.ID, month_dropdown_id)
            label = month_dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
            print(f"   Found month dropdown, current value: '{label.text}'")

            driver.execute_script("arguments[0].click();", label)
            time.sleep(1)

            panel = driver.find_element(By.ID, f"{month_dropdown_id}_panel")
            WebDriverWait(driver, 5).until(EC.visibility_of(panel))

            options = panel.find_elements(By.TAG_NAME, "li")
            option_texts = [opt.text for opt in options]
            print(f"   Available options: {option_texts}")

            month_selected = False
            for opt in options:
                if target_month_abbr in opt.text.upper():
                    driver.execute_script("arguments[0].click();", opt)
                    print(f"   Selected month: {opt.text}")
                    month_selected = True
                    time.sleep(2)
                    break

            if not month_selected:
                print(f"   Month '{target_month_abbr}' not found in options")
                driver.find_element(By.TAG_NAME, "body").click()
                time.sleep(0.5)

        except Exception as e:
            print(f"   Error selecting month: {e}")

        # 7. Find and click CSV/Excel download icon
        print("\n7. Looking for download icon...")
        download_found = False

        try:
            # Common selectors for download icons
            csv_selectors = [
                "//img[contains(@src, 'csv') or contains(@alt, 'csv') or contains(@alt, 'CSV')]",
                "//a[contains(@href, 'csv') or contains(@title, 'csv') or contains(@title, 'CSV')]",
                "//img[contains(@src, 'excel') or contains(@alt, 'excel') or contains(@alt, 'Excel')]",
                "//img[contains(@title, 'Excel') or contains(@title, 'Download') or contains(@title, 'Export')]",
                "//*[contains(@onclick, 'csv') or contains(@onclick, 'CSV')]",
                "//a[contains(@id, 'csv') or contains(@class, 'csv')]",
                "//a[.//img]",
            ]

            for selector in csv_selectors:
                try:
                    elements = driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            elem_tag = elem.tag_name
                            elem_src = elem.get_attribute("src") or ""
                            elem_alt = elem.get_attribute("alt") or ""
                            elem_title = elem.get_attribute("title") or ""
                            combined = (elem_src + elem_alt + elem_title).lower()

                            if any(x in combined for x in ['csv', 'download', 'excel', 'export']):
                                print(f"   Found: {elem_tag}, src={elem_src}, alt={elem_alt}, title={elem_title}")
                                driver.execute_script("arguments[0].click();", elem)
                                print("   Download icon clicked!")
                                download_found = True
                                break
                    if download_found:
                        break
                except:
                    continue

            # Fallback: look for any images that might be download icons
            if not download_found:
                print("   Searching for any download/export icons...")
                all_images = driver.find_elements(By.TAG_NAME, "img")
                for img in all_images:
                    src = img.get_attribute("src") or ""
                    alt = img.get_attribute("alt") or ""
                    title = img.get_attribute("title") or ""
                    combined = (src + alt + title).lower()

                    if img.is_displayed() and any(x in combined for x in ['csv', 'xls', 'excel', 'download', 'export']):
                        print(f"   Found image: src={src}, alt={alt}")
                        driver.execute_script("arguments[0].click();", img)
                        download_found = True
                        break

        except Exception as e:
            print(f"   Error finding download icon: {e}")

        # 8. Wait for download to complete
        if download_found:
            print("\n8. Waiting for download to complete...")
            downloaded_file = wait_for_download(temp_download_dir, timeout=60)

            if downloaded_file:
                print(f"   Download complete: {downloaded_file}")
            else:
                print("   Download timeout - file may not have downloaded")
        else:
            print("\n8. No download icon found. Taking screenshot for debugging...")
            driver.save_screenshot(os.path.join(script_dir, "debug_no_download.png"))

        # 9. Process downloaded files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        downloaded_files = os.listdir(temp_download_dir)

        for file in downloaded_files:
            if file.endswith(('.xlsx', '.xls', '.csv')):
                src_path = os.path.join(temp_download_dir, file)
                name, ext = os.path.splitext(file)
                new_filename = f"{name}_{timestamp}"

                if ext in ('.xlsx', '.xls'):
                    # Convert xlsx/xls to csv
                    df = pd.read_excel(src_path, header=None)
                    csv_path = os.path.join(download_dir, f"{new_filename}.csv")
                    df.to_csv(csv_path, index=False, header=False)
                    print(f"\nConverted and saved to: {csv_path}")
                    os.remove(src_path)
                else:
                    # Already CSV, just move it
                    dest_path = os.path.join(download_dir, f"{new_filename}.csv")
                    shutil.move(src_path, dest_path)
                    print(f"\nDownloaded file saved to: {dest_path}")

        print("\n" + "=" * 60)
        print("Download process completed")
        print("=" * 60)

    except Exception as e:
        print(f"\nError: {e}")
        # Save screenshot on error
        try:
            driver.save_screenshot(os.path.join(script_dir, "debug_error.png"))
            print("Error screenshot saved")
        except:
            pass
        raise

    finally:
        driver.quit()
        # Clean up temp directory
        if os.path.exists(temp_download_dir):
            shutil.rmtree(temp_download_dir)
        print("\nBrowser closed")


if __name__ == "__main__":
    download_vahan_data_headless()
