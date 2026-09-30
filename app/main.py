from __future__ import annotations

import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .calendar import is_nse_trading_day, previous_trading_day
from .config import SETTINGS
from .dhan_client import DhanClient
from .indicators import add_indicators
from .nse_universe import build_universe, refresh_dynamic_volume_gainers
from .risk import build_risk_and_targets
from .state import load, save, record_alert
from .strategy import evaluate_b1_breakout, t1_blocked, momentum_surge_qualifies, market_trend_aligned
from .candle_utils import completed_candles
from .telegram import send, signal_message
from .summary import build_summary
from .logging_utils import ScanStats, log_orb_check, log_15m_candle_check, log_setup_created, log_5m_confirmation_check, log_signal_generated, log_risk_validation_failure, log_t1_blocked, log_telegram_failure, log_confirmed_rejection
from .state import backup_and_clear
from .orb_manager import get_orb_with_fallback
from .orb_tracker import log_orb_used, log_orb_selection
from .signal_monitor import monitor_active_signals

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)
ORB_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)

# NSE indices that don't have intraday data in Dhan API
INDICES_TO_SKIP = {
    "NIFTY50", "NIFTYIT", "NIFTY100", "NIFTYAUTO", "NIFTYCONSTRUCTION",
    "NIFTYINFRA", "NIFTYENERGY", "NIFTYHEALTHCARE", "NIFTYFMCG", "NIFTYMEDIA",
    "NIFTYPHARM", "NIFTYTECH", "NIFTYREALTY", "NIFTYBANK", "NIFTYFINANCE",
    "NIFTYPSE", "NIFTYPSURVEY", "NIFTYSERV", "NIFTYTOTAL", "NIFTYCONSUM",
}


def _now_ist():
    return datetime.now(IST)


def _as_ist_index(df):
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    x.index = pd.to_datetime(x.index)
    if x.index.tz is None:
        x.index = x.index.tz_localize(IST)
    else:
        x.index = x.index.tz_convert(IST)
    return x.sort_index()


def _hhmm(ts):
    t = pd.Timestamp(ts).tz_convert(IST).time()
    return t.hour * 100 + t.minute


def _scan_window(ts):
    hhmm = _hhmm(ts)
    return SETTINGS.scan_start_hhmm <= hhmm <= SETTINGS.scan_end_hhmm


def _is_market_close(ts):
    """Check if we're at or past market close time (15:30 IST)."""
    t = ts.time()
    return t >= MARKET_CLOSE_TIME


def _orb_for_day(df15, trading_day):
    x = _as_ist_index(df15)
    x = x[(x.index.date == trading_day) & (x.index.strftime("%H:%M") == "09:15")]
    if x.empty:
        return None
    r = x.iloc[0]
    return {
        "timestamp": x.index[0].isoformat(),
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
    }


def _state_for_symbol(state, symbol):
    state.setdefault("b1", {})
    state["b1"].setdefault(symbol, {})
    s = state["b1"][symbol]
    s.setdefault("status", "WAITING")
    s.setdefault("last_processed_5m", None)
    s.setdefault("orb", None)
    return s


def _daily_values(dhan, item, trading_day):
    close = item.get("prev_close")
    volume = item.get("prev_volume")
    if close is not None and volume is not None:
        return float(close), float(volume)

    prev_day = previous_trading_day(trading_day)
    df = dhan.historical_daily_df(
        security_id=item["security_id"],
        from_date=prev_day.isoformat(),
        to_date=(prev_day + pd.Timedelta(days=1)).isoformat(),
    )
    if df is None or df.empty:
        raise RuntimeError(f"{item['symbol']}: no previous-day daily data")
    x = _as_ist_index(df)
    rows = x[x.index.date == prev_day]
    if rows.empty:
        raise RuntimeError(f"{item['symbol']}: no candle for {prev_day}")
    row = rows.iloc[-1]
    return float(row["close"]), float(row["volume"])


def _prepare_15m(dhan, security_id, ts):
    trading_day = pd.Timestamp(ts).date()
    lookback_start = previous_trading_day(trading_day)
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=15,
        from_date=lookback_start.isoformat(),
        to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
        retry_on_empty=True,
        max_retries=6,
        retry_delay_seconds=5.0,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    x = completed_candles(raw, ts, 15)
    return add_indicators(x, rvol_lookback=SETTINGS.rvol_lookback)


