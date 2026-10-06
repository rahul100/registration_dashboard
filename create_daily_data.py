"""
Create daily registration data from cumulative monthly snapshots.
- Each file contains month-to-date totals (resets at start of each month)
- Daily = Current day value - Previous day value
- If previous day missing, interpolate from nearest available file
- Store results in SQLite database
- Supports incremental updates: only reprocesses months affected by new files
"""

import os
import glob
import sqlite3
import argparse
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vahan_data")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vahan_data.db")


def get_all_csv_files():
    """Return sorted list of all CSV file paths in DATA_DIR."""
    return sorted(glob.glob(os.path.join(DATA_DIR, "reportTable_*.csv")))


def get_data_date(filename):
    """Extract the data date from a CSV filename."""
    date_str = filename.split('_')[1]
    file_date = datetime.strptime(date_str, '%Y%m%d').date()
    if '_monthend' in filename:
        return file_date
    else:
        return file_date - timedelta(days=1)


def get_new_files():
    """Return list of CSV filepaths that haven't been processed yet."""
    all_files = get_all_csv_files()

    if not os.path.exists(DB_PATH):
        return all_files

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if processed_files table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='processed_files'"
    )
    if not cursor.fetchone():
        conn.close()
        return all_files

    cursor.execute("SELECT filename FROM processed_files")
    processed = {row[0] for row in cursor.fetchall()}
    conn.close()

    new_files = [f for f in all_files if os.path.basename(f) not in processed]
    return new_files


def get_affected_months(new_files):
    """Determine which (year, month) tuples are affected by the new files."""
    affected = set()
    for filepath in new_files:
        filename = os.path.basename(filepath)
        data_date = get_data_date(filename)
        affected.add((data_date.year, data_date.month))
    return affected


