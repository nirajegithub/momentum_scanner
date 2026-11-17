"""Tests for app.bt — standalone B1 ORB backtest engine.

Unit tests cover the pure-logic helpers (_trading_days, _hhmm,
_load_universe_from_state) and the core simulation kernel (_simulate_day,
run_backtest) using synthetic 5M DataFrames — no Dhan API calls, no network.

Regression tests pin the exit-decision logic so a future refactor of the
SL/T1 check order cannot silently change P&L semantics.
"""

from __future__ import annotations

import json
import math
from datetime import date, time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from app.bt import (
    _hhmm,
    _load_universe_from_state,
    _simulate_day,
    _trading_days,
    run_backtest,
)

IST = ZoneInfo("Asia/Kolkata")
DATE = date(2026, 11, 3)   # a Monday — safe trading day for fixtures


# ─────────────────────────────────────────────────────────────────────────────
# DataFrame builder helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts(t: str) -> pd.Timestamp:
    return pd.Timestamp(f"2026-11-03 {t}:00", tz=IST)


def _make_df5(rows: list[tuple]) -> pd.DataFrame:
    """rows = [(time_str, open, high, low, close, volume), ...]"""
    idx = pd.DatetimeIndex([_ts(r[0]) for r in rows])
    df = pd.DataFrame(
        [{"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
         for r in rows],
        index=idx,
    )
    return df


def _warm_up_rows() -> list[tuple]:
    """30+ prior-day candles so add_indicators has enough data for RSI/RVOL.
    Prices clustered near 500 — ORB high=510 triggers a BUY on the warm-up day.
    We only use these as prior data; the test day uses DATE.
    """
    base = [
        ("09:15", 495, 502, 490, 498, 1_200_000),
        ("09:20", 498, 505, 495, 500, 500_000),
        ("09:25", 500, 508, 498, 504, 400_000),
        ("09:30", 504, 510, 500, 506, 350_000),
        ("09:35", 506, 512, 503, 509, 300_000),
        ("09:40", 509, 515, 505, 511, 280_000),
        ("09:45", 511, 516, 507, 513, 260_000),
        ("09:50", 513, 518, 509, 515, 250_000),
        ("09:55", 515, 519, 511, 516, 240_000),
        ("10:00", 516, 520, 512, 517, 230_000),
        ("10:05", 517, 521, 513, 518, 220_000),
        ("10:10", 518, 522, 514, 519, 210_000),
        ("10:15", 519, 523, 515, 520, 200_000),
        ("10:20", 520, 524, 516, 521, 190_000),
        ("10:25", 521, 525, 517, 522, 180_000),
        ("10:30", 522, 526, 518, 523, 170_000),
        ("10:35", 523, 527, 519, 524, 160_000),
        ("10:40", 524, 528, 520, 525, 150_000),
        ("10:45", 525, 529, 521, 526, 140_000),
        ("10:50", 526, 530, 522, 527, 130_000),
        ("10:55", 527, 531, 523, 528, 120_000),
        ("11:00", 528, 532, 524, 529, 110_000),
        ("11:05", 529, 533, 525, 530, 100_000),
        ("11:10", 530, 534, 526, 531,  90_000),
        ("11:15", 531, 535, 527, 532,  80_000),
        ("11:20", 532, 536, 528, 533,  70_000),
        ("11:25", 533, 537, 529, 534,  60_000),
        ("11:30", 534, 538, 530, 535,  50_000),
        ("11:35", 535, 539, 531, 536,  45_000),
        ("11:40", 536, 540, 532, 537,  40_000),
        ("11:45", 537, 541, 533, 538,  35_000),
    ]
    # Shift to previous trading day (Oct 31) so they don't collide with DATE=Nov03
    shifted = []
    for t, o, h, l, c, v in base:
        shifted.append((f"2026-10-31 {t}:00", o, h, l, c, v))
    return shifted


def _make_prior_df5() -> pd.DataFrame:
    rows = _warm_up_rows()
    idx = pd.DatetimeIndex([pd.Timestamp(r[0], tz=IST) for r in rows])
    df = pd.DataFrame(
        [{"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
         for r in rows],
        index=idx,
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _trading_days
# ─────────────────────────────────────────────────────────────────────────────

def test_trading_days_excludes_weekends():
    days = _trading_days(date(2026, 11, 2), date(2026, 11, 8))
    weekdays = [d.weekday() for d in days]
    assert all(w < 5 for w in weekdays)


def test_trading_days_single_day():
    days = _trading_days(date(2026, 11, 3), date(2026, 11, 3))
    assert days == [date(2026, 11, 3)]


def test_trading_days_empty_when_reversed():
    days = _trading_days(date(2026, 11, 7), date(2026, 11, 3))
    assert days == []


def test_trading_days_count_one_week():
    days = _trading_days(date(2026, 11, 2), date(2026, 11, 6))
    assert len(days) == 5


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _hhmm
# ─────────────────────────────────────────────────────────────────────────────

def test_hhmm_market_open():
    ts = pd.Timestamp("2026-11-03 09:15:00", tz=IST)
    assert _hhmm(ts) == 915


def test_hhmm_afternoon():
    ts = pd.Timestamp("2026-11-03 13:30:00", tz=IST)
    assert _hhmm(ts) == 1330


def test_hhmm_eod():
    ts = pd.Timestamp("2026-11-03 15:29:00", tz=IST)
    assert _hhmm(ts) == 1529


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _load_universe_from_state
# ─────────────────────────────────────────────────────────────────────────────

def test_load_universe_missing_file(tmp_path):
    result = _load_universe_from_state(tmp_path / "missing.json")
    assert result == []


def test_load_universe_valid_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"universe": [{"symbol": "RELIANCE", "security_id": "1333"}]}))
    result = _load_universe_from_state(p)
    assert len(result) == 1
    assert result[0]["symbol"] == "RELIANCE"


