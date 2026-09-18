"""
Standalone test for the new rejection-reason logging in app/strategy.py.

Run this any time (market open or closed, no Dhan/Telegram credentials needed):

    python test_rejection_logging.py

It builds small synthetic 15M candle DataFrames designed to trip each
rejection branch on purpose, calls evaluate_b1_breakout() directly, and
prints the resulting log line for each case so you can confirm the
reason/detail fields look right before relying on it in production logs.
"""
from __future__ import annotations

import logging
import sys
import os

# Make sure "app" is importable when run from the repo root or from this file's folder.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import pandas as pd

from app.strategy import evaluate_b1_breakout

logging.basicConfig(level=logging.INFO, format="%(message)s")

ORB = {"high": 105.0, "low": 95.0, "timestamp": "2026-09-18T09:15:00+05:30", "close": 100.0, "open": 100.0}


def _candles(rows):
    """rows: list of dicts with open/high/low/close/rsi14/rvol."""
    idx = pd.date_range("2026-09-18 09:30", periods=len(rows), freq="15min", tz="Asia/Kolkata")
    return pd.DataFrame(rows, index=idx)


def case(name, df, daily_close=500.0, daily_volume=1_000_000, symbol="TESTSYM"):
    print(f"\n--- {name} ---")
    result = evaluate_b1_breakout(df, ORB, daily_close, daily_volume, symbol=symbol)
    print("returned:", "SIGNAL ACCEPTED" if result else "None (rejected — see B1_FILTER_REJECTED line above)")


# 1) RSI out of band: BUY breakout but RSI already overbought (>70)
case(
    "RSI_OUT_OF_BAND (BUY, RSI too high)",
    _candles([
        {"open": 96, "high": 100, "low": 95, "close": 98, "rsi14": 50, "rvol": 1.0},
        {"open": 98, "high": 110, "low": 97, "close": 109, "rsi14": 78, "rvol": 1.5},
    ]),
)

# 2) RSI momentum not aligned: BUY breakout, RSI in band but falling, not rising
case(
    "RSI_MOMENTUM_NOT_ALIGNED (BUY, RSI in band but falling)",
    _candles([
        {"open": 96, "high": 100, "low": 95, "close": 98, "rsi14": 65, "rvol": 1.0},
        {"open": 98, "high": 110, "low": 97, "close": 109, "rsi14": 60, "rvol": 1.5},
    ]),
)

# 3) RVOL too low: everything else fine, but relative volume under threshold
case(
    "RVOL_TOO_LOW (BUY, good RSI, thin volume)",
    _candles([
        {"open": 96, "high": 100, "low": 95, "close": 98, "rsi14": 58, "rvol": 1.0},
        {"open": 98, "high": 110, "low": 97, "close": 109, "rsi14": 62, "rvol": 0.8},
    ]),
)

# 4) Price/volume gate: daily_close under MIN_PRICE
case(
    "PRICE_TOO_LOW (daily close below MIN_PRICE)",
    _candles([
        {"open": 96, "high": 100, "low": 95, "close": 98, "rsi14": 58, "rvol": 1.0},
        {"open": 98, "high": 110, "low": 97, "close": 109, "rsi14": 62, "rvol": 1.5},
    ]),
    daily_close=200.0,  # below default MIN_PRICE=350
)

# 5) SELL side, RSI out of band low
case(
    "RSI_OUT_OF_BAND (SELL, RSI too low)",
    _candles([
        {"open": 100, "high": 101, "low": 96, "close": 98, "rsi14": 50, "rvol": 1.0},
        {"open": 98, "high": 99, "low": 88, "close": 90, "rsi14": 20, "rvol": 1.5},
    ]),
)

# 6) A case that should plausibly pass every gate through RVOL (score is data-dependent,
#    so this may still be rejected on SCORE_OUT_OF_RANGE with only 2 candles of history —
#    that's expected and fine, it exercises that branch too).
case(
    "Likely SCORE_OUT_OF_RANGE (insufficient history for a real quality score)",
    _candles([
        {"open": 96, "high": 100, "low": 95, "close": 98, "rsi14": 58, "rvol": 1.0},
        {"open": 98, "high": 110, "low": 97, "close": 109, "rsi14": 62, "rvol": 1.5},
    ]),
)

print("\nDone. Each '--- case ---' above should be immediately followed by a")
print("B1_FILTER_REJECTED log line with a specific reason and numbers attached.")
