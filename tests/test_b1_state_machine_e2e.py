"""
Single working B1 state-machine regression test for the current app.main.py.

This test deliberately isolates _process_b1 from:
  - Dhan HTTP/API calls
  - completed_candles() timestamp semantics
  - strategy thresholds
  - T1 safety logic
  - real Telegram transport

It DOES exercise the real _process_b1 state transitions.

Run:
    pytest -q -s test_b1_state_machine_e2e.py
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


def _state():
    state = blank(TRADING_DAY)
    state["universe"] = [
        {
            "symbol": SYMBOL,
            "security_id": SECURITY_ID,
            "exchange_segment": "NSE_EQ",
            "instrument": "EQUITY",
            "prev_close": 103.0,
            "prev_volume": 2_000_000,
        }
    ]
    return state


def _df15():
    # IMPORTANT: timezone-aware index.
    # Current main.py stores orb["timestamp"] with isoformat() including +05:30
    # and later compares it against the DataFrame index.
    idx = pd.DatetimeIndex(
        [
            "2026-09-18 09:15:00",
            "2026-09-18 09:30:00",
        ],
        tz=IST,
    )

    return pd.DataFrame(
        {
            "open": [100.0, 107.0],
            "high": [105.0, 110.0],
            "low": [99.0, 106.0],
            "close": [103.0, 108.0],
            "volume": [1_000_000, 1_500_000],
        },
        index=idx,
    )


def _setup():
    # Deterministic result returned by the mocked strategy evaluator.
    return {
        "setup_15m_high": 110.0,
        "setup_15m_low": 106.0,
        "setup_15m_close": 108.0,
    }


def _patch_strategy(monkeypatch):
    setup = _setup()

    monkeypatch.setattr(
        "app.main.evaluate_b1_breakout",
        lambda *args, **kwargs: dict(setup),
    )

    monkeypatch.setattr(
        "app.main.t1_blocked",
        lambda *args, **kwargs: False,
    )

    monkeypatch.setattr(
        "app.main.signal_message",
        lambda signal: "TEST ALERT",
    )

    return setup


def _patch_15m(monkeypatch):
    # Bypass Dhan and completed_candles; return already-completed 15M candles.
    monkeypatch.setattr(
        "app.main._prepare_15m",
        lambda dhan, security_id, ts: _df15(),
    )


def _no_confirmation(monkeypatch):
    monkeypatch.setattr(
        "app.main._confirmation_5m",
        lambda dhan, security_id, setup_completion, now_ts:
            (None, pd.DataFrame()),
    )


def _confirmation(monkeypatch):
    # One completed 5M candle:
    # close 112 > stored BUY setup high 110.
    ts5 = pd.Timestamp("2026-09-18 09:50:00", tz=IST)

    rows5 = pd.DataFrame(
        {
            "open": [109.0],
            "high": [113.0],
            "low": [108.5],
            "close": [112.0],
            "volume": [500_000],
        },
        index=pd.DatetimeIndex([ts5]),
    )

    monkeypatch.setattr(
        "app.main._confirmation_5m",
        lambda dhan, security_id, setup_completion, now_ts:
            (rows5, rows5),
    )

    return ts5


def _scan_ts(hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(
        f"2026-09-18 {hhmm}:00",
        tz=IST,
    )


def test_b1_setup_waits_then_confirms_and_consumes(monkeypatch):
    setup = _patch_strategy(monkeypatch)
    _patch_15m(monkeypatch)
    _no_confirmation(monkeypatch)

    state = _state()
    sent = []

    monkeypatch.setattr(
        "app.main.send",
        lambda message: sent.append(message) or True,
    )

    # First scan: completed 15M breakout exists, but no 5M confirmation.
    _process_b1(object(), state, _scan_ts("09:50"))

    ss = state["b1"][SYMBOL]

    assert ss["status"] == "WAITING_FOR_5M"
    assert ss["setup"] is not None
    assert ss["setup"]["direction"] == "BUY"
    assert ss["setup"]["setup_15m_high"] == 110.0
    assert ss["setup"]["setup_15m_close"] == 108.0
    assert sent == []

    # Second scan: completed 5M close crosses stored 15M high.
    confirmation_ts = _confirmation(monkeypatch)

    _process_b1(object(), state, _scan_ts("10:00"))

    ss = state["b1"][SYMBOL]

    assert ss["status"] == "CONSUMED"
    assert ss["setup"] is None
    assert len(sent) == 1

    assert isinstance(state["signals"], dict)
    assert len(state["signals"]) == 1

    signal = next(iter(state["signals"].values()))

    # Core B1 contract.
    assert signal["entry"] == 112.0
    assert signal["sl"] == 108.0
    assert signal["confirmation_5m_close"] == 112.0
    assert signal["confirmation_5m_timestamp"] == confirmation_ts.isoformat()


def test_b1_telegram_failure_keeps_setup(monkeypatch):
    _patch_strategy(monkeypatch)
    _patch_15m(monkeypatch)
    _no_confirmation(monkeypatch)

    state = _state()
    attempts = []

    monkeypatch.setattr(
        "app.main.send",
        lambda message: attempts.append(message) or False,
    )

    _process_b1(object(), state, _scan_ts("09:50"))

    assert state["b1"][SYMBOL]["status"] == "WAITING_FOR_5M"
    assert state["b1"][SYMBOL]["setup"] is not None

    _confirmation(monkeypatch)

    _process_b1(object(), state, _scan_ts("10:00"))

    ss = state["b1"][SYMBOL]

    assert len(attempts) == 1
    assert ss["status"] == "WAITING_FOR_5M"
    assert ss["setup"] is not None
    assert state.get("signals", {}) == {}


def test_b1_15m_setup_alone_never_sends(monkeypatch):
    _patch_strategy(monkeypatch)
    _patch_15m(monkeypatch)
    _no_confirmation(monkeypatch)

    state = _state()
    sent = []

    monkeypatch.setattr(
        "app.main.send",
        lambda message: sent.append(message) or True,
    )

    _process_b1(object(), state, _scan_ts("09:50"))

    assert state["b1"][SYMBOL]["status"] == "WAITING_FOR_5M"
    assert state["b1"][SYMBOL]["setup"] is not None
    assert sent == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main(["-q", "-s", __file__]))
