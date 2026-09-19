from __future__ import annotations

import pandas as pd

from app.config import SETTINGS
from app.risk import build_risk_and_targets
from app.scoring import score_trade_quality
from app.strategy import evaluate_b1_breakout, t1_blocked

IST = "Asia/Kolkata"
ORB = {"high": 520.0, "low": 480.0, "timestamp": "2026-09-10T09:15:00+05:30", "close": 500.0, "open": 500.0}


def _frame(direction="BUY", rows=30):
    """Synthetic 15M candles ending in a clean ORB breakout on the last row."""
    idx = pd.date_range("2026-09-10 09:30", periods=rows, freq="15min", tz=IST)
    bullish = direction == "BUY"

    base_price = 500.0
    close = pd.Series([base_price] * rows, index=idx, dtype=float)
    # Small alternating bodies on filler candles so the scoring module's
    # median-body calculation is realistic (a flat 0 body short-circuits it).
    open_ = pd.Series([base_price - 0.2 if i % 2 == 0 else base_price + 0.2 for i in range(rows)], index=idx, dtype=float)
    high = pd.Series([base_price + 1.0] * rows, index=idx, dtype=float)
    low = pd.Series([base_price - 1.0] * rows, index=idx, dtype=float)
    rvol = pd.Series([1.0] * rows, index=idx, dtype=float)

    rsi = pd.Series([50.0] * rows, index=idx, dtype=float)
    rsi.iloc[-2] = 58.0 if bullish else 42.0
    rsi.iloc[-1] = 62.0 if bullish else 38.0

    # Three compact base candles immediately before the breakout candle.
    for i in range(rows - 4, rows - 1):
        high.iloc[i] = close.iloc[i] + 0.5
        low.iloc[i] = close.iloc[i] - 0.5

    # Last candle: a strong departure/breakout candle, gapping away from the
    # prior base and closing outside the ORB (mirrors a real breakout candle).
    breakout_close = ORB["high"] + 6.0 if bullish else ORB["low"] - 6.0
    if bullish:
        open_.iloc[-1] = high.iloc[-2] + 1.0  # gap up beyond the last base candle's high
        high.iloc[-1] = breakout_close + 0.5
        low.iloc[-1] = open_.iloc[-1] - 0.3
    else:
        open_.iloc[-1] = low.iloc[-2] - 1.0  # gap down beyond the last base candle's low
        high.iloc[-1] = open_.iloc[-1] + 0.3
        low.iloc[-1] = breakout_close - 0.5
    close.iloc[-1] = breakout_close
    rvol.iloc[-1] = 1.8

    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "rsi14": rsi, "rvol": rvol,
    }, index=idx)


def test_buy_breakout_passes_all_filters():
    result = evaluate_b1_breakout(_frame("BUY"), ORB, daily_close=500, daily_volume=600_000, symbol="TEST")
    assert result is not None, "expected a BUY setup to be accepted"
    assert result["direction"] == "BUY"
    assert result["trade_quality_score"] >= SETTINGS.min_trade_score
    assert result["setup_15m_close"] == result["setup_15m_close"]


def test_sell_breakout_passes_all_filters():
    result = evaluate_b1_breakout(_frame("SELL"), ORB, daily_close=500, daily_volume=600_000, symbol="TEST")
    assert result is not None, "expected a SELL setup to be accepted"
    assert result["direction"] == "SELL"


def test_buy_rsi_out_of_band_rejected():
    frame = _frame("BUY")
    frame.iloc[-1, frame.columns.get_loc("rsi14")] = 75.0  # above buy_rsi_max
    assert evaluate_b1_breakout(frame, ORB, 500, 600_000) is None


def test_buy_rsi_momentum_not_aligned_rejected():
    frame = _frame("BUY")
    frame.iloc[-1, frame.columns.get_loc("rsi14")] = 56.0
    frame.iloc[-2, frame.columns.get_loc("rsi14")] = 65.0  # falling, not rising
    assert evaluate_b1_breakout(frame, ORB, 500, 600_000) is None