def _prepare_5m(dhan, security_id, ts):
    trading_day = pd.Timestamp(ts).date()
    # Fetch from previous trading day so RVOL rolling window has enough prior candles.
    lookback_start = previous_trading_day(trading_day)
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=5,
        from_date=lookback_start.isoformat(),
        to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
        retry_on_empty=True,
        max_retries=6,
        retry_delay_seconds=5.0,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    x = completed_candles(raw, ts, 5)
    return add_indicators(x, rvol_lookback=SETTINGS.rvol_lookback)


def _build_confirmed_signal(item, setup, confirmation_ts, confirmation_close, orb):
    """Build a trade only after a completed 5M confirmation candle."""
    direction = setup["direction"]
    entry = float(confirmation_close)
    # SL is the ORB Low (for BUY) or ORB High (for SELL)
    sl = float(orb["low"]) if direction == "BUY" else float(orb["high"])

    risk, reject = build_risk_and_targets(
        direction=direction,
        entry=entry,
        sl=sl,
        min_stop_distance_percent=SETTINGS.min_stop_distance_percent,
        t1_rr=SETTINGS.t1_rr,
        t2_rr=SETTINGS.t2_rr,
        t3_rr=SETTINGS.t3_rr,
        min_rr=SETTINGS.min_rr,
    )
    if risk is None:
        return None, reject or "RISK_REJECTED"

    confirmation_timestamp = pd.Timestamp(confirmation_ts)
    setup_completion = pd.Timestamp(setup["setup_15m_completion"])
    lag_minutes = (confirmation_timestamp - setup_completion).total_seconds() / 60.0
    lag_5m_candles = round(lag_minutes / SETTINGS.entry_timeframe) if SETTINGS.entry_timeframe else None

    signal = {
        "symbol": item["symbol"],
        "security_id": item["security_id"],
        **setup,
        "orb_timestamp": orb["timestamp"],
        "orb_high": orb["high"],
        "orb_low": orb["low"],
        "orb_close": orb["close"],
        "setup_15m_timestamp": setup["setup_15m_timestamp"],
        "setup_15m_completion": setup["setup_15m_completion"],
        "confirmation_5m_timestamp": confirmation_timestamp.isoformat(),
        "confirmation_5m_close": entry,
        "confirmation_lag_minutes": round(lag_minutes, 1),
        "confirmation_lag_5m_candles": lag_5m_candles,
        "status": "ACTIVE",
    }
    signal["risk"] = risk
    signal["entry"] = risk["entry"]
    signal["sl"] = risk["sl"]
    signal["t1"] = risk["t1"]
    signal["t2"] = risk["t2"]
    signal["t3"] = risk["t3"]

    return signal, None


def _confirmation_5m(dhan, security_id, setup_completion, now_ts):
    """Return the first completed 5M candle after setup that confirms B1."""
    setup_date = pd.Timestamp(setup_completion).date()
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=5,
        from_date=setup_date.isoformat(),
        to_date=(setup_date + pd.Timedelta(days=1)).isoformat(),
    )
    if raw is None or raw.empty:
        return None, pd.DataFrame()

    df5 = completed_candles(raw, now_ts, 5)
    if df5.empty:
        return None, df5
    df5 = add_indicators(df5, rvol_lookback=SETTINGS.rvol_lookback)
    df5 = _as_ist_index(df5)
    setup_ts = pd.Timestamp(setup_completion)
    rows = df5[df5.index > setup_ts]
    return rows, df5


