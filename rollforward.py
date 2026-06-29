"""Weekly roll-forward — implements Troy's described process exactly.

Given the current anchor A (the date at column X):
  1. the new week's 7 daily values  -> LWeek Day 1-7 (D:J), for every product;
  2. the week currently at the FRONT of the daily block, [A .. A+6] (last year's
     same week, X:AD) -> LYear Day1-7 (K:Q), for every product;
  3. the anchor advances 7 days (A -> A+7), so A+7 becomes the new column X and
     the block "shifts left" — the consumed front week no longer shows in the
     X-onward columns (it now lives in LYear). Prior daily history is preserved.

The new week goes into LWeek only — it is NOT appended to the daily block, just
as in the sheet. The incoming file is the wide weekly layout Troy sends:
    SKU CODE,10-Feb,11-Feb,12-Feb,13-Feb,14-Feb,15-Feb,16-Feb
SKUs are read strictly as text; blank cells mean zero usage.
"""

import csv
import datetime as _dt
import io

import calc
import db

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _new_week_dates(labels, base):
    """Real dates for the new week. The new week is THIS year (anchor year + 1);
    its month/day come from the uploaded file's column labels (e.g. '11-Nov'),
    so banking lands on the actual week — not blindly anchor+1yr (which is only
    right when the new week happens to be exactly one year after column X)."""
    year = base.year + 1
    dates = []
    for lbl in (labels or [])[:7]:
        try:
            parts = str(lbl).strip().replace(".", "").split("-")
            dates.append(_dt.date(year, _MONTHS[parts[1][:3].lower()], int(parts[0])).isoformat())
        except Exception:
            dates.append(None)
    if len(dates) != 7 or any(d is None for d in dates):   # fallback: one year after the anchor week
        try:
            tw = base.replace(year=year)
        except ValueError:
            tw = base.replace(year=year, day=28)
        dates = [(tw + _dt.timedelta(days=i)).isoformat() for i in range(7)]
    return dates


def parse_weekly_csv(text: str):
    """Return ({sku: [7 daily values]}, [7 header labels], report)."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    report = {"format_ok": False, "rows": 0, "labels": []}
    if not rows:
        return {}, [], report
    header = [c.strip() for c in rows[0]]
    labels = header[1:8]
    report["labels"] = labels
    report["format_ok"] = len(labels) >= 1
    usage = {}
    for r in rows[1:]:
        sku = (r[0] or "").strip()
        if not sku:
            continue
        vals = []
        for i in range(1, 8):
            cell = (r[i].strip() if i < len(r) else "")
            try:
                vals.append(float(cell) if cell != "" else 0.0)
            except ValueError:
                vals.append(0.0)
        usage[sku] = vals
        report["rows"] += 1
    return usage, labels, report


def roll_forward(conn, weekly_usage: dict, labels=None):
    params = db.get_params(conn)
    old_anchor = params["lead_window_anchor"]
    base = _dt.date.fromisoformat(old_anchor)
    front_dates = [(base + _dt.timedelta(days=i)).isoformat() for i in range(7)]

    # the front week of the block, per SKU (becomes LYear)
    front = {}
    placeholders = ",".join("?" * 7)
    for sku, d, qty in conn.execute(
        f"SELECT sku, usage_date, qty FROM daily_usage WHERE usage_date IN ({placeholders})",
        tuple(front_dates),
    ):
        front.setdefault(sku, {})[d] = qty

    known = [r["sku"] for r in conn.execute("SELECT sku FROM products")]
    known_set = set(known)
    skipped_unknown = sorted(s for s in weekly_usage if s not in known_set)

    # Real dates for the new week, taken from the uploaded file's labels.
    new_week_dates = _new_week_dates(labels, base)

    banked = 0
    for sku in known:
        lweek = weekly_usage.get(sku, [0.0] * 7)                       # new week -> D:J (LWeek)
        lyear = [front.get(sku, {}).get(front_dates[i], 0.0) for i in range(7)]  # block front -> K:Q (LYear)
        db.set_comparison_week(conn, sku, lweek, lyear)
        # Bank the new week onto the END of the daily block (real dates), so it
        # becomes next year's "last year" data (Troy, 2026-06).
        for i, qty in enumerate(lweek):
            if qty:
                conn.execute(
                    "INSERT INTO daily_usage(sku, usage_date, qty) VALUES (?,?,?) "
                    "ON CONFLICT(sku, usage_date) DO UPDATE SET qty = excluded.qty",
                    (sku, new_week_dates[i], qty),
                )
                banked += 1

    new_anchor = (base + _dt.timedelta(days=7)).isoformat()
    db.set_params(conn, params["safety_factor"], new_anchor)
    conn.commit()

    run_date = _dt.date.today().isoformat()
    n = calc.run_calculation(conn, run_date, db.get_params(conn))

    return {
        "old_anchor": old_anchor,
        "new_anchor": new_anchor,
        "new_week_start": new_week_dates[0],
        "new_week_end": new_week_dates[6],
        "skus_in_file": len(weekly_usage),
        "skus_updated": len(known),
        "banked_values": banked,
        "skipped_unknown": skipped_unknown,
        "computed": n,
        "run_date": run_date,
    }
