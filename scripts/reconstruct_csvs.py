#!/usr/bin/env python3
"""
Reconstruct CSV files from Parquet files while preserving directory structure.

Usage:
    python reconstruct_csv.py --input parquet --output csv [--dataset nyc_tlc] [--year 2020] [--month 2]
"""

import argparse
import duckdb
import os
import time
from utils import filesystem_data_paths

if __name__ == "__main__" and __package__ is None:
    # allow running `./scripts/reconstruct_csv.py` directly
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

def convert_parquet_to_csv(in_file: str, out_file: str):
    """Convert a single Parquet file to CSV with DuckDB."""
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    if os.path.exists(out_file):
        print(f"⏭ Skipping {out_file} (already exists)")
        return

    print(f"🔄 Converting {in_file} → {out_file}")
    start = time.time()

    try:
        duckdb.sql(f"""
            COPY (SELECT * FROM read_parquet('{in_file}'))
            TO '{out_file}'
            WITH (HEADER, DELIMITER ',');
        """)
        elapsed = time.time() - start
        print(f"✅ Done in {elapsed:.2f} sec")
    except Exception as e:
        print(f"❌ Failed {in_file}: {e}")


def process_all_parquet(input_root: str, output_root: str, year: str = None, month: str = None):
    """Walk input_root, convert Parquet → CSV into mirrored structure under output_root."""
    for dirpath, _, filenames in os.walk(input_root):
        for fname in filenames:
            if not fname.endswith(".parquet"):
                continue

            # Year/month filters (if provided)
            if year and year not in fname:
                continue
            if month and f"-{int(month):02d}" not in fname:
                continue

            rel_path = os.path.relpath(dirpath, input_root)
            in_file = os.path.join(dirpath, fname)

            out_dir = os.path.join(output_root, rel_path)
            out_file = os.path.join(out_dir, fname.replace(".parquet", ".csv"))

            convert_parquet_to_csv(in_file, out_file)


def main():
    parser = argparse.ArgumentParser(description="Reconstruct CSVs from Parquet files")
    parser.add_argument("--input", required=True, choices=["parquet"], help="Input subfolder under dataset root")
    parser.add_argument("--output", required=True, choices=["csv"], help="Output subfolder under dataset root")
    parser.add_argument("--dataset", default="nyc_tlc", help="Dataset name (default: nyc_tlc)")
    parser.add_argument("--year", help="Optional year filter (e.g. 2020)")
    parser.add_argument("--month", help="Optional month filter (1–12)")

    args = parser.parse_args()

    # Resolve tiered paths
    paths = filesystem_data_paths(args.dataset)
    input_root = os.path.join(paths["hot"], args.input)   # e.g. /hotdata/nyc_tlc/parquet
    output_root = os.path.join(paths["cold"], args.output)  # e.g. /colddata/nyc_tlc/csv

    print(f"📂 Input root: {input_root}")
    print(f"📂 Output root: {output_root}")

    process_all_parquet(input_root, output_root, year=args.year, month=args.month)


if __name__ == "__main__":
    main()
