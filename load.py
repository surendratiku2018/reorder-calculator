"""One-time data migration — loads the workbook into SQLite, mirroring the
sheet's structure so a full export reproduces its exact layout.

  * products        — Create Date, Description, Category, Supplier, Lead Time
                      (split: a number -> lead_time; a word like 'Static' ->
                      calc_method, and the row does not calculate).
  * comparison_week — D:J ("LWeek Day 1-7", this year) and K:Q ("LYear Day1-7",
                      last year) stored as explicit per-SKU values.
  * daily_usage     — the dated block (column X onward), at real calendar dates.
                      Column X = 10-Feb-2025; each subsequent column is the next
                      day (positional — the source's date labels contain
                      duplicates, and the spreadsheet's OFFSET sums by position).
  * calc_parameters — safety_factor 1.15 and the anchor (10-Feb-2025).

SKUs are handled as text throughout; no spreadsheet round-trip.
"""

import datetime as _dt

import openpyxl

import db

COL_CREATE_DATE = 1            # A
COL_CATEGORY, COL_SUPPLIER = 2, 3
COL_LWEEK = range(4, 11)       # D..J  this year
COL_LYEAR = range(11, 18)      # K..Q  last year
COL_SKU, COL_DESC, COL_LEAD = 19, 20, 22
COL_DAILY_START = 24           # X
FIRST_ROW, LAST_ROW = 2, 680

ANCHOR = "2025-02-10"          # column X = 10-Feb-2025
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _parse_lead(value):
    """(lead_time:int|None, method_word:str|None). A number -> it calculates; a
    word ('Static','Sales Velocity',…) -> it does not."""
    if value is None or str(value).strip() == "":
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        return (n, None) if n >= 1 else (None, str(value).strip())
    text = str(value).strip()
    try:
        n = int(float(text))
        return (n, None) if n >= 1 else (None, text)
    except ValueError:
        return None, text


def _create_date(value):
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.date().isoformat() if isinstance(value, _dt.datetime) else value.isoformat()
    return None if value is None else str(value).strip()


def _block_dates(labels, start_year=2025):
    """Map each daily header to a REAL ISO date. Handles every header style seen
    in the wild:

      * real Excel date cells (datetime/date objects) — used as-is, their own
        year included (this is what "Start fresh" uploads built from a full
        export or with formatted date headers contain);
      * text with a year, e.g. '01-Jul-2025' — parsed fully;
      * text without a year, e.g. '10-Feb' (the original workbook) — the year
        starts at ``start_year`` and advances when the month wraps (Dec -> Jan).

    Duplicate labels (a data-entry artifact) map to the same date and are summed
    by the caller."""
    dates, year, prev = [], start_year, None
    for h in labels:
        if h is None or str(h).strip() == "":
            dates.append(None)
            continue
        # real date cell -> trust it completely
        if isinstance(h, (_dt.datetime, _dt.date)):
            d = h.date() if isinstance(h, _dt.datetime) else h
            dates.append(d.isoformat())
            prev, year = d.month, d.year
            continue
        parts = str(h).strip().replace(".", "").split("-")
        try:
            day, month = int(parts[0]), _MONTHS[parts[1][:3].lower()]
        except (ValueError, KeyError, IndexError):
            dates.append(None)
            continue
        if len(parts) >= 3 and parts[2].strip().isdigit():   # '01-Jul-2025' style
            year = int(parts[2])
            prev = month
        else:                                                # '10-Feb' style
            if prev is not None and month < prev:
                year += 1
            prev = month
        dates.append(_dt.date(year, month, day).isoformat())
    return dates


def migrate(xlsx_path, db_path=db.DEFAULT_DB_PATH, sheet=None, start_year=2025):
    """Load a master spreadsheet into a fresh database. ``start_year`` is the year
    that column X (the first daily-usage column) falls in — only needed when the
    daily headers are year-less text like '10-Feb'; real date headers carry their
    own year. ``sheet`` defaults to 'Sheet1' when present, else the first sheet."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    if sheet is None:
        sheet = "Sheet1" if "Sheet1" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet]
    rows = list(ws.iter_rows(min_row=1, max_row=LAST_ROW, values_only=True))
    block_dates = _block_dates(rows[0][COL_DAILY_START - 1:], start_year)
    anchor_iso = next((d for d in block_dates if d), f"{start_year}-01-01")  # column X date

    report = {"products": 0, "suppliers": 0, "daily_rows": 0, "comparison_rows": 0,
              "calc_methods": {}, "duplicate_skus": []}

    conn = db.connect(db_path)
    db.reset_db(conn)

    supplier_ids, seen = {}, set()
    products, comp_rows = [], []
    daily_agg = {}   # (sku, iso_date) -> summed qty (duplicate date labels collapse here)

    for row in rows[1:]:
        sku = row[COL_SKU - 1]
        if sku is None or str(sku).strip() == "":
            continue
        sku = str(sku).strip()
        if sku in seen:
            report["duplicate_skus"].append(sku)
            continue
        seen.add(sku)

        supplier_raw = row[COL_SUPPLIER - 1]
        supplier_id = None
        if supplier_raw not in (None, "", 0, "0"):
            name = str(supplier_raw).strip()
            if name:
                if name not in supplier_ids:
                    cur = conn.execute("INSERT INTO suppliers(name) VALUES (?)", (name,))
                    supplier_ids[name] = cur.lastrowid
                supplier_id = supplier_ids[name]

        category = row[COL_CATEGORY - 1]
        category = str(category).strip() if category is not None else None
        lead_time, calc_method = _parse_lead(row[COL_LEAD - 1])
        report["calc_methods"][calc_method] = report["calc_methods"].get(calc_method, 0) + 1
        desc = row[COL_DESC - 1]

        products.append((sku, _create_date(row[COL_CREATE_DATE - 1]),
                         (str(desc).strip() if desc is not None else None),
                         category, lead_time, calc_method, supplier_id))

        comp_rows.append((sku,
                          [_num(row[c - 1]) for c in COL_LWEEK],
                          [_num(row[c - 1]) for c in COL_LYEAR]))

        for idx, cell in enumerate(row[COL_DAILY_START - 1:]):
            qty = _num(cell)
            if qty not in (None, 0.0) and idx < len(block_dates) and block_dates[idx]:
                key = (sku, block_dates[idx])
                daily_agg[key] = daily_agg.get(key, 0.0) + qty   # sum duplicate-date labels

    conn.executemany(
        "INSERT INTO products(sku, create_date, description, category, lead_time, calc_method, supplier_id) "
        "VALUES (?,?,?,?,?,?,?)", products)
    for sku, lweek, lyear in comp_rows:
        db.set_comparison_week(conn, sku, lweek, lyear)
    conn.executemany("INSERT INTO daily_usage(sku, usage_date, qty) VALUES (?,?,?)",
                     [(s, d, q) for (s, d), q in daily_agg.items()])
    db.set_params(conn, 1.15, anchor_iso)
    conn.commit()

    report["products"] = len(products)
    report["suppliers"] = len(supplier_ids)
    report["daily_rows"] = len(daily_agg)
    report["comparison_rows"] = len(comp_rows)
    conn.close()
    wb.close()
    return report
