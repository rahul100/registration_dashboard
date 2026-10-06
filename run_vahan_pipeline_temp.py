"""
Vahan Data Pipeline Runner
1. Downloads data from Vahan dashboard (Maker x Fuel - daily)
2. Downloads Maker x Vehicle Class data (monthly, on 1st of month)
3. Cleans and processes the data
4. Creates daily registration data in SQLite
"""

import subprocess
import sys
import os
from datetime import datetime, timedelta


def is_first_of_month():
    """Check if today is the first day of the month"""
    return datetime.now().day == 1


def get_previous_month():
    """Get year and month for the previous month"""
    today = datetime.now()
    first_of_this_month = today.replace(day=1)
    last_month = first_of_this_month - timedelta(days=1)
    return last_month.year, last_month.month


def run_script(script_name, args=None):
    """Run a Python script and return success status"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, script_name)

    print(f"\n{'='*60}")
    print(f"Running: {script_name}")
    print('='*60)

    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)

    result = subprocess.run(cmd, cwd=script_dir)

    return result.returncode == 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vahan Data Pipeline Runner")
    parser.add_argument(
        '--rebuild', action='store_true',
        help='Force a full rebuild of the daily data database'
    )
    args = parser.parse_args()

    print("Vahan Data Pipeline")
    print("="*60)

    # Step 1: Download daily Maker x Fuel data
    if not run_script("vahan_daily_download_v2.py"):
        print("\nDaily download failed!")
        sys.exit(1)

    # Step 2: Download Maker x Vehicle Class data (on 1st of month only)
    if is_first_of_month():
        year, month = get_previous_month()
        print(f"\nFirst of month - downloading Maker x Vehicle Class for {year}-{month:02d}")
        if not run_script("download_maker_vehicle_class_v2.py", ["--year", str(year), "--month", str(month)]):
            print("\nMaker x Vehicle Class download failed!")
            sys.exit(1)
    else:
        print(f"\nNot first of month (day={datetime.now().day}), skipping Maker x Vehicle Class download")

    # Step 3: Clean data
    if not run_script("clean_vahan_data.py"):
        print("\nData cleaning failed!")
        sys.exit(1)

    # Step 4: Create daily data in SQLite (incremental by default)
    daily_args = ['--rebuild'] if args.rebuild else None
    if not run_script("create_daily_data.py", args=daily_args):
        print("\nDaily data creation failed!")
        sys.exit(1)

    print("\n" + "="*60)
    print("Pipeline completed successfully!")
    print("="*60)


if __name__ == "__main__":
    main()
