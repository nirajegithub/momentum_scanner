"""Extended tests for app.risk.build_risk_and_targets."""

from __future__ import annotations

import pytest

from app.risk import build_risk_and_targets


def test_stop_too_large_is_rejected():
    # entry=100, sl=80 → stop=20% which exceeds max_stop_distance_percent=10%
    risk, reason = build_risk_and_targets("BUY", 100, 80, 0.50, 2, 3, 4, 2, max_stop_distance_percent=10.0)
    assert risk is None
    assert reason == "STOP_DISTANCE_TOO_LARGE"


def test_invalid_risk_sl_equals_entry():
    risk, reason = build_risk_and_targets("BUY", 100, 100, 0.50, 2, 3, 4, 2)
    assert risk is None
    assert reason == "INVALID_RISK"


def test_invalid_risk_sl_above_entry_for_buy():
    risk, reason = build_risk_and_targets("BUY", 100, 105, 0.50, 2, 3, 4, 2)
    assert risk is None
    assert reason == "INVALID_RISK"


def test_t1_rr_below_min_rr_is_rejected():
    risk, reason = build_risk_and_targets("BUY", 1000, 995, 0.50, t1_rr=1.5, t2_rr=3, t3_rr=4, min_rr=2.0)
    assert risk is None
    assert reason == "T1_RR_BELOW_MIN"


def test_buy_trailing_sl_below_entry():
    risk, reason = build_risk_and_targets("BUY", 1000, 995, 0.50, 2, 3, 4, 2, trailing_stop_pct=5.0)
    assert reason is None
    assert risk["trailing_sl"] == pytest.approx(1000 * (1 - 0.05))  # 950.0


def test_sell_trailing_sl_above_entry():
    risk, reason = build_risk_and_targets("SELL", 1000, 1005, 0.50, 2, 3, 4, 2, trailing_stop_pct=5.0)
    assert reason is None
    assert risk["trailing_sl"] == pytest.approx(1000 * (1 + 0.05))  # 1050.0


def test_sell_invalid_risk_sl_below_entry():
    risk, reason = build_risk_and_targets("SELL", 1000, 995, 0.50, 2, 3, 4, 2)
    assert risk is None
    assert reason == "INVALID_RISK"


def test_exact_max_stop_is_accepted():
    # stop = 10/1000 = 1% == max_stop_distance_percent=1%
    risk, reason = build_risk_and_targets("BUY", 1000, 990, 0.50, 2, 3, 4, 2, max_stop_distance_percent=1.0)
    assert reason is None
    assert risk is not None


def test_stop_just_above_max_is_rejected():
    # stop = 11/1000 = 1.1% > max=1%
    risk, reason = build_risk_and_targets("BUY", 1000, 989, 0.50, 2, 3, 4, 2, max_stop_distance_percent=1.0)
    assert risk is None
    assert reason == "STOP_DISTANCE_TOO_LARGE"