def _process_b1(dhan, state, ts):
    trading_day = ts.date()

    # SAMPLING MODE: Test with subset of symbols to diagnose API rate-limiting
    universe = state.get("universe", [])
    if os.getenv("SAMPLE_SYMBOLS"):
        sample_list = os.getenv("SAMPLE_SYMBOLS").split(",")
        universe = [item for item in universe if item.get("symbol") in sample_list]
        LOG.info("SAMPLING_MODE | testing %d/%d symbols: %s",
                 len(universe), len(state.get("universe", [])), sample_list)

    stats = ScanStats(total_symbols=len(state.get("universe", [])))

    b1_state = state.get("b1", {})
    orb_cached_count = sum(
        1 for ss in b1_state.values()
        if (ss.get("orb") or {}).get("timestamp", "")[:10] == trading_day.isoformat()
    )
    LOG.info(
        "UNIVERSE | total=%d | orb_cached=%d | orb_pending=%d",
        len(universe), orb_cached_count, len(universe) - orb_cached_count,
    )

    for item in universe:
        symbol = item.get("symbol")
        if not symbol or item.get("security_id") is None:
            continue

        if symbol in INDICES_TO_SKIP:
            stats.skipped_indices += 1
            continue

        ss = _state_for_symbol(state, symbol)

        try:
            df5 = _prepare_5m(dhan, item["security_id"], ts)
            if df5.empty:
                LOG.info("%s | DATA_STAGE | status=5M_DATA_UNAVAILABLE", symbol)
                stats.data_unavailable += 1
                continue

            day5 = df5[df5.index.date == trading_day]

            # Use cached ORB from state if already fetched today; otherwise fetch from API.
            cached_orb = ss.get("orb")
            cached_orb_date = (cached_orb or {}).get("date") or (
                str((cached_orb or {}).get("timestamp", ""))[:10]
            )
            if cached_orb and cached_orb_date == trading_day.isoformat():
                orb = cached_orb
                orb_source = ss.get("orb_source", "CACHED")
            else:
                orb, orb_source = get_orb_with_fallback(dhan, item["security_id"], trading_day)
                if orb is None:
                    LOG.info("%s | DATA_STAGE | status=ORB_NOT_AVAILABLE", symbol)
                    stats.orb_not_available += 1
                    continue
                log_orb_selection(symbol, trading_day, previous_trading_day(trading_day), orb_source)
                ss["orb"] = orb
                ss["orb_source"] = orb_source
                ss["status"] = "WAITING_FOR_5M"
                ss["last_processed_5m"] = None
                ss["setup"] = None
                log_orb_check(symbol, orb)

            # Once an alert is active, do not create another setup for the symbol.
            if ss.get("status") == "CONSUMED":
                continue

            # Scan each new completed 5M candle for ORB breakout.
            # On confirmation, apply filters and send signal immediately (entry = 5M close).
            candidates = day5[day5.index > pd.Timestamp(orb["timestamp"])].sort_index()
            last_processed = ss.get("last_processed_5m")
            if last_processed:
                candidates = candidates[candidates.index > pd.Timestamp(last_processed)]

            for setup_ts, row5 in candidates.iterrows():
                ss["last_processed_5m"] = setup_ts.isoformat()
                close5 = float(row5["close"])
                if close5 > orb["high"]:
                    side = "BUY"
                elif close5 < orb["low"]:
                    side = "SELL"
                else:
                    log_15m_candle_check(symbol, setup_ts, close5, orb["high"], orb["low"], None)
                    stats.no_breakout += 1
                    continue

                log_orb_used(symbol, orb, ss.get("orb_source", "UNKNOWN"), close5, side)
                log_15m_candle_check(symbol, setup_ts, close5, orb["high"], orb["low"], side)

                try:
                    daily_close, daily_volume = _daily_values(dhan, item, trading_day)
                except Exception as exc:
                    LOG.warning("B1_5M | symbol=%s | status=DATA_UNAVAILABLE | reason=%s", symbol, exc)
                    # Rewind so this candle is retried next scan cycle.
                    ss["last_processed_5m"] = (setup_ts - pd.Timedelta(minutes=5)).isoformat()
                    break

                candidate = evaluate_b1_breakout(day5.loc[:setup_ts], orb, daily_close, daily_volume, symbol=symbol)
                if candidate is None:
                    stats.filter_rejected += 1
                    continue

                setup = dict(candidate)
                setup["direction"] = side
                # setup_15m_* keys kept for Telegram/signal compatibility; values are from the 5M candle.
                setup["setup_15m_timestamp"] = setup_ts.isoformat()
                setup["setup_15m_completion"] = (setup_ts + pd.Timedelta(minutes=5)).isoformat()

                trend_aligned = market_trend_aligned(None, side)
                setup["market_trend_aligned"] = trend_aligned
                if not trend_aligned:
                    LOG.info("%s | BREAKOUT_STAGE | status=MARKET_TREND_REJECTED | direction=%s", symbol, side)
                    stats.filter_rejected += 1
                    continue

                # Build signal; entry = close of confirming 5M candle (≈ open of next candle).
                signal, reject = _build_confirmed_signal(item, setup, setup_ts, close5, orb)
                if signal is None:
                    log_confirmed_rejection(symbol, side, setup_ts, reject,
                                            sl=float(orb["low"]) if side == "BUY" else float(orb["high"]),
                                            entry=close5)
                    ss["status"] = "CONSUMED"
                    break

                try:
                    if t1_blocked(df5, setup_ts, signal["risk"]["entry"], signal["risk"]["t1"], side):
                        log_t1_blocked(symbol, side, signal["risk"]["entry"], signal["risk"]["t1"], close5)
                        ss["status"] = "CONSUMED"
                        break
                except Exception as exc:
                    LOG.warning("%s T1 block check failed; continuing | %s", symbol, exc)

                sent = send(signal_message(signal))
                if sent:
                    record_alert(state, signal, ts)
                    signal_key = f"{symbol}|{side}|{setup['setup_15m_timestamp']}|{signal['confirmation_5m_timestamp']}"
                    state.setdefault("signals", {})[signal_key] = signal
                    ss["status"] = "CONSUMED"
                    ss["setup"] = None
                    ss["confirmation_5m_timestamp"] = signal["confirmation_5m_timestamp"]

                    rvol = float(setup.get("setup_15m_rvol", 0))
                    rsi = float(setup.get("setup_15m_rsi14", 0))
                    log_signal_generated(symbol, side, signal["entry"], signal["sl"],
                                        signal["t1"], rvol, rsi, signal["confirmation_5m_timestamp"])
                    stats.signals_generated += 1
                else:
                    log_telegram_failure(symbol, side, "SEND_FAILED", signal["entry"])
                break

        except Exception as exc:
            LOG.exception("%s | B1_PROCESSING_FAILED | error=%s", symbol, exc)

    save(state)
    stats.setups_confirmed = len(state.get("signals", {}))
    stats.print_summary()