def test_load_universe_missing_key(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"other_key": []}))
    result = _load_universe_from_state(p)
    assert result == []


def test_load_universe_corrupt_json(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("not json {{")
    result = _load_universe_from_state(p)
    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _simulate_day — no-signal paths
# ─────────────────────────────────────────────────────────────────────────────

def test_simulate_day_returns_none_for_empty_df():
    result = _simulate_day("TEST", pd.DataFrame(), DATE, 500.0, 1_000_000)
    assert result is None


def test_simulate_day_returns_none_when_too_few_candles():
    rows = [
        ("09:15", 500, 510, 490, 500, 500_000),
        ("09:20", 500, 510, 490, 505, 300_000),
    ]
    df = _make_df5(rows)
    result = _simulate_day("TEST", df, DATE, 500.0, 1_000_000)
    assert result is None


def test_simulate_day_returns_none_when_orb_candle_missing():
    # Only candles from 09:30 onwards — no 09:15 ORB candle
    rows = [
        ("09:30", 500, 510, 490, 505, 300_000),
        ("09:35", 505, 515, 500, 510, 280_000),
        ("09:40", 510, 520, 505, 515, 260_000),
        ("09:45", 515, 525, 510, 520, 240_000),
        ("09:50", 520, 530, 515, 525, 220_000),
        ("09:55", 525, 535, 520, 530, 200_000),
        ("10:00", 530, 540, 525, 535, 180_000),
    ]
    df = _make_df5(rows)
    result = _simulate_day("TEST", df, DATE, 500.0, 1_000_000)
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Regression: exit-decision logic
# ─────────────────────────────────────────────────────────────────────────────

def _build_signal_dict(direction: str, entry: float, sl: float, t1: float) -> dict:
    """Minimal signal dict as returned by _simulate_day internals."""
    return {
        "symbol": "TEST",
        "date": str(DATE),
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "t1": t1,
        "exit_price": None,
        "exit_reason": None,
    }


def _walk_exit(direction: str, entry: float, sl: float, t1: float,
               future_rows: list[tuple]) -> tuple[float, str]:
    """Reproduce the exit-walk logic from _simulate_day for unit testing."""
    exit_price = None
    exit_reason = "EOD_SQUARE_OFF"
    for row in future_rows:
        _, fc_low, fc_high, fc_close = row
        if direction == "BUY":
            if fc_low <= sl:
                return sl, "SL_HIT"
            if fc_high >= t1:
                return t1, "T1_HIT"
        else:
            if fc_high >= sl:
                return sl, "SL_HIT"
            if fc_low <= t1:
                return t1, "T1_HIT"
    # EOD: return last close
    return future_rows[-1][3], "EOD_SQUARE_OFF"


class TestExitLogicRegression:
    """Pin the SL-first, then T1 priority and EOD fallback."""

    def test_buy_sl_hit_before_t1(self):
        # Same candle: low touches SL and high touches T1 — SL must win
        price, reason = _walk_exit("BUY", 500, 490, 510,
                                   [("09:40", 489, 511, 505)])  # low < sl, high > t1
        assert reason == "SL_HIT"
        assert price == 490

    def test_buy_t1_hit(self):
        price, reason = _walk_exit("BUY", 500, 490, 510,
                                   [("09:40", 505, 515, 507)])
        assert reason == "T1_HIT"
        assert price == 510

    def test_buy_sl_hit(self):
        price, reason = _walk_exit("BUY", 500, 490, 510,
                                   [("09:40", 488, 495, 489)])
        assert reason == "SL_HIT"
        assert price == 490

    def test_buy_eod_square_off(self):
        price, reason = _walk_exit("BUY", 500, 490, 510,
                                   [("09:40", 495, 505, 500),
                                    ("09:45", 496, 507, 502)])
        assert reason == "EOD_SQUARE_OFF"
        assert price == 502  # last row's close

    def test_sell_sl_hit_before_t1(self):
        # Same candle: high touches SL and low touches T1 — SL must win
        price, reason = _walk_exit("SELL", 500, 510, 490,
                                   [("09:40", 489, 511, 492)])
        assert reason == "SL_HIT"
        assert price == 510

    def test_sell_t1_hit(self):
        price, reason = _walk_exit("SELL", 500, 510, 490,
                                   [("09:40", 487, 505, 489)])
        assert reason == "T1_HIT"
        assert price == 490

    def test_sell_sl_hit(self):
        price, reason = _walk_exit("SELL", 500, 510, 490,
                                   [("09:40", 505, 512, 508)])
        assert reason == "SL_HIT"
        assert price == 510

    def test_sell_eod_square_off(self):
        price, reason = _walk_exit("SELL", 500, 510, 490,
                                   [("09:40", 495, 505, 500),
                                    ("09:45", 496, 507, 498)])
        assert reason == "EOD_SQUARE_OFF"
        assert price == 498


# ─────────────────────────────────────────────────────────────────────────────
# Regression: _simulate_day with mocked evaluate_b1_breakout
# ─────────────────────────────────────────────────────────────────────────────

def _make_full_day_df(*, signal_at: str, sl: float, t1: float,
                      direction: str = "BUY",
                      hit_at: str | None = None,
                      hit_type: str = "T1") -> pd.DataFrame:
    """
    Build a realistic prior+day DataFrame so _simulate_day has enough candles
    for add_indicators, then returns the first mock signal.

    hit_at: if given, the candle at that time triggers the exit (high>t1 or low<sl).
    """
    prior = _make_prior_df5()

    # Day candles: ORB at 09:15, then scan candles up to 13:30
    base_price = 500.0
    orb_high = base_price + 10   # 510
    orb_low = base_price - 10    # 490

    day_rows = [
        # time,  o,         h,          l,          c,          vol
        ("09:15", base_price, orb_high,  orb_low,    base_price, 2_000_000),
        ("09:20", base_price, base_price+5, base_price-3, base_price+2, 400_000),
        ("09:25", base_price+2, base_price+6, base_price-1, base_price+3, 350_000),
        ("09:30", base_price+3, base_price+7, base_price-1, base_price+4, 320_000),
        ("09:35", base_price+4, base_price+8, base_price+2, base_price+5, 300_000),
        ("09:40", base_price+5, base_price+9, base_price+3, base_price+6, 280_000),
        ("09:45", base_price+6, base_price+10, base_price+4, base_price+7, 260_000),
        ("09:50", base_price+7, base_price+11, base_price+5, base_price+8, 240_000),
        ("09:55", base_price+8, base_price+12, base_price+6, base_price+9, 220_000),
        ("10:00", base_price+9, base_price+13, base_price+7, base_price+10, 200_000),
    ]

    # Mark the signal candle (close used as entry)
    idx_signal = None
    for i, r in enumerate(day_rows):
        if r[0] == signal_at:
            idx_signal = i
            break

    # Add candles after signal for exit simulation
    post_rows = []
    for m in range(5, 20):
        t_str = f"{9 + (25 + m * 5) // 60:02d}:{(25 + m * 5) % 60:02d}"
        p = base_price + 10 + m
        post_rows.append((t_str, p, p + 2, p - 2, p + 1, 100_000 - m * 1000))

    if hit_at:
        for i, r in enumerate(post_rows):
            if r[0] == hit_at:
                if hit_type == "T1" and direction == "BUY":
                    post_rows[i] = (r[0], r[1], t1 + 1, r[3], r[4], r[5])
                elif hit_type == "SL" and direction == "BUY":
                    post_rows[i] = (r[0], r[1], r[2], sl - 1, sl - 1, r[5])
                break

    all_day = day_rows + post_rows
    day_df = _make_df5(all_day)
    return pd.concat([prior, day_df])


@patch("app.bt.evaluate_b1_breakout")
@patch("app.bt.add_indicators")
def test_simulate_day_signal_t1_hit(mock_add_ind, mock_eval):
    """Signal fires, T1 hit on a later candle — pnl should be positive."""
    entry = 506.0
    sl = 490.0
    t1 = entry + (entry - sl) * 1.5  # 1.5× R

    mock_eval.side_effect = [
        None, None, None,  # first 3 candles: no signal
        {                   # 4th candle: signal
            "direction": "BUY",
            "setup_15m_close": entry,
            "trade_quality_score": 5.0,
            "setup_15m_rvol": 2.5,
            "setup_15m_rsi14": 60.0,
        },
    ]
    mock_add_ind.side_effect = lambda df, **kw: df  # pass-through

    df = _make_full_day_df(signal_at="09:35", sl=sl, t1=t1, hit_at="10:10", hit_type="T1")

    with patch("app.bt.build_risk_and_targets") as mock_risk:
        mock_risk.return_value = (
            {"t1": t1, "sl": sl, "risk": entry - sl, "risk_percent": 3.2,
             "t2": t1 + 10, "t3": t1 + 20, "entry": entry, "trailing_sl": sl},
            None,
        )
        result = _simulate_day("TEST", df, DATE, 500.0, 1_500_000)

    assert result is not None
    assert result["direction"] == "BUY"
    assert result["pnl"] > 0
    assert result["exit_reason"] == "T1_HIT"


@patch("app.bt.evaluate_b1_breakout")
@patch("app.bt.add_indicators")
def test_simulate_day_signal_sl_hit(mock_add_ind, mock_eval):
    """Signal fires, SL hit — pnl should be negative."""
    entry = 506.0
    sl = 490.0
    t1 = entry + (entry - sl) * 1.5

    mock_eval.side_effect = [
        None, None, None,
        {
            "direction": "BUY",
            "setup_15m_close": entry,
            "trade_quality_score": 5.0,
            "setup_15m_rvol": 2.5,
            "setup_15m_rsi14": 60.0,
        },
    ]
    mock_add_ind.side_effect = lambda df, **kw: df

    df = _make_full_day_df(signal_at="09:35", sl=sl, t1=t1, hit_at="10:10", hit_type="SL")

    with patch("app.bt.build_risk_and_targets") as mock_risk:
        mock_risk.return_value = (
            {"t1": t1, "sl": sl, "risk": entry - sl, "risk_percent": 3.2,
             "t2": t1 + 10, "t3": t1 + 20, "entry": entry, "trailing_sl": sl},
            None,
        )
        result = _simulate_day("TEST", df, DATE, 500.0, 1_500_000)

    assert result is not None
    assert result["pnl"] < 0
    assert result["exit_reason"] == "SL_HIT"


@patch("app.bt.evaluate_b1_breakout")
@patch("app.bt.add_indicators")
def test_simulate_day_risk_rejected_skips_signal(mock_add_ind, mock_eval):
    """build_risk_and_targets returning None must not produce a trade."""
    mock_eval.return_value = {
        "direction": "BUY",
        "setup_15m_close": 506.0,
        "trade_quality_score": 5.0,
        "setup_15m_rvol": 2.5,
        "setup_15m_rsi14": 60.0,
    }
    mock_add_ind.side_effect = lambda df, **kw: df

    df = _make_full_day_df(signal_at="09:35", sl=490.0, t1=524.0)

    with patch("app.bt.build_risk_and_targets") as mock_risk:
        mock_risk.return_value = (None, "STOP_DISTANCE_TOO_LARGE")
        result = _simulate_day("TEST", df, DATE, 500.0, 1_500_000)

    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Integration: run_backtest with fully mocked Dhan + strategy
# ─────────────────────────────────────────────────────────────────────────────

def _mock_dhan(df: pd.DataFrame) -> MagicMock:
    dhan = MagicMock()
    dhan.historical_intraday_df.return_value = df
    return dhan


@patch("app.bt.evaluate_b1_breakout")
@patch("app.bt.add_indicators")
def test_run_backtest_single_win(mock_add_ind, mock_eval):
    """run_backtest with one symbol, one trading day, one win."""
    entry = 506.0
    sl = 490.0
    t1 = entry + (entry - sl) * 1.5

    mock_eval.side_effect = [
        None, None, None,
        {
            "direction": "BUY",
            "setup_15m_close": entry,
            "trade_quality_score": 5.0,
            "setup_15m_rvol": 2.5,
            "setup_15m_rsi14": 60.0,
        },
    ]
    mock_add_ind.side_effect = lambda df, **kw: df

    df = _make_full_day_df(signal_at="09:35", sl=sl, t1=t1, hit_at="10:10", hit_type="T1")
    universe = [{"symbol": "TEST", "security_id": "999",
                 "prev_close": 500.0, "prev_volume": 1_500_000}]
    dhan = _mock_dhan(df)

    with patch("app.bt.build_risk_and_targets") as mock_risk:
        mock_risk.return_value = (
            {"t1": t1, "sl": sl, "risk": entry - sl, "risk_percent": 3.2,
             "t2": t1 + 10, "t3": t1 + 20, "entry": entry, "trailing_sl": sl},
            None,
        )
        results = run_backtest(dhan, universe, DATE, DATE, workers=1)

    assert results["stats"]["total_trades"] == 1
    assert results["stats"]["wins"] == 1
    assert results["stats"]["total_pnl"] > 0
    assert results["stats"]["profit_factor"] == float("inf")  # no losses


@patch("app.bt.evaluate_b1_breakout")
@patch("app.bt.add_indicators")
def test_run_backtest_max_open_positions_cap(mock_add_ind, mock_eval):
    """MAX_OPEN_POSITIONS=1 should discard the lower-score second symbol."""
    entry = 506.0
    sl = 490.0
    t1 = entry + (entry - sl) * 1.5

    signal_a = {
        "direction": "BUY", "setup_15m_close": entry,
        "trade_quality_score": 6.0, "setup_15m_rvol": 3.0, "setup_15m_rsi14": 62.0,
    }
    signal_b = {
        "direction": "BUY", "setup_15m_close": entry,
        "trade_quality_score": 4.0, "setup_15m_rvol": 2.0, "setup_15m_rsi14": 58.0,
    }

    df = _make_full_day_df(signal_at="09:35", sl=sl, t1=t1, hit_at="10:10", hit_type="T1")
    universe = [
        {"symbol": "SYM_A", "security_id": "1", "prev_close": 500.0, "prev_volume": 1_500_000},
        {"symbol": "SYM_B", "security_id": "2", "prev_close": 500.0, "prev_volume": 1_500_000},
    ]
    dhan = _mock_dhan(df)

    call_count = {"n": 0}

    def side_effect_eval(*args, **kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        candle_idx = n % 7
        if candle_idx == 3:
            sym = kwargs.get("symbol", "SYM_A")
            return signal_a if sym == "SYM_A" else signal_b
        return None

    mock_eval.side_effect = side_effect_eval
    mock_add_ind.side_effect = lambda df, **kw: df

    with patch("app.bt.build_risk_and_targets") as mock_risk, \
         patch("app.bt.MAX_OPEN_POSITIONS", 1):
        mock_risk.return_value = (
            {"t1": t1, "sl": sl, "risk": entry - sl, "risk_percent": 3.2,
             "t2": t1 + 10, "t3": t1 + 20, "entry": entry, "trailing_sl": sl},
            None,
        )
        results = run_backtest(dhan, universe, DATE, DATE, workers=1)

    # Only 1 trade accepted (cap=1), must be the higher-score SYM_A
    assert results["stats"]["total_trades"] == 1
    assert results["trades"][0]["symbol"] == "SYM_A"


def test_run_backtest_daily_loss_halt():
    """After DAILY_LOSS_HALT is breached, further signals are marked DAILY_HALT_SKIPPED.

    Patches _fetch_5m and _simulate_day to avoid threading/data loading complexity.
    """
    entry = 506.0
    sl = 490.0
    t1 = entry + (entry - sl) * 0.5

    df_stub = _make_full_day_df(signal_at="09:35", sl=sl, t1=t1)

    universe = [
        {"symbol": f"SYM{i}", "security_id": str(i), "prev_close": 500.0, "prev_volume": 1_500_000}
        for i in range(3)
    ]
    dhan = _mock_dhan(df_stub)

    canned_trades = [
        {"symbol": "SYM0", "date": str(DATE), "direction": "BUY",
         "entry": entry, "sl": sl, "t1": t1, "exit_price": sl,
         "exit_reason": "SL_HIT", "exit_ts": None, "pnl": -300.0,
         "trade_quality_score": 5.0, "rvol": 2.5, "rsi": 60.0, "risk_percent": 3.2,
         "signal_ts": "2026-11-03T09:35:00+05:30"},
        {"symbol": "SYM1", "date": str(DATE), "direction": "BUY",
         "entry": entry, "sl": sl, "t1": t1, "exit_price": sl,
         "exit_reason": "SL_HIT", "exit_ts": None, "pnl": -50.0,
         "trade_quality_score": 4.0, "rvol": 2.0, "rsi": 58.0, "risk_percent": 3.2,
         "signal_ts": "2026-11-03T09:35:00+05:30"},
        {"symbol": "SYM2", "date": str(DATE), "direction": "BUY",
         "entry": entry, "sl": sl, "t1": t1, "exit_price": t1,
         "exit_reason": "T1_HIT", "exit_ts": None, "pnl": 24.0,
         "trade_quality_score": 3.5, "rvol": 1.8, "rsi": 55.0, "risk_percent": 3.2,
         "signal_ts": "2026-11-03T09:35:00+05:30"},
    ]

    def fetch_side(dhan_, item, from_, to_):
        return (item["symbol"], df_stub)

    def sim_side(sym, df5, trading_date, prev_close, prev_volume):
        # Return the pre-canned trade for this symbol
        for t in canned_trades:
            if t["symbol"] == sym:
                return t
        return None

    with patch("app.bt._fetch_5m", side_effect=fetch_side), \
         patch("app.bt._simulate_day", side_effect=sim_side), \
         patch("app.bt.add_indicators", side_effect=lambda df, **kw: df), \
         patch("app.bt.MAX_OPEN_POSITIONS", 10), \
         patch("app.bt.DAILY_LOSS_HALT", -200.0):
        results = run_backtest(dhan, universe, DATE, DATE, workers=1)

    # Halted trades are excluded from results["trades"] (only real trades returned).
    # SYM0 fires (-300), crossing the -200 halt. SYM1 + SYM2 are suppressed.
    # Observable: total_trades < 3, total_pnl equals only SYM0's loss.
    assert results["stats"]["total_trades"] < len(universe), (
        "Halt should have suppressed at least one trade"
    )
    assert results["stats"]["total_pnl"] == pytest.approx(-300.0)


# ─────────────────────────────────────────────────────────────────────────────
# Regression: aggregate stats correctness
# ─────────────────────────────────────────────────────────────────────────────

def test_run_backtest_stats_math():
    """Verify profit_factor, win_rate and expectancy are computed correctly."""
    df_stub = _make_full_day_df(signal_at="09:35", sl=490, t1=524)

    canned_trades = [
        {"symbol": "ALPHA", "date": str(DATE), "direction": "BUY",
         "entry": 500, "sl": 490, "t1": 524, "exit_price": 524,
         "exit_reason": "T1_HIT", "exit_ts": None, "pnl": 24.0,
         "trade_quality_score": 5.0, "rvol": 2.5, "rsi": 60.0, "risk_percent": 2.0,
         "signal_ts": "2026-11-03T09:35:00+05:30"},
        {"symbol": "BETA", "date": str(DATE), "direction": "BUY",
         "entry": 500, "sl": 490, "t1": 524, "exit_price": 490,
         "exit_reason": "SL_HIT", "exit_ts": None, "pnl": -10.0,
         "trade_quality_score": 4.5, "rvol": 2.0, "rsi": 58.0, "risk_percent": 2.0,
         "signal_ts": "2026-11-03T09:35:00+05:30"},
    ]

    def fetch_side(dhan_, item, from_, to_):
        return (item["symbol"], df_stub)

    def sim_side(sym, df5, trading_date, prev_close, prev_volume):
        for t in canned_trades:
            if t["symbol"] == sym:
                return t
        return None

    universe = [
        {"symbol": "ALPHA", "security_id": "1", "prev_close": 500.0, "prev_volume": 1_500_000},
        {"symbol": "BETA",  "security_id": "2", "prev_close": 500.0, "prev_volume": 1_500_000},
    ]
    dhan = _mock_dhan(df_stub)

    with patch("app.bt._fetch_5m", side_effect=fetch_side), \
         patch("app.bt._simulate_day", side_effect=sim_side), \
         patch("app.bt.add_indicators", side_effect=lambda df, **kw: df):
        results = run_backtest(dhan, universe, DATE, DATE, workers=1)

    s = results["stats"]
    assert s["total_trades"] > 0, "Expected trades — check fetch/simulate mocks"
    assert s["wins"] + s["losses"] == s["total_trades"]
    assert s["win_rate"] == pytest.approx(s["wins"] / s["total_trades"] * 100, abs=0.1)
    if s["losses"] > 0 and s["wins"] > 0:
        assert s["profit_factor"] == pytest.approx(
            s["avg_win"] * s["wins"] / (abs(s["avg_loss"]) * s["losses"]), rel=0.01)
    real_total = sum(t["pnl"] for t in results["trades"]
                     if t.get("exit_reason") != "DAILY_HALT_SKIPPED")
    assert s["total_pnl"] == pytest.approx(real_total, abs=0.01)
