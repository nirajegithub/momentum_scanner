#!/usr/bin/env python3
"""Debug version: Check high-momentum stocks anytime (ignores market hours)."""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.dhan_client import DhanClient
from app.nse_universe import build_universe
from app.indicators import add_indicators
from app.candle_utils import completed_candles
from app.state import load
from app.calendar import previous_trading_day

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

# Alert thresholds
RVOL_THRESHOLD = 5.0  # 5x relative volume
RSI_MIN = 30
RSI_MAX = 70


def debug_high_momentum():
    """Debug: Find high-momentum stocks (ignores market hours)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    ts = datetime.now(IST)
    trading_day = ts.date()

    print("\n" + "="*80)
    print("🔍 DEBUG: HIGH-MOMENTUM STOCKS + ORB TIMESTAMP CHECK")
    print("="*80)
    print(f"Current time: {ts.strftime('%H:%M IST')}")
    print(f"Trading day: {trading_day}\n")

    dhan = DhanClient()
    state = load(trading_day)

    if not state.get("universe"):
        print("❌ Universe not populated.")
        return

    high_momentum_stocks = []

    for item in state.get("universe", []):
        symbol = item.get("symbol")
        security_id = item.get("security_id")

        if not symbol or security_id is None:
            continue

        try:
            # Fetch 15M data for today
            raw = dhan.historical_intraday_df(
                security_id=security_id,
                interval=15,
                from_date=trading_day.isoformat(),
                to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
            )

            if raw is None or raw.empty:
                continue

            df15 = completed_candles(raw, ts, 15)
            if df15.empty:
                continue

            df15 = add_indicators(df15, rvol_lookback=20)

            # Get latest 15M candle
            latest = df15.iloc[-1]
            rvol = float(latest.get("rvol", 0))
            rsi = float(latest.get("rsi14", 50))
            close = float(latest["close"])

            # Check for high momentum
            if rvol >= RVOL_THRESHOLD and RSI_MIN <= rsi <= RSI_MAX:
                # Debug: Check ORB timestamps
                df_tz = df15.copy()
                df_tz.index = pd.to_datetime(df_tz.index)
                if df_tz.index.tz is None:
                    df_tz.index = df_tz.index.tz_localize(IST)

                times_hhmm = df_tz.index.strftime("%H:%M")
                has_915 = (times_hhmm == "09:15").any()
                has_930 = (times_hhmm == "09:30").any()

                # Get first candle time
                first_time = df_tz.index[0].strftime("%H:%M")

                # Try to get ORB (09:15 or 09:30)
                orb_data = None
                orb_time = None

                if has_915:
                    rows = df_tz[times_hhmm == "09:15"]
                    if not rows.empty:
                        r = rows.iloc[0]
                        orb_data = {
                            "high": float(r["high"]),
                            "low": float(r["low"]),
                        }
                        orb_time = "09:15"

                elif has_930:
                    rows = df_tz[times_hhmm == "09:30"]
                    if not rows.empty:
                        r = rows.iloc[0]
                        orb_data = {
                            "high": float(r["high"]),
                            "low": float(r["low"]),
                        }
                        orb_time = "09:30"

                # Check for breakout
                breakout = None
                if orb_data:
                    if close > orb_data["high"]:
                        breakout = "BUY"
                    elif close < orb_data["low"]:
                        breakout = "SELL"

                high_momentum_stocks.append({
                    "symbol": symbol,
                    "rvol": rvol,
                    "rsi": rsi,
                    "close": close,
                    "breakout": breakout,
                    "orb_high": orb_data["high"] if orb_data else None,
                    "orb_low": orb_data["low"] if orb_data else None,
                    "orb_time": orb_time,
                    "first_candle_time": first_time,
                    "has_915": has_915,
                    "has_930": has_930,
                })

        except Exception as exc:
            pass

    if not high_momentum_stocks:
        print("ℹ️  No high-momentum stocks found (RVOL >= %.1fx)" % RVOL_THRESHOLD)
        return

    # Sort by RVOL
    high_momentum_stocks.sort(key=lambda x: x["rvol"], reverse=True)

    # Print detailed report
    print(f"Found {len(high_momentum_stocks)} high-momentum stocks:\n")

    print(f"{'SYMBOL':<12} {'RVOL':<8} {'RSI':<8} {'BREAKOUT':<10} {'ORB TIME':<12} {'DATA TIMES':<40}")
    print("-" * 100)

    for stock in high_momentum_stocks[:10]:
        breakout_str = stock["breakout"] or "—"
        orb_str = stock["orb_time"] or "❌ MISSING"
        data_times = f"First: {stock['first_candle_time']} | "
        data_times += f"Has 09:15: {stock['has_915']} | Has 09:30: {stock['has_930']}"

        print(
            f"{stock['symbol']:<12} {stock['rvol']:<8.2f} {stock['rsi']:<8.1f} "
            f"{breakout_str:<10} {orb_str:<12} {data_times:<40}"
        )

    print("\n" + "="*80)
    print("KEY FINDINGS:")
    print("="*80)

    # Analyze ORB issue
    orb_times = [s["orb_time"] for s in high_momentum_stocks if s["orb_time"]]
    first_times = set(s["first_candle_time"] for s in high_momentum_stocks)
    has_915_count = sum(1 for s in high_momentum_stocks if s["has_915"])
    has_930_count = sum(1 for s in high_momentum_stocks if s["has_930"])

    print(f"\n1️⃣  ORB Data Availability:")
    print(f"   - Stocks with 09:15 candle: {has_915_count}")
    print(f"   - Stocks with 09:30 candle: {has_930_count}")
    print(f"   - Data starts from: {', '.join(sorted(first_times))}")

    if has_930_count > has_915_count:
        print(f"\n   ⚠️  FINDING: Data has 09:30 but not 09:15")
        print(f"   → Dhan timestamps candles at CLOSE time (09:30) not OPEN time (09:15)")
        print(f"   → FIX: Change code to look for '09:30' instead of '09:15'")
    elif has_915_count > 0:
        print(f"\n   ✅ Data has 09:15 ORB - code should work")
    else:
        print(f"\n   ❌ No ORB data found in any high-momentum stock")
        print(f"   → Market data might start after opening range")

    print(f"\n2️⃣  Breakout Detection:")
    breakouts = sum(1 for s in high_momentum_stocks if s["breakout"])
    print(f"   - Stocks with detected breakout: {breakouts}")

    print("\n" + "="*80)


if __name__ == "__main__":
    debug_high_momentum()