def create_universe(dhan, state):
    if state.get("universe"):
        LOG.info("CREATE_UNIVERSE SKIPPED | size=%d", len(state["universe"]))
        return False
    state["universe"] = build_universe(dhan)
    save(state)
    LOG.info("FINAL UNIVERSE: %d symbols", len(state["universe"]))
    return True


def refresh_universe(dhan, state, ts):
    before = len(state.get("universe", []))
    existing_ids = {str(x.get("security_id")) for x in state.get("universe", []) if x.get("security_id") is not None}
    existing_symbols = {str(x.get("symbol", "")).upper() for x in state.get("universe", [])}

    static_candidates = build_universe(dhan)
    static_added = 0
    for item in static_candidates:
        sid = item.get("security_id")
        symbol = str(item.get("symbol", "")).upper()
        if sid is not None and str(sid) in existing_ids:
            continue
        if symbol and symbol in existing_symbols:
            continue
        state.setdefault("universe", []).append(item)
        if sid is not None:
            existing_ids.add(str(sid))
        if symbol:
            existing_symbols.add(symbol)
        static_added += 1

    dynamic_before = len(state.get("universe", []))
    dynamic_changed = refresh_dynamic_volume_gainers(dhan, state, ts)
    dynamic_added = len(state.get("universe", [])) - dynamic_before
    save(state)
    LOG.info(
        "UNIVERSE_REFRESH | before=%d | static_candidates=%d | static_added=%d | dynamic_changed=%s | dynamic_added=%d | total=%d",
        before, len(static_candidates), static_added, dynamic_changed, dynamic_added, len(state.get("universe", [])),
    )
    return True


def _fetch_current_prices(dhan, state):
    """Fetch current LTP for all active signals.

    Uses security_id from signals directly so this works even after
    backup_and_clear has blanked state["universe"].
    """
    current_prices = {}
    for signal in state.get("signals", {}).values():
        symbol = signal.get("symbol")
        security_id = signal.get("security_id")
        if not symbol or security_id is None:
            continue
        if symbol in current_prices:
            continue
        try:
            quotes = dhan.quotes(security_id=security_id)
            if quotes and quotes.get("ltp"):
                current_prices[symbol] = float(quotes["ltp"])
        except Exception as exc:
            LOG.debug("Failed to fetch current price for %s: %s", symbol, exc)
    return current_prices


def _send_daily_summary(dhan, state, ts):
    """Send daily summary comparing each signal's entry vs current LTP."""
    # Fetch current LTP for all universe symbols so P&L reflects today's close price.
    final_prices = _fetch_current_prices(dhan, state)

    summary_text = build_summary(state, final_prices)
    LOG.info("SUMMARY\n%s", summary_text)

    sent = send(summary_text)
    if sent:
        LOG.info("DAILY_SUMMARY_SENT | symbols=%d | text_len=%d", len(final_prices), len(summary_text))
    else:
        LOG.warning("DAILY_SUMMARY_FAILED | symbols=%d", len(final_prices))


