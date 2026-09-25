"""
Recalculate indicators on 15M CSV data with correct 15M RSI.

The fetched CSV has 15M candles, but the RSI was calculated with 5M logic.
This script recalculates RSI/RVOL correctly for 15M analysis.
"""

import pandas as pd
import sys
from pathlib import Path
from .indicators import add_indicators

def recalculate_csv(csv_path, output_path=None):
    """Recalculate indicators on CSV with correct 15M logic."""
    print(f"\n[RECALC] Loading: {csv_path}")

    df = pd.read_csv(csv_path, parse_dates=['timestamp'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('Asia/Kolkata')
    df = df.set_index('timestamp')

    print(f"  Candles: {len(df)}")
    print(f"  Symbols: {df['symbol'].nunique()}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")

    # Recalculate indicators per symbol
    results = []
    for symbol, group_data in df.groupby('symbol'):
        print(f"\n  {symbol}: recalculating indicators...")

        # Sort and prepare
        group_sorted = group_data.sort_index()

        # Add indicators with correct 15M logic
        with_indicators = add_indicators(group_sorted, rvol_lookback=20)

        # Add symbol back
        with_indicators['symbol'] = symbol
        results.append(with_indicators)

        print(f"    {len(with_indicators)} candles with valid indicators")

    # Combine all symbols
    combined = pd.concat(results, ignore_index=False)
    combined = combined.sort_index()

    # Save
    if output_path is None:
        output_path = str(Path(csv_path).parent / 'indicators_recalc_15m.csv')

    combined.to_csv(output_path)
    print(f"\n[SAVED] {output_path}")
    print(f"  Total candles: {len(combined)}")

    return output_path

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.recalc_indicators_15m <csv_file>")
        sys.exit(1)

    csv_file = sys.argv[1]
    recalculate_csv(csv_file)

if __name__ == "__main__":
    main()
