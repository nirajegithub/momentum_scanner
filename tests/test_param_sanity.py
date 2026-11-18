"""Parameter sanity tests — read the live workflow file and assert all constraints
that would silently block signals if violated.

These tests exist to catch configuration mistakes like:
  - T1_RR < MIN_RR  → T1_RR_BELOW_MIN on every trade → 0 alerts all day (bug Nov-18-2026)
  - MAX_STOP < MIN_STOP → no stop distance is ever valid → 0 alerts
  - T2_RR <= T1_RR → target ordering is broken
  - DAILY_LOSS_HALT > 0 → halt fires immediately on first trade
  ...before they reach production.

The workflow file is the source of truth; SETTINGS in-process values are also
tested so both paths are covered.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "momentum-scan.yml"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_workflow_params() -> dict[str, str]:
    """Merge job-level env + scanner step env from the workflow YAML.

    Step-level env overrides job-level (same as GitHub Actions resolution).
    Returns a flat dict of all string values.
    """
    if not WORKFLOW_PATH.exists():
        pytest.skip(f"Workflow file not found: {WORKFLOW_PATH}")

    raw = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job = list(raw["jobs"].values())[0]  # first (only) job

    # Job-level env
    params = dict(job.get("env", {}))

    # Find the scanner step (the one that runs app.main)
    for step in job.get("steps", []):
        run = step.get("run", "")
        if "app.main" in run:
            params.update(step.get("env", {}))
            break

    # Coerce all values to strings (YAML may parse "1.5" as float)
    return {k: str(v) for k, v in params.items()}


def _f(params: dict, key: str, default: float) -> float:
    """Return float value for key, falling back to default."""
    val = params.get(key, str(default))
    # Strip GitHub Actions expression syntax if present
    if "${{" in str(val):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Workflow-file parameter tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkflowParams:
    """Read the live workflow YAML and assert all signal-blocking invariants."""

    @pytest.fixture(scope="class")
    def p(self):
        return _load_workflow_params()

    def test_workflow_file_exists(self):
        assert WORKFLOW_PATH.exists(), f"Workflow missing: {WORKFLOW_PATH}"

    def test_t1_rr_not_below_min_rr(self, p):
        """T1_RR < MIN_RR → T1_RR_BELOW_MIN on EVERY trade → 0 alerts all day.
        Root cause of the Nov-18-2026 outage.
        """
        t1 = _f(p, "T1_RR", 1.0)
        mn = _f(p, "MIN_RR", 1.0)
        assert t1 >= mn, (
            f"T1_RR={t1} < MIN_RR={mn}: build_risk_and_targets() will reject "
            f"every signal with T1_RR_BELOW_MIN → no alerts will fire"
        )

    def test_t2_rr_greater_than_t1_rr(self, p):
        t1 = _f(p, "T1_RR", 1.0)
        t2 = _f(p, "T2_RR", 2.0)
        assert t2 > t1, f"T2_RR={t2} must be > T1_RR={t1}"

    def test_t3_rr_greater_than_t2_rr(self, p):
        t2 = _f(p, "T2_RR", 2.0)
        t3 = _f(p, "T3_RR", 3.0)
        assert t3 > t2, f"T3_RR={t3} must be > T2_RR={t2}"

    def test_max_stop_greater_than_min_stop(self, p):
        """MAX_STOP <= MIN_STOP → no valid stop distance → 0 alerts."""
        mn = _f(p, "MIN_STOP_DISTANCE_PERCENT", 0.5)
        mx = _f(p, "MAX_STOP_DISTANCE_PERCENT", 2.0)
        assert mx > mn, (
            f"MAX_STOP_DISTANCE_PERCENT={mx} must be > MIN_STOP_DISTANCE_PERCENT={mn}"
        )

    def test_min_trade_score_not_above_max_trade_score(self, p):
        """MIN_TRADE_SCORE > MAX_TRADE_SCORE → every signal rejected."""
        mn = _f(p, "MIN_TRADE_SCORE", 3.0)
        mx = _f(p, "MAX_TRADE_SCORE", 7.0)
        assert mn <= mx, (
            f"MIN_TRADE_SCORE={mn} > MAX_TRADE_SCORE={mx}: no signal will pass score filter"
        )

    def test_daily_loss_halt_is_negative(self, p):
        """DAILY_LOSS_HALT_INR > 0 → halt fires on the very first profitable trade."""
        halt = _f(p, "DAILY_LOSS_HALT_INR", -400.0)
        assert halt < 0, (
            f"DAILY_LOSS_HALT_INR={halt} must be negative (it is a loss threshold)"
        )

    def test_max_open_positions_positive(self, p):
        mx = _f(p, "MAX_OPEN_POSITIONS", 12.0)
        assert mx >= 1, f"MAX_OPEN_POSITIONS={mx} must be >= 1"

    def test_min_price_positive(self, p):
        mn = _f(p, "MIN_PRICE", 450.0)
        assert mn > 0, f"MIN_PRICE={mn} must be positive"

    def test_scan_end_not_before_scan_start(self, p):
        start = _f(p, "SCAN_START_HHMM", 930.0)
        end = _f(p, "SCAN_END_HHMM", 1330.0)
        assert end > start, (
            f"SCAN_END_HHMM={end} must be after SCAN_START_HHMM={start}"
        )

    def test_buy_rsi_band_is_valid(self, p):
        lo = _f(p, "BUY_RSI_MIN", 50.0)
        hi = _f(p, "BUY_RSI_MAX", 100.0)
        assert lo < hi, f"BUY_RSI_MIN={lo} must be < BUY_RSI_MAX={hi}"
        assert 0 <= lo <= 100 and 0 <= hi <= 100, "RSI values must be in [0, 100]"

    def test_sell_rsi_band_is_valid(self, p):
        lo = _f(p, "SELL_RSI_MIN", 0.0)
        hi = _f(p, "SELL_RSI_MAX", 50.0)
        assert lo < hi, f"SELL_RSI_MIN={lo} must be < SELL_RSI_MAX={hi}"
        assert 0 <= lo <= 100 and 0 <= hi <= 100, "RSI values must be in [0, 100]"

    def test_min_rr_positive(self, p):
        mn = _f(p, "MIN_RR", 1.0)
        assert mn > 0, f"MIN_RR={mn} must be positive"

    def test_scan_workers_reasonable(self, p):
        w = _f(p, "SCAN_WORKERS", 3.0)
        assert 1 <= w <= 10, f"SCAN_WORKERS={w} should be between 1 and 10"


# ─────────────────────────────────────────────────────────────────────────────
# In-process SETTINGS tests (catches env-var overrides at import time)
# ─────────────────────────────────────────────────────────────────────────────

class TestSettingsInvariants:
    """Assert the same constraints on the SETTINGS object that is actually used
    by the running process.  Catches os.environ overrides that bypass the YAML.
    """

    @pytest.fixture(scope="class", autouse=True)
    def settings(self):
        from app.config import SETTINGS
        return SETTINGS

    def test_t1_rr_not_below_min_rr(self, settings):
        assert settings.t1_rr >= settings.min_rr, (
            f"SETTINGS: t1_rr={settings.t1_rr} < min_rr={settings.min_rr} "
            f"→ T1_RR_BELOW_MIN on every trade"
        )

    def test_t2_rr_greater_than_t1_rr(self, settings):
        assert settings.t2_rr > settings.t1_rr, (
            f"SETTINGS: t2_rr={settings.t2_rr} must be > t1_rr={settings.t1_rr}"
        )

    def test_t3_rr_greater_than_t2_rr(self, settings):
        assert settings.t3_rr > settings.t2_rr, (
            f"SETTINGS: t3_rr={settings.t3_rr} must be > t2_rr={settings.t2_rr}"
        )

    def test_max_stop_greater_than_min_stop(self, settings):
        assert settings.max_stop_distance_percent > settings.min_stop_distance_percent, (
            f"SETTINGS: max_stop={settings.max_stop_distance_percent} must be "
            f"> min_stop={settings.min_stop_distance_percent}"
        )

    def test_min_trade_score_not_above_max_trade_score(self, settings):
        assert settings.min_trade_score <= settings.max_trade_score, (
            f"SETTINGS: min_trade_score={settings.min_trade_score} > "
            f"max_trade_score={settings.max_trade_score}"
        )

    def test_min_rr_positive(self, settings):
        assert settings.min_rr > 0

    def test_max_open_positions_or_env_positive(self):
        mx = int(os.getenv("MAX_OPEN_POSITIONS", "1"))
        assert mx >= 1

    def test_daily_loss_halt_negative_or_unset(self):
        halt_str = os.getenv("DAILY_LOSS_HALT_INR")
        if halt_str is not None:
            assert float(halt_str) < 0, (
                f"DAILY_LOSS_HALT_INR={halt_str} must be negative"
            )
