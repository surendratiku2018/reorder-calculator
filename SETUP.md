# Reorder Calculator — Setup Guide

This is a small app that runs **on your own computer**. It works the same on
**Mac or Windows** — only the one-time setup differs. Your data stays on your
machine; nothing is sent anywhere.

---

## Step 1 — Install Python (one time, ~2 minutes)

The app needs Python 3.11 or newer (free).

1. Go to **https://www.python.org/downloads/** and click the big "Download Python" button.
2. Run the installer.
   - **Windows:** on the first screen, **tick "Add python.exe to PATH"**, then click "Install Now".
   - **Mac:** just run through the installer normally.

(If you already have Python 3.11+, skip this.)

## Step 2 — Unzip the folder

Unzip `reorder_calculator.zip` somewhere easy to find, like your Desktop. You'll
get a folder called `reorder_calculator`.

## Step 3 — Start the app

**Mac:** open the folder and **double-click `run_mac.command`**.
  - The first time, macOS may say it's from an unidentified developer. If so:
    right-click the file → **Open** → **Open**. (Only needed once.)

**Windows:** open the folder and **double-click `run_windows.bat`**.

The first launch takes 1–2 minutes (it sets itself up). After that it starts in
a few seconds. A black/terminal window will open and stay open — that's normal;
**leave it open while you use the app.** Your web browser will open automatically
to **http://localhost:8501**.

To **stop** the app, just close that terminal window.

---

## Using it

* **Reorder dashboard** — view/filter/sort all products and their reorder points.
* **Run calculation** — recompute (and adjust the safety factor if ever needed).
* **Import usage** — upload a week of actual usage to roll the data forward.
* **Edit products** — change a lead time, supplier, category.
* **Export** — download results; use the **Excel-safe .xlsx** to open in Excel
  (SKUs stay text and never turn into dates).
* **Start fresh** — load a brand-new master spreadsheet to re-base everything on
  newer data (e.g. start over with current data).

The app opens with the sample dataset already loaded. To switch to your own
current data, use **Start fresh**.

---

## Notes

* **Mac vs Windows:** no functional difference — same features, same numbers.
* **Your data persists** on your computer between sessions (unlike the temporary
  preview link).
* **Password:** none is needed for local use. (If you ever put it on a shared
  server, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
  and set a password — then only people with the password can open it.)
* **Run the built-in checks** (optional, for peace of mind): in the terminal,
  from the folder, run `.venv/bin/pytest -q` (Mac) or `.venv\Scripts\pytest -q`
  (Windows) — it confirms the formulas match the spreadsheet's known values.

See `README.md` for the technical details and `SPEC.md` for the original spec.
