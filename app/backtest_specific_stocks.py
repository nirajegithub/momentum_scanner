"""
Backtest 5-filter B1 ORB strategy on specific stocks.
Load 90-day historical data and evaluate filter pass rates.
"""
import pandas as pd
from pathlib import Path
from .strategy import evaluate_b1_breakout

DATA_FILE = Path(__file__).parent.parent / "data" / "15m_last_90d_2026-09-22.csv"

TARGET_STOCKS = [
    "PNBHOUSING",
    "USHAMART",
    "SBILIFE",
    "TRENT",
    "PIRAMALFIN",
    "AXISBANK",
    "HONASA",
    "AUBANK",
    "BAJFINANCE",
]


def load_stock_data(symbol):
    """Load 90-day 15M data for a specific stock."""
    if not DATA_FILE.exists():
        print(f"[ERROR] Data file not found: {DATA_FILE}")
        return None

    df = pd.read_csv(DATA_FILE)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")

    # Filter for specific symbol
    stock_data = df[df["symbol"] == symbol].copy()
    if stock_data.empty:
        print(f"[WARN] No data for {symbol}")
        return None

    stock_data.index = pd.to_datetime(stock_data.index)
    return stock_data.sort_index()


def evaluate_stock_backtest(symbol):
    """Backtest a single stock."""
    print(f"\n{'='*80}")
    print(f"BACKTEST: {symbol}")
    print(f"{'='*80}")

    data = load_stock_data(symbol)
    if data is None or data.empty:
        return None

    total_candles = 0
    passed_filters = 0
    rejections_by_reason = {}
    passes = []

    # Group by date to process each trading day
    for date, day_data in data.groupby(data.index.date):
        day_df = day_data.sort_index()

        # Get ORB for this day (9:15 candle)
        orb_row = day_df[day_df.index.strftime("%H:%M") == "09:15"]
        if orb_row.empty:
            continue

        orb = {
            "high": float(orb_row.iloc[0]["high"]),
            "low": float(orb_row.iloc[0]["low"]),
            "close": float(orb_row.iloc[0]["close"]),
            "timestamp": orb_row.index[0].isoformat(),
        }

        # Process all 15M candles after ORB
        candidates = day_df[day_df.index > pd.Timestamp(orb["timestamp"])]

        for candle_ts, candle in candidates.iterrows():
            total_candles += 1
            close = float(candle["close"])

            # Check breakout
            if close <= orb["high"] and close >= orb["low"]:
                continue  # No breakout

            # Evaluate 5-filter B1 strategy
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
                    rvol = result.get('rvol', 0)
                    passes.append((candle_ts, close, rvol))
                    print(f"  [PASS] {candle_ts.strftime('%Y-%m-%d %H:%M')} | close={close:.2f} | rvol={rvol:.2f}")
            except Exception as e:
                reason = str(e).split("|")[0].strip() if "|" in str(e) else "EXCEPTION"
                rejections_by_reason[reason] = rejections_by_reason.get(reason, 0) + 1

    # Summary for this stock
    if total_candles > 0:
        pass_rate = (passed_filters / total_candles) * 100
        print(f"\n[SUMMARY] {symbol}:")
        print(f"   Total 15M candles: {total_candles}")
        print(f"   Passed filters: {passed_filters}")
        print(f"   Pass rate: {pass_rate:.2f}%")
        if rejections_by_reason:
            print(f"   Top rejections:")
            for reason, count in sorted(rejections_by_reason.items(), key=lambda x: x[1], reverse=True)[:5]:
                pct = (count / total_candles) * 100
                print(f"     - {reason}: {count} ({pct:.1f}%)")
        return {
            "symbol": symbol,
            "total_candles": total_candles,
            "passed": passed_filters,
            "pass_rate": pass_rate,
            "rejections": rejections_by_reason,
        }

    return None


def main():
    """Run backtest for all target stocks."""
    results = []

    for symbol in TARGET_STOCKS:
        result = evaluate_stock_backtest(symbol)
        if result:
            results.append(result)

    # Overall summary
    print(f"\n\n{'='*80}")
    print("OVERALL BACKTEST SUMMARY - 9 STOCKS")
    print(f"{'='*80}")

    if not results:
        print("[ERROR] No backtest results generated")
        return

    total_candles_all = sum(r["total_candles"] for r in results)
    total_passed_all = sum(r["passed"] for r in results)
    overall_rate = (total_passed_all / total_candles_all * 100) if total_candles_all > 0 else 0

    print(f"\n{'Stock':<15} {'Candles':<12} {'Passed':<10} {'Pass Rate':<12}")
    print("-" * 50)
    for r in sorted(results, key=lambda x: x["pass_rate"], reverse=True):
        print(f"{r['symbol']:<15} {r['total_candles']:<12} {r['passed']:<10} {r['pass_rate']:>6.2f}%")

    print("-" * 50)
    print(f"{'TOTAL':<15} {total_candles_all:<12} {total_passed_all:<10} {overall_rate:>6.2f}%")

    print(f"\nExpected baseline: 20.45% (from 90-day full universe)")
    print(f"These 9 stocks: {overall_rate:.2f}%")

    if overall_rate > 20.45:
        print(f"[GOOD] Better than baseline by {overall_rate - 20.45:.2f}%")
    else:
        print(f"[NOTE] Lower than baseline by {20.45 - overall_rate:.2f}%")


if __name__ == "__main__":
    main()
