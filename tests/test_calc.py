"""Parity tests — Technical Spec §9 (the definition of done).

The primary test drives Troy's own ``acceptance_pairs.csv`` through the formula
layer and asserts W, R and U cell-for-cell. The remaining tests pin the two
fidelity details (Excel rounding; U is not rounded) and the Static-item rule.

Run:  pytest -q
"""

import csv
import os
from decimal import Decimal

import calc

HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS = os.path.join(HERE, "acceptance_pairs.csv")


def _pairs():
    with open(PAIRS, newline="") as fh:
        return list(csv.DictReader(fh))


def test_acceptance_pairs_cell_for_cell():
    """W, R, U must match the spreadsheet for every pair Troy supplied."""
    rows = _pairs()
    assert len(rows) >= 12, "expected the full acceptance set"
    failures = []
    for r in rows:
        W = calc.baseline_reorder_point(r["lead_time_window_usage"])
        R = calc.yoy_difference(r["this_week_usage"], r["last_year_week_usage"])
        U = calc.new_reorder_point(W, R)
        eW = int(r["expected_baseline_W"])
        eR = Decimal(r["expected_yoy_R"])
        eU = Decimal(r["expected_new_reorder_point_U"])
        if not (W == eW and R == eR and U == eU):
            failures.append(f"{r['sku']}: got W={W},R={R},U={U} expected W={eW},R={eR},U={eU}")
    assert not failures, "acceptance mismatches:\n  " + "\n  ".join(failures)


def test_excel_rounding_half_away_from_zero():
    assert calc.excel_round(Decimal("0.5")) == 1
    assert calc.excel_round(Decimal("2.5")) == 3
    assert calc.excel_round(Decimal("12.5")) == 13
    # the live example: 10 * 1.15 = 11.5 -> 12
    assert calc.baseline_reorder_point(10) == 12


def test_U_is_not_rounded():
    # 35-0009: W=1946, R=29.261, U=1975.261 (must stay fractional)
    assert calc.new_reorder_point(1946, Decimal("29.261")) == Decimal("1975.261")


def test_static_item_window_is_zero():
    # window usage 0 -> baseline 0; reorder point driven by R alone
    assert calc.baseline_reorder_point(0) == 0
    assert calc.new_reorder_point(0, Decimal("4")) == Decimal("4")     # 99-5101 / 99-0000
    assert calc.new_reorder_point(0, Decimal("-5")) == Decimal("0")    # 35-0017 fallback


def test_fallback_when_sum_not_positive():
    # 58-3708: W=12, R=-14 -> W+R=-2 (<=0) -> U falls back to W=12
    assert calc.new_reorder_point(12, Decimal("-14")) == Decimal("12")
