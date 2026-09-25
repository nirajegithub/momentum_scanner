"""
Backtest for 9 specific stocks with current filter configuration.
"""

import pandas as pd
import logging
from pathlib import Path
from .strategy import evaluate_b1_breakout

logging.basicConfig(level=logging.INFO, format='%(message)s')
LOG = logging.getLogger(__name__)

# Target 9 stocks
SELL_STOCKS = ['PNBHOUSING', 'USHAMART', 'SBILIFE', 'TRENT', 'PIRAMALFIN', 'HONASA']
BUY_STOCKS = ['AXISBANK', 'AUBANK', 'BAJFINANCE']
TARGET_STOCKS = SELL_STOCKS + BUY_STOCKS

def backtest_9stocks(csv_file):
    """Backtest only the 9 target stocks."""
    print(f"\n{'='*90}")
    print("BACKTEST: 9 SPECIFIC STOCKS WITH CURRENT FILTERS")
    print(f"{'='*90}")

    df = pd.read_csv(csv_file, parse_dates=['timestamp'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('Asia/Kolkata')
    df = df.set_index('timestamp')

    print(f"\nLoading: {csv_file}")
    print(f"  Total records: {len(df):,}")
    print(f"  Symbols: {df['symbol'].nunique()}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")

    # Filter to only target stocks
    target_df = df[df['symbol'].isin(TARGET_STOCKS)]
    print(f"\n  Target stocks found: {target_df['symbol'].nunique()}")
    print(f"  Target records: {len(target_df):,}")

    results = {}

    print(f"\n{'='*90}")
    print("RESULTS BY STOCK")
    print(f"{'='*90}\n")

    for symbol in sorted(TARGET_STOCKS):
        symbol_data = target_df[target_df['symbol'] == symbol]
        if symbol_data.empty:
            print(f"{symbol:15} | No data found")
            continue

        total_candles = 0
        passed = 0
        rejected_by = {}
        last_setup = None

        for date, day_data in symbol_data.groupby(symbol_data.index.date):
            day_df = day_data.sort_index()

            # Get ORB
            orb_row = day_df[day_df.index.strftime("%H:%M") == "09:15"]
            if orb_row.empty:
                continue

            orb = {
                "high": float(orb_row.iloc[0]["high"]),
                "low": float(orb_row.iloc[0]["low"]),
                "close": float(orb_row.iloc[0]["close"]),
                "timestamp": orb_row.index[0].isoformat(),
            }

            # Check all candles after ORB
            candidates = day_df[day_df.index > pd.Timestamp(orb["timestamp"])]

            for candle_ts, candle in candidates.iterrows():
                close = float(candle["close"])
                total_candles += 1

                # Check breakout
                if close <= orb["high"] and close >= orb["low"]:
                    continue

                # Evaluate
                try:
                    result = evaluate_b1_breakout(
                        day_df.loc[:candle_ts],
                        orb,
                        daily_close=float(candle.get("close", 0)),
                        daily_volume=float(candle.get("volume", 0)),
                        symbol=symbol,
                    )
                    if result is not None:
                        passed += 1
                        last_setup = {
                            'timestamp': candle_ts,
                            'close': close,
                            'direction': 'BUY' if close > orb["high"] else 'SELL'
                        }
                except Exception as e:
                    pass

        if total_candles > 0:
            pass_rate = (passed / total_candles) * 100
            direction_type = "SELL" if symbol in SELL_STOCKS else "BUY"
            print(f"{symbol:15} | {direction_type:4} | Candles: {total_candles:5} | Passed: {passed:3} | Rate: {pass_rate:5.2f}%", end="")
            if last_setup:
                print(f" | Last setup: {last_setup['timestamp'].strftime('%Y-%m-%d %H:%M')} ({last_setup['direction']})")
            else:
                print()
            results[symbol] = {
                'direction': direction_type,
                'total': total_candles,
                'passed': passed,
                'rate': pass_rate
            }

    # Summary
    print(f"\n{'='*90}")
    print("SUMMARY")
    print(f"{'='*90}\n")

    sell_results = [r for s, r in results.items() if s in SELL_STOCKS]
    buy_results = [r for s, r in results.items() if s in BUY_STOCKS]

    if sell_results:
        avg_sell = sum(r['passed'] for r in sell_results) / sum(r['total'] for r in sell_results) * 100 if any(r['total'] for r in sell_results) else 0
        print(f"SELL Stocks (6 total)")
        print(f"  Total candles: {sum(r['total'] for r in sell_results)}")
        print(f"  Passed: {sum(r['passed'] for r in sell_results)}")
        print(f"  Average pass rate: {avg_sell:.2f}%\n")

    if buy_results:
        avg_buy = sum(r['passed'] for r in buy_results) / sum(r['total'] for r in buy_results) * 100 if any(r['total'] for r in buy_results) else 0
        print(f"BUY Stocks (3 total)")
        print(f"  Total candles: {sum(r['total'] for r in buy_results)}")
        print(f"  Passed: {sum(r['passed'] for r in buy_results)}")
        print(f"  Average pass rate: {avg_buy:.2f}%\n")

    total_passed = sum(r['passed'] for r in results.values())
    total_candles = sum(r['total'] for r in results.values())

    print(f"COMBINED (9 stocks)")
    print(f"  Total candles: {total_candles}")
    print(f"  Passed: {total_passed}")
    print(f"  Overall pass rate: {(total_passed/total_candles*100):.2f}%\n")

def main():
    csv_file = "data/historical/indicators_recalc_15m.csv"
    backtest_9stocks(csv_file)

if __name__ == "__main__":
    main()
