#!/usr/bin/env python3
"""Diagnostic tool: Find top 10 most active stocks that didn't qualify."""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .dhan_client import DhanClient
from .nse_universe import build_universe
from .indicators import add_indicators
from .candle_utils import completed_candles
from .state import load
from .strategy import evaluate_b1_breakout

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


def diagnose_top_10_missed():
    """Find top 10 most active stocks and why they didn't generate signals."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    ts = datetime.now(IST)
    trading_day = ts.date()

    dhan = DhanClient()
    state = load(trading_day)

    if not state.get("universe"):
        print("❌ Universe not populated. Run universe action first.")
        return

    print("\n" + "="*80)
    print("🔍 DIAGNOSTIC: TOP 10 MOST ACTIVE STOCKS (NOT QUALIFIED)")
    print("="*80 + "\n")

    # Track all stocks with their RVOL and rejection reason
    stocks_data = []

    for item in state.get("universe", []):
        symbol = item.get("symbol")
        security_id = item.get("security_id")

        if not symbol or security_id is None:
            continue

        try:
            # Fetch 15M data
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

            if rvol < 0.5:  # Skip very low RVOL
                continue

            # Check if it has ORB
            x = df15[df15.index.strftime("%H:%M") == "09:15"]
            if x.empty:
                rejection = "NO_ORB"
                stocks_data.append({
                    "symbol": symbol,
                    "rvol": rvol,
                    "rsi": rsi,
                    "rejection": rejection,
                    "details": "Opening Range not found"
                })
                continue

            orb = x.iloc[0]
            orb_high = float(orb["high"])
            orb_low = float(orb["low"])
            close = float(latest["close"])

            # Check for breakout
            breakout_side = None
            if close > orb_high:
                breakout_side = "BUY"
            elif close < orb_low:
                breakout_side = "SELL"

            if breakout_side is None:
                rejection = "NO_BREAKOUT"
                stocks_data.append({
                    "symbol": symbol,
                    "rvol": rvol,
                    "rsi": rsi,
                    "rejection": rejection,
                    "details": f"Price {close:.2f} in range [{orb_low:.2f}, {orb_high:.2f}]"
                })
                continue

            # Check filters
            if rvol < 2.5:
                rejection = "RVOL_LOW"
                stocks_data.append({
                    "symbol": symbol,
                    "rvol": rvol,
                    "rsi": rsi,
                    "rejection": rejection,
                    "details": f"RVOL {rvol:.2f}x < 2.5x minimum"
                })
                continue

            if rsi < 30 or rsi > 70:
                rejection = "RSI_EXTREME"
                stocks_data.append({
                    "symbol": symbol,
                    "rvol": rvol,
                    "rsi": rsi,
                    "rejection": rejection,
                    "details": f"RSI {rsi:.2f} outside 30-70 range"
                })
                continue

            # If we got here, it has ORB + breakout + good RVOL/RSI but still no setup
            # This means it's waiting for setup or other criteria
            rejection = "WAITING_FOR_SETUP"
            stocks_data.append({
                "symbol": symbol,
                "rvol": rvol,
                "rsi": rsi,
                "rejection": rejection,
                "details": f"Setup quality score threshold not met"
            })

        except Exception as exc:
            # Skip stocks with data errors
            pass

    # Sort by RVOL and take top 10
    stocks_data.sort(key=lambda x: x["rvol"], reverse=True)
    top_10 = stocks_data[:10]

    if not top_10:
        print("ℹ️  No active stocks found today.\n")
        return

    # Print report
    print(f"{'#':<3} {'SYMBOL':<10} {'RVOL':<8} {'RSI':<8} {'REJECTION':<20} {'DETAILS':<40}")
    print("-" * 95)

    for i, stock in enumerate(top_10, 1):
        print(
            f"{i:<3} {stock['symbol']:<10} {stock['rvol']:<8.2f} "
            f"{stock['rsi']:<8.2f} {stock['rejection']:<20} {stock['details']:<40}"
        )

    print("\n" + "="*80)
    print("REJECTION LEGEND:")
    print("  NO_ORB              → Opening Range data not available")
    print("  NO_BREAKOUT         → Price still in ORB range (no breakout)")
    print("  RVOL_LOW            → Relative Volume < 2.5x (low momentum)")
    print("  RSI_EXTREME         → RSI outside 30-70 range (overbought/oversold)")
    print("  WAITING_FOR_SETUP   → Has breakout + momentum but setup quality too low")
    print("="*80 + "\n")


if __name__ == "__main__":
    diagnose_top_10_missed()