def main():
    class ISTFormatter(logging.Formatter):
        """Custom formatter that converts UTC times to IST."""
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=IST)
            if datefmt:
                return dt.strftime(datefmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S IST")

    handler = logging.StreamHandler()
    handler.setFormatter(ISTFormatter(fmt="%(asctime)s | %(levelname)s | %(message)s"))
    logging.root.addHandler(handler)
    logging.root.setLevel(os.getenv("LOG_LEVEL", "INFO"))

    ts = _now_ist()
    if not is_nse_trading_day(ts.date()):
        LOG.info("Not an NSE trading day")
        return

    dhan = DhanClient()
    action = os.getenv("SCANNER_ACTION", "scan").strip().lower()
    state = load(ts.date())

    if action == "universe":
        create_universe(dhan, state)
        return
    if action == "universe_refresh":
        if not state.get("universe"):
            create_universe(dhan, state)
        else:
            refresh_universe(dhan, state, ts)
        return
    if action == "summary":
        _send_daily_summary(dhan, state, ts)
        return
    if action != "scan":
        LOG.info("Unknown SCANNER_ACTION=%s", action)
        return

    if not state.get("universe"):
        LOG.warning(
            "Universe is empty — skipping this scan cycle. Waiting for the "
            "dedicated universe/universe_refresh workflow to populate it "
            "(scan no longer rebuilds the universe itself, to avoid two "
            "workflows hammering Dhan concurrently)."
        )
        return

    if not _scan_window(ts):
        LOG.info("Outside scan window | now=%s | window=%s-%s", ts.strftime("%H:%M"), SETTINGS.scan_start_hhmm, SETTINGS.scan_end_hhmm)
        return

    try:
        if refresh_dynamic_volume_gainers(dhan, state, ts):
            save(state)
    except Exception as exc:
        LOG.warning("Dynamic universe refresh failed | %s", exc)

    # Clear any previous day's signals/setups to start fresh each trading day
    current_date = ts.date()
    cleared_signals = {}
    cleared_setups = {}

    for key, signal in state.get("signals", {}).items():
        signal_date = pd.Timestamp(signal.get("confirmation_5m_timestamp", signal.get("setup_15m_timestamp", ""))).date()
        if signal_date == current_date:
            cleared_signals[key] = signal

    for symbol, setup in state.get("pending_setups", {}).items():
        setup_date = pd.Timestamp(setup.get("setup_15m_timestamp", "")).date()
        if setup_date == current_date:
            cleared_setups[symbol] = setup

    if len(cleared_signals) < len(state.get("signals", {})) or len(cleared_setups) < len(state.get("pending_setups", {})):
        old_signal_count = len(state.get("signals", {}))
        old_setup_count = len(state.get("pending_setups", {}))
        state["signals"] = cleared_signals
        state["pending_setups"] = cleared_setups
        LOG.info("Cleared previous day entries | signals: %d -> %d | setups: %d -> %d",
                old_signal_count, len(cleared_signals), old_setup_count, len(cleared_setups))
        save(state)

    # Remove b1 entries whose ORB is from a previous trading day. Symbols that
    # leave the universe mid-week accumulate stale state; clear it each morning
    # so only today's scan results persist.
    b1 = state.get("b1", {})
    stale_b1 = [
        sym for sym, ss in b1.items()
        if pd.Timestamp(ss.get("orb", {}).get("timestamp", "1970-01-01")).date() != current_date
    ]
    if stale_b1:
        for sym in stale_b1:
            del b1[sym]
        LOG.info("Cleared stale b1 entries | count=%d", len(stale_b1))
        save(state)

    # Monitor active signals against current market prices
    try:
        current_prices = _fetch_current_prices(dhan, state)
        if current_prices:
            state = monitor_active_signals(state, current_prices)
            save(state)
    except Exception as exc:
        LOG.warning("Signal monitoring failed | %s", exc)

    _process_b1(dhan, state, ts)

    if _is_market_close(ts):
        try:
            backup_and_clear(state, ts.date())
            LOG.info("MARKET_CLOSE | Daily state backed up and cleared for next trading day")
        except Exception as exc:
            LOG.error("Failed to backup and clear state at market close | %s", exc)


if __name__ == "__main__":
    main()
