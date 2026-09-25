"""
Diagnose which filters reject the 9 weak stocks with 15M RSI fix.
"""

import pandas as pd
import sys
from pathlib import Path
from .strategy import evaluate_b1_breakout
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
LOG = logging.getLogger(__name__)

# Track rejections
REJECTIONS = {
    'NO_BREAKOUT': 0,
    'RSI_OUT_OF_BAND': 0,
    'RVOL_TOO_LOW': 0,
    'CANDLE_BODY_TOO_WEAK': 0,
    'RVOL_BELOW_TIME_THRESHOLD': 0,
    'OTHER': 0,
}

weak_stocks = ['PNBHOUSING', 'USHAMART', 'SBILIFE', 'TRENT', 'PIRAMALFIN', 'AXISBANK', 'HONASA', 'AUBANK', 'BAJFINANCE']

# Capture rejections via custom logger
class RejectionCapture(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if 'B1_FILTER_REJECTED' in msg:
            for reason in REJECTIONS:
                if reason in msg:
                    REJECTIONS[reason] += 1
                    break

def diagnose_csv(csv_path):
    """Analyze rejection patterns."""
    print(f"\n[DIAGNOSE] Loading: {csv_path}")

    df = pd.read_csv(csv_path, parse_dates=['timestamp'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('Asia/Kolkata')
    df = df.set_index('timestamp')

    # Add rejection capture
    capture = RejectionCapture()
    LOG.addHandler(capture)

    print(f"  Analyzing 9 weak stocks...")
    weak_df = df[df['symbol'].isin(weak_stocks)]

    total_breakouts = 0
    total_passed = 0

    for symbol in weak_stocks:
        symbol_data = weak_df[weak_df['symbol'] == symbol]
        passed = 0

        for date, day_data in symbol_data.groupby(symbol_data.index.date):
            day_df = day_data.sort_index()

            orb_row = day_df[day_df.index.strftime("%H:%M") == "09:15"]
            if orb_row.empty:
                continue

            orb = {
                "high": float(orb_row.iloc[0]["high"]),
                "low": float(orb_row.iloc[0]["low"]),
                "close": float(orb_row.iloc[0]["close"]),
                "timestamp": orb_row.index[0].isoformat(),
            }

            candidates = day_df[day_df.index > pd.Timestamp(orb["timestamp"])]

            for candle_ts, candle in candidates.iterrows():
                close = float(candle["close"])

                if close <= orb["high"] and close >= orb["low"]:
                    continue

                total_breakouts += 1

                try:
                    result = evaluate_b1_breakout(
                        day_df.loc[:candle_ts],
                        orb,
                        daily_close=float(candle.get("close", 0)),
                        daily_volume=float(candle.get("volume", 0)),
                        symbol=symbol,
                    )
                    if result is not None:
                        passed += 1
                        total_passed += 1
                except Exception as e:
                    pass

        pass_rate = (passed / max(1, total_breakouts)) * 100
        print(f"\n{symbol}: {passed} passed")

    print(f"\n" + "="*60)
    print(f"TOTAL: {total_passed} passed / {total_breakouts} breakouts")
    print(f"Pass rate: {(total_passed / max(1, total_breakouts)) * 100:.2f}%")
    print(f"\nFilter rejection counts:")
    for reason, count in sorted(REJECTIONS.items(), key=lambda x: -x[1]):
        if count > 0:
            pct = (count / max(1, total_breakouts)) * 100
            print(f"  {reason}: {count} ({pct:.1f}%)")

def main():
    if len(sys.argv) < 2:
        csv_file = "data/historical/indicators_recalc_15m.csv"
    else:
        csv_file = sys.argv[1]

    diagnose_csv(csv_file)

if __name__ == "__main__":
    main()
