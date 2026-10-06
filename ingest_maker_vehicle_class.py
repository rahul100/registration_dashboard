"""
Ingest Maker x Vehicle Class CSV files into SQLite.

Reads files from monthly_maker_vehicle_class_data/, cleans them,
normalizes (pivots) into relational rows, and stores in vahan_data.db.

Usage:
    python ingest_maker_vehicle_class.py              # process new files only
    python ingest_maker_vehicle_class.py --rebuild    # drop tables and reprocess all
"""

import os
import glob
import sqlite3
import argparse
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "monthly_maker_vehicle_class_data")
DB_PATH = os.path.join(SCRIPT_DIR, "vahan_data.db")


def get_all_files():
    """Return sorted list of CSV/Excel files in DATA_DIR."""
    patterns = [
        os.path.join(DATA_DIR, "maker_vehicle_class_*.csv"),
        os.path.join(DATA_DIR, "maker_vehicle_class_*.xlsx"),
    ]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    return sorted(files)


def parse_year_month(filepath):
    """Extract (year, month) from filename like maker_vehicle_class_YYYY_MM.csv."""
    basename = os.path.basename(filepath)
    name, _ = os.path.splitext(basename)
    parts = name.split("_")
    # maker_vehicle_class_YYYY_MM -> parts = ['maker', 'vehicle', 'class', 'YYYY', 'MM']
    year = int(parts[3])
    month = int(parts[4])
    return year, month


def ensure_tables(conn):
    """Create the maker_vehicle_class and processed_vehicle_class_files tables if needed."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maker_vehicle_class (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            maker TEXT NOT NULL,
            vehicle_class TEXT NOT NULL,
            registrations INTEGER DEFAULT 0,
            UNIQUE(year, month, maker, vehicle_class)
        )
    """)

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_mvc_year_month ON maker_vehicle_class(year, month)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_mvc_maker ON maker_vehicle_class(maker)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_mvc_vehicle_class ON maker_vehicle_class(vehicle_class)"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_vehicle_class_files (
            filename TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()


def drop_tables(conn):
    """Drop the maker_vehicle_class and tracking tables."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS maker_vehicle_class")
    cursor.execute("DROP TABLE IF EXISTS processed_vehicle_class_files")
    conn.commit()


def get_processed_files(conn):
    """Return set of already-processed filenames."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='processed_vehicle_class_files'"
    )
    if not cursor.fetchone():
        return set()
    cursor.execute("SELECT filename FROM processed_vehicle_class_files")
    return {row[0] for row in cursor.fetchall()}


def get_new_files(conn):
    """Return list of file paths not yet processed."""
    all_files = get_all_files()
    processed = get_processed_files(conn)
    return [f for f in all_files if os.path.basename(f) not in processed]


def clean_and_normalize(filepath):
    """Read a downloaded file, clean it, and return normalized records.

    Returns list of dicts: [{year, month, maker, vehicle_class, registrations}, ...]
    """
    year, month = parse_year_month(filepath)

    # Read file
    _, ext = os.path.splitext(filepath)
    if ext in (".xlsx", ".xls"):
        df = pd.read_csv(filepath, header=None) if ext == ".csv" else pd.read_excel(filepath, header=None)
    else:
        df = pd.read_csv(filepath, header=None)

    print(f"  Raw shape: {df.shape}")

    # Skip first 3 rows (dashboard metadata)
    df = df.iloc[3:].reset_index(drop=True)

    # Set 4th row (now row 0) as column headers
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)

    # Rename: col[0] -> S No, col[1] -> Maker, col[-1] -> Total
    columns = list(df.columns)
    columns[0] = "S No"
    columns[1] = "Maker"
    columns[-1] = "Total"
    df.columns = columns

    print(f"  Cleaned shape: {df.shape}")
    print(f"  Columns: {list(df.columns)}")

    # Vehicle class columns are everything except S No, Maker, Total
    skip_cols = {"S No", "Maker", "Total"}
    vehicle_class_cols = [c for c in df.columns if c not in skip_cols]

    records = []
    for _, row in df.iterrows():
        maker = str(row["Maker"]).strip()
        if not maker or maker.lower() == "nan":
            continue

        for vc_col in vehicle_class_cols:
            raw_val = row[vc_col]
            # Convert: strip commas, to int, NaN -> 0
            try:
                val = int(str(raw_val).replace(",", "").strip())
            except (ValueError, TypeError):
                val = 0

            records.append({
                "year": year,
                "month": month,
                "maker": maker,
                "vehicle_class": str(vc_col).strip(),
                "registrations": val,
            })

    print(f"  Normalized records: {len(records)}")
    return records


