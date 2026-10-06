"""
Download Maker x Vehicle Class data from the Vahan Parivahan dashboard.
Downloads monthly totals (Y-Axis: Maker, X-Axis: Vehicle Class).

Usage:
    python download_maker_vehicle_class.py --year 2026 --month 1
    python download_maker_vehicle_class.py --legacy   # downloads Jan-Dec 2025 + Jan 2026
"""

import os
import time
import shutil
import argparse
from datetime import datetime

from selenium.webdriver.common.by import By
import pandas as pd

from vahan_download import setup_driver, wait_for_page_load, select_dropdown_by_id

DASHBOARD_URL = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"

MONTH_ABBRS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "monthly_maker_vehicle_class_data")


def download_month(year, month):
    """Download Maker x Vehicle Class data for a single month.

    Args:
        year: int, e.g. 2026
        month: int, 1-12
    """
    month_abbr = MONTH_ABBRS[month - 1]
    print(f"\n{'='*60}")
    print(f"Downloading Maker x Vehicle Class data for {month_abbr} {year}")
    print(f"{'='*60}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    temp_download_dir = os.path.join(SCRIPT_DIR, "temp_downloads_mvc")
    os.makedirs(temp_download_dir, exist_ok=True)

    driver = setup_driver(temp_download_dir)

    try:
        # 1. Navigate to dashboard
        print(f"Navigating to: {DASHBOARD_URL}")
        driver.get(DASHBOARD_URL)
        print("Waiting for page to load...")
        time.sleep(8)
        wait_for_page_load(driver)

        # 2. Set Y-Axis to Maker
        print("\n1. Setting Y-Axis to 'Maker'...")
        select_dropdown_by_id(driver, "yaxisVar", "Maker")

        # 3. Set X-Axis to Vehicle Class
        print("\n2. Setting X-Axis to 'Vehicle Class'...")
        select_dropdown_by_id(driver, "xaxisVar", "Vehicle Class")

        # 4. Set Year Type to Calendar Year
        print("\n3. Setting Year Type to 'Calendar Year'...")
        select_dropdown_by_id(driver, "selectedYearType", "Calendar")

        # 5. Set Year
        print(f"\n4. Setting Year to '{year}'...")
        select_dropdown_by_id(driver, "selectedYear", str(year))

        # 6. Click Refresh button
        print("\n5. Clicking Refresh button...")
        _click_refresh(driver)

        # 7. Wait for data to load
        print("\nWaiting for data to load...")
        time.sleep(5)

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
            print("\n8. No download icon found. Please check the page manually.")

    except Exception as e:
        print(f"\nError: {e}")
        raise

    finally:
        driver.quit()
        if os.path.exists(temp_download_dir):
            shutil.rmtree(temp_download_dir)
        print("\nBrowser closed")


def _click_refresh(driver):
    """Click the Refresh button on the dashboard."""
    try:
        refresh_btn = driver.find_element(
            By.XPATH,
            "//button[contains(@id, 'refresh') or .//span[contains(text(), 'Refresh')]]",
        )
        refresh_btn.click()
        print("   Clicked refresh button")
        time.sleep(5)
    except Exception:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if "Refresh" in btn.text:
                btn.click()
                print("   Clicked refresh button")
                time.sleep(5)
                break


def _select_month(driver, month_abbr):
    """Select a month from the groupingTable:selectMonth dropdown."""
    try:
        month_dropdown_id = "groupingTable:selectMonth"
        month_dropdown = driver.find_element(By.ID, month_dropdown_id)
        label = month_dropdown.find_element(By.CSS_SELECTOR, "label.ui-selectonemenu-label")
        print(f"   Found month dropdown, current value: '{label.text}'")

        label.click()
        time.sleep(1)

        panel = driver.find_element(By.ID, f"{month_dropdown_id}_panel")
        options = panel.find_elements(By.TAG_NAME, "li")
        option_texts = [opt.text for opt in options]
        print(f"   Available options: {option_texts}")

        month_selected = False
        for opt in options:
            if month_abbr in opt.text.upper():
                opt.click()
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
    """Find and click the CSV/Excel download icon. Returns True if clicked."""
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
                    if any(x in combined for x in ['csv', 'download', 'excel', 'export']):
                        elem.click()
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
        if img.is_displayed() and any(x in combined for x in ['csv', 'xls', 'excel', 'download', 'export']):
            print(f"   Found image: src={src}, alt={alt}")
            img.click()
            time.sleep(10)
            return True

    for link in driver.find_elements(By.TAG_NAME, "a"):
        href = link.get_attribute("href") or ""
        title = link.get_attribute("title") or ""
        onclick = link.get_attribute("onclick") or ""
        combined = (href + title + onclick).lower()
        if link.is_displayed() and any(x in combined for x in ['csv', 'xls', 'excel', 'download', 'export']):
            print(f"   Found link: href={href}, title={title}")
            link.click()
            time.sleep(10)
            return True

    return False


def _wait_and_move_file(temp_download_dir, year, month):
    """Wait for a file to appear in temp dir and move it to OUTPUT_DIR."""
    max_wait = 30
    waited = 0
    while waited < max_wait:
        files = os.listdir(temp_download_dir)
        ready_files = [
            f for f in files
            if f.endswith(('.csv', '.xlsx', '.xls')) and not f.endswith('.crdownload')
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
        if file.endswith(('.xlsx', '.xls', '.csv')):
            src_path = os.path.join(temp_download_dir, file)
            _, ext = os.path.splitext(file)

            if ext in ('.xlsx', '.xls'):
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


def download_legacy():
    """Download data for Jan 2025 through Jan 2026 (13 months)."""
    months_to_download = []
    # Jan 2025 - Dec 2025
    for m in range(1, 13):
        months_to_download.append((2025, m))
    # Jan 2026
    months_to_download.append((2026, 1))

    print(f"Legacy download: {len(months_to_download)} months")
    for year, month in months_to_download:
        print(f"\n>>> {MONTH_ABBRS[month - 1]} {year} <<<")
        download_month(year, month)
        # Pause between downloads to avoid rate limiting
        print("Pausing before next download...")
        time.sleep(5)

    print(f"\nLegacy download complete. Files saved to: {OUTPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Download Maker x Vehicle Class data from Vahan dashboard."
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
