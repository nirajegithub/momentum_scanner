"""Count setups in historical data - simple version without timestamps."""

import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import SETTINGS
from app.indicators import add_indicators

def count_setups(df5_path: str, df15_path: str):
    """Count 15M breakouts + 5M confirmations."""

    print("Loading data...")
    df5 = pd.read_csv(df5_path)
    df15 = pd.read_csv(df15_path)

    print(f"5M data: {len(df5)} rows, columns: {list(df5.columns)}")
    print(f"15M data: {len(df15)} rows, columns: {list(df15.columns)}")

    # Convert to numeric
    for c in ["open", "high", "low", "close", "volume"]:
        df5[c] = pd.to_numeric(df5[c], errors="coerce")
        df15[c] = pd.to_numeric(df15[c], errors="coerce")

    # Add indicators to 15M
    df15_with_ind = add_indicators(df15.set_index("symbol"), rvol_lookback=SETTINGS.rvol_lookback)

    setup_count = 0
    buy_count = 0
    sell_count = 0

    symbols = df15["symbol"].unique()
    print(f"\nScanning {len(symbols)} symbols...")

    for symbol in symbols:
        symbol_15m = df15[df15["symbol"] == symbol]
        symbol_5m = df5[df5["symbol"] == symbol]

        if len(symbol_15m) < 5 or len(symbol_5m) < 10:
            continue

        # Try to find ORB (first candle of each symbol group)
        # Group by day and find 09:15 candle if possible
        for idx, row15 in symbol_15m.iterrows():
            close15 = float(row15["close"])
            high15 = float(row15["high"])
            low15 = float(row15["low"])
            rsi15 = row15.get("rsi14", 50)
            rvol15 = row15.get("rvol", 1)

            # Skip if indicators missing
            if pd.isna(rsi15) or pd.isna(rvol15):
                continue

            rsi15 = float(rsi15)
            rvol15 = float(rvol15)

            # Check for BUY breakout (needs simple ORB detection)
            # For now, just count when price is > 15M open + RVOL is high + RSI good
            orb_open = float(symbol_15m.iloc[0]["open"]) if len(symbol_15m) > 0 else None

            if orb_open is None:
                continue

            # BUY: price above ORB open, good RSI, good RVOL
            if close15 > orb_open:
                if SETTINGS.buy_rsi_min < rsi15 < SETTINGS.buy_rsi_max:
                    if rvol15 >= SETTINGS.min_15m_rvol:
                        setup_count += 1
                        buy_count += 1

            # SELL: price below ORB open, good RSI, good RVOL
            elif close15 < orb_open:
                if SETTINGS.sell_rsi_min < rsi15 < SETTINGS.sell_rsi_max:
                    if rvol15 >= SETTINGS.min_15m_rvol:
                        setup_count += 1
                        sell_count += 1

    print(f"\n✅ BACKTEST RESULTS")
    print(f"{'='*50}")
    print(f"Total Setups Found: {setup_count}")
    print(f"BUY Setups: {buy_count}")
    print(f"SELL Setups: {sell_count}")
    print(f"{'='*50}")
    print(f"\nSettings Used:")
    print(f"  Min 15M RVOL: {SETTINGS.min_15m_rvol}")
    print(f"  Buy RSI Range: {SETTINGS.buy_rsi_min}-{SETTINGS.buy_rsi_max}")
    print(f"  Sell RSI Range: {SETTINGS.sell_rsi_min}-{SETTINGS.sell_rsi_max}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-5m", required=True)
    parser.add_argument("--data-15m", required=True)

    args = parser.parse_args()
    count_setups(args.data_5m, args.data_15m)