def ingest_file(conn, filepath):
    """Clean, normalize, and insert one file into the database."""
    filename = os.path.basename(filepath)
    year, month = parse_year_month(filepath)
    print(f"\nProcessing: {filename} (year={year}, month={month})")

    records = clean_and_normalize(filepath)

    cursor = conn.cursor()

    # Delete existing records for this year/month (re-ingest)
    cursor.execute(
        "DELETE FROM maker_vehicle_class WHERE year = ? AND month = ?",
        (year, month),
    )
    deleted = cursor.rowcount
    if deleted:
        print(f"  Deleted {deleted:,} existing records for {year}-{month:02d}")

    # Insert new records
    insert_sql = """
        INSERT OR REPLACE INTO maker_vehicle_class
        (year, month, maker, vehicle_class, registrations)
        VALUES (?, ?, ?, ?, ?)
    """
    batch = []
    for rec in records:
        batch.append((rec["year"], rec["month"], rec["maker"], rec["vehicle_class"], rec["registrations"]))
        if len(batch) >= 10000:
            cursor.executemany(insert_sql, batch)
            batch = []
    if batch:
        cursor.executemany(insert_sql, batch)

    # Mark file as processed
    cursor.execute(
        "INSERT OR REPLACE INTO processed_vehicle_class_files (filename, year, month) VALUES (?, ?, ?)",
        (filename, year, month),
    )

    conn.commit()
    print(f"  Inserted {len(records):,} records")


def print_stats(conn):
    """Print summary statistics."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM maker_vehicle_class")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT maker) FROM maker_vehicle_class")
    makers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT vehicle_class) FROM maker_vehicle_class")
    vehicle_classes = cursor.fetchone()[0]

    cursor.execute(
        "SELECT DISTINCT year, month FROM maker_vehicle_class ORDER BY year, month"
    )
    months = cursor.fetchall()

    print(f"\n{'='*60}")
    print(f"Database: {DB_PATH}")
    print(f"Table: maker_vehicle_class")
    print(f"{'='*60}")
    print(f"Total records: {total:,}")
    print(f"Unique makers: {makers}")
    print(f"Unique vehicle classes: {vehicle_classes}")
    print(f"Months: {len(months)}")
    for y, m in months:
        print(f"  {y}-{m:02d}")

    print(f"\nTop 10 makers by total registrations:")
    cursor.execute("""
        SELECT maker, SUM(registrations) as total
        FROM maker_vehicle_class
        GROUP BY maker
        ORDER BY total DESC
        LIMIT 10
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]:,}")


def full_rebuild():
    """Drop tables and reprocess all files."""
    print("Full rebuild requested.")

    all_files = get_all_files()
    if not all_files:
        print(f"No files found in {DATA_DIR}")
        return

    conn = sqlite3.connect(DB_PATH)
    drop_tables(conn)
    ensure_tables(conn)

    print(f"Found {len(all_files)} file(s) to process")
    for filepath in all_files:
        ingest_file(conn, filepath)

    print_stats(conn)
    conn.close()


def incremental_update():
    """Process only new (unprocessed) files."""
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)

    new_files = get_new_files(conn)
    if not new_files:
        print("No new files to process. Database is up to date.")
        conn.close()
        return

    print(f"Found {len(new_files)} new file(s):")
    for f in new_files:
        print(f"  {os.path.basename(f)}")

    for filepath in new_files:
        ingest_file(conn, filepath)

    print_stats(conn)
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Maker x Vehicle Class data into SQLite."
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop tables and reprocess all files from scratch",
    )
    args = parser.parse_args()

    if args.rebuild:
        full_rebuild()
    else:
        incremental_update()

    print("\nDone!")


if __name__ == "__main__":
    main()
