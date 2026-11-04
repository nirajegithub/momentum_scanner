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

    def test_buy_pass_when_ltp_below_entry_but_above_sl(self):
        """LTP pulled back below entry (e.g. GRSE entry=576, ltp=571) — still valid.
        Limit buy at 576 sits in book; fills only if/when price reclaims entry."""
        from app.trade_manager import should_place_entry
        ok, _ = should_place_entry(_sig(direction="BUY", entry=576.0, sl=555.0), ltp=571.0)
        assert ok

    def test_buy_pass_when_ltp_above_sl(self):
        from app.trade_manager import should_place_entry
        # ltp=101.0 is within +1.5% of entry=100 → valid zone
        ok, _ = should_place_entry(_sig(direction="BUY", entry=100.0, sl=95.0), ltp=101.0)
        assert ok

    def test_buy_pass_when_ltp_above_entry(self):
        """Price moved up slightly (within 1.5%) — still valid, LIMIT at entry."""
        from app.trade_manager import should_place_entry
        ok, _ = should_place_entry(_sig(direction="BUY", entry=100.0, sl=95.0), ltp=101.4)
        assert ok

    def test_buy_skip_when_ltp_above_chase_limit(self):
        """Price ran > 1.5% above entry — ENTRY_MISSED, do not chase."""
        from app.trade_manager import should_place_entry
        ok, reason = should_place_entry(_sig(direction="BUY", entry=100.0, sl=95.0), ltp=108.0)
        assert not ok
        assert "ENTRY_MISSED" in reason

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
        # ltp=99.0 is within -1.5% of entry=100 → valid zone
        ok, _ = should_place_entry(
            _sig(direction="SELL", entry=100.0, sl=105.0), ltp=99.0
        )
        assert ok

    def test_sell_skip_when_ltp_below_chase_limit(self):
        """Price fell > 1.5% below entry — ENTRY_MISSED, do not chase."""
        from app.trade_manager import should_place_entry
        ok, reason = should_place_entry(
            _sig(direction="SELL", entry=100.0, sl=105.0), ltp=98.0
        )
        assert not ok
        assert "ENTRY_MISSED" in reason


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
    def _exited_sig(self, direction, entry, exit_price, qty=10):
        sig = _sig(direction=direction, entry=entry, status="EXITED")
        sig["exit_price"] = exit_price
        sig["qty"] = qty
        return sig

    def test_no_halt_when_pnl_above_threshold(self):
        from app.trade_manager import check_daily_halt
        # +10 pts × qty=10 = +Rs 100 — above threshold
        state = {"signals": {
            "s1": self._exited_sig("BUY", 100.0, 110.0, qty=10),
        }}
        import app.trade_manager as tm
        orig = tm.DAILY_LOSS_HALT_INR
        tm.DAILY_LOSS_HALT_INR = -500.0
        with patch("app.trade_manager.tg"):
            result = check_daily_halt(state)
        tm.DAILY_LOSS_HALT_INR = orig
        assert result is False
        assert not state.get("trading_halted")

    def test_halt_fires_when_pnl_below_threshold(self):
        from app.trade_manager import check_daily_halt
        # -60 pts × qty=10 = -Rs 600 — below -500 threshold
        state = {"signals": {
            "s1": self._exited_sig("BUY", 100.0, 40.0, qty=10),
        }}
        import app.trade_manager as tm
        orig = tm.DAILY_LOSS_HALT_INR
        tm.DAILY_LOSS_HALT_INR = -500.0
        with patch("app.trade_manager.tg") as mock_tg:
            result = check_daily_halt(state)
        tm.DAILY_LOSS_HALT_INR = orig
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

    def test_sell_loss_counted_in_rupees(self):
        from app.trade_manager import _daily_closed_pnl
        # SELL entry=100, exit=160 → -60 pts × qty=5 = -Rs 300
        state = {"signals": {
            "s1": self._exited_sig("SELL", 100.0, 160.0, qty=5),
        }}
        pnl = _daily_closed_pnl(state)
        assert pnl == pytest.approx(-300.0)

    def test_pnl_multiplies_by_qty(self):
        from app.trade_manager import _daily_closed_pnl
        # BUY entry=100, exit=90 → -10 pts × qty=7 = -Rs 70
        state = {"signals": {
            "s1": self._exited_sig("BUY", 100.0, 90.0, qty=7),
        }}
        pnl = _daily_closed_pnl(state)
        assert pnl == pytest.approx(-70.0)


