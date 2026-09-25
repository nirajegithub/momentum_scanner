"""
Backtest 9 specific stocks using 90-day local CSV data.
Load from data/historical/15m_last_90d_2026-09-22.csv and evaluate B1 ORB strategy.
"""
import pandas as pd
import logging
from pathlib import Path
from .strategy import evaluate_b1_breakout

LOG = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent.parent / "data" / "historical" / "15m_last_90d_2026-09-22.csv"

TARGET_STOCKS = {
    "PNBHOUSING",
    "USHAMART",
    "SBILIFE",
    "TRENT",
    "PIRAMALFIN",
    "AXISBANK",
    "HONASA",
    "AUBANK",
    "BAJFINANCE",
}


def get_90day_data(symbol):
    """Load 90-day 15M candle data for a stock from CSV."""
    if not DATA_FILE.exists():
        print(f"[ERROR] Data file not found: {DATA_FILE}")
        return None

    try:
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
    except Exception as e:
        print(f"[ERROR] Failed to load {symbol}: {e}")
        return None


def backtest_stock(symbol):
    """Backtest a single stock."""
    print(f"\n{'='*80}")
    print(f"BACKTEST: {symbol}")
    print(f"{'='*80}")

    data = get_90day_data(symbol)
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
            except Exception as e:
                reason = str(e).split("|")[0].strip() if "|" in str(e) else str(type(e).__name__)
                rejections_by_reason[reason] = rejections_by_reason.get(reason, 0) + 1

    # Summary for this stock
    if total_candles > 0:
        pass_rate = (passed_filters / total_candles) * 100
        print(f"[RESULTS] {symbol}:")
        print(f"   Data points: {len(data)}")
        print(f"   Trading days: {data.index.date.nunique()}")
        print(f"   Total 15M candles: {total_candles}")
        print(f"   Passed filters: {passed_filters}")
        print(f"   Pass rate: {pass_rate:.2f}%")

        if passes:
            print(f"   Sample passes:")
            for ts, close, rvol in passes[:3]:
                print(f"     - {ts.strftime('%Y-%m-%d %H:%M')} | close={close:.2f} | rvol={rvol:.2f}")

        if rejections_by_reason:
            print(f"   Top rejections:")
            for reason, count in sorted(rejections_by_reason.items(), key=lambda x: x[1], reverse=True)[:3]:
                pct = (count / total_candles) * 100
                print(f"     - {reason}: {count} ({pct:.1f}%)")

        return {
            "symbol": symbol,
            "total_candles": total_candles,
            "passed": passed_filters,
            "pass_rate": pass_rate,
            "data_points": len(data),
            "trading_days": data.index.date.nunique(),
            "rejections": rejections_by_reason,
        }

    return None


def main():
    """Backtest all 9 target stocks."""
    print("\n" + "="*80)
    print("90-DAY BACKTEST: 9 SPECIFIC STOCKS")
    print(f"Data: {DATA_FILE}")
    print("="*80)

    results = []

    for symbol in sorted(TARGET_STOCKS):
        result = backtest_stock(symbol)
        if result:
            results.append(result)

    # Overall summary
    print(f"\n\n{'='*80}")
    print("OVERALL SUMMARY - 9 STOCKS (90-day backtest)")
    print(f"{'='*80}")

    if not results:
        print("[ERROR] No backtest results generated")
        return

    total_candles_all = sum(r["total_candles"] for r in results)
    total_passed_all = sum(r["passed"] for r in results)
    total_days = sum(r["trading_days"] for r in results)
    overall_rate = (total_passed_all / total_candles_all * 100) if total_candles_all > 0 else 0

    print(f"\n{'Stock':<15} {'Days':<8} {'Candles':<12} {'Passed':<10} {'Pass Rate':<12} {'Strength':<12}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: x["pass_rate"], reverse=True):
        strength = "STRONG" if r["pass_rate"] > 25 else "AVERAGE" if r["pass_rate"] > 15 else "WEAK"
        print(f"{r['symbol']:<15} {r['trading_days']:<8} {r['total_candles']:<12} {r['passed']:<10} {r['pass_rate']:>6.2f}%   {strength:<12}")

    print("-" * 70)
    print(f"{'TOTAL':<15} {total_days:<8} {total_candles_all:<12} {total_passed_all:<10} {overall_rate:>6.2f}%")

    # Analysis
    print(f"\n[COMPARISON]")
    print(f"Baseline (all 36 stocks, 90-day): 20.45%")
    print(f"These 9 stocks (90-day): {overall_rate:.2f}%")

    if overall_rate > 25:
        diff = overall_rate - 20.45
        print(f"Result: SIGNIFICANTLY BETTER than baseline (+{diff:.2f}%)")
        print(f"Verdict: These are STRONG momentum stocks")
    elif overall_rate > 20.45:
        diff = overall_rate - 20.45
        print(f"Result: Slightly BETTER than baseline (+{diff:.2f}%)")
        print(f"Verdict: These are ABOVE-AVERAGE stocks")
    elif overall_rate > 15:
        diff = 20.45 - overall_rate
        print(f"Result: Slightly BELOW baseline (-{diff:.2f}%)")
        print(f"Verdict: REASONABLE performers")
    else:
        diff = 20.45 - overall_rate
        print(f"Result: SIGNIFICANTLY BELOW baseline (-{diff:.2f}%)")
        print(f"Verdict: These are WEAK breakout stocks")

    # Stock ranking
    print(f"\n[INDIVIDUAL STRENGTH RANKING]")
    strong = sum(1 for r in results if r["pass_rate"] > 25)
    average = sum(1 for r in results if 15 <= r["pass_rate"] <= 25)
    weak = sum(1 for r in results if r["pass_rate"] < 15)
    print(f"Strong (>25%): {strong}/9 stocks")
    print(f"Average (15-25%): {average}/9 stocks")
    print(f"Weak (<15%): {weak}/9 stocks")

    # Verdict
    print(f"\n[FINAL VERDICT]")
    if overall_rate >= 20.45:
        print(f"✓ Portfolio quality: GOOD")
        print(f"✓ Day 1 loss was likely due to market conditions (choppy/ranging)")
        print(f"✓ Recommendation: Continue Phase 1, expect better results on trend days")
    else:
        print(f"✗ Portfolio quality: BELOW AVERAGE")
        print(f"✗ Day 1 loss may reflect weak stock selection")
        print(f"✗ Recommendation: Replace weak performers or add sector/trend filters")


if __name__ == "__main__":
    import logging as logmod
    logmod.basicConfig(level=logmod.INFO)
    main()
