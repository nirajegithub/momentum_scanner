"""Simple backtest using current strategy code."""

import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import SETTINGS
from app.indicators import add_indicators

IST = ZoneInfo("Asia/Kolkata")


def load_data(csv_path: str) -> pd.DataFrame:
    """Load CSV data and prepare it."""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(IST)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(IST)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def simple_backtest(df5: pd.DataFrame, df15: pd.DataFrame, output_file: str = "backtest/simple_baseline.csv"):
    """Simple backtest: count trades where 15M breakout + 5M confirmation."""

    print("Loading and preparing data...")
    df5 = load_data(df5) if isinstance(df5, str) else df5
    df15 = load_data(df15) if isinstance(df15, str) else df15

    # Add indicators to 15M
    df15_with_ind = add_indicators(df15.set_index("timestamp"), rvol_lookback=SETTINGS.rvol_lookback).reset_index()

    trades = []

    for symbol in df15["symbol"].unique():
        symbol_15m = df15_with_ind[df15_with_ind["symbol"] == symbol].sort_values("timestamp")
        symbol_5m = df5[df5["symbol"] == symbol].sort_values("timestamp")

        if symbol_15m.empty or symbol_5m.empty:
            continue

        # Get ORB (09:15)
        orb_data = symbol_15m[symbol_15m["timestamp"].dt.strftime("%H:%M") == "09:15"]
        if orb_data.empty:
            continue

        orb = orb_data.iloc[0]
        orb_high = float(orb["high"])
        orb_low = float(orb["low"])

        # Scan for setups
        for idx, row15 in symbol_15m.iterrows():
            if row15["timestamp"] <= orb["timestamp"]:
                continue

            close15 = float(row15["close"])

            # Check for breakout
            if close15 > orb_high:
                direction = "BUY"
            elif close15 < orb_low:
                direction = "SELL"
            else:
                continue

            # Check quality (RSI, RVOL)
            rsi = float(row15.get("rsi14", 0))
            rvol = float(row15.get("rvol", 0))

            if direction == "BUY":
                if rsi < SETTINGS.buy_rsi_min or rsi > SETTINGS.buy_rsi_max:
                    continue
                if rvol < SETTINGS.min_15m_rvol:
                    continue
            else:
                if rsi < SETTINGS.sell_rsi_min or rsi > SETTINGS.sell_rsi_max:
                    continue
                if rvol < SETTINGS.min_15m_rvol:
                    continue

            # Look for 5M confirmation after setup
            setup_time = row15["timestamp"]
            symbol_5m_after = symbol_5m[symbol_5m["timestamp"] > setup_time]

            for _, row5 in symbol_5m_after.head(10).iterrows():
                close5 = float(row5["close"])

                # Check confirmation
                if direction == "BUY" and close5 > float(row15["high"]):
                    entry = close5
                    sl = close15
                    trades.append({
                        "symbol": symbol,
                        "direction": direction,
                        "setup_15m_timestamp": setup_time.isoformat(),
                        "confirmation_5m_timestamp": row5["timestamp"].isoformat(),
                        "entry_price": entry,
                        "sl_price": sl,
                        "setup_rsi": rsi,
                        "setup_rvol": rvol,
                    })
                    break
                elif direction == "SELL" and close5 < float(row15["low"]):
                    entry = close5
                    sl = close15
                    trades.append({
                        "symbol": symbol,
                        "direction": direction,
                        "setup_15m_timestamp": setup_time.isoformat(),
                        "confirmation_5m_timestamp": row5["timestamp"].isoformat(),
                        "entry_price": entry,
                        "sl_price": sl,
                        "setup_rsi": rsi,
                        "setup_rvol": rvol,
                    })
                    break

    # Save results
    if trades:
        results_df = pd.DataFrame(trades)
        results_df.to_csv(output_file, index=False)
        print(f"\n✅ Backtest complete!")
        print(f"Total setups found: {len(trades)}")
        print(f"Buy setups: {len([t for t in trades if t['direction'] == 'BUY'])}")
        print(f"Sell setups: {len([t for t in trades if t['direction'] == 'SELL'])}")
        print(f"Saved to: {output_file}")
        return results_df
    else:
        print("❌ No trades found in backtest")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Simple backtest")
    parser.add_argument("--data-5m", required=True, help="5M CSV file")
    parser.add_argument("--data-15m", required=True, help="15M CSV file")
    parser.add_argument("--out", default="backtest/simple_baseline.csv", help="Output file")

    args = parser.parse_args()

    simple_backtest(args.data_5m, args.data_15m, args.out)
