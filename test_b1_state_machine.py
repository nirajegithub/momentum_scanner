"""
B1 ORB state-machine regression test.

Run from the repository root:
    python test_b1_state_machine.py

This complements the historical B1 backtest. It verifies the live scanner
state transition: 15M setup -> WAITING_FOR_5M -> 5M confirmation -> alert
-> CONSUMED, including protection against premature CONSUMED and Telegram
failure.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pandas as pd

from app.main import _process_b1
from app.state import blank

logging.basicConfig(level=logging.INFO, format="%(message)s")

SYMBOL = "TESTSYM"
SECURITY_ID = "999999"
TRADING_DAY = "2026-09-18"
IST = "Asia/Kolkata"


def make_state():
    from datetime import date
    state = blank(date.fromisoformat(TRADING_DAY))
    state["universe"] = [{
        "symbol": SYMBOL,
        "security_id": SECURITY_ID,
        "prev_close": 500.0,
        "prev_volume": 2_000_000.0,
    }]
    return state


def make_15m():
    idx = pd.date_range(f"{TRADING_DAY} 09:15", periods=3,
                        freq="15min", tz=IST)
    return pd.DataFrame([
        {
            "open": 100,
            "high": 105,
            "low": 95,
            "close": 100,
            "volume": 100000,
            "rsi14": 55,
            "rvol": 1.0,
        },
        {
            "open": 100,
            "high": 104,
            "low": 98,
            "close": 103,
            "volume": 120000,
            "rsi14": 58,
            "rvol": 1.3,
        },
        {
            "open": 103,
            "high": 111,
            "low": 102,
            "close": 109,
            "volume": 180000,
            "rsi14": 62,
            "rvol": 1.5,
        },
    ], index=idx)


def make_5m():
    idx = pd.date_range(f"{TRADING_DAY} 09:50", periods=4,
                        freq="5min", tz=IST)
    return pd.DataFrame([
        {"open":104,"high":105,"low":103,"close":104,"volume":10000},
        {"open":104,"high":105.5,"low":103.8,"close":104.8,"volume":11000},
        {"open":104.8,"high":106.5,"low":104.5,"close":106.0,"volume":15000},
        {"open":106,"high":107,"low":105.5,"close":106.5,"volume":16000},
    ], index=idx)


class FakeDhan:
    def __init__(self):
        self.df15 = make_15m()
        self.df5 = make_5m()

    def historical_intraday_df(self, security_id, interval, from_date, to_date):
        if interval == 15:
            return self.df15.copy()
        if interval == 5:
            return self.df5.copy()
        raise AssertionError(f"Unexpected interval: {interval}")

    def historical_daily_df(self, security_id, from_date, to_date):
        return pd.DataFrame(
            [{"close": 500.0, "volume": 2_000_000.0}],
            index=pd.DatetimeIndex(
                [pd.Timestamp(f"{TRADING_DAY} 00:00", tz=IST)]
            ),
        )


def test_setup_waits_for_5m():
    state = make_state()
    with patch("app.main.send", return_value=True) as send_mock:
        _process_b1(
            FakeDhan(), state,
            pd.Timestamp(f"{TRADING_DAY} 09:50", tz=IST).to_pydatetime()
        )

    ss = state["b1"][SYMBOL]
    assert ss["status"] == "WAITING_FOR_5M", ss["status"]
    assert ss.get("setup") is not None
    assert ss["setup"]["direction"] == "BUY"
    assert float(ss["setup"]["setup_15m_high"]) == 105.0
    assert send_mock.call_count == 0


def test_confirmation_then_consumed():
    state = make_state()
    dhan = FakeDhan()

    with patch("app.main.send", return_value=True):
        _process_b1(
            dhan, state,
            pd.Timestamp(f"{TRADING_DAY} 09:50", tz=IST).to_pydatetime()
        )

    with patch("app.main.send", return_value=True) as send_mock:
        _process_b1(
            dhan, state,
            pd.Timestamp(f"{TRADING_DAY} 10:10", tz=IST).to_pydatetime()
        )

    ss = state["b1"][SYMBOL]
    assert send_mock.call_count == 1
    assert ss["status"] == "CONSUMED"
    assert ss.get("setup") is None
    assert ss.get("confirmation_5m_timestamp") is not None


def test_telegram_failure_does_not_consume():
    state = make_state()
    dhan = FakeDhan()

    with patch("app.main.send", return_value=True):
        _process_b1(
            dhan, state,
            pd.Timestamp(f"{TRADING_DAY} 09:50", tz=IST).to_pydatetime()
        )

    with patch("app.main.send", return_value=False) as send_mock:
        _process_b1(
            dhan, state,
            pd.Timestamp(f"{TRADING_DAY} 10:10", tz=IST).to_pydatetime()
        )

    ss = state["b1"][SYMBOL]
    assert send_mock.call_count == 1
    assert ss["status"] != "CONSUMED"
    assert ss.get("setup") is not None


if __name__ == "__main__":
    tests = [
        test_setup_waits_for_5m,
        test_confirmation_then_consumed,
        test_telegram_failure_does_not_consume,
    ]
    failed = 0
    print("\nB1 STATE-MACHINE REGRESSION TEST")
    print("=" * 50)
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL: {test.__name__}: {type(exc).__name__}: {exc}")
    print("=" * 50)
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("ALL B1 STATE-MACHINE TESTS PASSED")
