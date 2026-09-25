"""
Job: Backtest fetched historical data.

This job reads a fetched CSV file and runs the B1 ORB strategy backtest
on all stocks in the file.

Usage:
    python -m app.job_backtest_fetched_data DATA_FILE

Example:
    python -m app.job_backtest_fetched_data data/historical/fetched_20260925_1430.csv
"""

import pandas as pd
import logging
import sys
from pathlib import Path
from .strategy import evaluate_b1_breakout

LOG = logging.getLogger(__name__)


def backtest_stock(symbol, data):
    """Backtest one stock."""
    total_candles = 0
    passed_filters = 0
    rejections = {}

    # Group by trading day
    for date, day_data in data.groupby(data.index.date):
        day_df = day_data.sort_index()

        # Get ORB (9:15 candle)
        orb_row = day_df[day_df.index.strftime("%H:%M") == "09:15"]
        if orb_row.empty:
            continue

        orb = {
            "high": float(orb_row.iloc[0]["high"]),
            "low": float(orb_row.iloc[0]["low"]),
            "close": float(orb_row.iloc[0]["close"]),
            "timestamp": orb_row.index[0].isoformat(),
        }

        # Process all candles after ORB
        candidates = day_df[day_df.index > pd.Timestamp(orb["timestamp"])]

        for candle_ts, candle in candidates.iterrows():
            total_candles += 1
            close = float(candle["close"])

            # Check breakout
            if close <= orb["high"] and close >= orb["low"]:
                continue

            # Evaluate strategy
            try:
                result = evaluate_b1_breakout(
                    day_df.loc[:candle_ts],
                    orb,
                    daily_close=float(candle.get("close", 0)),
                    daily_volume=float(candle.get("volume", 0)),
                    symbol=symbol,
                )
                if result is not None:
                    passed_filters += 1
            except Exception as e:
                reason = str(e).split("|")[0][:40]
                rejections[reason] = rejections.get(reason, 0) + 1

    if total_candles > 0:
        pass_rate = (passed_filters / total_candles) * 100
        return {
            "symbol": symbol,
            "total": total_candles,
            "passed": passed_filters,
            "rate": pass_rate,
            "rejections": rejections,
        }

    return None


def main(csv_file):
    """Run backtest on fetched data."""
    # Setup logging
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)

    csv_path = Path(csv_file)

    if not csv_path.exists():
        print(f"[ERROR] File not found: {csv_path}")
        return False

    print("\n" + "="*90)
    print("JOB: BACKTEST FETCHED DATA")
    print("="*90)
    print(f"\nLoading: {csv_path}")

    # Load data
    try:
        df = pd.read_csv(csv_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    except Exception as e:
        print(f"[ERROR] Failed to load CSV: {e}")
        return False

    print(f"  Records: {len(df):,}")
    print(f"  Symbols: {df['symbol'].nunique()}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")

    # Run backtest for each stock
    print(f"\n[BACKTEST START]")
    results = []

    for symbol in sorted(df['symbol'].unique()):
        stock_data = df[df['symbol'] == symbol]
        print(f"\n{symbol}:", end=" ")

        result = backtest_stock(symbol, stock_data)
        if result:
            results.append(result)
            print(f"{result['total']:>5} candles | {result['passed']:>3} passed | {result['rate']:>6.2f}%")
        else:
            print("No valid data")

    # Summary
    if not results:
        print("\n[ERROR] No backtest results")
        return False

    print("\n" + "="*90)
    print("BACKTEST SUMMARY")
    print("="*90)

    total_all = sum(r["total"] for r in results)
    passed_all = sum(r["passed"] for r in results)
    overall = (passed_all / total_all * 100) if total_all > 0 else 0

    print(f"\n{'Stock':<15} {'Candles':<12} {'Passed':<10} {'Pass Rate':<12} {'Strength':<12}")
    print("-" * 65)

    for r in sorted(results, key=lambda x: x["rate"], reverse=True):
        strength = "STRONG" if r["rate"] > 25 else "AVERAGE" if r["rate"] > 15 else "WEAK"
        print(f"{r['symbol']:<15} {r['total']:<12} {r['passed']:<10} {r['rate']:>6.2f}%    {strength:<12}")

    print("-" * 65)
    print(f"{'TOTAL':<15} {total_all:<12} {passed_all:<10} {overall:>6.2f}%")

    # Analysis
    print(f"\n[ANALYSIS]")
    print(f"Baseline (36-stock universe): 20.45%")
    print(f"Fetched stocks: {overall:.2f}%")

    strong = sum(1 for r in results if r["rate"] > 25)
    average = sum(1 for r in results if 15 <= r["rate"] <= 25)
    weak = sum(1 for r in results if r["rate"] < 15)

    print(f"\nStrength distribution:")
    print(f"  Strong (>25%): {strong}/{len(results)}")
    print(f"  Average (15-25%): {average}/{len(results)}")
    print(f"  Weak (<15%): {weak}/{len(results)}")

    if overall >= 20.45:
        print(f"\nVerdict: GOOD - These stocks perform at or above baseline")
        print(f"Recommendation: Safe to trade in Phase 1")
    else:
        print(f"\nVerdict: BELOW BASELINE - Consider stricter filters or replacement")
        print(f"Recommendation: Manual review before using in Phase 1")

    # Save results
    results_df = pd.DataFrame(results)
    output_file = csv_path.parent / f"backtest_results_{csv_path.stem}.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\n[SAVED] Results: {output_file}")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.job_backtest_fetched_data DATA_FILE")
        print("Example: python -m app.job_backtest_fetched_data data/historical/fetched_20260925_1430.csv")
        sys.exit(1)

    success = main(sys.argv[1])
    sys.exit(0 if success else 1)
