"""
B1 state-machine E2E tests for the current single-phase 5M architecture.

_process_b1 directly scans each completed 5M candle for an ORB breakout;
there is no separate 15M setup phase. Entry = close of the confirming 5M candle.

Tests isolate _process_b1 from:
  - Dhan HTTP/API calls  (_prepare_5m, get_orb_with_fallback patched)
  - strategy thresholds  (evaluate_b1_breakout, market_trend_aligned patched)
  - T1 safety logic      (t1_blocked patched)
  - Telegram transport   (send, signal_message patched)
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.main import _process_b1
from app.state import blank


IST = "Asia/Kolkata"
TRADING_DAY = date(2026, 9, 18)
SYMBOL = "TEST"
SECURITY_ID = "999999"

ORB = {
    "timestamp": "2026-09-18T09:15:00+05:30",
    "open": 100.0, "high": 110.0, "low": 95.0, "close": 100.0,
}


def _state():
    state = blank(TRADING_DAY)
    state["universe"] = [
        {
            "symbol": SYMBOL,
            "security_id": SECURITY_ID,
            "exchange_segment": "NSE_EQ",
            "instrument": "EQUITY",
            "prev_close": 103.0,   # used by _daily_values without hitting dhan
            "prev_volume": 2_000_000,
        }
    ]
    return state


def _df5_breakout():
    """5M candles for TRADING_DAY; last candle is a BUY breakout (close > ORB.high=110)."""
    idx = pd.DatetimeIndex(
        [
            "2026-09-18 09:20:00",
            "2026-09-18 09:25:00",
            "2026-09-18 09:30:00",
            "2026-09-18 09:35:00",
        ],
        tz=IST,
    )
    df = pd.DataFrame(
        {
            "open":   [100.0, 101.0, 105.0, 110.0],
            "high":   [102.0, 106.0, 108.0, 114.0],
            "low":    [ 99.0, 100.0, 104.0, 109.5],
            "close":  [101.0, 105.0, 107.0, 112.0],  # last close > 110 = BUY breakout
            "volume": [100_000] * 4,
            "rvol":   [1.5] * 4,
            "rsi14":  [55.0] * 4,
            "body_ratio": [0.5] * 4,
        },
        index=idx,
    )
    return df


def _df5_no_breakout():
    """5M candles where all closes stay inside the ORB range [95, 110]."""
    idx = pd.DatetimeIndex(
        ["2026-09-18 09:20:00", "2026-09-18 09:25:00"],
        tz=IST,
    )
    return pd.DataFrame(
        {
            "open":   [100.0, 101.0],
            "high":   [102.0, 104.0],
            "low":    [ 99.0, 100.0],
            "close":  [101.0, 103.0],  # all inside [95, 110]
            "volume": [100_000, 100_000],
            "rvol":   [1.5, 1.5],
            "rsi14":  [55.0, 55.0],
            "body_ratio": [0.5, 0.5],
        },
        index=idx,
    )


def _scan_ts(hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"2026-09-18 {hhmm}:00", tz=IST)


def _patch_infra(monkeypatch, df5, send_fn):
    """Patch all external calls; return the mocked setup dict."""
    setup_candidate = {"setup_15m_high": 114.0, "setup_15m_close": 112.0, "setup": "B1_ORB"}

    monkeypatch.setattr("app.main._prepare_5m",
                        lambda dhan, sid, ts: df5)
    monkeypatch.setattr("app.main.get_orb_with_fallback",
                        lambda dhan, sid, day: (ORB, "API"))
    monkeypatch.setattr("app.main.evaluate_b1_breakout",
                        lambda *a, **kw: dict(setup_candidate))
    monkeypatch.setattr("app.main.market_trend_aligned",
                        lambda *a, **kw: True)
    monkeypatch.setattr("app.main.t1_blocked",
                        lambda *a, **kw: False)
    monkeypatch.setattr("app.main.signal_message",
                        lambda signal: "TEST ALERT")
    monkeypatch.setattr("app.main.send", send_fn)
    monkeypatch.setattr("app.main.save", lambda state: None)

    return setup_candidate


def test_b1_5m_breakout_sends_signal_and_consumes(monkeypatch):
    """A BUY breakout 5M candle results in a signal and CONSUMED state."""
    sent = []
    _patch_infra(monkeypatch, _df5_breakout(), lambda msg: sent.append(msg) or True)

    state = _state()
    _process_b1(object(), state, _scan_ts("09:40"))

    ss = state["b1"][SYMBOL]
    assert ss["status"] == "CONSUMED"
    assert len(sent) == 1
    assert len(state.get("signals", {})) == 1

    signal = next(iter(state["signals"].values()))
    assert signal["symbol"] == SYMBOL
    assert signal["direction"] == "BUY"
    assert signal["confirmation_5m_close"] == 112.0   # entry = close of breakout candle
    assert "risk" in signal


def test_b1_telegram_failure_does_not_consume(monkeypatch):
    """When send() returns False the signal is NOT recorded and state is NOT CONSUMED."""
    attempts = []
    _patch_infra(monkeypatch, _df5_breakout(), lambda msg: attempts.append(msg) or False)

    state = _state()
    _process_b1(object(), state, _scan_ts("09:40"))

    ss = state["b1"][SYMBOL]
    assert len(attempts) == 1
    assert ss["status"] != "CONSUMED"
    assert state.get("signals", {}) == {}


def test_b1_no_breakout_stays_waiting(monkeypatch):
    """When all 5M closes are inside the ORB range no signal is sent and status stays WAITING_FOR_5M."""
    sent = []
    _patch_infra(monkeypatch, _df5_no_breakout(), lambda msg: sent.append(msg) or True)
    # evaluate_b1_breakout is not even called when no breakout candle exists;
    # override to crash loudly if it is called unexpectedly.
    monkeypatch.setattr("app.main.evaluate_b1_breakout",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not be called")))

    state = _state()
    _process_b1(object(), state, _scan_ts("09:30"))

    assert sent == []
    assert state.get("signals", {}) == {}
    assert state["b1"][SYMBOL]["status"] == "WAITING_FOR_5M"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main(["-q", "-s", __file__]))
