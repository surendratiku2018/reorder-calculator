#!/usr/bin/env python
"""One-time migration CLI (Technical Spec §8).

    python load_cli.py [path/to/workbook.xlsx]

Loads the workbook into data/reorder.db, seeds calc_parameters, and runs the
first calculation. Safe to re-run (rebuilds from a clean slate).
"""

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import calc  # noqa: E402
import db  # noqa: E402
import load  # noqa: E402

DEFAULT_XLSX = os.path.join(db.PROJECT_DIR, "data", "source_workbook.xlsx")


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    if not os.path.exists(xlsx):
        sys.exit(f"Workbook not found: {xlsx}")

    print(f"Migrating {xlsx} → {db.DEFAULT_DB_PATH} …")
    rep = load.migrate(xlsx, db.DEFAULT_DB_PATH)

    conn = db.connect(db.DEFAULT_DB_PATH)
    run_date = _dt.date.today().isoformat()
    n = calc.run_calculation(conn, run_date)
    conn.close()

    print(f"  products            : {rep['products']}")
    print(f"  suppliers           : {rep['suppliers']}")
    print(f"  daily-usage rows    : {rep['daily_rows']:,}")
    print(f"  comparison-week rows: {rep['comparison_rows']:,}")
    print(f"  calc methods        : {rep['calc_methods']}")
    print(f"  first run ({run_date}): {n} products computed")


if __name__ == "__main__":
    main()
