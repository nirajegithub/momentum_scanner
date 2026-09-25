"""
Fetch 90-day 15M candle data from Dhan API for 8 missing stocks.
Save to CSV and run backtest.
"""
import pandas as pd
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .dhan_client import DhanClient

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

# NSE security IDs for the 8 stocks (approximate, may need verification)
STOCKS_TO_FETCH = {
    "PNBHOUSING": 2031296,
    "SBILIFE": 1922057,
    "TRENT": 1705857,
    "PIRAMALFIN": 1918597,
    "AXISBANK": 1333441,
    "HONASA": 2004729,
    "AUBANK": 1346753,
    "BAJFINANCE": 1346369,
}

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "historical" / "fetched_9stocks_90d.csv"


def fetch_stock_data(dhan, symbol, security_id):
    """Fetch 90-day 15M data for a stock."""
    print(f"\n[FETCH] {symbol} (ID: {security_id})...")

    to_date = datetime.now(IST).date()
    from_date = to_date - timedelta(days=90)

    try:
        df = dhan.historical_minute_df(
            security_id=security_id,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            interval=15,
        )

        if df is None or df.empty:
            print(f"  [WARN] No data returned")
            return None

        # Standardize column names
        df = df.reset_index()
        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi']
        df['symbol'] = symbol

        # Select relevant columns
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']]

        print(f"  [OK] {len(df)} candles fetched ({from_date} to {to_date})")
        return df

    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return None


def main():
    """Fetch 90-day data for 8 stocks."""
    print("\n" + "="*80)
    print("FETCH 90-DAY DATA FOR 8 STOCKS FROM DHAN API")
    print("="*80)

    dhan = DhanClient()

    all_data = []

    for symbol, security_id in STOCKS_TO_FETCH.items():
        df = fetch_stock_data(dhan, symbol, security_id)
        if df is not None:
            all_data.append(df)

    if not all_data:
        print("\n[ERROR] No data fetched for any stock")
        return

    # Combine all data
    combined = pd.concat(all_data, ignore_index=True)
    combined = combined.sort_values('timestamp').reset_index(drop=True)

    print(f"\n[SUMMARY]")
    print(f"  Total records: {len(combined)}")
    print(f"  Symbols: {combined['symbol'].nunique()}")
    print(f"  Date range: {combined['timestamp'].min()} to {combined['timestamp'].max()}")

    # Save to CSV
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\n[SAVED] {OUTPUT_FILE}")

    # Show summary by stock
    print(f"\n[DATA BY STOCK]")
    for symbol in sorted(combined['symbol'].unique()):
        count = len(combined[combined['symbol'] == symbol])
        print(f"  {symbol:<15} - {count:>5} candles")

    print(f"\nNext: Run backtest on combined data (existing + new)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
