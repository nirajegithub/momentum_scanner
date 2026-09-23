#!/usr/bin/env python3
"""Debug: Check what timestamps are in today's 15M data."""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

# Add app to path
sys.path.insert(0, os.path.dirname(__file__))

from app.dhan_client import DhanClient
from app.nse_universe import build_universe
from app.state import load
from app.candle_utils import completed_candles

IST = ZoneInfo("Asia/Kolkata")
ts = datetime.now(IST)
trading_day = ts.date()

print("="*80)
print(f"🔍 DEBUGGING: ORB TIMESTAMP ISSUE")
print(f"Current time: {ts.strftime('%Y-%m-%d %H:%M:%S IST')}")
print(f"Trading day: {trading_day}")
print("="*80 + "\n")

dhan = DhanClient()
state = load(trading_day)

# Test with BHEL (had high RVOL in diagnostic)
test_symbols = ["BHEL", "KPITTECH", "RBLBANK"]

for symbol in test_symbols:
    print(f"\n{'='*80}")
    print(f"📊 {symbol}")
    print('='*80)

    # Find security_id
    item = next((s for s in state.get("universe", []) if s["symbol"] == symbol), None)
    if not item:
        print(f"❌ {symbol} not found in universe")
        continue

    security_id = item["security_id"]

    try:
        # Fetch raw 15M data
        print(f"\nFetching 15M data for {trading_day}...")
        raw = dhan.historical_intraday_df(
            security_id=security_id,
            interval=15,
            from_date=trading_day.isoformat(),
            to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
        )

        if raw is None or raw.empty:
            print("❌ No data returned")
            continue

        print(f"✅ Data fetched: {len(raw)} candles")

        # Show raw timestamps
        print(f"\nRaw timestamps (first 10):")
        print(raw.index[:10].tolist())

        # Convert to DataFrame and set IST timezone
        df = pd.DataFrame(raw).copy()
        df.index = pd.to_datetime(df.index)

        print(f"\nTimezone before localization: {df.index.tz}")

        if df.index.tz is None:
            df.index = df.index.tz_localize(IST)
        else:
            df.index = df.index.tz_convert(IST)

        print(f"Timezone after localization: {df.index.tz}")

        # Show converted timestamps
        print(f"\nConverted timestamps (first 10):")
        for i, ts_val in enumerate(df.index[:10]):
            print(f"  {i}: {ts_val} → HH:MM = {ts_val.strftime('%H:%M')}")

        # Look for 9:15
        times_hhmm = df.index.strftime("%H:%M")
        times_unique = sorted(times_hhmm.unique())

        print(f"\nAll unique times in data: {times_unique[:20]}")

        # Check for 9:15, 9:30, etc.
        for check_time in ["09:15", "09:30", "09:45"]:
            count = (times_hhmm == check_time).sum()
            if count > 0:
                print(f"  ✅ {check_time}: {count} candle(s)")
                matching = df[times_hhmm == check_time]
                print(f"     {matching.index[0]}")
            else:
                print(f"  ❌ {check_time}: NOT FOUND")

        # Show first and last candle
        print(f"\nFirst candle: {df.index[0]} ({df.index[0].strftime('%H:%M')})")
        print(f"Last candle: {df.index[-1]} ({df.index[-1].strftime('%H:%M')})")

    except Exception as exc:
        print(f"❌ Error: {exc}")
        import traceback
        traceback.print_exc()

print("\n" + "="*80)
print("ANALYSIS:")
print("="*80)
print("""
If 09:15 is NOT found but 09:30 IS found:
→ Dhan timestamps candles at CLOSE time, not OPEN time
→ The "09:30" candle is actually the 9:15-9:30 opening range
→ SOLUTION: Change code to look for "09:30" instead of "09:15"

If 09:15 IS found:
→ Code is correct, there's a different issue (data availability, timezone, etc.)

If NEITHER found:
→ Data doesn't start from market open
→ SOLUTION: Check data starting time
""")