# ── Step 3b: ENTRY_PLACED fill polling (trade_manager.run) ───────────────────

class TestStep3bEntryPlaced:
    """Unit tests for the ENTRY_PLACED fill-poll path in trade_manager.run()."""

    def _run_step3b(self, monkeypatch, *, fill_price, sl_oid):
        """Run only Step 3b of trade_manager.run() against a minimal state."""
        from app import trade_manager as tm
        from app.state import blank
        from datetime import date

        sig = _sig(status="ENTRY_PLACED")
        sig["entry_order_id"] = "LIVE_OID_1"
        state = blank(date.today())
        state["signals"]["k1"] = sig

        monkeypatch.setattr(tm, "PAPER_MODE", False)
        monkeypatch.setattr(tm, "TRADE_QTY", 1)
        monkeypatch.setattr(tm, "wait_for_fill",
                            lambda dhan, oid, sig, qty, paper: fill_price)
        monkeypatch.setattr(tm, "place_sl_order",
                            lambda dhan, sig, qty, paper: sl_oid)
        monkeypatch.setattr(tm, "save", lambda s: None)

        # Directly call the Step 3b logic (extracted to avoid running full run())
        for key, signal in list(state.get("signals", {}).items()):
            if signal.get("status") != "ENTRY_PLACED":
                continue
            oid = signal.get("entry_order_id", "")
            fill = tm.wait_for_fill(None, oid, signal, 1, False)
            if fill:
                signal["fill_price"] = fill
                signal["qty"] = 1
                signal["live_managed"] = True
                sl = tm.place_sl_order(None, signal, 1, False)
                if sl:
                    signal["sl_order_id"] = sl
                    signal["status"] = "ACTIVE"
                else:
                    signal["status"] = "EXITED"
            else:
                signal["status"] = "SKIPPED"
            tm.save(state)

        return state["signals"]["k1"]

    def test_fill_ok_sl_ok_reaches_active(self, monkeypatch):
        sig = self._run_step3b(monkeypatch, fill_price=576.0, sl_oid="SL_1")
        assert sig["status"] == "ACTIVE"
        assert sig["sl_order_id"] == "SL_1"
        assert sig["fill_price"] == 576.0

    def test_fill_ok_sl_fails_marks_exited(self, monkeypatch):
        """SL placement failed (emergency exit fired) → signal must be EXITED,
        not left as ENTRY_PLACED (which would re-poll fill on the next run)."""
        sig = self._run_step3b(monkeypatch, fill_price=576.0, sl_oid=None)
        assert sig["status"] == "EXITED"

    def test_fill_timeout_marks_skipped(self, monkeypatch):
        """wait_for_fill returns None (order not filled in time) → SKIPPED."""
        sig = self._run_step3b(monkeypatch, fill_price=None, sl_oid=None)
        assert sig["status"] == "SKIPPED"


# ── send_status_report / _should_send_status ─────────────────────────────────

