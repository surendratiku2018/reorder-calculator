# Reorder Calculator

A small, database-backed reorder-point tool for **The USA Trailer Store**,
built to the supplied technical spec ([SPEC.md](SPEC.md)). It replaces the Excel
reorder-point spreadsheet: the same three formulas, the same numbers — but SKUs
can never be coerced into dates, and the math is locked down by tests.

Stack (per spec): **SQLite + a pure Python calc module + a Streamlit UI**.

---

## Verified against the spec's acceptance test

```
pytest -q        →  7 passed
```

* **All 12 acceptance pairs match cell-for-cell** (`W`, `R`, `U`), both at the
  formula layer and recomputed from the database — including the fractional
  `35-0009 → 1975.261`, the `11.5 → 12` rounding, every `Static` item, and the
  fallback cases.
* **SKU `16-2400` computes to `0`**, per the spec's acceptance notes: the sheet's
  `24` was a hand-typed value over a broken (`#REF!`) formula, so the rebuilt
  tool computes it normally — there is no override mechanism.
* Beyond the 12 pairs, the engine also reproduces the spreadsheet's own cached
  `W`/`R`/`U` for **all 679 products** (the only difference is `16-2400`, the
  intentional divergence above).

---

## The three formulas (`calc.py`)

Kept in one small, reviewable module — no averaging, smoothing, or alternative
forecasting; only the `1.15` safety factor and the 7-day comparison windows.

```
W (baseline)          = EXCEL_ROUND(lead_time_window_usage * 1.15, 0)
R (YoY difference)    = this_week_usage - last_year_week_usage
U (new reorder point) = (W + R) if (W + R) > 0 else W
```

Two fidelity rules, both covered by tests:
* **Rounding** is Excel's — half away from zero, done in `Decimal` so `11.5 → 12`
  (binary float would give `11.4999… → 11`). Only `W` is rounded.
* **`U` is never rounded** — `R` can be fractional, so `U` can be too.

A non-numeric / missing lead time makes the window usage `0`, so `W = 0` — the
spec's `IFERROR(...,0)` behaviour.

---

## SKUs stay text

`10-35` must never become `Oct-35`:
* the importer uses only the standard-library `csv` module — every field is read
  as a raw string, never handed to a spreadsheet engine;
* `products.sku` is declared `TEXT`, so SQLite stores and returns the literal
  string;
* exports are fully quoted and write SKUs as text.

---

## Run it

Requires Python 3.10+ (built on 3.11).

```bash
cd reorder_calculator
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# one-time migration: workbook -> SQLite, then the first calculation
python load_cli.py data/source_workbook.xlsx

# launch the UI
streamlit run app.py            # opens http://localhost:8501
```

---

## The UI (`app.py`) — five screens

1. **Reorder dashboard** — the latest run as a sortable table (Product id,
   Description, Supplier, Category, Lead Time, Baseline `W`, YoY `R`, New Reorder
   Point `U`), with Search and Category / Supplier / Calc-method filters.
2. **Run calculation** — set the safety factor and the three window dates (with a
   one-click "advance anchor 7 days" for the weekly roll-forward), then recompute;
   reports how many reorder points changed.
3. **Import usage** — append a `(sku, usage_date, qty)` CSV to history (SKU read
   as text). Never deletes prior history.
4. **Edit products** — adjust an item's lead time, calc method, category, supplier.
5. **Export** — full results CSV and a Finale upload subset (SKU + reorder point).

---

## How the spreadsheet maps to the database

* The ~384 dated daily-usage **columns** become `daily_usage` **rows**. The
  source's date *labels* contain duplicates (the sheet's `OFFSET` sums by column
  *position*, not by date), so each column is stored on a consecutive
  **positional** date from the anchor — a `V`-day date window then reproduces the
  `OFFSET` sum exactly. The going-forward monthly feed uses real calendar dates.
* The lead-time column is overloaded (a number, or a word like `Static`): it is
  split into numeric `lead_time` + text `calc_method`.
* The "this week" (`D:J`) and "last year week" (`K:Q`) inputs are independent of
  the daily series; they are seeded as `daily_usage` rows on dedicated dates that
  the `calc_parameters` windows point at, so `R` reproduces exactly.

See [SPEC.md](SPEC.md) §4–§5 for the full schema and procedure.

---

## Open items to confirm with the client

* **Finale export columns** — the subset currently exports `ProductID` +
  `ReorderPoint`; confirm the exact column names/order Finale expects.
* **`products_all_679.csv`** — the spec references this cleaned products/suppliers
  file. This build derives products/suppliers directly from the workbook (679
  products, 116 suppliers); supply the CSV to use it as the canonical source.
* **Comparison-week dates** — seeded to reproduce the current sheet; the Run
  screen lets you set the real per-run dates going forward.

## Tests

```bash
pytest -q
```
* `tests/test_calc.py` — the formulas + the 12 acceptance pairs at the formula layer.
* `tests/test_acceptance.py` — the same pairs recomputed from the live database,
  plus the `16-2400 → 0` rule. (Skips if the DB isn't built yet.)
