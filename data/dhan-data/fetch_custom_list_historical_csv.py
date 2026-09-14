"""
fetch_custom_list_historical_csv.py

A single, standalone script: fetches historical OHLCV candles for a
CUSTOM list of stocks, at both 5-minute and 15-minute intervals, for a
given date range, and saves everything as CSV files.

This does NOT touch any other script or file. Just edit the settings
below and run it.

What it does, step by step:
  1. Downloads Dhan's scrip master (to map each symbol to its Dhan
     security_id) -- no manual lookup needed.
  2. For each stock in SYMBOLS below, calls Dhan's intraday history
     endpoint twice: once for 5-min candles, once for 15-min candles.
  3. Saves one CSV per stock per timeframe, plus two combined CSVs
     (all stocks together) -- one for 5-min, one for 15-min.

Usage:
    set DHAN_CLIENT_ID=your_client_id
    set DHAN_ACCESS_TOKEN=your_access_token
    python fetch_custom_list_historical_csv.py
"""

import os
import csv
import io
import json
import time
from datetime import datetime
import urllib.request
import urllib.error

# ============================================================
# EDIT THESE SETTINGS
# ============================================================

FROM_DATE = "2026-06-01 09:00:00"   # format: YYYY-MM-DD HH:MM:SS
TO_DATE = "2026-07-12 15:30:00"

INTERVALS = {
    "5min": "5",
    "15min": "15",
}

OUTPUT_DIR = "custom_list_data"   # folder where CSVs will be saved

CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")

# ============================================================
# Your custom stock list (NSE trading symbols)
# ============================================================

SYMBOLS = [
    "ABCAPITAL", "ADANIENSOL", "ADANIGREEN", "ATHERENERG", "BHARATFORG",
    "BHEL", "BSE", "CGPOWER", "FEDERALBNK", "FINCABLES",
    "GESHIP", "GMDCLTD", "GRANULES", "HINDALCO", "HINDCOPPER",
    "HONASA", "KARURVYSYA", "KEI", "LAURUSLABS", "LTF",
    "MCX", "NATIONALUM", "NETWEB", "NLCINDIA", "NTPC",
    "POLYCAB", "RBLBANK", "RRKABEL", "SAILIFE", "SHRIRAMFIN",
    "SYRMA", "VEDL", "WELCORP",
]

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
DHAN_INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
EXCHANGE_SEGMENT = "NSE_EQ"
INSTRUMENT = "EQUITY"

REQUEST_SLEEP_SECONDS = 0.35

# ============================================================
# Script logic (no need to edit below this line)
# ============================================================


def get_security_ids():
    """Download Dhan's scrip master and map symbols to security_id."""
    print("Downloading Dhan scrip master to find security IDs...")
    req = urllib.request.Request(SCRIP_MASTER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw_csv = resp.read().decode("utf-8", errors="ignore")

    reader = csv.DictReader(io.StringIO(raw_csv))
    fieldnames = reader.fieldnames or []

    def find_col(*candidates):
        for c in candidates:
            if c in fieldnames:
                return c
        return None

    col_exch = find_col("SEM_EXM_EXCH_ID", "EXCH_ID", "Exchange")
    col_series = find_col("SEM_SERIES", "Series")
    col_symbol = find_col("SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "TradingSymbol")
    col_secid = find_col("SEM_SMST_SECURITY_ID", "SecurityId")

    if not all([col_exch, col_series, col_symbol, col_secid]):
        raise RuntimeError(f"Could not find expected columns. Columns present: {fieldnames}")

    wanted = {s.upper(): None for s in SYMBOLS}

    for row in reader:
        exch = (row.get(col_exch) or "").strip().upper()
        series = (row.get(col_series) or "").strip().upper()
        symbol = (row.get(col_symbol) or "").strip().upper()
        secid = (row.get(col_secid) or "").strip()

        if exch == "NSE" and series == "EQ" and symbol in wanted and wanted[symbol] is None:
            wanted[symbol] = secid

    found = {k: v for k, v in wanted.items() if v}
    missing = [k for k in SYMBOLS if k not in found]
    if missing:
        print(f"WARNING: could not find security_id for: {missing}")

    return found


def fetch_intraday(security_id, interval):
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": EXCHANGE_SEGMENT,
        "instrument": INSTRUMENT,
        "interval": interval,
        "oi": False,
        "fromDate": FROM_DATE,
        "toDate": TO_DATE,
    }
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        DHAN_INTRADAY_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": ACCESS_TOKEN,
            "client-id": CLIENT_ID,
        },
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def parse_candles(raw):
    required = ("open", "high", "low", "close", "volume", "timestamp")
    if not all(k in raw for k in required):
        raise ValueError(f"Unexpected response shape: {list(raw.keys())}")

    n = len(raw["timestamp"])
    rows = []
    for i in range(n):
        ts = datetime.fromtimestamp(raw["timestamp"][i]).strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "timestamp": ts,
            "open": raw["open"][i],
            "high": raw["high"][i],
            "low": raw["low"][i],
            "close": raw["close"][i],
            "volume": raw["volume"][i],
        })
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    if not CLIENT_ID or not ACCESS_TOKEN:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables first.")
        return

    # # --- DEBUG: verify what the script actually received ---
    # print(f"DEBUG: CLIENT_ID = {repr(CLIENT_ID)}")
    # print(f"DEBUG: ACCESS_TOKEN length = {len(ACCESS_TOKEN)}")
    # print(f"DEBUG: ACCESS_TOKEN starts with = {ACCESS_TOKEN[:15]!r}")
    # print(f"DEBUG: ACCESS_TOKEN ends with   = {ACCESS_TOKEN[-15:]!r}")
    # print(f"DEBUG: ACCESS_TOKEN dot count = {ACCESS_TOKEN.count('.')}  (a real JWT has exactly 2)")
    # print("---")
    print("Dhan credentials detected.")
    # # --- END DEBUG ---

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    security_ids = get_security_ids()
    combined_rows = {tf: [] for tf in INTERVALS}
    failures = []

    for symbol in SYMBOLS:
        security_id = security_ids.get(symbol)
        if not security_id:
            print(f"Skipping {symbol}: no security_id found.")
            continue

        for tf_name, interval in INTERVALS.items():
            print(f"Fetching {symbol} ({security_id}) - {tf_name} ...")
            try:
                raw = fetch_intraday(security_id, interval)
                rows = parse_candles(raw)
                out_path = os.path.join(OUTPUT_DIR, f"{symbol}_{tf_name}.csv")
                write_csv(out_path, rows)

                for r in rows:
                    combined_rows[tf_name].append({"symbol": symbol, **r})

                print(f"  -> {len(rows)} candles saved to {out_path}")
            except Exception as e:
                print(f"  !! FAILED: {e}")
                failures.append((symbol, tf_name, str(e)))

            time.sleep(REQUEST_SLEEP_SECONDS)

    for tf_name in INTERVALS:
        rows = combined_rows[tf_name]
        if not rows:
            continue
        out_path = os.path.join(OUTPUT_DIR, f"all_custom_{tf_name}.csv")
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["symbol", "timestamp", "open", "high", "low", "close", "volume"]
            )
            writer.writeheader()
            writer.writerows(rows)
        print(f"Combined file written: {out_path} ({len(rows)} rows)")

    if failures:
        print("\nSymbols/timeframes that failed:")
        for symbol, tf_name, err in failures:
            print(f"  {symbol} [{tf_name}]: {err}")


if __name__ == "__main__":
    main()
