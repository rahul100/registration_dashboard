"""
Vahan Dashboard Data Downloader
Downloads Maker-wise Fuel data from the Vahan Parivahan dashboard
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
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd


def setup_driver(download_dir):
    """Setup Chrome driver with download preferences"""
    chrome_options = Options()

    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def wait_for_page_load(driver, timeout=30):
    """Wait for page to fully load"""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def select_dropdown_by_id(driver, dropdown_id, option_text):
    """Select an option from a PrimeFaces dropdown by ID"""
    try:
        dropdown = driver.find_element(By.ID, dropdown_id)
        label = dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
        print(f"   Current value: {label.text}")
        label.click()
        time.sleep(1)

        panel = driver.find_element(By.ID, f"{dropdown_id}_panel")
        options = panel.find_elements(By.TAG_NAME, "li")
        for opt in options:
            if option_text in opt.text:
                opt.click()
                print(f"   Selected: {opt.text}")
                time.sleep(1)
                return True
        print(f"   Option '{option_text}' not found")
        return False
    except Exception as e:
        print(f"   Error: {e}")
        return False


def scrape_table_data(driver):
    """Scrape data from the table on the page"""
    try:
        # Wait for table to be present
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.ui-datatable-data, tbody[id$='_data']"))
        )

        # Find the data table
        tables = driver.find_elements(By.CSS_SELECTOR, "table")
        print(f"   Found {len(tables)} tables on page")

        # Look for the data table with maker data
        for table in tables:
            table_id = table.get_attribute("id") or ""
            if "_data" in table_id or "datatable" in table_id.lower():
                print(f"   Processing table: {table_id}")

                # Get headers
                headers = []
                header_row = table.find_elements(By.CSS_SELECTOR, "thead th")
                if not header_row:
                    # Try getting headers from parent container
                    parent = table.find_element(By.XPATH, "./ancestor::div[contains(@class, 'ui-datatable')]")
                    header_row = parent.find_elements(By.CSS_SELECTOR, "thead th")

                for th in header_row:
                    headers.append(th.text.strip())
                print(f"   Headers: {headers}")

                # Get data rows
                rows = table.find_elements(By.TAG_NAME, "tr")
                data = []
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if cells:
                        row_data = [cell.text.strip() for cell in cells]
                        if any(row_data):  # Skip empty rows
                            data.append(row_data)

                if data:
                    print(f"   Found {len(data)} data rows")
                    return headers, data

        # If no table found with standard selectors, try tbody directly
        tbody = driver.find_element(By.CSS_SELECTOR, "tbody[id$='_data']")
        rows = tbody.find_elements(By.TAG_NAME, "tr")

        # Get headers from thead
        thead = driver.find_element(By.CSS_SELECTOR, "thead")
        header_cells = thead.find_elements(By.TAG_NAME, "th")
        headers = [th.text.strip() for th in header_cells]

        data = []
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if cells:
                row_data = [cell.text.strip() for cell in cells]
                if any(row_data):
                    data.append(row_data)

        return headers, data

    except Exception as e:
        print(f"   Error scraping table: {e}")
        return [], []


def scroll_and_collect_all_data(driver):
    """Scroll through the table and collect all data (for paginated tables)"""
    all_data = []
    headers = []
    seen_rows = set()

    try:
        # First, try to find how many pages or if there's pagination
        while True:
            # Scrape current page data
            current_headers, current_data = scrape_table_data(driver)

            if current_headers and not headers:
                headers = current_headers

            # Add new rows (avoid duplicates)
            for row in current_data:
                row_key = tuple(row)
                if row_key not in seen_rows:
                    seen_rows.add(row_key)
                    all_data.append(row)

            # Try to find and click "next" pagination button
            try:
                next_buttons = driver.find_elements(By.CSS_SELECTOR, "span.ui-paginator-next, a.ui-paginator-next")
                clicked_next = False
                for btn in next_buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        # Check if it's not disabled
                        btn_class = btn.get_attribute("class") or ""
                        if "ui-state-disabled" not in btn_class:
                            btn.click()
                            time.sleep(2)
                            clicked_next = True
                            break

                if not clicked_next:
                    break  # No more pages
            except:
                break  # No pagination or error

            # Safety check - don't loop infinitely
            if len(all_data) > 10000:
                break

    except Exception as e:
        print(f"   Error during pagination: {e}")

    return headers, all_data


def download_vahan_data():
    """Main function to download Vahan data"""

    # Calculate date for filters (current_date - 1 day)
    yesterday = datetime.now() - timedelta(days=1)
    target_year = str(yesterday.year)
    target_month_full = yesterday.strftime("%B")  # Full month name (e.g., January)
    target_month_abbr = yesterday.strftime("%b").upper()  # Abbreviated month (e.g., JAN)

    print(f"Target date: {target_month_abbr} {target_year}")

    # Setup paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    download_dir = os.path.join(script_dir, "vahan_data")
    temp_download_dir = os.path.join(script_dir, "temp_downloads")

    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(temp_download_dir, exist_ok=True)

    driver = setup_driver(temp_download_dir)

    try:
        # Navigate to the Vahan dashboard
        url = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"
        print(f"Navigating to: {url}")
        driver.get(url)

        print("Waiting for page to load...")
        time.sleep(8)
        wait_for_page_load(driver)

        print("\n--- Setting Filters ---")

        # 1. Set Y-Axis to Maker
        print("\n1. Setting Y-Axis to 'Maker'...")
        select_dropdown_by_id(driver, "yaxisVar", "Maker")

        # 2. Set X-Axis to Fuel
        print("\n2. Setting X-Axis to 'Fuel'...")
        select_dropdown_by_id(driver, "xaxisVar", "Fuel")

        # 3. Year Type should already be Calendar Year, but let's confirm
        print("\n3. Verifying Year Type is 'Calendar Year'...")
        select_dropdown_by_id(driver, "selectedYearType", "Calendar")

        # 4. Set Year
        print(f"\n4. Setting Year to '{target_year}'...")
        select_dropdown_by_id(driver, "selectedYear", target_year)

        # 5. Look for month dropdown - might be in different locations
        print(f"\n5. Looking for Month selector...")
        try:
            # Check for various month dropdown IDs
            month_ids = ["selectedMonth", "groupingTable:selectedMonth", "j_idt85"]
            month_found = False
            for month_id in month_ids:
                try:
                    month_dropdown = driver.find_element(By.ID, month_id)
                    print(f"   Found month dropdown with ID: {month_id}")
                    select_dropdown_by_id(driver, month_id, target_month)
                    month_found = True
                    break
                except:
                    continue

            if not month_found:
                # Look for dropdown near the table header that might contain months
                all_dropdowns = driver.find_elements(By.CSS_SELECTOR, "div.ui-selectonemenu")
                for dd in all_dropdowns:
                    dd_id = dd.get_attribute("id")
                    try:
                        label = dd.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
                        label_text = label.text
                        # Check if this looks like a month dropdown (V26 might be version)
                        if any(m in label_text for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]):
                            print(f"   Found month dropdown: {dd_id} with value {label_text}")
                            select_dropdown_by_id(driver, dd_id, target_month)
                            month_found = True
                            break
                    except:
                        continue

            if not month_found:
                print("   Month dropdown not found - might be auto-selected or not available")

        except Exception as e:
            print(f"   Note on Month selection: {e}")

        # 6. Click Refresh button
        print("\n6. Clicking Refresh button...")
        try:
            refresh_btn = driver.find_element(By.XPATH, "//button[contains(@id, 'refresh') or .//span[contains(text(), 'Refresh')]]")
            refresh_btn.click()
            print("   Clicked refresh button")
            time.sleep(5)
        except:
            # Try finding by text
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if "Refresh" in btn.text:
                    btn.click()
                    print("   Clicked refresh button")
                    time.sleep(5)
                    break

        # Wait for data to load
        print("\nWaiting for data to load...")
        time.sleep(5)

        # 7. Select month from dropdown near the table (groupingTable:selectMonth)
        print(f"\n7. Selecting month '{target_month_abbr}' from table dropdown...")
        try:
            # The month dropdown ID is groupingTable:selectMonth
            month_dropdown_id = "groupingTable:selectMonth"

            month_dropdown = driver.find_element(By.ID, month_dropdown_id)
            label = month_dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
            print(f"   Found month dropdown, current value: '{label.text}'")

            # Click to open
            label.click()
            time.sleep(1)

            # Find and click the target month (using abbreviated name like JAN, FEB, etc.)
            panel = driver.find_element(By.ID, f"{month_dropdown_id}_panel")
            options = panel.find_elements(By.TAG_NAME, "li")
            option_texts = [opt.text for opt in options]
            print(f"   Available options: {option_texts}")

            month_selected = False
            for opt in options:
                if target_month_abbr in opt.text.upper():
                    opt.click()
                    print(f"   Selected month: {opt.text}")
                    month_selected = True
                    time.sleep(2)
                    break

            if not month_selected:
                print(f"   Month '{target_month_abbr}' not found in options")
                # Close dropdown
                driver.find_element(By.TAG_NAME, "body").click()
                time.sleep(0.5)

        except Exception as e:
            print(f"   Error selecting month: {e}")

        # 8. Find and click CSV download icon (green icon)
        print("\n8. Looking for CSV download icon...")
        download_found = False

        try:
            # Look for CSV icon - typically an image or link with csv-related attributes
            csv_selectors = [
                "//img[contains(@src, 'csv') or contains(@alt, 'csv') or contains(@alt, 'CSV')]",
                "//a[contains(@href, 'csv') or contains(@title, 'csv') or contains(@title, 'CSV')]",
                "//img[contains(@src, 'green') or contains(@class, 'csv')]",
                "//*[contains(@onclick, 'csv') or contains(@onclick, 'CSV')]",
                "//a[contains(@id, 'csv') or contains(@class, 'csv')]",
                "//button[contains(@id, 'csv') or contains(@title, 'CSV')]",
                "//span[contains(@class, 'csv')]/parent::*",
                "//img[contains(@title, 'Excel') or contains(@title, 'Download')]",
                "//a[.//img]",  # Links containing images
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
                            print(f"   Found element: {elem_tag}, src={elem_src}, alt={elem_alt}, title={elem_title}")

                            # Click if it looks like a CSV/download icon
                            if any(x in (elem_src + elem_alt + elem_title).lower() for x in ['csv', 'download', 'excel', 'export']):
                                elem.click()
                                print("   CSV download icon clicked!")
                                download_found = True
                                time.sleep(10)
                                break
                    if download_found:
                        break
                except:
                    continue

            # If still not found, look for any green-colored icons or images near the table
            if not download_found:
                print("   Looking for any download/export icons...")
                all_images = driver.find_elements(By.TAG_NAME, "img")
                all_links = driver.find_elements(By.TAG_NAME, "a")

                for img in all_images:
                    src = img.get_attribute("src") or ""
                    alt = img.get_attribute("alt") or ""
                    title = img.get_attribute("title") or ""
                    if img.is_displayed() and any(x in (src + alt + title).lower() for x in ['csv', 'xls', 'excel', 'download', 'export']):
                        print(f"   Found image: src={src}, alt={alt}")
                        img.click()
                        download_found = True
                        time.sleep(10)
                        break

                if not download_found:
                    for link in all_links:
                        href = link.get_attribute("href") or ""
                        title = link.get_attribute("title") or ""
                        onclick = link.get_attribute("onclick") or ""
                        if link.is_displayed() and any(x in (href + title + onclick).lower() for x in ['csv', 'xls', 'excel', 'download', 'export']):
                            print(f"   Found link: href={href}, title={title}")
                            link.click()
                            download_found = True
                            time.sleep(10)
                            break

        except Exception as e:
            print(f"   Error finding download icon: {e}")

        # 9. Wait for download to complete and move file
        if download_found:
            print("\n9. Waiting for download to complete...")
            # Wait for file to appear in temp directory
            max_wait = 30
            waited = 0
            while waited < max_wait:
                files = os.listdir(temp_download_dir)
                csv_files = [f for f in files if f.endswith('.csv') and not f.endswith('.crdownload')]
                if csv_files:
                    print(f"   Download complete: {csv_files[0]}")
                    break
                time.sleep(1)
                waited += 1

            if waited >= max_wait:
                print("   Download may still be in progress...")
        else:
            print("\n9. No CSV download icon found. Please check the page manually.")

        # Check for downloaded files in temp directory and convert to CSV
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
                    print(f"Converted and saved to: {csv_path}")
                    os.remove(src_path)
                else:
                    # Already CSV, just move it
                    dest_path = os.path.join(download_dir, f"{new_filename}.csv")
                    shutil.move(src_path, dest_path)
                    print(f"Downloaded file saved to: {dest_path}")

    except Exception as e:
        print(f"\nError: {e}")
        raise

    finally:
        driver.quit()
        if os.path.exists(temp_download_dir):
            shutil.rmtree(temp_download_dir)
        print("\nBrowser closed")


if __name__ == "__main__":
    download_vahan_data()
