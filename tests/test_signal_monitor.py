"""Tests for app.signal_monitor.monitor_active_signals."""

from __future__ import annotations

import pytest

from app.signal_monitor import monitor_active_signals


def _signal(direction="BUY", entry=100.0, sl=95.0, t1=110.0, t2=115.0, t3=120.0, **kwargs):
    s = {
        "symbol": "TEST",
        "direction": direction,
        "status": "ACTIVE",
        "risk": {
            "entry": entry, "sl": sl, "t1": t1, "t2": t2, "t3": t3,
        },
    }
    s.update(kwargs)
    return s


def _state_with(signal, key="TEST|BUY|ts"):
    return {"signals": {key: signal}}


# ── BUY direction ────────────────────────────────────────────────────────────


def test_buy_sl_hit_exits_signal():
    sig = _signal("BUY")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 94.0})  # below sl=95
    assert sig["status"] == "EXITED"
    assert sig["sl_hit"] is True
    assert sig["exit_reason"] == "SL_HIT"
    assert sig["exit_price"] == 95.0


def test_buy_sl_not_hit_stays_active():
    sig = _signal("BUY")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 96.0})  # above sl=95
    assert sig["status"] == "ACTIVE"
    assert not sig.get("sl_hit")


def test_buy_t1_hit_records_target_and_moves_sl_to_breakeven():
    sig = _signal("BUY")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 110.0})  # at t1=110
    assert sig.get("highest_target_hit") == "T1_HIT"
    assert float(sig["risk"]["sl"]) == 100.0  # moved to entry (breakeven)
    assert sig["status"] == "ACTIVE"  # not exited


def test_buy_t2_hit_upgrades_target():
    sig = _signal("BUY")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 115.0})  # at t2=115
    assert sig.get("highest_target_hit") == "T2_HIT"


def test_buy_t3_hit_records_highest():
    sig = _signal("BUY")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 120.0})  # at t3=120
    assert sig.get("highest_target_hit") == "T3_HIT"


def test_buy_t1_already_hit_does_not_downgrade_at_t2():
    """Once T2 is reached, a later price at only T1 level must not downgrade."""
    sig = _signal("BUY", highest_target_hit="T2_HIT")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 111.0})  # above t1 but below t2
    assert sig.get("highest_target_hit") == "T2_HIT"


def test_buy_live_managed_does_not_move_sl():
    """live_managed=True signals let trade_manager handle SL; monitor must not touch it."""
    sig = _signal("BUY", live_managed=True)
    original_sl = float(sig["risk"]["sl"])
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 110.0})  # t1 hit
    assert float(sig["risk"]["sl"]) == original_sl  # unchanged


# ── SELL direction ───────────────────────────────────────────────────────────


def test_sell_sl_hit_exits_signal():
    sig = _signal("SELL", entry=100.0, sl=105.0, t1=90.0, t2=85.0, t3=80.0)
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 106.0})  # above sl=105
    assert sig["status"] == "EXITED"
    assert sig["sl_hit"] is True
    assert sig["exit_price"] == 105.0


def test_sell_sl_not_hit_stays_active():
    sig = _signal("SELL", entry=100.0, sl=105.0, t1=90.0, t2=85.0, t3=80.0)
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 104.0})  # below sl=105
    assert sig["status"] == "ACTIVE"


def test_sell_t1_hit_moves_sl_to_breakeven():
    sig = _signal("SELL", entry=100.0, sl=105.0, t1=90.0, t2=85.0, t3=80.0)
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 90.0})  # at t1=90
    assert sig.get("highest_target_hit") == "T1_HIT"
    assert float(sig["risk"]["sl"]) == 100.0  # moved to entry


def test_sell_t3_hit():
    sig = _signal("SELL", entry=100.0, sl=105.0, t1=90.0, t2=85.0, t3=80.0)
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 80.0})
    assert sig.get("highest_target_hit") == "T3_HIT"


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_non_active_signal_is_skipped():
    sig = _signal("BUY", status="EXITED")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 94.0})  # would trigger SL if active
    assert sig["status"] == "EXITED"  # unchanged


def test_missing_symbol_in_prices_is_skipped():
    sig = _signal("BUY")
    state = _state_with(sig)
    monitor_active_signals(state, {})  # empty price dict
    assert sig["status"] == "ACTIVE"
    assert not sig.get("sl_hit")


def test_sl_already_hit_flag_prevents_duplicate_exit():
    sig = _signal("BUY", sl_hit=True, status="EXITED")
    state = _state_with(sig)
    monitor_active_signals(state, {"TEST": 94.0})
    # Should not re-process — signal is not ACTIVE so skipped entirely.
    assert sig["status"] == "EXITED"


def test_returns_state():
    state = {"signals": {}}
    result = monitor_active_signals(state, {})
    assert result is state
