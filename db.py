"""Database access — open a connection, apply the schema, and small helpers
(Technical Spec §10: db.py = "open connection, apply schema, helpers").
"""

import os
import sqlite3

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(PROJECT_DIR, "data", "reorder.db")
SCHEMA_PATH = os.path.join(PROJECT_DIR, "schema.sql")


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like row access."""
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Apply schema.sql (idempotent — uses CREATE TABLE IF NOT EXISTS)."""
    with open(SCHEMA_PATH) as fh:
        conn.executescript(fh.read())
    conn.commit()


def reset_db(conn: sqlite3.Connection) -> None:
    """Drop everything and recreate — used by the one-time migration."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS reorder_results;
        DROP TABLE IF EXISTS calc_parameters;
        DROP TABLE IF EXISTS comparison_week;
        DROP TABLE IF EXISTS daily_usage;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS suppliers;
        """
    )
    init_db(conn)


# ---- calc_parameters (single row, id = 1) ----

def get_params(conn) -> dict:
    row = conn.execute("SELECT * FROM calc_parameters WHERE id = 1").fetchone()
    return dict(row) if row else None


def set_params(conn, safety_factor, lead_window_anchor) -> None:
    conn.execute(
        """INSERT INTO calc_parameters (id, safety_factor, lead_window_anchor)
           VALUES (1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             safety_factor = excluded.safety_factor,
             lead_window_anchor = excluded.lead_window_anchor""",
        (safety_factor, lead_window_anchor),
    )
    conn.commit()


# ---- comparison weeks (D:J this year, K:Q last year) ----

_CW_COLS = [f"lweek_d{i}" for i in range(1, 8)] + [f"lyear_d{i}" for i in range(1, 8)]


def set_comparison_week(conn, sku, lweek7, lyear7) -> None:
    vals = list(lweek7) + list(lyear7)
    conn.execute(
        f"INSERT INTO comparison_week (sku, {', '.join(_CW_COLS)}) "
        f"VALUES (?, {', '.join('?' * 14)}) "
        f"ON CONFLICT(sku) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in _CW_COLS),
        (sku, *vals),
    )


def comparison_sums(conn, sku):
    """Return (this_week_sum, last_year_sum) for a SKU, treating NULLs as 0."""
    row = conn.execute(
        "SELECT COALESCE(lweek_d1,0)+COALESCE(lweek_d2,0)+COALESCE(lweek_d3,0)+COALESCE(lweek_d4,0)"
        "+COALESCE(lweek_d5,0)+COALESCE(lweek_d6,0)+COALESCE(lweek_d7,0) AS tw,"
        " COALESCE(lyear_d1,0)+COALESCE(lyear_d2,0)+COALESCE(lyear_d3,0)+COALESCE(lyear_d4,0)"
        "+COALESCE(lyear_d5,0)+COALESCE(lyear_d6,0)+COALESCE(lyear_d7,0) AS ly"
        " FROM comparison_week WHERE sku = ?",
        (sku,),
    ).fetchone()
    return (row["tw"], row["ly"]) if row else (0.0, 0.0)


# ---- results ----

def upsert_results(conn, results) -> None:
    """Insert/replace a batch of per-SKU result dicts for their run_date."""
    conn.executemany(
        """INSERT INTO reorder_results
             (sku, run_date, lead_time_window_usage, baseline_reorder_point,
              this_week_usage, last_year_week_usage, yoy_difference, new_reorder_point)
           VALUES (:sku, :run_date, :lead_time_window_usage, :baseline_reorder_point,
                   :this_week_usage, :last_year_week_usage, :yoy_difference, :new_reorder_point)
           ON CONFLICT(sku, run_date) DO UPDATE SET
             lead_time_window_usage = excluded.lead_time_window_usage,
             baseline_reorder_point = excluded.baseline_reorder_point,
             this_week_usage        = excluded.this_week_usage,
             last_year_week_usage   = excluded.last_year_week_usage,
             yoy_difference         = excluded.yoy_difference,
             new_reorder_point      = excluded.new_reorder_point""",
        results,
    )
    conn.commit()


def latest_run_date(conn):
    row = conn.execute("SELECT MAX(run_date) AS d FROM reorder_results").fetchone()
    return row["d"] if row else None
