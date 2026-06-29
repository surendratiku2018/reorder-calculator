"""End-to-end acceptance test — Technical Spec §9, run against the live database.

Confirms the full pipeline (migrate → daily_usage date windows → calc) reproduces
the spreadsheet, not just the formula layer:

  * every one of Troy's acceptance pairs matches when its window usage is
    recomputed from daily_usage via the stored anchor;
  * SKU 16-2400 computes to 0 (the spec's one intentional divergence from the
    sheet's hand-typed 24 — there is no override mechanism).

Skips (doesn't fail) when the database hasn't been built, so the pure formula
tests still run on a clean checkout. Build it with:  python load_cli.py
"""

import csv
import os

import pytest

import calc
import db

HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS = os.path.join(HERE, "acceptance_pairs.csv")
TOL = 1e-6


def _close(a, b):
    return abs(float(a) - float(b)) <= TOL


@pytest.fixture(scope="module")
def conn():
    if not os.path.exists(db.DEFAULT_DB_PATH):
        pytest.skip("database not built — run `python load_cli.py` first")
    c = db.connect(db.DEFAULT_DB_PATH)
    if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        pytest.skip("database empty — run `python load_cli.py` first")
    return c


def test_pairs_match_from_database(conn):
    """Numeric-lead SKUs reproduce the spreadsheet cell-for-cell. Non-numeric-lead
    SKUs (Static / Sales Velocity / …) do NOT calculate under Troy's 2026-06 rule,
    so their W/R/U are blank — this supersedes the old expected values for the
    Static rows in acceptance_pairs.csv (e.g. 99-5101 was 4, 16-2400 was 0)."""
    params = db.get_params(conn)
    pairs = list(csv.DictReader(open(PAIRS, newline="")))
    failures = []
    for p in pairs:
        prod = conn.execute("SELECT lead_time FROM products WHERE sku = ?", (p["sku"],)).fetchone()
        if prod is None:
            failures.append(f"{p['sku']}: not in database")
            continue
        r = calc.compute_for_sku(conn, p["sku"], prod["lead_time"], params, "test")

        if not calc.lead_time_calculates(prod["lead_time"]):
            # New rule: non-numeric lead time -> the row produces no reorder point.
            for k in ("lead_time_window_usage", "baseline_reorder_point",
                      "yoy_difference", "new_reorder_point"):
                if r[k] is not None:
                    failures.append(f"{p['sku']}: {k} should be blank (non-numeric lead), got {r[k]}")
            continue

        if not _close(r["lead_time_window_usage"], p["lead_time_window_usage"]):
            failures.append(f"{p['sku']}: window {r['lead_time_window_usage']} != {p['lead_time_window_usage']}")
        if not _close(r["baseline_reorder_point"], p["expected_baseline_W"]):
            failures.append(f"{p['sku']}: W {r['baseline_reorder_point']} != {p['expected_baseline_W']}")
        if not _close(r["yoy_difference"], p["expected_yoy_R"]):
            failures.append(f"{p['sku']}: R {r['yoy_difference']} != {p['expected_yoy_R']}")
        if not _close(r["new_reorder_point"], p["expected_new_reorder_point_U"]):
            failures.append(f"{p['sku']}: U {r['new_reorder_point']} != {p['expected_new_reorder_point_U']}")
    assert not failures, "acceptance failures:\n  " + "\n  ".join(failures)


def test_16_2400_static_does_not_calculate(conn):
    """16-2400 is a Static item (non-numeric lead time). Under Troy's 2026-06 rule
    a row calculates ONLY when its lead time is a number, so 16-2400 now produces
    no reorder point (blank). This replaces the earlier "computes to 0" behaviour
    (the sheet's hand-typed 24 over a #REF! is still not carried over)."""
    params = db.get_params(conn)
    prod = conn.execute("SELECT lead_time FROM products WHERE sku = '16-2400'").fetchone()
    r = calc.compute_for_sku(conn, "16-2400", prod["lead_time"], params, "test")
    assert r["baseline_reorder_point"] is None
    assert r["yoy_difference"] is None
    assert r["new_reorder_point"] is None
