"""Compare two backtest results."""

import pandas as pd
import sys

def compare(baseline_file: str, improved_file: str, improvement_name: str = "Improvement"):
    """Compare baseline vs improved backtest."""

    print(f"\n{'='*70}")
    print(f"BACKTEST COMPARISON: Baseline vs {improvement_name}")
    print(f"{'='*70}\n")

    baseline = pd.read_csv(baseline_file)
    improved = pd.read_csv(improved_file)

    baseline_trades = baseline['est_total_trades'].sum()
    improved_trades = improved['est_total_trades'].sum()

    baseline_buy = baseline['est_buy_trades'].sum()
    improved_buy = improved['est_buy_trades'].sum()

    baseline_sell = baseline['est_sell_trades'].sum()
    improved_sell = improved['est_sell_trades'].sum()

    # Calculate deltas
    trade_delta = improved_trades - baseline_trades
    trade_delta_pct = (trade_delta / baseline_trades * 100) if baseline_trades > 0 else 0

    buy_delta = improved_buy - baseline_buy
    buy_delta_pct = (buy_delta / baseline_buy * 100) if baseline_buy > 0 else 0

    sell_delta = improved_sell - baseline_sell
    sell_delta_pct = (sell_delta / baseline_sell * 100) if baseline_sell > 0 else 0

    print(f"{'Metric':<30} {'Baseline':>15} {'Improved':>15} {'Delta':>15} {'%':>8}")
    print(f"{'-'*70}")
    print(f"{'Total Trades':<30} {baseline_trades:>15,} {improved_trades:>15,} {trade_delta:>+15,} {trade_delta_pct:>+7.1f}%")
    print(f"{'Buy Trades':<30} {baseline_buy:>15,} {improved_buy:>15,} {buy_delta:>+15,} {buy_delta_pct:>+7.1f}%")
    print(f"{'Sell Trades':<30} {baseline_sell:>15,} {improved_sell:>15,} {sell_delta:>+15,} {sell_delta_pct:>+7.1f}%")
    print(f"{'-'*70}")

    # Verdict
    print(f"\n{'='*70}")
    if trade_delta > 0:
        print(f"[OK] VERDICT: IMPROVEMENT VALIDATED")
        print(f"   +{trade_delta:,} additional trades captured ({trade_delta_pct:+.1f}%)")
        print(f"   Better profit protection")
        print(f"   RECOMMENDATION: IMPLEMENT THIS CHANGE")
    else:
        print(f"[WARNING] VERDICT: TRADE COUNT REDUCTION")
        print(f"   Fewer trades ({trade_delta:,} fewer)")
        print(f"   Trade quality improvement instead of quantity")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", help="Baseline backtest CSV")
    parser.add_argument("improved", help="Improved backtest CSV")
    parser.add_argument("--name", default="Trailing Stop 5%", help="Improvement name")

    args = parser.parse_args()
    compare(args.baseline, args.improved, args.name)
