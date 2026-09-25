"""
Analyze Day 1 (2026-09-25) live signals for 9 specific stocks.
Show actual P&L, SL/target hits, and signal quality.
"""
import json
from pathlib import Path
from datetime import datetime

TARGET_STOCKS = {
    "PNBHOUSING", "USHAMART", "SBILIFE", "TRENT", "PIRAMALFIN",
    "AXISBANK", "HONASA", "AUBANK", "BAJFINANCE",
}

STATE_FILE = Path(__file__).parent.parent / "state" / "runtime_state.json"


def load_state():
    """Load runtime state with signals."""
    if not STATE_FILE.exists():
        print(f"[ERROR] State file not found: {STATE_FILE}")
        return None

    with open(STATE_FILE) as f:
        return json.load(f)


def analyze_signal(signal_key, signal):
    """Analyze a single signal."""
    symbol = signal.get("symbol")
    direction = signal.get("direction")
    status = signal.get("status")

    entry = float(signal["risk"]["entry"])
    sl = float(signal["risk"]["sl"])
    t1 = float(signal["risk"]["t1"])
    t2 = float(signal["risk"]["t2"])
    t3 = float(signal["risk"]["t3"])

    # Determine result
    result_price = entry
    exit_reason = "PENDING"
    points = 0

    if signal.get("sl_hit"):
        result_price = sl
        exit_reason = "SL_HIT"
        points = sl - entry if direction == "SELL" else entry - sl
    elif signal.get("highest_target_hit"):
        target_hit = signal.get("highest_target_hit")
        if target_hit == "T3_HIT":
            result_price = t3
            exit_reason = "T3_HIT"
        elif target_hit == "T2_HIT":
            result_price = t2
            exit_reason = "T2_HIT"
        elif target_hit == "T1_HIT":
            result_price = t1
            exit_reason = "T1_HIT"
        points = result_price - entry if direction == "BUY" else entry - result_price
    elif status == "EXITED":
        exit_price = float(signal.get("exit_price", entry))
        result_price = exit_price
        exit_reason = signal.get("exit_reason", "MANUAL_EXIT")
        points = result_price - entry if direction == "BUY" else entry - result_price
    else:
        exit_reason = "STILL_OPEN"
        result_price = entry
        points = 0

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "result_price": result_price,
        "points": points,
        "exit_reason": exit_reason,
        "status": status,
        "setup_time": signal.get("setup_15m_timestamp", ""),
        "confirm_time": signal.get("confirmation_5m_timestamp", ""),
        "sl_hit": signal.get("sl_hit", False),
        "highest_target": signal.get("highest_target_hit", "NONE"),
    }


def main():
    state = load_state()
    if not state:
        return

    # Collect signals for target stocks
    signals_data = []
    for signal_key, signal in state.get("signals", {}).items():
        symbol = signal.get("symbol")
        if symbol not in TARGET_STOCKS:
            continue

        analysis = analyze_signal(signal_key, signal)
        signals_data.append(analysis)

    if not signals_data:
        print("[WARN] No signals found for target stocks")
        return

    # Sort by symbol and entry time
    signals_data.sort(key=lambda x: (x["symbol"], x["setup_time"]))

    # Print detailed results
    print("\n" + "="*100)
    print("DAY 1 LIVE SIGNALS ANALYSIS - 9 STOCKS (2026-09-25)")
    print("="*100)

    print(f"\n{'Symbol':<15} {'Dir':<6} {'Entry':<10} {'Result':<10} {'Points':<8} {'Exit Reason':<20} {'Status':<15}")
    print("-" * 100)

    total_points = 0
    winners = 0
    losers = 0

    for sig in signals_data:
        symbol = sig["symbol"]
        direction = sig["direction"]
        entry = sig["entry"]
        result = sig["result_price"]
        points = sig["points"]
        reason = sig["exit_reason"]
        status = sig["status"]

        # Count wins/losses
        if points > 0:
            winners += 1
            outcome = "WIN"
        elif points < 0:
            losers += 1
            outcome = "LOSS"
        else:
            outcome = "BREAK"

        total_points += points

        print(f"{symbol:<15} {direction:<6} {entry:<10.2f} {result:<10.2f} {points:>+7.2f} {reason:<20} {outcome:<15}")

    # Summary
    print("-" * 100)
    total_trades = winners + losers
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0

    print(f"\n[SUMMARY]")
    print(f"  Total Signals: {total_trades}")
    print(f"  Winners: {winners}")
    print(f"  Losers: {losers}")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Total Points: {total_points:+.2f}")
    print(f"  Avg Points/Trade: {total_points/total_trades:+.2f}" if total_trades > 0 else "  Avg Points/Trade: 0.00")

    # Performance by stock
    print(f"\n[PERFORMANCE BY STOCK]")
    stock_perf = {}
    for sig in signals_data:
        symbol = sig["symbol"]
        if symbol not in stock_perf:
            stock_perf[symbol] = {"wins": 0, "losses": 0, "points": 0}

        if sig["points"] > 0:
            stock_perf[symbol]["wins"] += 1
        elif sig["points"] < 0:
            stock_perf[symbol]["losses"] += 1
        stock_perf[symbol]["points"] += sig["points"]

    print(f"{'Stock':<15} {'Signals':<10} {'Wins':<6} {'Losses':<8} {'Points':<10} {'Avg':<8}")
    print("-" * 60)
    for stock in sorted(stock_perf.keys()):
        perf = stock_perf[stock]
        total = perf["wins"] + perf["losses"]
        win_pct = (perf["wins"] / total * 100) if total > 0 else 0
        avg = perf["points"] / total if total > 0 else 0
        print(f"{stock:<15} {total:<10} {perf['wins']:<6} {perf['losses']:<8} {perf['points']:>+9.2f} {avg:>+7.2f}")

    # Exit reasons
    print(f"\n[EXIT REASONS]")
    exit_counts = {}
    for sig in signals_data:
        reason = sig["exit_reason"]
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    for reason, count in sorted(exit_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_trades * 100) if total_trades > 0 else 0
        print(f"  {reason:<20}: {count:>2} ({pct:>5.1f}%)")

    # Compare to backtest
    print(f"\n[COMPARISON TO BACKTEST]")
    print(f"  90-day backtest pass rate: 20.45%")
    print(f"  Day 1 win rate: {win_rate:.1f}%")
    if win_rate > 40:
        print(f"  Status: EXCELLENT - Exceeds 40% target!")
    elif win_rate >= 30:
        print(f"  Status: GOOD - Within acceptable range")
    else:
        print(f"  Status: BELOW TARGET - May need adjustment")


if __name__ == "__main__":
    main()
