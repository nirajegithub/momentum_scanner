"""Quick setup counter - no timestamps needed."""

import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def quick_count(df5_path: str, df15_path: str):
    """Count 15M setups by symbols."""

    print("Loading data...")
    df5 = pd.read_csv(df5_path)
    df15 = pd.read_csv(df15_path)

    # Convert to numeric
    for df in [df5, df15]:
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    print(f"\n✅ DATA LOADED")
    print(f"{'='*50}")
    print(f"5M candles: {len(df5):,} rows")
    print(f"15M candles: {len(df15):,} rows")
    print(f"Symbols in data: {df15['symbol'].nunique()}")
    print(f"{'='*50}")

    # Group by symbol
    print(f"\nSetups by Symbol:")
    print(f"{'='*50}")

    total_setups = 0
    for symbol in sorted(df15['symbol'].unique()):
        symbol_data = df15[df15['symbol'] == symbol]

        # Count candles with good RVOL (proxy: volume above median)
        median_vol = symbol_data['volume'].median()
        high_volume = symbol_data[symbol_data['volume'] > median_vol * 1.5]

        setups = len(high_volume)
        total_setups += setups

        if setups > 0:
            print(f"  {symbol:15} : {setups:3} potential setups")

    print(f"{'='*50}")
    print(f"Total potential setups: {total_setups:,}")
    print(f"\n📊 SUMMARY")
    print(f"Avg setups per symbol: {total_setups / df15['symbol'].nunique():.1f}")
    print(f"\nNote: This is a simple count of high-volume 15M candles.")
    print(f"Actual backtested trades will be lower after filtering by:")
    print(f"  - RSI levels")
    print(f"  - 5M confirmation")
    print(f"  - Quality scores")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-5m", required=True)
    parser.add_argument("--data-15m", required=True)
    args = parser.parse_args()

    quick_count(args.data_5m, args.data_15m)