def test_sell_rsi_out_of_band_rejected():
    frame = _frame("SELL")
    frame.iloc[-1, frame.columns.get_loc("rsi14")] = 20.0  # below sell_rsi_min
    assert evaluate_b1_breakout(frame, ORB, 500, 600_000) is None


def test_rvol_too_low_rejected():
    frame = _frame("BUY")
    frame.iloc[-1, frame.columns.get_loc("rvol")] = 0.5
    assert evaluate_b1_breakout(frame, ORB, 500, 600_000) is None


def test_daily_price_filter_is_strict():
    frame = _frame("BUY")
    assert evaluate_b1_breakout(frame, ORB, SETTINGS.min_price, 600_000) is None


def test_daily_volume_filter_is_strict():
    frame = _frame("BUY")
    assert evaluate_b1_breakout(frame, ORB, 500, SETTINGS.min_daily_volume) is None


def test_no_breakout_returns_none():
    frame = _frame("BUY")
    # Pull the close back inside the ORB range so it's not actually a breakout.
    frame.iloc[-1, frame.columns.get_loc("close")] = 500.0
    frame.iloc[-1, frame.columns.get_loc("high")] = 505.0
    frame.iloc[-1, frame.columns.get_loc("low")] = 495.0
    assert evaluate_b1_breakout(frame, ORB, 500, 600_000) is None


def test_score_range_and_components():
    result = score_trade_quality(_frame("BUY"), "BUY")
    assert 0 <= result["trade_quality_score"] <= 7
    assert result["departure_score"] in {0.0, 1.5, 3.0}
    assert result["freshness_score"] in {0.0, 1.0, 2.0}
    assert result["base_candle_score"] in {0.0, 1.0, 2.0}


def test_t1_blocked_buy_when_target_already_touched():
    idx = pd.date_range("2026-09-10 09:30", periods=3, freq="5min", tz=IST)
    df5 = pd.DataFrame({
        "open": [500, 505, 512], "high": [504, 512, 515],
        "low": [499, 504, 510], "close": [503, 511, 513],
    }, index=idx)
    # Entry 500, T1 510: high of 512 before confirmation already touched T1.
    assert t1_blocked(df5, idx[-1], entry=500, t1=510, direction="BUY") is True


def test_t1_not_blocked_when_target_untouched():
    idx = pd.date_range("2026-09-10 09:30", periods=3, freq="5min", tz=IST)
    df5 = pd.DataFrame({
        "open": [500, 502, 505], "high": [503, 506, 508],
        "low": [499, 501, 504], "close": [502, 505, 507],
    }, index=idx)
    assert t1_blocked(df5, idx[-1], entry=500, t1=510, direction="BUY") is False


def test_small_stop_examples_are_rejected():
    examples = [
        ("SELL", 1037.00, 1037.90),
        ("BUY", 1259.90, 1259.30),
        ("SELL", 1038.40, 1038.80),
        ("BUY", 457.90, 457.00),
    ]
    for direction, entry, sl in examples:
        risk, reason = build_risk_and_targets(direction, entry, sl, 0.50, 2, 3, 4, 2)
        assert risk is None
        assert reason == "STOP_DISTANCE_TOO_SMALL"


def test_exact_half_percent_stop_is_accepted():
    risk, reason = build_risk_and_targets("BUY", 1000, 995, 0.50, 2, 3, 4, 2)
    assert reason is None
    assert risk["risk"] == 5
    assert risk["t1"] == 1010
    assert risk["t2"] == 1015
    assert risk["t3"] == 1020


def test_sell_targets_are_symmetric():
    risk, reason = build_risk_and_targets("SELL", 1000, 1005, 0.50, 2, 3, 4, 2)
    assert reason is None
    assert risk["t1"] == 990
    assert risk["t2"] == 985
    assert risk["t3"] == 980
