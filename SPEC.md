# Reorder Calculator — Technical Spec

**Prepared for:** The USA Trailer Store — IT / development
**Purpose:** Rebuild the reorder-point calculator as a small database-backed
application. The calculation logic is a faithful, line-for-line reproduction of
the existing spreadsheet formulas. **No new forecasting method is introduced** —
no averaging, smoothing, or statistical models. The tool computes reorder points
from *actual* daily usage and an *actual* year-over-year comparison, exactly as
the spreadsheet does today.

---

## 1. Scope

Build three things:

1. A **SQLite database** holding products, suppliers, and daily usage history.
2. A **calculation module** that reproduces the spreadsheet's three formulas
   exactly.
3. A **Streamlit UI** to view reorder points, run the monthly recompute, edit
   product attributes, and import the monthly usage feed.

Out of scope: any forecasting technique not already in the spreadsheet. The only
arithmetic in this system is the three formulas in Section 3.

---

## 2. Why a database (and why SKUs stop breaking)

The current corruption comes from spreadsheet date-coercion: values like `10-35`
get reinterpreted as dates on import. In SQLite the SKU column is declared `TEXT`,
so `10-35` is stored and returned as the literal string `"10-35"` — nothing ever
reinterprets it. **All ingestion must go through the database/API path, never an
Excel/Google-Sheets round-trip**, or the coercion returns.

SQLite (a single file) is sufficient: the dataset is ~679 products and roughly a
year of daily usage per SKU (a few hundred thousand rows at most). Back up by
copying the file. Migrate to Postgres later only if multiple users need
concurrent write access.

---

## 3. The calculation — reproduce these formulas exactly

These are the **only** formulas in the system. They are copied from the source
workbook (`Sheet1`, row 2 shown):

| Output | Spreadsheet column | Exact formula |
|---|---|---|
| YoY Difference | `R` | `=(SUM(D2:J2)-SUM(K2:Q2))` |
| Baseline Reorder Point | `W` | `=ROUND(IFERROR(SUM(OFFSET(X2,,,,V2)),0)*1.15,0)` |
| New Reorder Point | `U` | `=IF((W2+R2)>0,W2+R2,W2)` |

### 3.1 Column meaning in the source sheet

- `D:J` = " LWeek Day 1" … " LWeek Day 7" → **this year's comparison week**
  (7 days of actual usage).
- `K:Q` = "LYear Day1" … "LYear Day7" → **last year's same week** (7 days of
  actual usage).
- `V` = Lead Time (integer number of days).
- `X` onward = dated daily-usage columns. In the source copy the region starts
  at `X` = "10-Feb" and runs chronologically to column `OQ` (~384 days).

### 3.2 What each formula does (plain English, no added logic)

1. **Baseline Reorder Point (`W`)**
   `SUM(OFFSET(X,,,,V))` sums the **first `V` dated daily-usage days starting at
   the anchor column `X`** (i.e. the `V`-day lead-time window of actual usage).
   `IFERROR(...,0)` makes that sum `0` if it cannot be computed. Multiply by the
   **1.15 safety factor**, then `ROUND` to a whole number.

   ```
   window_usage = SUM(daily_usage for this SKU over the V-day lead-time window)   # 0 if not computable
   baseline     = EXCEL_ROUND(window_usage * 1.15, 0)
   ```

2. **YoY Difference (`R`)**
   This year's comparison-week actual usage minus last year's same-week actual
   usage. This is the seasonality signal — a direct subtraction of real numbers,
   not a forecast.

   ```
   yoy_difference = SUM(this_week_7_days) - SUM(last_year_same_week_7_days)
   ```

3. **New Reorder Point (`U`)**
   If baseline plus the YoY adjustment is positive, use it; otherwise fall back
   to the baseline alone.

   ```
   new_reorder_point = (baseline + yoy_difference) if (baseline + yoy_difference) > 0 else baseline
   ```

### 3.3 Two fidelity details that must be preserved

- **Rounding.** Excel `ROUND` rounds half **away from zero**. Python's built-in
  `round()` uses banker's rounding and will disagree on `.5` cases. Implement
  Excel rounding explicitly:

  ```python
  from decimal import Decimal, ROUND_HALF_UP
  def excel_round(value, digits=0):
      q = Decimal(1).scaleb(-digits)              # 10**-digits
      return int(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))
  ```

- **The `IFERROR(...,0)` guard.** If a product has no lead time, a non-positive
  lead time, or no usage rows in the window, the window sum is `0` (so
  `baseline = 0`). Do not raise; default to `0`, matching the sheet.

---

## 4. Data model (SQLite)

