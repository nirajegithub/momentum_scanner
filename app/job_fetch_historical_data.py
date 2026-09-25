"""
Job: Fetch 90-day historical data from Dhan API.

This is a reusable job script that reads config from config/stocks_to_fetch.json
and fetches 15M candle data for all enabled stocks.

Usage:
    python -m app.job_fetch_historical_data [--config CONFIG_FILE]

Environment Requirements:
    - DHAN_CLIENT_ID
    - DHAN_ACCESS_TOKEN

Output:
    - data/historical/fetched_YYYYMMDD_HHMM.csv (timestamped)
    - Can be appended to existing data or saved separately
"""

import json
import pandas as pd
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
from .dhan_client import DhanClient

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent.parent / "config" / "stocks_to_fetch.json"
DATA_DIR = Path(__file__).parent.parent / "data" / "historical"


def load_config(config_path=None):
    """Load stocks to fetch from config JSON."""
    path = config_path or CONFIG_FILE

    if not path.exists():
        LOG.error(f"Config not found: {path}")
        return None

    try:
        with open(path) as f:
            config = json.load(f)
        return config["fetch_config"]
    except Exception as e:
        LOG.error(f"Failed to load config: {e}")
        return None


def fetch_stock_data(dhan, symbol, security_id, days_back=90, interval=15):
    """Fetch historical data for one stock."""
    to_date = datetime.now(IST).date()
    from_date = to_date - timedelta(days=days_back)

    try:
        LOG.info(f"[FETCH] {symbol:<15} (ID: {security_id}) | {from_date} to {to_date}")

        df = dhan.historical_minute_df(
            security_id=security_id,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            interval=interval,
        )

        if df is None or df.empty:
            LOG.warning(f"  [WARN] No data returned for {symbol}")
            return None

        # Standardize columns
        df = df.reset_index()
        if 'datetime' in df.columns:
            df.rename(columns={'datetime': 'timestamp'}, inplace=True)

        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi']
        df['symbol'] = symbol

        # Select relevant columns
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']]
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        LOG.info(f"  [OK] {len(df):>5} candles | {df['timestamp'].min()} to {df['timestamp'].max()}")
        return df

    except Exception as e:
        LOG.error(f"  [ERROR] {symbol}: {type(e).__name__}: {str(e)[:80]}")
        return None


def main(config_file=None):
    """Main job: fetch data for all enabled stocks."""
    # Setup logging
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)

    print("\n" + "="*90)
    print("JOB: FETCH 90-DAY HISTORICAL DATA")
    print("="*90)

    # Load config
    config = load_config(config_file)
    if not config:
        print("[ERROR] Failed to load configuration")
        return False

    # Check Dhan credentials
    if not os.getenv("DHAN_CLIENT_ID") or not os.getenv("DHAN_ACCESS_TOKEN"):
        print("[ERROR] Dhan credentials not set:")
        print("  export DHAN_CLIENT_ID=your_client_id")
        print("  export DHAN_ACCESS_TOKEN=your_fresh_token")
        return False

    # Initialize Dhan client
    try:
        dhan = DhanClient()
    except Exception as e:
        print(f"[ERROR] Failed to initialize Dhan client: {e}")
        return False

    # Filter enabled stocks
    stocks = [s for s in config["stocks"] if s.get("enabled", True)]
    print(f"\nFetching data for {len(stocks)} stocks...")
    print(f"  Interval: {config['parameters']['interval_minutes']}M")
    print(f"  Period: {config['parameters']['days_back']} days")

    # Fetch data
    all_data = []
    successful = 0

    for stock_config in stocks:
        symbol = stock_config["symbol"]
        security_id = stock_config["security_id"]

        df = fetch_stock_data(
            dhan,
            symbol,
            security_id,
            days_back=config["parameters"]["days_back"],
            interval=config["parameters"]["interval_minutes"],
        )

        if df is not None:
            all_data.append(df)
            successful += 1

    print(f"\n[RESULT] {successful}/{len(stocks)} stocks fetched successfully")

    if not all_data:
        print("[ERROR] No data fetched")
        return False

    # Combine data
    combined = pd.concat(all_data, ignore_index=True)
    combined = combined.sort_values('timestamp').reset_index(drop=True)

    # Generate output filename
    now = datetime.now(IST)
    timestamp = now.strftime("%Y%m%d_%H%M")
    output_file = DATA_DIR / f"fetched_{timestamp}.csv"

    # Ensure directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Save to CSV
    combined.to_csv(output_file, index=False)

    print(f"\n[SAVED] {output_file}")
    print(f"  Total records: {len(combined):,}")
    print(f"  Symbols: {combined['symbol'].nunique()}")
    print(f"  Date range: {combined['timestamp'].min()} to {combined['timestamp'].max()}")

    # Summary by stock
    print(f"\n[DATA BY STOCK]")
    for symbol in sorted(combined['symbol'].unique()):
        count = len(combined[combined['symbol'] == symbol])
        print(f"  {symbol:<15} - {count:>5} candles")

    print(f"\n[NEXT STEPS]")
    print(f"1. Run backtest: python -m app.job_backtest_fetched_data {output_file}")
    print(f"2. Or combine with existing data manually")
    print(f"3. To fetch more stocks, update config/stocks_to_fetch.json and re-run this job")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch 90-day historical data from Dhan API")
    parser.add_argument("--config", type=str, help="Path to config JSON file", default=None)
    args = parser.parse_args()

    success = main(args.config)
    exit(0 if success else 1)
