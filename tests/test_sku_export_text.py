import openpyxl
import db
import exports


def test_finale_subset_keeps_sku_as_text(tmp_path):
    dbfile = tmp_path / "test.db"
    conn = db.connect(str(dbfile))
    db.init_db(conn)
    conn.execute("INSERT INTO products (sku, description) VALUES (?, ?)", ("01-2500", "Test"))
    conn.execute("INSERT INTO reorder_results (sku, run_date, new_reorder_point) VALUES (?, ?, ?)", ("01-2500", "2026-07-09", 12))
    conn.commit()

    out = tmp_path / "subset.xlsx"
    exports.finale_subset_xlsx(conn, str(out), "2026-07-09")
    wb = openpyxl.load_workbook(out, data_only=False)
    cell = wb["Finale Subset"]["A2"]
    assert cell.value == "01-2500"
    assert cell.data_type == "s"
    assert cell.number_format == "@"