```sql
CREATE TABLE suppliers (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE products (
    sku         TEXT PRIMARY KEY,        -- TEXT: never coerced (e.g. '10-35', '99-999')
    description TEXT,
    category    TEXT,                    -- 'Domestic' / 'Import' (stored as-is)
    lead_time   INTEGER,                 -- V (days)
    calc_method TEXT,                    -- 'Calculated' / 'Static' / 'Parent' / 'Inactive' / etc. (as-is)
    supplier_id INTEGER REFERENCES suppliers(id)
);

-- One row per SKU per day of ACTUAL usage. Replaces the ~384 dated columns.
CREATE TABLE daily_usage (
    sku        TEXT NOT NULL REFERENCES products(sku),
    usage_date TEXT NOT NULL,            -- ISO 'YYYY-MM-DD'
    qty        REAL NOT NULL,            -- actual units used that day
    PRIMARY KEY (sku, usage_date)
);

-- The three windows that the spreadsheet hard-codes as columns, made explicit
-- so the math stays yours and is adjustable per run. (Single-row table.)
CREATE TABLE calc_parameters (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    safety_factor          REAL NOT NULL DEFAULT 1.15,  -- the 1.15 in W
    lead_window_anchor     TEXT NOT NULL,               -- first day of the V-day lead-time window  (sheet column X)
    this_week_start        TEXT NOT NULL,               -- first day of the 7-day "this week"        (sheet D:J)
    last_year_week_start   TEXT NOT NULL                -- first day of the 7-day "last year week"   (sheet K:Q)
);

-- Output of each calculation run. Mirrors columns W, R, U plus the inputs used.
CREATE TABLE reorder_results (
    sku                     TEXT NOT NULL REFERENCES products(sku),
    run_date                TEXT NOT NULL,   -- ISO date the calc was run
    lead_time_window_usage  REAL,            -- SUM(OFFSET(X,,,,V))
    baseline_reorder_point  INTEGER,         -- W
    this_week_usage         REAL,            -- SUM(D:J)
    last_year_week_usage    REAL,            -- SUM(K:Q)
    yoy_difference          REAL,            -- R
    new_reorder_point       INTEGER,         -- U
    PRIMARY KEY (sku, run_date)
);
```

Notes:
- `usage_date` and the parameter dates are stored as ISO `TEXT` (`YYYY-MM-DD`),
  which sorts correctly and avoids any locale/coercion ambiguity.
- `category` and `calc_method` are stored verbatim from the source (including
  rows where the source has lowercase `domestic`/`parent` or methods like
  `Static`/`Parent`/`Inactive`). Do not normalize silently.

---

## 5. Calculation procedure

Run per product. The three windows come from `calc_parameters`.

```python
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

def excel_round(value, digits=0):
    q = Decimal(1).scaleb(-digits)
    return int(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))

def window_sum(conn, sku, start_iso, num_days):
    """SUM of actual daily usage over [start, start + num_days - 1]. 0 if none."""
    if not num_days or num_days <= 0:
        return 0.0
    start = date.fromisoformat(start_iso)
    end = start + timedelta(days=num_days - 1)
    row = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM daily_usage "
        "WHERE sku = ? AND usage_date BETWEEN ? AND ?",
        (sku, start.isoformat(), end.isoformat()),
    ).fetchone()
    return float(row[0])

def compute_for_sku(conn, sku, lead_time, params, run_date_iso):
    sf, anchor, tw_start, ly_start = params

    # W: ROUND( IFERROR(SUM(OFFSET(X,,,,V)),0) * 1.15, 0 )
    window_usage = window_sum(conn, sku, anchor, lead_time)      # IFERROR -> 0 handled inside
    baseline = excel_round(window_usage * sf, 0)

    # R: SUM(D:J) - SUM(K:Q)   (7-day this-week minus 7-day last-year-week)
    this_week = window_sum(conn, sku, tw_start, 7)
    last_year = window_sum(conn, sku, ly_start, 7)
    yoy = this_week - last_year

    # U: IF((W+R)>0, W+R, W)
    new_rp = (baseline + yoy) if (baseline + yoy) > 0 else baseline

    return {
        "sku": sku, "run_date": run_date_iso,
        "lead_time_window_usage": window_usage,
        "baseline_reorder_point": baseline,
        "this_week_usage": this_week,
        "last_year_week_usage": last_year,
        "yoy_difference": yoy,
        "new_reorder_point": int(new_rp),
    }
```

A run iterates all products, computes the dict above, and upserts into
`reorder_results` for the given `run_date`.

### 5.1 The lead-time window and how it advances (confirmed behavior)

In the spreadsheet the daily-usage columns are a **fixed block of positions**
beginning at column `X`, and the data **scrolls through them one week at a time**.
The date sitting at column `X` is the window **anchor**. `SUM(OFFSET(X,,,,V))`
sums the first `V` columns starting at `X` — i.e. the `V` days beginning at the
anchor date. `V` is per-SKU, so the number of days summed varies by row
(e.g. `V=10` sums `X:AG`, `V=14` sums `X:AK`).

Each weekly roll-forward, the oldest week drops off and the anchor advances by
**7 days** (anchor `10-Feb` this week becomes `17-Feb` next week). The window is
therefore **not frozen**, and it is **not** "the most recent `V` days ending
today" — it is `V` days starting at an anchor date that moves forward one week
per roll-forward.

In the database there are no scrolling columns; `daily_usage` holds every date as
rows and nothing is deleted. The equivalent is a single stored
`lead_window_anchor` date:

