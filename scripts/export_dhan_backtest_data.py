"""Export Dhan historical data for backtesting.

Since Dhan API only provides last 90 days, run this script periodically
(weekly/monthly) to build a persistent backtest dataset.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dhan_client import DhanClient
from app.nse_universe import build_universe

IST = ZoneInfo("Asia/Kolkata")


def export_backtest_data(output_dir: Path, symbol_filter: list = None):
    """Export last 90 days of 5M and 15M data for backtesting."""
    output_dir.mkdir(parents=True, exist_ok=True)

    dhan = DhanClient()
    today = datetime.now(IST).date()
    lookback_date = today - timedelta(days=90)

    print(f"Exporting historical data from {lookback_date} to {today}")
    print(f"Output directory: {output_dir}")

    # Get universe
    universe = build_universe(dhan)
    if symbol_filter:
        universe = [u for u in universe if u.get("symbol") in symbol_filter]

    print(f"Exporting {len(universe)} symbols...")

    candles_5m = []
    candles_15m = []
    failed_symbols = []

    for idx, item in enumerate(universe, 1):
        symbol = item.get("symbol")
        security_id = item.get("security_id")

        if not symbol or security_id is None:
            continue

        try:
            # Fetch 5M data
            df5 = dhan.historical_intraday_df(
                security_id=security_id,
                interval=5,
                from_date=lookback_date.isoformat(),
                to_date=today.isoformat(),
            )
            if df5 is not None and not df5.empty:
                df5 = df5.reset_index()  # Move timestamp from index to column
                df5["symbol"] = symbol
                candles_5m.append(df5)

            # Fetch 15M data
            df15 = dhan.historical_intraday_df(
                security_id=security_id,
                interval=15,
                from_date=lookback_date.isoformat(),
                to_date=today.isoformat(),
            )
            if df15 is not None and not df15.empty:
                df15 = df15.reset_index()  # Move timestamp from index to column
                df15["symbol"] = symbol
                candles_15m.append(df15)

            if (idx % 10) == 0:
                print(f"  ✓ {idx}/{len(universe)} - {symbol}")

        except Exception as e:
            print(f"  ✗ {symbol}: {e}")
            failed_symbols.append(symbol)

    # Combine and save
    if candles_5m:
        df5_combined = pd.concat(candles_5m, ignore_index=True)
        file_5m = output_dir / f"5m_last_90d_{today.isoformat()}.csv"
        df5_combined.to_csv(file_5m, index=False)
        print(f"\n✅ Saved 5M data: {file_5m}")
        print(f"   Rows: {len(df5_combined)}, Symbols: {df5_combined['symbol'].nunique()}")

    if candles_15m:
        df15_combined = pd.concat(candles_15m, ignore_index=True)
        file_15m = output_dir / f"15m_last_90d_{today.isoformat()}.csv"
        df15_combined.to_csv(file_15m, index=False)
        print(f"✅ Saved 15M data: {file_15m}")
        print(f"   Rows: {len(df15_combined)}, Symbols: {df15_combined['symbol'].nunique()}")

    if failed_symbols:
        print(f"\n⚠️  Failed to export ({len(failed_symbols)}): {', '.join(failed_symbols[:5])}...")

    # Create symlink to latest (skip on Windows if permission denied)
    latest_5m = file_5m
    latest_15m = file_15m

    if candles_5m:
        latest_5m = output_dir / "5m_last_90d.csv"
        latest_5m.unlink(missing_ok=True)
        try:
            latest_5m.symlink_to(file_5m.name)
        except OSError:
            latest_5m = file_5m
            print(f"\n⚠️  Symlink failed (Windows permission) - using direct file path")

    if candles_15m:
        latest_15m = output_dir / "15m_last_90d.csv"
        latest_15m.unlink(missing_ok=True)
        try:
            latest_15m.symlink_to(file_15m.name)
        except OSError:
            latest_15m = file_15m

    print(f"\n✅ Export complete!")
    print(f"Run backtest with:")
    print(f"  python scripts/historical_backtest_15m5m_confirmation.py \\")
    print(f"    --data-5m {latest_5m} \\")
    print(f"    --data-15m {latest_15m}")


if __name__ == "__main__":
    output_dir = Path("data/historical")

    # Optional: filter to specific symbols
    # symbol_filter = ["AARTIIND", "ACMESOLAR", "ADANIGREEN", ...]
    symbol_filter = None

    export_backtest_data(output_dir, symbol_filter)
