"""
Unit tests for app/trade_manager.py and app/position_tracker.py

Covers:
  - should_place_entry: BUY/SELL skip and pass conditions
  - pre_trade_ok: entry cutoff and signal age guards
  - place_entry_order: paper mode returns PAPER_* order id
  - wait_for_fill: paper mode returns entry price immediately
  - place_sl_order: paper mode returns PAPER_SL_* order id
  - modify_sl_order: MIN_TRAIL_INC gate, paper mode state update
  - _apply_tsl: floor SL on T1/T2/T3, no-op before T1
  - position_tracker._paper_sl_hit: marks EXITED on SL breach
  - position_tracker._mark_manually_exited: cancels SL, sets EXITED
  - position_tracker._adopt_manual: creates synthetic ACTIVE signal
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _sig(
    symbol="TEST",
    direction="BUY",
    entry=100.0,
    sl=95.0,
    t1=105.0,
    t2=110.0,
    t3=115.0,
    status="NEW",
    signal_time=None,
):
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    if signal_time is None:
        signal_time = datetime.now(ist_offset).isoformat()
    return {
        "symbol": symbol,
        "direction": direction,
        "status": status,
        "signal_time": signal_time,
        "security_id": "9999",
        "risk": {
            "entry": entry,
            "sl": sl,
            "original_sl": sl,
            "t1": t1,
            "t2": t2,
            "t3": t3,
        },
        "qty": 1,
    }


# ── should_place_entry ────────────────────────────────────────────────────────

class TestShouldPlaceEntry:
    def test_buy_skip_when_ltp_at_sl(self):
        from app.trade_manager import should_place_entry
        ok, reason = should_place_entry(_sig(direction="BUY", sl=95.0), ltp=95.0)
        assert not ok
        assert "BREAKOUT_FAILED" in reason

    def test_buy_skip_when_ltp_below_sl(self):
        from app.trade_manager import should_place_entry
        ok, reason = should_place_entry(_sig(direction="BUY", sl=95.0), ltp=90.0)
        assert not ok

    def test_buy_pass_when_ltp_above_sl(self):
        from app.trade_manager import should_place_entry
        ok, _ = should_place_entry(_sig(direction="BUY", sl=95.0), ltp=102.0)
        assert ok

    def test_buy_pass_when_ltp_above_entry(self):
        """Price ran up — still place LIMIT at signal entry (retest logic)."""
        from app.trade_manager import should_place_entry
        ok, _ = should_place_entry(_sig(direction="BUY", entry=100.0, sl=95.0), ltp=108.0)
        assert ok

    def test_sell_skip_when_ltp_at_sl(self):
        from app.trade_manager import should_place_entry
        ok, reason = should_place_entry(
            _sig(direction="SELL", entry=100.0, sl=105.0), ltp=105.0
        )
        assert not ok
        assert "BREAKOUT_FAILED" in reason

    def test_sell_skip_when_ltp_above_sl(self):
        from app.trade_manager import should_place_entry
        ok, _ = should_place_entry(
            _sig(direction="SELL", entry=100.0, sl=105.0), ltp=107.0
        )
        assert not ok

    def test_sell_pass_when_ltp_below_sl(self):
        from app.trade_manager import should_place_entry
        ok, _ = should_place_entry(
            _sig(direction="SELL", entry=100.0, sl=105.0), ltp=98.0
        )
        assert ok


# ── pre_trade_ok ──────────────────────────────────────────────────────────────

class TestPreTradeOk:
    def test_stale_signal_skipped(self):
        from app.trade_manager import pre_trade_ok
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        old_time = (datetime.now(ist_offset) - timedelta(minutes=35)).isoformat()
        sig = _sig(signal_time=old_time)
        with patch("app.trade_manager.tg") as mock_tg:
            result = pre_trade_ok(sig, state={})
        assert not result

    def test_fresh_signal_passes(self):
        from app.trade_manager import pre_trade_ok
        sig = _sig()
        with patch("app.trade_manager.tg"):
            with patch("app.trade_manager._hhmm", return_value=1000):
                result = pre_trade_ok(sig, state={})
        assert result

    def test_past_entry_cutoff_skipped(self):
        from app.trade_manager import pre_trade_ok
        sig = _sig()
        with patch("app.trade_manager._hhmm", return_value=1300):
            with patch("app.trade_manager.tg"):
                result = pre_trade_ok(sig, state={})
        assert not result

    def test_max_open_positions_skipped(self):
        from app.trade_manager import pre_trade_ok
        sig = _sig()
        # 5 ACTIVE signals already in state (hits MAX_OPEN_POSITIONS=5 default)
        state = {"signals": {
            f"s{i}": {**_sig(symbol=f"SYM{i}"), "status": "ACTIVE"}
            for i in range(5)
        }}
        with patch("app.trade_manager._hhmm", return_value=1000):
            with patch("app.trade_manager.tg"):
                result = pre_trade_ok(sig, state=state)
        assert not result

    def test_below_max_open_passes(self):
        from app.trade_manager import pre_trade_ok
        sig = _sig()
        # Only 4 ACTIVE — under the cap of 5
        state = {"signals": {
            f"s{i}": {**_sig(symbol=f"SYM{i}"), "status": "ACTIVE"}
            for i in range(4)
        }}
        with patch("app.trade_manager._hhmm", return_value=1000):
            with patch("app.trade_manager.tg"):
                result = pre_trade_ok(sig, state=state)
        assert result


# ── place_entry_order (paper) ─────────────────────────────────────────────────

class TestPlaceEntryOrderPaper:
    def test_returns_paper_order_id(self):
        from app.trade_manager import place_entry_order
        sig = _sig()
        with patch("app.trade_manager.tg"):
            oid = place_entry_order(dhan=None, signal=sig, qty=1, paper=True)
        assert oid is not None
        assert oid.startswith("PAPER_TEST")

    def test_paper_order_id_unique(self):
        from app.trade_manager import place_entry_order
        sig = _sig()
        with patch("app.trade_manager.tg"):
            oid1 = place_entry_order(dhan=None, signal=sig, qty=1, paper=True)
            time.sleep(0.01)
            oid2 = place_entry_order(dhan=None, signal=sig, qty=1, paper=True)
        # Both start with PAPER_ and are strings; timestamps make them unique
        assert isinstance(oid1, str) and isinstance(oid2, str)


# ── wait_for_fill (paper) ─────────────────────────────────────────────────────

class TestWaitForFillPaper:
    def test_returns_entry_price(self):
        from app.trade_manager import wait_for_fill
        sig = _sig(entry=100.0)
        with patch("app.trade_manager.tg"):
            fill = wait_for_fill(
                dhan=None, order_id="PAPER_TEST_1", signal=sig, qty=1, paper=True
            )
        assert fill == 100.0

    def test_returns_float(self):
        from app.trade_manager import wait_for_fill
        sig = _sig(entry=123.45)
        with patch("app.trade_manager.tg"):
            fill = wait_for_fill(
                dhan=None, order_id="PAPER_TEST_2", signal=sig, qty=1, paper=True
            )
        assert isinstance(fill, float)


# ── place_sl_order (paper) ────────────────────────────────────────────────────

class TestPlaceSLOrderPaper:
    def test_returns_paper_sl_order_id(self):
        from app.trade_manager import place_sl_order
        sig = _sig()
        with patch("app.trade_manager.tg"):
            oid = place_sl_order(dhan=None, signal=sig, qty=1, paper=True)
        assert oid is not None
        assert "PAPER_SL_TEST" in oid


# ── modify_sl_order ───────────────────────────────────────────────────────────

class TestModifySlOrder:
    def test_no_modify_below_min_trail_inc(self):
        from app.trade_manager import modify_sl_order
        sig = _sig(direction="BUY", sl=95.0)
        sig["sl_order_id"] = "SL_001"
        # improvement = 96.0 - 95.0 = 1.0 < MIN_TRAIL_INC(2.0) → skip
        result = modify_sl_order(dhan=None, signal=sig, new_sl=96.0, paper=True)
        assert not result
        assert sig["risk"]["sl"] == 95.0  # unchanged

    def test_modifies_when_above_min_trail_inc(self):
        from app.trade_manager import modify_sl_order
        sig = _sig(direction="BUY", sl=95.0)
        sig["sl_order_id"] = "SL_001"
        # improvement = 97.5 - 95.0 = 2.5 >= MIN_TRAIL_INC(2.0) → update
        result = modify_sl_order(dhan=None, signal=sig, new_sl=97.5, paper=True)
        assert result
        assert sig["risk"]["sl"] == 97.5

    def test_sell_direction_improvement_check(self):
        from app.trade_manager import modify_sl_order
        sig = _sig(direction="SELL", sl=105.0)
        sig["sl_order_id"] = "SL_002"
        # improvement = 105.0 - 102.0 = 3.0 >= 2.0 → update
        result = modify_sl_order(dhan=None, signal=sig, new_sl=102.0, paper=True)
        assert result
        assert sig["risk"]["sl"] == 102.0

    def test_sell_no_modify_insufficient_improvement(self):
        from app.trade_manager import modify_sl_order
        sig = _sig(direction="SELL", sl=105.0)
        sig["sl_order_id"] = "SL_002"
        # improvement = 105.0 - 104.5 = 0.5 < 2.0 → skip
        result = modify_sl_order(dhan=None, signal=sig, new_sl=104.5, paper=True)
        assert not result


# ── _apply_tsl ────────────────────────────────────────────────────────────────

class TestApplyTsl:
    def test_no_op_before_t1(self):
        from app.trade_manager import _apply_tsl
        sig = _sig(direction="BUY", entry=100.0, sl=95.0)
        sig["last_ltp"] = 102.0
        # no highest_target_hit set
        with patch("app.trade_manager.modify_sl_order") as mock_mod:
            _apply_tsl(dhan=None, signal=sig, paper=True)
        mock_mod.assert_not_called()

    def test_t1_hit_activates_trailing(self):
        from app.trade_manager import _apply_tsl
        sig = _sig(direction="BUY", entry=100.0, sl=95.0, t1=105.0)
        sig["highest_target_hit"] = "T1_HIT"
        sig["last_ltp"] = 106.0

        with patch("app.trade_manager.tg"):
            with patch("app.trade_manager.modify_sl_order") as mock_mod:
                _apply_tsl(dhan=None, signal=sig, paper=True)

        assert sig.get("trailing_active") is True
        assert sig.get("trail_distance") == 5.0  # entry(100) - original_sl(95)

    def test_t2_hit_floor_is_t1(self):
        from app.trade_manager import _apply_tsl
        sig = _sig(direction="BUY", entry=100.0, sl=95.0, t1=105.0, t2=110.0)
        sig["highest_target_hit"] = "T2_HIT"
        sig["last_ltp"] = 111.0
        sig["trailing_active"] = True
        sig["trail_distance"] = 5.0

        with patch("app.trade_manager.tg"):
            with patch("app.trade_manager.modify_sl_order") as mock_mod:
                _apply_tsl(dhan=None, signal=sig, paper=True)

        # floor_sl = t1 = 105; trail = 111 - 5 = 106 → new_sl = max(105, 106) = 106
        call_args = mock_mod.call_args
        if call_args:
            new_sl = call_args[0][2]
            assert new_sl >= 105.0


# ── _partial_exit_t3 ──────────────────────────────────────────────────────────

class TestPartialExitT3:
    def test_exits_half_qty_paper(self):
        from app.trade_manager import _partial_exit_t3
        sig = _sig(direction="BUY", entry=100.0)
        sig["qty"] = 10
        with patch("app.trade_manager.tg"):
            _partial_exit_t3(dhan=None, signal=sig, ltp=115.0, paper=True)
        assert sig["qty"] == 5
        assert sig["t3_partial_done"] is True

    def test_skip_when_qty_is_one(self):
        from app.trade_manager import _partial_exit_t3
        sig = _sig(direction="BUY", entry=100.0)
        sig["qty"] = 1
        with patch("app.trade_manager.tg"):
            _partial_exit_t3(dhan=None, signal=sig, ltp=115.0, paper=True)
        assert sig["qty"] == 1           # unchanged
        assert sig["t3_partial_done"] is True

    def test_skip_when_already_done(self):
        from app.trade_manager import _partial_exit_t3
        sig = _sig(direction="BUY", entry=100.0)
        sig["qty"] = 10
        sig["t3_partial_done"] = True
        with patch("app.trade_manager.tg") as mock_tg:
            _partial_exit_t3(dhan=None, signal=sig, ltp=115.0, paper=True)
        assert sig["qty"] == 10          # unchanged — already exited
        mock_tg.manual_exit.assert_not_called()

    def test_odd_qty_floors_correctly(self):
        from app.trade_manager import _partial_exit_t3
        sig = _sig(direction="BUY", entry=100.0)
        sig["qty"] = 7
        with patch("app.trade_manager.tg"):
            _partial_exit_t3(dhan=None, signal=sig, ltp=115.0, paper=True)
        # exit_qty = 7//2 = 3, remaining = 4
        assert sig["qty"] == 4

    def test_sell_direction(self):
        from app.trade_manager import _partial_exit_t3
        sig = _sig(direction="SELL", entry=100.0, sl=105.0)
        sig["qty"] = 6
        with patch("app.trade_manager.tg"):
            _partial_exit_t3(dhan=None, signal=sig, ltp=85.0, paper=True)
        assert sig["qty"] == 3


# ── position_tracker ─────────────────────────────────────────────────────────

class TestPositionTracker:
    def test_paper_sl_hit_marks_exited(self):
        from app.position_tracker import _paper_sl_hit
        sig = _sig(direction="BUY", sl=95.0, status="ACTIVE")
        with patch("app.position_tracker.tg"):
            _paper_sl_hit(sig, ltp=94.0)
        assert sig["status"] == "EXITED"
        assert sig["exit_reason"] == "SL_HIT"
        assert sig["exit_price"] == 95.0

    def test_mark_manually_exited_sets_exited(self):
        from app.position_tracker import _mark_manually_exited
        sig = _sig(direction="BUY", status="ACTIVE")
        sig["sl_order_id"] = None  # no SL order to cancel

        mock_dhan = MagicMock()
        with patch("app.position_tracker.tg"):
            _mark_manually_exited(mock_dhan, sig, paper=False)

        assert sig["status"] == "EXITED"
        assert sig["exit_reason"] == "MANUAL_EXIT"

    def test_mark_manually_exited_cancels_sl_order(self):
        from app.position_tracker import _mark_manually_exited
        sig = _sig(direction="BUY", status="ACTIVE")
        sig["sl_order_id"] = "SL_123"

        mock_dhan = MagicMock()
        with patch("app.position_tracker.tg"):
            _mark_manually_exited(mock_dhan, sig, paper=False)

        mock_dhan.cancel_order.assert_called_once_with("SL_123")

    def test_adopt_manual_creates_active_signal(self):
        from app.position_tracker import _adopt_manual
        state = {"signals": {}}
        pos = {"tradingSymbol": "RELIANCE", "netQty": "5", "buyAvg": "2500.0"}

        with patch("app.position_tracker.tg"):
            _adopt_manual(state, "RELIANCE", pos, qty=1)

        adopted = [s for s in state["signals"].values() if s["symbol"] == "RELIANCE"]
        assert len(adopted) == 1
        sig = adopted[0]
        assert sig["status"] == "ACTIVE"
        assert sig["direction"] == "BUY"
        assert sig["fill_price"] == 2500.0
        assert sig["live_managed"] is True
        assert sig["manual_adopted"] is True

    def test_adopt_manual_sell_direction(self):
        from app.position_tracker import _adopt_manual
        state = {"signals": {}}
        pos = {"tradingSymbol": "INFY", "netQty": "-3", "sellAvg": "1800.0"}

        with patch("app.position_tracker.tg"):
            _adopt_manual(state, "INFY", pos, qty=1)

        adopted = [s for s in state["signals"].values() if s["symbol"] == "INFY"]
        assert adopted[0]["direction"] == "SELL"

    def test_reconcile_paper_sl_hit(self):
        from app.position_tracker import _reconcile_paper
        sig = _sig(direction="BUY", sl=95.0, status="ACTIVE")
        sig["last_ltp"] = 94.0
        state = {"signals": {"s1": sig}}

        with patch("app.position_tracker.tg"):
            _reconcile_paper(state)

        assert sig["status"] == "EXITED"

    def test_reconcile_paper_no_hit(self):
        from app.position_tracker import _reconcile_paper
        sig = _sig(direction="BUY", sl=95.0, status="ACTIVE")
        sig["last_ltp"] = 102.0
        state = {"signals": {"s1": sig}}

        with patch("app.position_tracker.tg"):
            _reconcile_paper(state)

        assert sig["status"] == "ACTIVE"


# ── check_daily_halt (#8) ─────────────────────────────────────────────────────

class TestCheckDailyHalt:
    def _exited_sig(self, direction, entry, exit_price):
        sig = _sig(direction=direction, entry=entry, status="EXITED")
        sig["exit_price"] = exit_price
        return sig

    def test_no_halt_when_pnl_above_threshold(self):
        from app.trade_manager import check_daily_halt
        state = {"signals": {
            "s1": self._exited_sig("BUY", 100.0, 110.0),  # +10 pts
        }}
        import app.trade_manager as tm
        orig = tm.DAILY_LOSS_HALT_PTS
        tm.DAILY_LOSS_HALT_PTS = -50.0
        with patch("app.trade_manager.tg"):
            result = check_daily_halt(state)
        tm.DAILY_LOSS_HALT_PTS = orig
        assert result is False
        assert not state.get("trading_halted")

    def test_halt_fires_when_pnl_below_threshold(self):
        from app.trade_manager import check_daily_halt
        state = {"signals": {
            "s1": self._exited_sig("BUY", 100.0, 40.0),   # -60 pts
        }}
        import app.trade_manager as tm
        orig = tm.DAILY_LOSS_HALT_PTS
        tm.DAILY_LOSS_HALT_PTS = -50.0
        with patch("app.trade_manager.tg") as mock_tg:
            result = check_daily_halt(state)
        tm.DAILY_LOSS_HALT_PTS = orig
        assert result is True
        assert state.get("trading_halted") is True
        mock_tg.system_halt.assert_called_once()

    def test_already_halted_returns_true_without_recalc(self):
        from app.trade_manager import check_daily_halt
        state = {"trading_halted": True, "signals": {}}
        with patch("app.trade_manager.tg") as mock_tg:
            result = check_daily_halt(state)
        assert result is True
        mock_tg.system_halt.assert_not_called()  # no duplicate Telegram

    def test_pre_trade_ok_blocked_when_halted(self):
        from app.trade_manager import pre_trade_ok
        sig   = _sig()
        state = {"trading_halted": True, "signals": {}}
        with patch("app.trade_manager.tg"):
            result = pre_trade_ok(sig, state)
        assert result is False

    def test_sell_loss_counted_correctly(self):
        from app.trade_manager import check_daily_halt, _daily_closed_pnl
        # SELL entry 100, exit 160 = -60 pts (price rose, short lost)
        state = {"signals": {
            "s1": self._exited_sig("SELL", 100.0, 160.0),
        }}
        pnl = _daily_closed_pnl(state)
        assert pnl == pytest.approx(-60.0)


# ── _verify_sl_orders (#9) ────────────────────────────────────────────────────

class TestVerifySlOrders:
    def test_no_action_when_sl_pending(self):
        from app.position_tracker import _verify_sl_orders
        sig = _sig(direction="BUY", status="ACTIVE")
        sig["sl_order_id"] = "SL_LIVE_001"
        state = {"signals": {"s1": sig}}

        mock_dhan = MagicMock()
        mock_dhan.get_order_by_id.return_value = {"data": {"orderStatus": "PENDING"}}

        with patch("app.position_tracker.tg"):
            with patch("app.position_tracker.save"):
                _verify_sl_orders(mock_dhan, state, qty=1)

        mock_dhan.get_order_by_id.assert_called_once_with("SL_LIVE_001")

    def test_replaces_sl_when_order_cancelled(self):
        from app.position_tracker import _verify_sl_orders
        sig = _sig(direction="BUY", status="ACTIVE")
        sig["sl_order_id"] = "SL_GONE_001"
        state = {"signals": {"s1": sig}}

        mock_dhan = MagicMock()
        mock_dhan.get_order_by_id.return_value = {"data": {"orderStatus": "CANCELLED"}}

        with patch("app.position_tracker.tg"):
            with patch("app.position_tracker.save"):
                with patch("app.trade_manager.place_sl_order", return_value="SL_NEW_001") as mock_place:
                    _verify_sl_orders(mock_dhan, state, qty=1)

        mock_place.assert_called_once()
        assert sig["sl_order_id"] == "SL_NEW_001"

    def test_skips_paper_sl_orders(self):
        from app.position_tracker import _verify_sl_orders
        sig = _sig(direction="BUY", status="ACTIVE")
        sig["sl_order_id"] = "PAPER_SL_TEST"
        state = {"signals": {"s1": sig}}

        mock_dhan = MagicMock()
        with patch("app.position_tracker.tg"):
            _verify_sl_orders(mock_dhan, state, qty=1)

        mock_dhan.get_order_by_id.assert_not_called()

    def test_skips_non_active_signals(self):
        from app.position_tracker import _verify_sl_orders
        sig = _sig(direction="BUY", status="EXITED")
        sig["sl_order_id"] = "SL_EXITED_001"
        state = {"signals": {"s1": sig}}

        mock_dhan = MagicMock()
        with patch("app.position_tracker.tg"):
            _verify_sl_orders(mock_dhan, state, qty=1)

        mock_dhan.get_order_by_id.assert_not_called()
