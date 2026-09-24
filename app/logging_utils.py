"""Enhanced logging utilities for momentum scanner."""

import logging
from dataclasses import dataclass
from typing import Optional

LOG = logging.getLogger(__name__)


@dataclass
class ScanStats:
    """Track scan statistics across all symbols."""
    total_symbols: int = 0
    skipped_indices: int = 0
    data_unavailable: int = 0
    orb_not_available: int = 0
    no_breakout: int = 0
    filter_rejected: int = 0
    setups_created: int = 0
    setups_confirmed: int = 0
    signals_generated: int = 0

    def print_summary(self):
        """Print scan summary statistics."""
        LOG.info("=" * 80)
        LOG.info("SCAN_SUMMARY | total_symbols=%d | skipped_indices=%d", self.total_symbols, self.skipped_indices)
        LOG.info("  Data Stage: unavailable=%d | orb_missing=%d",
                 self.data_unavailable, self.orb_not_available)
        LOG.info("  Breakout Stage: no_breakout=%d | filter_rejected=%d | setups=%d",
                 self.no_breakout, self.filter_rejected, self.setups_created)
        LOG.info("  Confirmation Stage: confirmed=%d | signals=%d",
                 self.setups_confirmed, self.signals_generated)
        LOG.info("=" * 80)


def log_data_check(symbol: str, available: bool, reason: Optional[str] = None):
    """Log data availability check."""
    if available:
        LOG.debug("%s | DATA_CHECK | status=OK", symbol)
    else:
        LOG.info("%s | DATA_CHECK | status=FAILED | reason=%s", symbol, reason or "UNKNOWN")


def log_orb_check(symbol: str, orb: Optional[dict]):
    """Log ORB detection."""
    if orb:
        LOG.info("%s | ORB_DETECTED | time=%s | high=%.2f | low=%.2f | close=%.2f",
                 symbol, orb["timestamp"][:16], orb["high"], orb["low"], orb["close"])
    else:
        LOG.info("%s | ORB_CHECK | status=NOT_FOUND", symbol)


def log_15m_candle_check(symbol: str, timestamp, close: float, orb_high: float,
                         orb_low: float, breakout_side: Optional[str]):
    """Log 15M candle breakout check."""
    if breakout_side:
        LOG.info("%s | 15M_CANDLE | time=%s | close=%.2f | breakout=%s",
                 symbol, str(timestamp)[:16], close, breakout_side)
    else:
        LOG.debug("%s | 15M_CANDLE | time=%s | close=%.2f | status=NO_BREAKOUT (in_range)",
                  symbol, str(timestamp)[:16], close)


def log_filter_rejection(symbol: str, stage: str, reason: str, **details):
    """Log when a stock is rejected at a filter stage."""
    msg = f"{symbol} | {stage} | REJECTED | reason={reason}"
    for key, val in details.items():
        if isinstance(val, float):
            msg += f" | {key}={val:.2f}"
        else:
            msg += f" | {key}={val}"
    LOG.info(msg)


def log_setup_created(symbol: str, direction: str, timestamp, rvol: float,
                      rsi: float, quality_score: float, early_surge: bool = False):
    """Log when a setup is created."""
    surge_marker = " | EARLY_MOMENTUM_SURGE=true" if early_surge else ""
    LOG.info("%s | SETUP_CREATED | direction=%s | time=%s | rvol=%.2f | rsi=%.2f | score=%.2f%s",
             symbol, direction, str(timestamp)[:16], rvol, rsi, quality_score, surge_marker)


def log_5m_confirmation_check(symbol: str, candle_time, close: float, threshold: float,
                               direction: str, confirmed: bool):
    """Log 5M confirmation candle check."""
    status = "CONFIRMED" if confirmed else "NO_CONFIRMATION"
    LOG.info("%s | 5M_CANDLE | time=%s | close=%.2f | threshold=%.2f | direction=%s | status=%s",
             symbol, str(candle_time)[:16], close, threshold, direction, status)


def log_signal_generated(symbol: str, direction: str, entry: float, sl: float,
                        t1: float, rvol: float, rsi: float, confirmation_time):
    """Log when a signal is generated."""
    LOG.info("%s | SIGNAL_GENERATED | direction=%s | entry=%.2f | sl=%.2f | t1=%.2f | "
             "rvol=%.2f | rsi=%.2f | time=%s",
             symbol, direction, entry, sl, t1, rvol, rsi, str(confirmation_time)[:16])


def log_filters_applied(symbol: str, side: str, filters: dict):
    """Log applied filters and their results."""
    msg = f"{symbol} | FILTERS_CHECK | direction={side}"
    passed = []
    failed = []

    for filter_name, result in filters.items():
        if result.get("passed"):
            passed.append(filter_name)
        else:
            failed.append(f"{filter_name}({result.get('reason', 'unknown')})")

    if passed:
        msg += f" | passed=[{', '.join(passed)}]"
    if failed:
        msg += f" | failed=[{', '.join(failed)}]"

    LOG.info(msg)


def log_risk_validation_failure(symbol: str, direction: str, entry: float, sl: float,
                                reason: str, **details):
    """Log risk/reward validation failure after 5M confirmation."""
    msg = f"{symbol} | RISK_VALIDATION_FAILED | direction={direction} | entry={entry:.2f} | sl={sl:.2f} | reason={reason}"
    for key, val in details.items():
        if isinstance(val, float):
            msg += f" | {key}={val:.2f}"
        else:
            msg += f" | {key}={val}"
    LOG.info(msg)


def log_t1_blocked(symbol: str, direction: str, entry: float, t1: float, current_close: float):
    """Log when T1 target is already blocked (price already passed it)."""
    LOG.info("%s | T1_BLOCKED | direction=%s | entry=%.2f | t1=%.2f | current_close=%.2f | reason=TARGET_ALREADY_REACHED",
             symbol, direction, entry, t1, current_close)


def log_telegram_failure(symbol: str, direction: str, reason: str, entry: float = None):
    """Log Telegram send failure."""
    if entry:
        LOG.warning("%s | TELEGRAM_SEND_FAILED | direction=%s | entry=%.2f | reason=%s",
                   symbol, direction, entry, reason)
    else:
        LOG.warning("%s | TELEGRAM_SEND_FAILED | direction=%s | reason=%s",
                   symbol, direction, reason)


def log_confirmed_rejection(symbol: str, direction: str, confirmation_time, reason: str, **details):
    """Log rejection after 5M confirmation (catchall for other rejections)."""
    msg = f"{symbol} | CONFIRMED_BUT_REJECTED | direction={direction} | time={str(confirmation_time)[:16]} | reason={reason}"
    for key, val in details.items():
        if isinstance(val, float):
            msg += f" | {key}={val:.2f}"
        else:
            msg += f" | {key}={val}"
    LOG.info(msg)
