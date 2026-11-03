"""Extended tests for app.strategy utility functions."""

from __future__ import annotations

import pandas as pd
import pytest

from app.strategy import market_trend_aligned, momentum_surge_qualifies, t1_blocked


IST = "Asia/Kolkata"


# ── market_trend_aligned ─────────────────────────────────────────────────────


def _nifty(closes):
    idx = pd.date_range("2026-09-10 09:15", periods=len(closes), freq="5min", tz=IST)
    return pd.DataFrame({"close": closes}, index=idx)


def test_market_trend_no_data_returns_true():
    # No nifty data → assume aligned (don't block trades on missing data)
    assert market_trend_aligned(None, "BUY") is True
    assert market_trend_aligned(None, "SELL") is True


def test_market_trend_too_short_returns_true():
    df = _nifty([100.0] * 3)  # fewer than required bars → non-opinionated
    assert market_trend_aligned(df, "BUY") is True


def test_market_trend_buy_aligned_uptrend():
    # Steadily rising closes → BUY is aligned
    closes = list(range(100, 110))
    assert market_trend_aligned(_nifty(closes), "BUY")


def test_market_trend_sell_aligned_downtrend():
    # Steadily falling closes → SELL is aligned
    closes = list(range(110, 100, -1))
    assert market_trend_aligned(_nifty(closes), "SELL")


# ── momentum_surge_qualifies ─────────────────────────────────────────────────


def _setup(rvol, rsi):
    return {"setup_15m_rvol": rvol, "setup_15m_rsi14": rsi}


def test_momentum_surge_buy_high_rvol_high_rsi():
    assert momentum_surge_qualifies(_setup(4.0, 65.0), "BUY") is True


def test_momentum_surge_buy_rvol_too_low():
    assert momentum_surge_qualifies(_setup(3.0, 65.0), "BUY") is False


def test_momentum_surge_buy_rsi_below_threshold():
    assert momentum_surge_qualifies(_setup(4.0, 55.0), "BUY") is False


def test_momentum_surge_sell_high_rvol_low_rsi():
    assert momentum_surge_qualifies(_setup(4.0, 35.0), "SELL") is True


def test_momentum_surge_sell_rsi_above_threshold():
    assert momentum_surge_qualifies(_setup(4.0, 45.0), "SELL") is False


def test_momentum_surge_sell_rvol_too_low():
    assert momentum_surge_qualifies(_setup(3.0, 35.0), "SELL") is False


# ── t1_blocked ───────────────────────────────────────────────────────────────


def _df5(highs, lows):
    idx = pd.date_range("2026-09-10 09:20", periods=len(highs), freq="5min", tz=IST)
    return pd.DataFrame({"high": highs, "low": lows}, index=idx)


def test_t1_blocked_sell_when_target_already_touched():
    # SELL: T1 is below entry; a prior low touches or goes below t1
    df = _df5([101.0, 101.0, 101.0], [99.0, 89.0, 99.0])
    # Candles before idx[-1]: rows[0] and rows[1]; row[1].low=89 <= t1=90 → blocked
    assert t1_blocked(df, df.index[-1], entry=100, t1=90, direction="SELL") is True


def test_t1_not_blocked_sell_when_target_untouched():
    df = _df5([101.0, 101.0, 101.0], [95.0, 94.0, 95.0])
    # All lows > t1=90 → not blocked
    assert t1_blocked(df, df.index[-1], entry=100, t1=90, direction="SELL") is False


def test_t1_blocked_uses_only_candles_before_confirmation():
    # Row at idx[-1] has a high that would exceed t1, but it IS the confirmation candle
    # (df.index < confirmation_ts excludes it) → should not block.
    highs = [101.0, 101.0, 200.0]  # last high is huge but is the confirmation candle
    lows = [99.0] * 3
    df = _df5(highs, lows)
    assert t1_blocked(df, df.index[-1], entry=100, t1=110, direction="BUY") is False