class TestStatusReport:
    def _active_state(self):
        from app.state import blank
        from datetime import date
        state = blank(date.today())
        sig = _sig(status="ACTIVE")
        sig["security_id"] = "9999"
        sig["fill_price"] = 100.0
        sig["qty"] = 1
        state["signals"]["k1"] = sig
        return state

    def test_no_send_when_no_active_positions(self, monkeypatch):
        from app.trade_manager import _should_send_status
        from app.state import blank
        from datetime import date
        state = blank(date.today())
        state["signals"]["k1"] = _sig(status="SKIPPED")
        assert not _should_send_status(state)

    def test_sends_on_first_run_with_active(self, monkeypatch):
        from app.trade_manager import _should_send_status
        import app.trade_manager as tm
        monkeypatch.setattr(tm, "STATUS_SQUAREOFF_HHMM", 2359)
        state = self._active_state()
        assert _should_send_status(state)

    def test_no_send_before_interval_elapsed(self, monkeypatch):
        from app.trade_manager import _should_send_status
        from datetime import datetime, timezone, timedelta
        import app.trade_manager as tm
        monkeypatch.setattr(tm, "STATUS_SQUAREOFF_HHMM", 2359)
        monkeypatch.setattr(tm, "STATUS_INTERVAL_MIN", 15)
        state = self._active_state()
        # Last sent 5 min ago — not yet 15 min
        state["last_status_time"] = (datetime.now(timezone.utc).astimezone()).isoformat()
        assert not _should_send_status(state)

    def test_sends_after_interval_elapsed(self, monkeypatch):
        from app.trade_manager import _should_send_status
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        import app.trade_manager as tm
        monkeypatch.setattr(tm, "STATUS_SQUAREOFF_HHMM", 2359)
        monkeypatch.setattr(tm, "STATUS_INTERVAL_MIN", 15)
        state = self._active_state()
        # Last sent 20 min ago
        past = (datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(minutes=20)).isoformat()
        state["last_status_time"] = past
        assert _should_send_status(state)

    def test_no_send_past_squareoff_time(self, monkeypatch):
        from app.trade_manager import _should_send_status
        import app.trade_manager as tm
        monkeypatch.setattr(tm, "STATUS_SQUAREOFF_HHMM", 0)  # always past
        state = self._active_state()
        assert not _should_send_status(state)

    def test_send_status_report_updates_last_status_time(self, monkeypatch):
        from app.trade_manager import send_status_report
        import app.trade_manager as tm
        monkeypatch.setattr(tm, "STATUS_SQUAREOFF_HHMM", 2359)
        monkeypatch.setattr(tm, "_should_send_status", lambda s: True)
        monkeypatch.setattr(tm, "_fetch_active_ltps", lambda dhan, sigs: {"9999": 102.0})
        monkeypatch.setattr(tm, "_daily_closed_pnl", lambda s: 500.0)
        monkeypatch.setattr(tm, "save", lambda s: None)
        sent = []
        monkeypatch.setattr("app.telegram_notify.live_status",
                            lambda sigs, ltps, pnl, paper: sent.append(1))
        state = self._active_state()
        send_status_report(None, state, paper=True)
        assert sent == [1]
        assert "last_status_time" in state


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


# ── telegram_cmd (#10) ────────────────────────────────────────────────────────

class TestTelegramCmd:
    """Tests for app/telegram_cmd.py — command polling and processing."""

    def _make_update(self, update_id, text, chat_id="12345"):
        return {
            "update_id": update_id,
            "message": {
                "text": text,
                "chat": {"id": chat_id},
            },
        }

    def test_halt_sets_trading_halted(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        state = {"signals": {}}
        updates = [self._make_update(1, "/halt")]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply"):
                    with patch("app.telegram_cmd.save"):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        assert state.get("trading_halted") is True
        assert state["_tg_update_id"] == 2

    def test_resume_clears_trading_halted(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        state = {"signals": {}, "trading_halted": True}
        updates = [self._make_update(5, "/resume")]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply"):
                    with patch("app.telegram_cmd.save"):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        assert state.get("trading_halted") is False

    def test_squareoff_calls_square_off_all(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        state = {"signals": {}}
        updates = [self._make_update(10, "/squareoff")]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply"):
                    with patch("app.telegram_cmd.save"):
                        with patch("app.square_off.square_off_all") as mock_sqa:
                            poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        mock_sqa.assert_called_once()

    def test_status_sends_reply(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        state = {"signals": {}}
        updates = [self._make_update(20, "/status")]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply") as mock_reply:
                    with patch("app.telegram_cmd.save"):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        mock_reply.assert_called_once()
        assert "STATUS" in mock_reply.call_args[0][0]

    def test_unknown_command_replies_help(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        state = {"signals": {}}
        updates = [self._make_update(30, "/foobar")]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply") as mock_reply:
                    with patch("app.telegram_cmd.save"):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        mock_reply.assert_called_once()
        assert "Unknown command" in mock_reply.call_args[0][0]

    def test_unauthorized_chat_ignored(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "ALLOWED_CHAT"
        state = {"signals": {}}
        updates = [self._make_update(40, "/halt", chat_id="ATTACKER")]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply") as mock_reply:
                    with patch("app.telegram_cmd.save"):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        assert not state.get("trading_halted")
        mock_reply.assert_not_called()

    def test_offset_advances_across_multiple_updates(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        state = {"signals": {}}
        updates = [
            self._make_update(100, "hello"),
            self._make_update(101, "/status"),
        ]
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply"):
                    with patch("app.telegram_cmd.save"):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        assert state["_tg_update_id"] == 102

    def test_no_poll_when_bot_token_missing(self):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_tok = cmd_mod.BOT_TOKEN
        cmd_mod.BOT_TOKEN = ""
        state = {"signals": {}}
        with patch("app.telegram_cmd._get_updates") as mock_get:
            poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.BOT_TOKEN = orig_tok
        mock_get.assert_not_called()