def ensure_database():
    """Create the database and tables if they don't exist."""
    if os.path.exists(DB_PATH):
        # DB exists; ensure processed_files table exists (migration for old DBs)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_files (
                filename TEXT PRIMARY KEY,
                data_date DATE NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE daily_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            maker TEXT NOT NULL,
            metric TEXT NOT NULL,
            daily_value REAL,
            cumulative_value REAL,
            is_interpolated BOOLEAN,
            UNIQUE(date, maker, metric)
        )
    ''')

    cursor.execute('CREATE INDEX idx_date ON daily_registrations(date)')
    cursor.execute('CREATE INDEX idx_maker ON daily_registrations(maker)')
    cursor.execute('CREATE INDEX idx_metric ON daily_registrations(metric)')
    cursor.execute(
        'CREATE INDEX idx_date_maker_metric ON daily_registrations(date, maker, metric)'
    )

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_files (
            filename TEXT PRIMARY KEY,
            data_date DATE NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def load_all_files():
    """Load all CSV files and return dict with date -> dataframe"""
    csv_files = get_all_csv_files()

    files_by_date = {}
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        date = get_data_date(filename)

        df = pd.read_csv(filepath)
        # Convert numeric columns
        for col in df.columns:
            if col not in ['S No', 'Maker', 'Date']:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(',', ''),
                    errors='coerce'
                ).fillna(0)

        files_by_date[date] = df

    return files_by_date


def load_files_for_months(affected_months):
    """Load only the CSV files whose data dates fall within the affected months."""
    csv_files = get_all_csv_files()

    files_by_date = {}
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        date = get_data_date(filename)

        if (date.year, date.month) in affected_months:
            df = pd.read_csv(filepath)
            for col in df.columns:
                if col not in ['S No', 'Maker', 'Date']:
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace(',', ''),
                        errors='coerce'
                    ).fillna(0)
            files_by_date[date] = df

    return files_by_date


def get_month_key(date):
    """Get year-month key for grouping"""
    return (date.year, date.month)


def calculate_daily_data(files_by_date, month_filter=None):
    """Calculate daily registration numbers from cumulative data.

    Args:
        files_by_date: dict of date -> dataframe
        month_filter: optional set of (year, month) tuples to process.
                      If None, process all months.
    """

    # Group files by month
    months = defaultdict(list)
    for date in sorted(files_by_date.keys()):
        months[get_month_key(date)].append(date)

    daily_records = []
    numeric_cols = None

    for month_key, dates in sorted(months.items()):
        if month_filter is not None and month_key not in month_filter:
            continue

        dates = sorted(dates)
        print(f"\nProcessing {month_key[0]}-{month_key[1]:02d}: {len(dates)} files")

        for i, current_date in enumerate(dates):
            current_df = files_by_date[current_date]

            # Get numeric columns (exclude S No, Maker)
            if numeric_cols is None:
                numeric_cols = [col for col in current_df.columns
                               if col not in ['S No', 'Maker', 'Date']]

            if i == 0:
                # First file of month - cumulative from day 1 to this day
                # Divide by day of month to get estimated daily average
                day_of_month = current_date.day

                for _, row in current_df.iterrows():
                    maker = row['Maker']
                    for col in numeric_cols:
                        value = row[col]
                        # Divide by day of month to estimate daily registrations
                        if day_of_month > 0:
                            daily_value = value / day_of_month
                        else:
                            daily_value = value

                        # Fill in all days from start of month to current_date
                        month_start = current_date.replace(day=1)
                        for d in range(day_of_month):
                            fill_date = month_start + timedelta(days=d)
                            # Calculate cumulative value for this day
                            cumulative_for_day = daily_value * (d + 1)
                            # Last day (actual file date) is not interpolated, earlier days are
                            is_last_day = (d == day_of_month - 1)
                            daily_records.append({
                                'date': fill_date,
                                'maker': maker,
                                'metric': col,
                                'daily_value': round(daily_value),
                                'cumulative_value': round(cumulative_for_day) if not is_last_day else value,
                                'is_interpolated': not is_last_day
                            })
            else:
                # Calculate difference from previous available date
                prev_date = dates[i - 1]
                prev_df = files_by_date[prev_date]

                # Days between files
                days_diff = (current_date - prev_date).days

                # Get common numeric columns between both dataframes
                common_cols = [col for col in numeric_cols
                              if col in current_df.columns and col in prev_df.columns]

                # Merge on Maker to calculate difference
                merged = current_df.merge(
                    prev_df[['Maker'] + common_cols],
                    on='Maker',
                    suffixes=('_curr', '_prev'),
                    how='outer'
                )

                for _, row in merged.iterrows():
                    maker = row['Maker']
                    for col in common_cols:
                        curr_val = row.get(f'{col}_curr', 0)
                        prev_val = row.get(f'{col}_prev', 0)
                        # Handle NaN values
                        if pd.isna(curr_val):
                            curr_val = 0
                        if pd.isna(prev_val):
                            prev_val = 0

                        diff = curr_val - prev_val

                        # If multiple days between files, divide by days
                        if days_diff > 1:
                            daily_value = diff / days_diff
                            is_interpolated = True
                        else:
                            daily_value = diff
                            is_interpolated = False

                        # Handle negative or NaN values
                        if pd.isna(daily_value) or daily_value < 0:
                            daily_value = 0

                        # Fill in all days from prev_date+1 to current_date
                        for d in range(days_diff):
                            fill_date = prev_date + timedelta(days=d + 1)
                            # Calculate cumulative value for this day
                            cumulative_for_day = prev_val + daily_value * (d + 1)
                            daily_records.append({
                                'date': fill_date,
                                'maker': maker,
                                'metric': col,
                                'daily_value': round(daily_value),
                                'cumulative_value': round(cumulative_for_day) if d < days_diff - 1 else curr_val,
                                'is_interpolated': is_interpolated if d == days_diff - 1 else True
                            })

        print(f"  Processed {len(dates)} dates, {len(set(r['maker'] for r in daily_records if r['date'] in dates))} makers")

    return daily_records


def delete_months(conn, affected_months):
    """Delete all records for the given months from daily_registrations."""
    cursor = conn.cursor()
    for year, month in affected_months:
        month_start = f"{year:04d}-{month:02d}-01"
        if month == 12:
            next_month_start = f"{year + 1:04d}-01-01"
        else:
            next_month_start = f"{year:04d}-{month + 1:02d}-01"
        cursor.execute(
            "DELETE FROM daily_registrations WHERE date >= ? AND date < ?",
            (month_start, next_month_start)
        )
        deleted = cursor.rowcount
        print(f"  Deleted {deleted:,} existing records for {year}-{month:02d}")
    conn.commit()


def insert_records(conn, daily_records):
    """Insert daily records into the database."""
    cursor = conn.cursor()
    insert_sql = '''
        INSERT OR REPLACE INTO daily_registrations
        (date, maker, metric, daily_value, cumulative_value, is_interpolated)
        VALUES (?, ?, ?, ?, ?, ?)
    '''

    batch = []
    for record in daily_records:
        batch.append((
            record['date'].isoformat(),
            record['maker'],
            record['metric'],
            record['daily_value'],
            record['cumulative_value'],
            record['is_interpolated']
        ))

        if len(batch) >= 10000:
            cursor.executemany(insert_sql, batch)
            batch = []

    if batch:
        cursor.executemany(insert_sql, batch)

    conn.commit()


def update_processed_files(conn, new_files):
    """Record newly processed files in the processed_files table."""
    cursor = conn.cursor()
    for filepath in new_files:
        filename = os.path.basename(filepath)
        data_date = get_data_date(filename)
        cursor.execute(
            "INSERT OR REPLACE INTO processed_files (filename, data_date) VALUES (?, ?)",
            (filename, data_date.isoformat())
        )
    conn.commit()


def print_db_stats(conn):
    """Print database statistics."""
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM daily_registrations')
    total_records = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(DISTINCT date) FROM daily_registrations')
    total_dates = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(DISTINCT maker) FROM daily_registrations')
    total_makers = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(DISTINCT metric) FROM daily_registrations')
    total_metrics = cursor.fetchone()[0]

    print(f"\n{'='*60}")
    print(f"Database: {DB_PATH}")
    print(f"{'='*60}")
    print(f"Total records: {total_records:,}")
    print(f"Unique dates: {total_dates}")
    print(f"Unique makers: {total_makers}")
    print(f"Unique metrics: {total_metrics}")

    print(f"\nTop 10 makers by total EV_Total daily registrations:")
    cursor.execute('''
        SELECT maker, SUM(daily_value) as total
        FROM daily_registrations
        WHERE metric = 'EV_Total'
        GROUP BY maker
        ORDER BY total DESC
        LIMIT 10
    ''')
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]:,.0f}")


def full_rebuild():
    """Delete DB and rebuild from scratch (original behavior)."""
    print("Full rebuild requested. Deleting existing database...")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    ensure_database()

    print("Loading all files...")
    files_by_date = load_all_files()
    print(f"Loaded {len(files_by_date)} files")
    print(f"Date range: {min(files_by_date.keys())} to {max(files_by_date.keys())}")

    print("\nCalculating daily data...")
    daily_records = calculate_daily_data(files_by_date)
    print(f"\nTotal daily records: {len(daily_records):,}")

    print("\nWriting to database...")
    conn = sqlite3.connect(DB_PATH)
    insert_records(conn, daily_records)
    update_processed_files(conn, get_all_csv_files())
    print_db_stats(conn)
    conn.close()


def incremental_update():
    """Only reprocess months affected by new files."""
    ensure_database()

    new_files = get_new_files()
    if not new_files:
        print("Database is up to date. No new files to process.")
        return

    print(f"Found {len(new_files)} new file(s):")
    for f in new_files:
        print(f"  {os.path.basename(f)}")

    affected_months = get_affected_months(new_files)
    print(f"\nAffected months: {', '.join(f'{y}-{m:02d}' for y, m in sorted(affected_months))}")

    # Load all files for the affected months (not just new ones)
    # because daily calculation needs the full month context
    print("\nLoading files for affected months...")
    files_by_date = load_files_for_months(affected_months)
    print(f"Loaded {len(files_by_date)} files for affected months")

    print("\nCalculating daily data for affected months...")
    daily_records = calculate_daily_data(files_by_date, month_filter=affected_months)
    print(f"\nRecords to insert: {len(daily_records):,}")

    print("\nUpdating database...")
    conn = sqlite3.connect(DB_PATH)
    delete_months(conn, affected_months)
    insert_records(conn, daily_records)
    update_processed_files(conn, new_files)
    print_db_stats(conn)
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Create daily registration data from cumulative monthly snapshots."
    )
    parser.add_argument(
        '--rebuild', action='store_true',
        help='Force a full rebuild of the database (delete and reprocess all files)'
    )
    args = parser.parse_args()

    if args.rebuild:
        full_rebuild()
    else:
        incremental_update()

    print("\nDone!")


if __name__ == "__main__":
    main()
