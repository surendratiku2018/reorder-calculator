-- Reorder Calculator — SQLite schema.
--
-- Mirrors the source spreadsheet's structure so a full export reproduces its
-- exact column layout: Create Date, Category, Supplier, LWeek Day 1-7,
-- LYear Day1-7, YoY, Product id, Description, New Reorder Point, Lead Time,
-- Reorder point (baseline), then the dated daily-usage block (column X onward).
--
-- reorder_results.new_reorder_point is REAL (not INTEGER): U is not rounded and
-- can be fractional (e.g. 1975.261), per the acceptance notes.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS suppliers (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    sku         TEXT PRIMARY KEY,        -- TEXT: never coerced (e.g. '01-2500', '99-999')
    create_date TEXT,                    -- sheet column A
    description TEXT,
    category    TEXT,                    -- 'Domestic' / 'Import' (as-is)
    lead_time   INTEGER,                 -- V (days); a real number means the row calculates
    calc_method TEXT,                    -- the WORD when Lead Time isn't a number ('Static','Sales Velocity',...)
    supplier_id INTEGER REFERENCES suppliers(id)
);

-- The comparison weeks the sheet keeps as columns D:J (this year) and K:Q (last
-- year), stored as explicit per-SKU values — NOT as dated daily_usage rows — so
-- they never leak into the daily-date columns of an export.
CREATE TABLE IF NOT EXISTS comparison_week (
    sku      TEXT PRIMARY KEY REFERENCES products(sku),
    lweek_d1 REAL, lweek_d2 REAL, lweek_d3 REAL, lweek_d4 REAL, lweek_d5 REAL, lweek_d6 REAL, lweek_d7 REAL,  -- D:J
    lyear_d1 REAL, lyear_d2 REAL, lyear_d3 REAL, lyear_d4 REAL, lyear_d5 REAL, lyear_d6 REAL, lyear_d7 REAL   -- K:Q
);

-- One row per SKU per day of ACTUAL usage (the daily block, column X onward).
-- Real calendar dates only (the historical block is 2025; appended weeks 2026).
CREATE TABLE IF NOT EXISTS daily_usage (
    sku        TEXT NOT NULL REFERENCES products(sku),
    usage_date TEXT NOT NULL,            -- ISO 'YYYY-MM-DD'
    qty        REAL NOT NULL,
    PRIMARY KEY (sku, usage_date)
);

-- Single-row parameters. The anchor is the date sitting at column X; the weekly
-- roll-forward advances it 7 days.
CREATE TABLE IF NOT EXISTS calc_parameters (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    safety_factor      REAL NOT NULL DEFAULT 1.15,
    lead_window_anchor TEXT NOT NULL        -- first day of the V-day lead-time window (column X)
);

CREATE TABLE IF NOT EXISTS reorder_results (
    sku                     TEXT NOT NULL REFERENCES products(sku),
    run_date                TEXT NOT NULL,
    lead_time_window_usage  REAL,            -- SUM(OFFSET(X,,,,V))
    baseline_reorder_point  INTEGER,         -- W
    this_week_usage         REAL,            -- SUM(D:J)
    last_year_week_usage    REAL,            -- SUM(K:Q)
    yoy_difference          REAL,            -- R
    new_reorder_point       REAL,            -- U (not rounded)
    PRIMARY KEY (sku, run_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_usage_sku ON daily_usage(sku);
CREATE INDEX IF NOT EXISTS idx_results_run ON reorder_results(run_date);