```
baseline window = SUM(qty) over [lead_window_anchor, lead_window_anchor + V - 1 days]
W               = EXCEL_ROUND(baseline_window * 1.15, 0)
```

The weekly roll-forward (Section 6) does two things: append the new week's usage
rows, and advance `lead_window_anchor` by 7 days. `IFERROR(...,0)` still applies:
if `V` is non-numeric (a `Static` item) or there are no usage rows in the window,
the window sum is `0`, so `W = 0`.

---

## 6. Monthly workflow

1. **Import usage feed.** Append the month's actual daily usage to `daily_usage`
   (one row per SKU per date). SKUs arrive as text; the importer must not pass
   them through any spreadsheet engine.
2. **Advance the window.** Update `calc_parameters`: advance `lead_window_anchor`
   by 7 days, and set the two 7-day comparison-week start dates for this run. The
   lead-time window then sums `V` days from the new anchor (Section 5.1).
3. **Run the calculation.** Iterate all products, write `reorder_results` for the
   run date.
4. **Review / export.** View results in the UI; export CSV, including the
   `Upload to Finale` column already in your process.

---

## 7. UI (Streamlit)

Single Python app, same language as the calc module, so one person maintains both.

Screens:

1. **Reorder dashboard.** A sortable, filterable table of the latest run:
   SKU, Description, Supplier, Category, Lead Time, Baseline (`W`),
   YoY Difference (`R`), New Reorder Point (`U`). Filters for Supplier, Category,
   and Calc Method. This is the day-to-day view.
2. **Run calculation.** Controls for `safety_factor` (default **1.15**), the
   anchor date, and the two comparison-week start dates; a **Run** button that
   executes Section 5 and writes a new `run_date`. Show a short summary
   (e.g. count of SKUs whose New Reorder Point changed since the prior run).
3. **Edit products.** Edit `lead_time`, `supplier`, `calc_method`, `category`
   for a SKU (write-back to `products`). Optional in v1.
4. **Import usage.** Upload a CSV of `(sku, usage_date, qty)` rows, appended to
   `daily_usage`, with SKU read as text and dates parsed as ISO.
5. **Export.** Download the current run as CSV, and a Finale-formatted export.

No charts or forecasts are required; the table is the product.

---

## 8. Initial data migration

- **Products + suppliers:** load from the already-cleaned 679-row dataset
  (`products_all_679.csv`), which has correct, un-coerced SKUs. Suppliers are the
  117 distinct names; resolve `supplier_id` by name on load.
- **Daily usage:** unpivot the dated columns (`X`…`OQ`) from the original
  workbook into `daily_usage` rows — for each product row and each dated column,
  insert `(sku, usage_date, qty)` where `qty > 0` (skip zeros to keep the table
  lean; absence = zero usage). Going forward, the monthly feed appends here.
- **Parameters:** seed `calc_parameters` with `safety_factor = 1.15` and the
  three window dates that correspond to the columns the sheet currently uses.

Load everything via SQL/Python inserts — **not** through a spreadsheet import.

---

## 9. Acceptance test — prove parity with the spreadsheet

Before trusting the app, verify it reproduces the spreadsheet's numbers. Add a
unit test that, for a sample of SKUs, asserts the engine's `W`, `R`, and `U`
match the spreadsheet's values for the same inputs. Known reference points from
the current data to include:

- A product with usage on both sides of the YoY window, to confirm
  `R = SUM(this week) − SUM(last year week)` and the sign is correct.
- A product where `baseline + yoy <= 0`, to confirm `U` falls back to `W`.
- A `.5` rounding case, to confirm Excel-style half-up rounding (Section 3.3).

The test should load fixed inputs, run `compute_for_sku`, and compare to the
expected spreadsheet outputs cell-for-cell. This is the definition of done: the
app is correct when its three outputs equal the spreadsheet's for every SKU in
the sample.

---

## 10. Build notes for the coding agent

This spec is written to hand directly to a coding agent (Claude Code, Codex, or
Cursor) in an empty repository. Suggested structure:

```
reorder/
  schema.sql        # Section 4 verbatim
  db.py             # open connection, apply schema, helpers
  load.py           # Section 8 migration (products, suppliers, daily_usage)
  calc.py           # Section 5 — the three formulas, in ONE reviewable function
  app.py            # Section 7 Streamlit UI
  tests/test_calc.py# Section 9 parity tests
```

Instructions to give the agent:

- Implement `calc.py` to match Section 3 **exactly**. Keep the three formulas in
  one small function so they can be eyeballed against the spreadsheet. Do not add
  any averaging, smoothing, safety-stock statistics, or alternative forecasting —
  the only constants are the `1.15` factor and the `7`-day comparison windows.
- Use the `excel_round` helper for all rounding.
- Treat SKU as `TEXT` everywhere; never convert it to a number or date.
- Write the parity tests first (Section 9) and make them pass.

Keep `calc.py` under version control and require the parity tests to pass on any
change to it, so the formula logic can never silently drift from the spreadsheet.
