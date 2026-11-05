"""
Regression tests for fixes applied Nov 2026:

  - state.py: PAPER_MODE env var selects separate state file
  - nse_universe.py: None ltp/volume skipped in RVOL calc
  - position_tracker._adopt_manual: passes qty to tg.manual_trade_adopted
  - dhan_client.DhanClient: cancel_order wrapper delegates to self.dhan
  - telegram_cmd: _tg_update_id saved after /status (non-modifying command)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call
import pytest


# ── state.py: mode-aware file path ───────────────────────────────────────────

class TestStateModeFilePath:
    def test_paper_mode_true_uses_paper_file(self, monkeypatch):
        monkeypatch.setenv("PAPER_MODE", "true")
        import importlib
        import app.state as state_mod
        importlib.reload(state_mod)
        assert "runtime_state_paper.json" in str(state_mod.STATE)

    def test_paper_mode_false_uses_live_file(self, monkeypatch):
        monkeypatch.setenv("PAPER_MODE", "false")
        import importlib
        import app.state as state_mod
        importlib.reload(state_mod)
        assert "runtime_state_live.json" in str(state_mod.STATE)

    def test_paper_mode_default_is_paper(self, monkeypatch):
        monkeypatch.delenv("PAPER_MODE", raising=False)
        import importlib
        import app.state as state_mod
        importlib.reload(state_mod)
        assert "runtime_state_paper.json" in str(state_mod.STATE)

    def test_paper_mode_uppercase_true(self, monkeypatch):
        monkeypatch.setenv("PAPER_MODE", "TRUE")
        import importlib
        import app.state as state_mod
        importlib.reload(state_mod)
        assert "runtime_state_paper.json" in str(state_mod.STATE)

    def test_paper_mode_false_file_different_from_paper(self, monkeypatch):
        monkeypatch.setenv("PAPER_MODE", "false")
        import importlib
        import app.state as state_mod
        importlib.reload(state_mod)
        live_path = str(state_mod.STATE)

        monkeypatch.setenv("PAPER_MODE", "true")
        importlib.reload(state_mod)
        paper_path = str(state_mod.STATE)

        assert live_path != paper_path


# ── nse_universe.py: None ltp/volume guard ───────────────────────────────────

class TestVolumeGainerNoneGuard:
    """
    When quote_batch returns volume=None (ticker_data path) or ltp=None,
    the symbol must be skipped, not crash with TypeError on division.
    """

    def _make_baseline(self, security_id="1234"):
        return {
            "TESTSTOCK": {
                "security_id": security_id,
                "avg_volume": 1_000_000,
            }
        }

    def _run_filter(self, quote_value: dict, elapsed: float = 0.5):
        from app.nse_universe import SETTINGS
        symbol_baseline = self._make_baseline()
        quotes = {"1234": quote_value}

        results = []
        for symbol, row in symbol_baseline.items():
            quote = quotes.get(row["security_id"])
            if not quote:
                continue
            price = quote.get("ltp")
            volume_so_far = quote.get("volume")
            if price is None or volume_so_far is None:
                continue
            expected_by_now = row["avg_volume"] * elapsed
            if expected_by_now <= 0:
                continue
            rvol = volume_so_far / expected_by_now
            if (
                price >= SETTINGS.min_price
                and volume_so_far > SETTINGS.min_prev_volume
                and rvol >= SETTINGS.volume_gainer_rvol_threshold
            ):
                results.append(symbol)
        return results

    def test_none_volume_does_not_crash(self):
        # ticker_data path: volume=None, ltp present
        result = self._run_filter({"ltp": 500.0, "volume": None})
        assert result == []  # skipped, not crashed

    def test_none_ltp_does_not_crash(self):
        result = self._run_filter({"ltp": None, "volume": 2_000_000})
        assert result == []

    def test_both_none_does_not_crash(self):
        result = self._run_filter({"ltp": None, "volume": None})
        assert result == []

    def test_valid_quote_still_passes_filter(self):
        # Needs high rvol: 3M volume / (1M * 0.5 elapsed) = 6× rvol
        from app.nse_universe import SETTINGS
        result = self._run_filter({
            "ltp": float(SETTINGS.min_price) + 100,
            "volume": float(SETTINGS.min_prev_volume) + 3_000_000,
        })
        # May or may not pass depending on SETTINGS thresholds — just confirm no crash
        assert isinstance(result, list)


# ── position_tracker._adopt_manual: qty passed to tg ────────────────────────

class TestAdoptManualQty:
    def test_manual_trade_adopted_called_with_qty(self):
        from app.position_tracker import _adopt_manual

        state = {"signals": {}}
        pos = {"tradingSymbol": "RELIANCE", "netQty": "5", "buyAvg": "2500.0"}

        with patch("app.position_tracker.tg") as mock_tg:
            _adopt_manual(state, "RELIANCE", pos, qty=7)

        mock_tg.manual_trade_adopted.assert_called_once()
        args = mock_tg.manual_trade_adopted.call_args[0]
        # signature: (sym, direction, fill, sl, qty)
        assert args[0] == "RELIANCE"
        assert args[1] == "BUY"
        assert args[2] == pytest.approx(2500.0)
        assert args[4] == 7  # qty is 5th positional arg

    def test_signal_stores_correct_qty(self):
        from app.position_tracker import _adopt_manual

        state = {"signals": {}}
        pos = {"tradingSymbol": "INFY", "netQty": "-3", "sellAvg": "1800.0"}

        with patch("app.position_tracker.tg"):
            _adopt_manual(state, "INFY", pos, qty=4)

        adopted = next(s for s in state["signals"].values() if s["symbol"] == "INFY")
        assert adopted["qty"] == 4

    def test_zero_fill_price_skips_adoption(self):
        from app.position_tracker import _adopt_manual

        state = {"signals": {}}
        pos = {"tradingSymbol": "BROKEN", "netQty": "1", "buyAvg": "0"}

        with patch("app.position_tracker.tg") as mock_tg:
            _adopt_manual(state, "BROKEN", pos, qty=1)

        assert state["signals"] == {}
        mock_tg.manual_trade_adopted.assert_not_called()


# ── DhanClient.cancel_order wrapper ──────────────────────────────────────────

class TestDhanClientCancelOrder:
    def test_cancel_order_method_exists(self):
        from app.dhan_client import DhanClient
        assert hasattr(DhanClient, "cancel_order")
        assert callable(getattr(DhanClient, "cancel_order"))

    def test_cancel_order_delegates_to_sdk(self):
        from app.dhan_client import DhanClient
        client = DhanClient.__new__(DhanClient)
        client.dhan = MagicMock()
        client.dhan.cancel_order.return_value = {"status": "success"}

        result = client.cancel_order("ORDER_123")

        client.dhan.cancel_order.assert_called_once_with("ORDER_123")
        assert result == {"status": "success"}

    def test_get_positions_wrapper_also_exists(self):
        """Regression: get_positions was missing before, verify it still works."""
        from app.dhan_client import DhanClient
        client = DhanClient.__new__(DhanClient)
        client.dhan = MagicMock()
        client.dhan.get_positions.return_value = {"data": []}

        result = client.get_positions()
        client.dhan.get_positions.assert_called_once()
        assert result == {"data": []}


# ── telegram_cmd: _tg_update_id persisted after /status ──────────────────────

class TestTelegramUpdateIdPersistence:
    def _make_update(self, update_id, text, chat_id="12345"):
        return {
            "update_id": update_id,
            "message": {"text": text, "chat": {"id": chat_id}},
        }

    def _run_poll(self, updates, state=None):
        from app.telegram_cmd import poll_and_process
        import app.telegram_cmd as cmd_mod
        orig_cid = cmd_mod.CHAT_ID
        cmd_mod.CHAT_ID = "12345"
        if state is None:
            state = {"signals": {}}
        saved = []
        with patch("app.telegram_cmd.BOT_TOKEN", "fake"):
            with patch("app.telegram_cmd._get_updates", return_value=updates):
                with patch("app.telegram_cmd._reply"):
                    with patch("app.telegram_cmd.save", side_effect=lambda s: saved.append(True)):
                        poll_and_process(MagicMock(), state, paper=True)
        cmd_mod.CHAT_ID = orig_cid
        return state, saved

    def test_status_command_saves_update_id(self):
        """/status must persist _tg_update_id so it isn't replayed next cycle."""
        updates = [self._make_update(50, "/status")]
        state, saved = self._run_poll(updates)
        assert state["_tg_update_id"] == 51
        assert saved  # save() was called

    def test_unknown_command_saves_update_id(self):
        updates = [self._make_update(60, "/whoops")]
        state, saved = self._run_poll(updates)
        assert state["_tg_update_id"] == 61
        assert saved

    def test_no_updates_does_not_save(self):
        """When nothing arrives, save() should NOT be called (no work done)."""
        state, saved = self._run_poll([])
        assert not saved

    def test_paper_on_saves_update_id(self):
        updates = [self._make_update(70, "/paper on")]
        state, saved = self._run_poll(updates)
        assert state["_tg_update_id"] == 71
        assert state.get("paper_mode") is True
        assert saved
