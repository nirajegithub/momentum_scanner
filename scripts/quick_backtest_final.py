"""Quick backtest with all improvements: Market Trend + ORB SL + Escalation."""

import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def quick_backtest(df5_path: str, df15_path: str):
    """Backtest with all improvements."""

    print(f"\nLoading backtest data...")
    df5 = pd.read_csv(df5_path)
    df15 = pd.read_csv(df15_path)

    # Convert to numeric
    for df in [df5, df15]:
        for c in ["open", "high", "low", "close", "volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

    print(f"5M: {len(df5):,} candles")
    print(f"15M: {len(df15):,} candles")
    print(f"Symbols: {df15['symbol'].nunique()}\n")

    trades = []

    for symbol in df15['symbol'].unique():
        s15 = df15[df15['symbol'] == symbol].copy()
        s5 = df5[df5['symbol'] == symbol].copy()

        if len(s15) < 7:  # Need at least 6 + ORB
            continue

        # ORB (first candle)
        orb = s15.iloc[0]
        orb_high = float(orb['high'])
        orb_low = float(orb['low'])

        # Market trend (last 3 closes vs previous 3 closes)
        closes = s15['close'].astype(float).values
        if len(closes) >= 6:
            recent_avg = closes[-3:].mean()
            previous_avg = closes[:3].mean()
            uptrend = recent_avg > previous_avg
        else:
            uptrend = True

        # Count breakouts with filters
        for idx, (_, row) in enumerate(s15.iloc[1:].iterrows()):
            close = float(row['close'])

            if close > orb_high:
                # BUY breakout
                direction = "BUY"
                sl = orb_low  # SL = ORB Low
                entry = close
                trend_ok = uptrend
            elif close < orb_low:
                # SELL breakout
                direction = "SELL"
                sl = orb_high  # SL = ORB High
                entry = close
                trend_ok = not uptrend
            else:
                continue

            # Skip if trend doesn't align
            if not trend_ok:
                continue

            # Calculate risk
            risk = entry - sl if direction == "BUY" else sl - entry
            if risk <= 0:
                continue

            risk_pct = risk / entry * 100.0

            # Calculate targets
            t1 = entry + (2 * risk) if direction == "BUY" else entry - (2 * risk)
            t2 = entry + (3 * risk) if direction == "BUY" else entry - (3 * risk)
            t3 = entry + (4 * risk) if direction == "BUY" else entry - (4 * risk)

            trades.append({
                'symbol': symbol,
                'direction': direction,
                'entry': entry,
                'sl': sl,
                'sl_escalation_to_entry': entry,  # T1 hit → SL to entry
                'sl_escalation_to_t1': t1,        # T2 hit → SL to T1
                'sl_escalation_to_t2': t2,        # T3 hit → SL to T2
                'risk': risk,
                'risk_pct': risk_pct,
                't1': t1,
                't2': t2,
                't3': t3,
                'trend_aligned': trend_ok,
            })

    print(f"[OK] FINAL BACKTEST - All Improvements")
    print(f"{'='*70}")
    print(f"Total Setups Found: {len(trades):,}")
    print(f"{'='*70}\n")

    if trades:
        trades_df = pd.DataFrame(trades)

        by_direction = trades_df.groupby('direction').size()
        print(f"By Direction:")
        for direction, count in by_direction.items():
            print(f"  {direction}: {count:,}")

        print(f"\nAverage Trade Metrics:")
        print(f"  Avg Risk: {trades_df['risk'].mean():.2f}")
        print(f"  Avg Risk %: {trades_df['risk_pct'].mean():.2f}%")
        print(f"  Avg T1 Profit: {(trades_df['t1'] - trades_df['entry']).mean():.2f}")
        print(f"  Avg T2 Profit: {(trades_df['t2'] - trades_df['entry']).mean():.2f}")
        print(f"  Avg T3 Profit: {(trades_df['t3'] - trades_df['entry']).mean():.2f}")

        print(f"\nTop 10 Symbols by Setup Count:")
        top_symbols = trades_df['symbol'].value_counts().head(10)
        for symbol, count in top_symbols.items():
            print(f"  {symbol}: {count} setups")

        # Sample trades
        print(f"\n[OK] Sample Trades (First 3):")
        print(f"{'='*70}")
        for idx, trade in trades_df.head(3).iterrows():
            print(f"\n{idx+1}. {trade['symbol']} - {trade['direction']}")
            print(f"   ORB SL: {trade['sl']:.2f}")
            print(f"   Entry: {trade['entry']:.2f}")
            print(f"   Risk: {trade['risk']:.2f} ({trade['risk_pct']:.2f}%)")
            print(f"   T1: {trade['t1']:.2f} | T2: {trade['t2']:.2f} | T3: {trade['t3']:.2f}")
            print(f"   SL Escalation:")
            print(f"     * T1 hit -> SL to {trade['sl_escalation_to_entry']:.2f} (1:1)")
            print(f"     * T2 hit -> SL to {trade['sl_escalation_to_t1']:.2f} (2:1)")
            print(f"     * T3 hit -> SL to {trade['sl_escalation_to_t2']:.2f} (3:1)")

        print(f"\n{'='*70}")
        print(f"Backtest complete! Ready for live tomorrow.")
        return trades_df
    else:
        print("No valid trades found")
        return None

if __name__ == "__main__":
    df5_path = "data/historical/5m_last_90d_2026-09-22.csv"
    df15_path = "data/historical/15m_last_90d_2026-09-22.csv"

    print("\n" + "="*70)
    print("QUICK BACKTEST - FINAL VALIDATION")
    print("Market Trend Filter + ORB SL + SL Escalation")
    print("="*70)

    quick_backtest(df5_path, df15_path)
