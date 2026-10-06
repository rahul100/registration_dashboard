"""
Step 2: Clean and process Vahan data
- Delete first three rows
- Rename first column as 'S No', second column as 'Maker', last column as 'Total'
- Create EV_Total column as sum of 'PURE EV' and 'ELECTRIC(BOV)'
- Sort by EV_Total and save
"""

import os
import glob
import pandas as pd


def get_latest_csv_file(directory):
    """Get the most recently modified csv file in the directory"""
    csv_files = glob.glob(os.path.join(directory, "*.csv"))
    if not csv_files:
        return None
    return max(csv_files, key=os.path.getmtime)


def clean_vahan_data(filepath):
    """Clean and process the Vahan data file"""
    print(f"Processing file: {filepath}")

    # Read the CSV file
    df = pd.read_csv(filepath, header=None)
    print(f"Original shape: {df.shape}")
    print(f"First 5 rows:\n{df.head()}")

    # Step 1: Delete first three rows
    df = df.iloc[3:].reset_index(drop=True)
    print(f"\nAfter removing first 3 rows: {df.shape}")

    # Step 2: Set the first row as header
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    print(f"After setting header: {df.shape}")
    print(f"Columns: {list(df.columns)}")

    # Step 3: Rename columns - first as 'S No', second as 'Maker', last as 'Total'
    columns = list(df.columns)
    columns[0] = 'S No'
    columns[1] = 'Maker'
    columns[-1] = 'Total'
    df.columns = columns
    print(f"Renamed columns: {list(df.columns)}")

    # Step 4: Create EV_Total column as sum of 'PURE EV' and 'ELECTRIC(BOV)'
    # First, find the exact column names (they might have slight variations)
    pure_ev_col = None
    electric_bov_col = None

    for col in df.columns:
        col_upper = str(col).upper()
        if 'PURE EV' in col_upper:
            pure_ev_col = col
        elif 'ELECTRIC(BOV)' in col_upper or 'ELECTRIC (BOV)' in col_upper:
            electric_bov_col = col

    print(f"\nFound columns - PURE EV: '{pure_ev_col}', ELECTRIC(BOV): '{electric_bov_col}'")

    if pure_ev_col and electric_bov_col:
        # Convert to numeric, handling commas as thousands separators
        df[pure_ev_col] = df[pure_ev_col].astype(str).str.replace(',', '').replace('', '0')
        df[pure_ev_col] = pd.to_numeric(df[pure_ev_col], errors='coerce').fillna(0)
        df[electric_bov_col] = df[electric_bov_col].astype(str).str.replace(',', '').replace('', '0')
        df[electric_bov_col] = pd.to_numeric(df[electric_bov_col], errors='coerce').fillna(0)

        # Create EV_Total column
        df['EV_Total'] = df[pure_ev_col] + df[electric_bov_col]
        print(f"Created EV_Total column")
    else:
        print("Warning: Could not find PURE EV or ELECTRIC(BOV) columns")
        print(f"Available columns: {list(df.columns)}")
        # Try to find similar columns
        for col in df.columns:
            if 'EV' in str(col).upper() or 'ELECTRIC' in str(col).upper():
                print(f"  Potential EV column: {col}")
        df['EV_Total'] = 0

    # Step 5: Sort by EV_Total in descending order
    df = df.sort_values(by='EV_Total', ascending=False).reset_index(drop=True)
    print(f"\nSorted by EV_Total (descending)")

    # Step 6: Save cleaned data and remove original
    df.to_csv(filepath, index=False)
    print(f"\nSaved cleaned data to: {filepath}")
    print(f"Final shape: {df.shape}")

    # Show top 10 rows
    print(f"\nTop 10 rows by EV_Total:")
    print(df[['S No', 'Maker', 'EV_Total', 'Total']].head(10).to_string())

    return df


if __name__ == "__main__":
    # Get the vahan_data directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    vahan_data_dir = os.path.join(script_dir, "vahan_data")

    # Get the latest csv file
    latest_file = get_latest_csv_file(vahan_data_dir)

    if latest_file:
        clean_vahan_data(latest_file)
    else:
        print("No csv files found in vahan_data directory")
