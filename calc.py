"""The reorder-point calculation — Technical Spec §3 and §5.

These are the ONLY formulas in the system, reproduced from the source workbook:

    R (YoY difference)    = SUM(this_week 7 days) - SUM(last_year_week 7 days)
    W (baseline)          = EXCEL_ROUND(lead_time_window_usage * 1.15, 0)
    U (new reorder point) = (W + R) if (W + R) > 0 else W

No averaging, smoothing, or alternative forecasting — only the 1.15 safety
factor and the 7-day comparison windows.

Two fidelity details (Spec §3.3 and the acceptance notes):
  * Rounding is Excel's ROUND — half away from zero — done in Decimal so that
    e.g. 10*1.15 = 11.5 rounds to 12 (binary float would give 11.4999… -> 11).
    Only W is rounded.
  * U is NOT rounded. R can be fractional, so U = W + R can be fractional
    (e.g. 1946 + 29.261 = 1975.261). The spec's draft code cast U to int(); per
    the spec's own acceptance notes that is wrong, so we keep U exact here.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

SAFETY_FACTOR = Decimal("1.15")


def excel_round(value, digits: int = 0):
    """Excel ROUND(): round half away from zero, decimal-aware.

    Returns an int for digits=0 (whole-unit rounding, as W needs).
    """
    quantum = Decimal(1).scaleb(-digits)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else rounded


def lead_time_calculates(lead_time) -> bool:
    """A row produces a reorder point ONLY when its Lead Time is a real number of
    days. When the Lead Time column holds a word instead (e.g. 'Static',
    'Sales Velocity') or is blank, the row does not calculate at all.

    (Troy, 2026-06: "Lead time ... is a number of days that I enter ... With
    words — and not numbers — the system should be unable to make a calculation
    anyway." This supersedes the earlier behaviour where Static rows produced 0.)
    """
    if lead_time is None:
        return False
    try:
        return int(lead_time) >= 1
    except (TypeError, ValueError):
        return False


def baseline_reorder_point(lead_time_window_usage) -> int:
    """W = ROUND(window_usage * 1.15, 0). Window usage of 0 -> baseline 0."""
    return excel_round(Decimal(str(lead_time_window_usage)) * SAFETY_FACTOR, 0)


def yoy_difference(this_week_usage, last_year_week_usage):
    """R = SUM(this week) - SUM(last year same week). Kept exact via Decimal."""
    return Decimal(str(this_week_usage)) - Decimal(str(last_year_week_usage))


def new_reorder_point(baseline, yoy):
    """U = (W + R) if (W + R) > 0 else W. NOT rounded — may be fractional."""
    total = Decimal(str(baseline)) + Decimal(str(yoy))
    return total if total > 0 else Decimal(str(baseline))


def lead_time_calculates(lead_time) -> bool:
    """Troy's rule (2026-06): a row produces a reorder point ONLY when its Lead
    Time is a NUMBER of days. When Lead Time is a word — 'Static', 'Sales
    Velocity', 'Parent', etc. — the row does NOT calculate (W/R/U stay blank).

    The loader stores a numeric lead as an INTEGER >= 1 and a word as a NULL
    lead_time plus the word in calc_method, so "lead_time is a positive number"
    is exactly the gate, and it keeps the calc_method column in sync.
    """
    if lead_time is None or isinstance(lead_time, bool):
        return False
    try:
        return float(lead_time) >= 1
    except (TypeError, ValueError):
        return False


def window_sum(conn, sku, start_iso, num_days) -> float:
    """SUM of actual daily usage over [start, start + num_days - 1]. 0 if the
    window cannot be computed (no/invalid lead time, or no rows in range).

    This is the database form of SUM(OFFSET(X,,,,V)) and of the two 7-day
    comparison windows — all three are "sum qty over a date range".
    """
    if not num_days or int(num_days) <= 0:
        return 0.0
    start = date.fromisoformat(start_iso)
    end = start + timedelta(days=int(num_days) - 1)
    row = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM daily_usage "
        "WHERE sku = ? AND usage_date BETWEEN ? AND ?",
        (sku, start.isoformat(), end.isoformat()),
    ).fetchone()
    return float(row[0])


def compute_for_sku(conn, sku, lead_time, params, run_date_iso) -> dict:
    """Run all three formulas for one product (Spec §5). ``params`` is a mapping
    with keys safety_factor, lead_window_anchor, this_week_start,
    last_year_week_start.

    Kept as one small, reviewable function so it can be eyeballed against the
    spreadsheet, exactly as the spec asks.
    """
    if not lead_time_calculates(lead_time):
        # Non-numeric lead time (Static / Sales Velocity / Parent / …): this row
        # does not calculate — leave baseline, YoY and the reorder point blank.
        return {
            "sku": sku,
            "run_date": run_date_iso,
            "lead_time_window_usage": None,
            "baseline_reorder_point": None,
            "this_week_usage": None,
            "last_year_week_usage": None,
            "yoy_difference": None,
            "new_reorder_point": None,
        }

    # A row with a non-numeric Lead Time ('Static', 'Sales Velocity', blank)
    # does not calculate — every output is blank, not 0.
    if not lead_time_calculates(lead_time):
        return {
            "sku": sku, "run_date": run_date_iso,
            "lead_time_window_usage": None, "baseline_reorder_point": None,
            "this_week_usage": None, "last_year_week_usage": None,
            "yoy_difference": None, "new_reorder_point": None,
        }

    anchor = params["lead_window_anchor"]
    safety = Decimal(str(params.get("safety_factor", SAFETY_FACTOR)))

    # W — baseline. Sum the V-day lead-time window of the daily block (column X
    # onward) starting at the anchor, x1.15, rounded.
    window_usage = window_sum(conn, sku, anchor, lead_time)
    baseline = excel_round(Decimal(str(window_usage)) * safety, 0)

    # R — year-over-year difference: SUM(LWeek Day 1-7) - SUM(LYear Day1-7),
    # read from the explicit comparison-week columns (D:J and K:Q).
    this_week, last_year = db.comparison_sums(conn, sku)
    yoy = Decimal(str(this_week)) - Decimal(str(last_year))

    # U — new reorder point (not rounded)
    new_rp = (baseline + yoy) if (baseline + yoy) > 0 else Decimal(str(baseline))

    return {
        "sku": sku,
        "run_date": run_date_iso,
        "lead_time_window_usage": window_usage,
        "baseline_reorder_point": baseline,          # int
        "this_week_usage": this_week,
        "last_year_week_usage": last_year,
        "yoy_difference": float(yoy),
        "new_reorder_point": float(new_rp),          # exact value, not int-cast
    }


def run_calculation(conn, run_date_iso, params=None) -> int:
    """A full run: compute every product and upsert into reorder_results for
    ``run_date_iso`` (Spec §5). Returns the number of products computed.

    Takes an open connection so the UI and the migration can both call it.
    """
    if params is None:
        params = db.get_params(conn)
    products = conn.execute("SELECT sku, lead_time FROM products").fetchall()
    results = [compute_for_sku(conn, p["sku"], p["lead_time"], params, run_date_iso)
               for p in products]
    db.upsert_results(conn, results)
    return len(results)
