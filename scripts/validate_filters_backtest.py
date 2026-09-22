"""Validate new filters (Market Trend + Trailing Stop) on backtest data."""

import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def analyze_symbol_setups(df5_path: str, df15_path: str, symbol: str):
    """Analyze setups for a single symbol with new filters."""

    df5 = pd.read_csv(df5_path)
    df15 = pd.read_csv(df15_path)

    # Filter for symbol
    s15 = df15[df15['symbol'] == symbol].copy()
    s5 = df5[df5['symbol'] == symbol].copy()

    if s15.empty or s5.empty:
        print(f"No data for {symbol}")
        return

    # Convert to numeric
    for col in ["open", "high", "low", "close", "volume", "rsi14", "rvol"]:
        if col in s15.columns:
            s15[col] = pd.to_numeric(s15[col], errors="coerce")

    print(f"\n{'='*70}")
    print(f"SYMBOL: {symbol}")
    print(f"{'='*70}")

    # Get ORB (first candle)
    orb = s15.iloc[0]
    orb_high = float(orb['high'])
    orb_low = float(orb['low'])

    print(f"\n09:15 ORB:")
    print(f"  High: {orb_high:.2f}")
    print(f"  Low:  {orb_low:.2f}")
    print(f"  Close: {float(orb['close']):.2f}")

    # Analyze market trend (Nifty proxy - using first/last 3 closes)
    closes = s15['close'].astype(float).tail(6).values
    if len(closes) >= 6:
        recent_avg = closes[-3:].mean()
        previous_avg = closes[:3].mean()
        uptrend = recent_avg > previous_avg
        trend_str = "UPTREND" if uptrend else "DOWNTREND"
        print(f"\nMarket Trend (Nifty50 proxy):")
        print(f"  Previous 3 avg: {previous_avg:.2f}")
        print(f"  Recent 3 avg: {recent_avg:.2f}")
        print(f"  Direction: {trend_str}")
    else:
        uptrend = True
        trend_str = "UNKNOWN"
        print(f"\nMarket Trend: {trend_str} (insufficient data)")

    # Count breakouts with filters
    buy_breakouts = []
    sell_breakouts = []

    for idx, (_, row) in enumerate(s15.iloc[1:].iterrows()):  # Skip ORB
        close = float(row['close'])
        rsi = float(row.get('rsi14', 50))
        rvol = float(row.get('rvol', 1))

        if close > orb_high:
            # BUY breakout
            trend_ok = uptrend  # Only in uptrend
            buy_breakouts.append({
                'idx': idx + 1,
                'close': close,
                'rsi': rsi,
                'rvol': rvol,
                'trend_ok': trend_ok,
            })
        elif close < orb_low:
            # SELL breakout
            trend_ok = not uptrend  # Only in downtrend
            sell_breakouts.append({
                'idx': idx + 1,
                'close': close,
                'rsi': rsi,
                'rvol': rvol,
                'trend_ok': trend_ok,
            })

    print(f"\nBUY BREAKOUTS: {len(buy_breakouts)}")
    buy_aligned = sum(1 for b in buy_breakouts if b['trend_ok'])
    print(f"  Market-aligned (uptrend): {buy_aligned}")
    print(f"  Counter-trend (rejected): {len(buy_breakouts) - buy_aligned}")

    if buy_breakouts:
        print(f"\n  Sample BUY setups:")
        for b in buy_breakouts[:3]:
            status = "[OK]" if b['trend_ok'] else "[NO]"
            entry = b['close']
            trailing_sl = entry * 0.95
            print(f"    {status} Close: {entry:.2f} | RSI: {b['rsi']:.1f} | RVOL: {b['rvol']:.2f}x | Trailing SL: {trailing_sl:.2f}")

    print(f"\nSELL BREAKOUTS: {len(sell_breakouts)}")
    sell_aligned = sum(1 for s in sell_breakouts if s['trend_ok'])
    print(f"  Market-aligned (downtrend): {sell_aligned}")
    print(f"  Counter-trend (rejected): {len(sell_breakouts) - sell_aligned}")

    if sell_breakouts:
        print(f"\n  Sample SELL setups:")
        for s in sell_breakouts[:3]:
            status = "[OK]" if s['trend_ok'] else "[NO]"
            entry = s['close']
            trailing_sl = entry * 1.05
            print(f"    {status} Close: {entry:.2f} | RSI: {s['rsi']:.1f} | RVOL: {s['rvol']:.2f}x | Trailing SL: {trailing_sl:.2f}")

    # Summary
    total_setups = len(buy_breakouts) + len(sell_breakouts)
    aligned_setups = buy_aligned + sell_aligned
    print(f"\nSUMMARY:")
    print(f"  Total Breakouts: {total_setups}")
    print(f"  Market-Aligned: {aligned_setups} ({aligned_setups/total_setups*100:.1f}%)")
    print(f"  Rejected by Trend: {total_setups - aligned_setups} ({(total_setups-aligned_setups)/total_setups*100:.1f}%)")

if __name__ == "__main__":
    df5_path = "data/historical/5m_last_90d_2026-09-22.csv"
    df15_path = "data/historical/15m_last_90d_2026-09-22.csv"

    # Analyze top symbols
    top_symbols = ["CHOICEIN", "JYOTICNC", "USHAMART", "AEGISLOG", "FACT"]

    print("\n" + "="*70)
    print("BACKTEST DATA VALIDATION")
    print("Testing Market Trend Filter + Trailing Stop Loss 5%")
    print("="*70)

    for symbol in top_symbols:
        analyze_symbol_setups(df5_path, df15_path, symbol)
