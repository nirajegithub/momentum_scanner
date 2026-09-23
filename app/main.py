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

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)
ORB_TIME = time(9, 15)


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
    s.setdefault("last_processed_15m", None)
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
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=15,
        from_date=trading_day.isoformat(),
        to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    x = completed_candles(raw, ts, 15)
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
    df5 = _as_ist_index(df5)
    setup_ts = pd.Timestamp(setup_completion)
    rows = df5[df5.index > setup_ts]
    return rows, df5


def _fetch_nifty_15m(dhan):
    """Fetch Nifty50 15M data for market trend alignment."""
    try:
        nifty_security_id = 99926000  # Nifty50 security ID in Dhan
        ts = _now_ist()
        trading_day = ts.date()
        df = dhan.historical_intraday_df(
            security_id=nifty_security_id,
            interval=15,
            from_date=trading_day.isoformat(),
            to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
        )
        if df is not None and not df.empty:
            x = completed_candles(df, ts, 15)
            return x
    except Exception as exc:
        LOG.warning("Failed to fetch Nifty50 data: %s", exc)
    return None


def _process_b1(dhan, state, ts):
    trading_day = ts.date()
    nifty15m = _fetch_nifty_15m(dhan)
    stats = ScanStats(total_symbols=len(state.get("universe", [])))

    for item in state.get("universe", []):
        symbol = item.get("symbol")
        if not symbol or item.get("security_id") is None:
            continue

        ss = _state_for_symbol(state, symbol)

        try:
            df15 = _prepare_15m(dhan, item["security_id"], ts)
            if df15.empty:
                LOG.info("%s | DATA_STAGE | status=15M_DATA_UNAVAILABLE", symbol)
                stats.data_unavailable += 1
                continue

            day15 = df15[df15.index.date == trading_day]
            orb = _orb_for_day(day15, trading_day)
            if orb is None:
                LOG.info("%s | DATA_STAGE | status=ORB_NOT_AVAILABLE", symbol)
                stats.orb_not_available += 1
                continue

            if ss.get("orb") is None or ss["orb"].get("timestamp") != orb["timestamp"]:
                ss["orb"] = orb
                ss["status"] = "WAITING_FOR_15M"
                ss["last_processed_15m"] = None
                ss["setup"] = None
                log_orb_check(symbol, orb)

            # Once an alert is active, do not create another B1 setup for the symbol.
            if ss.get("status") == "CONSUMED":
                continue

            # ----------------------------------------------------------
            # Phase 1: completed 15M setup. Process every new 15M candle
            # in chronological order so a delayed GitHub Action cannot skip one.
            # ----------------------------------------------------------
            if not ss.get("setup"):
                candidates = day15[day15.index > pd.Timestamp(orb["timestamp"])].sort_index()
                last_processed = ss.get("last_processed_15m")
                if last_processed:
                    candidates = candidates[candidates.index > pd.Timestamp(last_processed)]

                for setup_ts, row15 in candidates.iterrows():
                    ss["last_processed_15m"] = setup_ts.isoformat()
                    close15 = float(row15["close"])
                    if close15 > orb["high"]:
                        side = "BUY"
                    elif close15 < orb["low"]:
                        side = "SELL"
                    else:
                        log_15m_candle_check(symbol, setup_ts, close15, orb["high"], orb["low"], None)
                        stats.no_breakout += 1
                        continue

                    log_15m_candle_check(symbol, setup_ts, close15, orb["high"], orb["low"], side)

                    try:
                        daily_close, daily_volume = _daily_values(dhan, item, trading_day)
                    except Exception as exc:
                        LOG.warning("B1_15M | symbol=%s | status=DATA_UNAVAILABLE | reason=%s", symbol, exc)
                        # Do not lose this breakout when daily data/API is temporarily unavailable.
                        ss["last_processed_15m"] = (setup_ts - pd.Timedelta(minutes=15)).isoformat()
                        break

                    candidate = evaluate_b1_breakout(day15.loc[:setup_ts], orb, daily_close, daily_volume, symbol=symbol)
                    if candidate is None:
                        stats.filter_rejected += 1
                        continue

                    setup = dict(candidate)
                    setup["direction"] = side
                    setup["setup_15m_timestamp"] = setup_ts.isoformat()
                    setup["setup_15m_completion"] = (setup_ts + pd.Timedelta(minutes=15)).isoformat()

                    # Check if setup qualifies for early 5M confirmation (momentum surge filter)
                    early_surge = momentum_surge_qualifies(setup, side)
                    setup["early_momentum_surge"] = early_surge
                    if early_surge:
                        # For early surge, start 5M search from current time, not full 15M completion
                        setup["early_5m_search_start"] = ts.isoformat()

                    # Check market trend alignment (Nifty50)
                    trend_aligned = market_trend_aligned(nifty15m, side)
                    setup["market_trend_aligned"] = trend_aligned
                    if not trend_aligned:
                        LOG.info("%s | BREAKOUT_STAGE | status=MARKET_TREND_REJECTED | direction=%s", symbol, side)
                        stats.filter_rejected += 1
                        continue

                    ss["setup"] = setup
                    ss["status"] = "WAITING_FOR_5M"
                    state.setdefault("pending_setups", {})[symbol] = setup

                    rvol = float(setup.get("setup_15m_rvol", 0))
                    rsi = float(setup.get("setup_15m_rsi14", 0))
                    quality_score = float(setup.get("trade_quality_score", 0))
                    log_setup_created(symbol, side, setup_ts, rvol, rsi, quality_score, early_surge)
                    stats.setups_created += 1
                    break

            # ----------------------------------------------------------
            # Phase 2: subsequent completed 5M close must cross the stored
            # 15M HIGH/LOW. Equality never confirms.
            # ----------------------------------------------------------
            setup = ss.get("setup")
            if not setup:
                continue

            # Use early search time if momentum surge qualifies, otherwise use normal completion time
            search_start = setup.get("early_5m_search_start") or setup["setup_15m_completion"]
            rows5, full5 = _confirmation_5m(
                dhan, item["security_id"], search_start, ts
            )
            if rows5 is None or rows5.empty:
                early_marker = " (EARLY_MOMENTUM_SURGE)" if setup.get("early_momentum_surge") else ""
                LOG.info("%s | CONFIRMATION_STAGE | status=WAITING_FOR_5M%s", symbol, early_marker)
                continue

            direction = setup["direction"]
            threshold = float(setup["setup_15m_high"] if direction == "BUY" else setup["setup_15m_low"])

            for ts5, row5 in rows5.iterrows():
                close5 = float(row5["close"])
                confirmed = close5 > threshold if direction == "BUY" else close5 < threshold
                log_5m_confirmation_check(symbol, ts5, close5, threshold, direction, confirmed)
                if not confirmed:
                    continue
                signal, reject = _build_confirmed_signal(item, setup, ts5, close5, orb)
                if signal is None:
                    log_confirmed_rejection(symbol, direction, ts5, reject, sl=float(orb["low"]) if direction == "BUY" else float(orb["high"]), entry=close5)
                    ss["status"] = "CONSUMED"
                    ss["setup"] = None
                    state.get("pending_setups", {}).pop(symbol, None)
                    break

                # T1 safety check is evaluated at the actual 5M entry.
                try:
                    if t1_blocked(full5, ts5, signal["risk"]["entry"], signal["risk"]["t1"], direction):
                        log_t1_blocked(symbol, direction, signal["risk"]["entry"], signal["risk"]["t1"], close5)
                        ss["status"] = "CONSUMED"
                        ss["setup"] = None
                        state.get("pending_setups", {}).pop(symbol, None)
                        break
                except Exception as exc:
                    LOG.warning("%s T1 block check failed; continuing | %s", symbol, exc)

                sent = send(signal_message(signal))
                if sent:
                    record_alert(state, signal, ts)
                    signal_key = f"{symbol}|{direction}|{setup['setup_15m_timestamp']}|{signal['confirmation_5m_timestamp']}"
                    state.setdefault("signals", {})[signal_key] = signal
                    ss["status"] = "CONSUMED"
                    ss["setup"] = None
                    ss["confirmation_5m_timestamp"] = signal["confirmation_5m_timestamp"]
                    state.get("pending_setups", {}).pop(symbol, None)

                    rvol = float(setup.get("setup_15m_rvol", 0))
                    rsi = float(setup.get("setup_15m_rsi14", 0))
                    log_signal_generated(symbol, direction, signal["entry"], signal["sl"],
                                        signal["t1"], rvol, rsi, signal["confirmation_5m_timestamp"])
                    stats.signals_generated += 1
                else:
                    log_telegram_failure(symbol, direction, "SEND_FAILED", signal["entry"])
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


def _send_daily_summary(dhan, state, ts):
    """Send daily summary of all signals/trades for the current session."""
    trading_day = ts.date()

    # Build summary message using final EOD prices
    final_prices = {}
    for item in state.get("universe", []):
        symbol = item.get("symbol")
        if not symbol or item.get("security_id") is None:
            continue
        try:
            df = dhan.historical_daily_df(
                security_id=item["security_id"],
                from_date=trading_day.isoformat(),
                to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
            )
            if df is not None and not df.empty:
                x = _as_ist_index(df)
                rows = x[x.index.date == trading_day]
                if not rows.empty:
                    final_prices[symbol] = float(rows.iloc[-1]["close"])
        except Exception as exc:
            LOG.warning("Failed to fetch EOD price for %s: %s", symbol, exc)

    summary_text = build_summary(state, final_prices)
    LOG.info("SUMMARY\n%s", summary_text)

    sent = send(summary_text)
    if sent:
        LOG.info("DAILY_SUMMARY_SENT | symbols=%d | text_len=%d", len(final_prices), len(summary_text))
    else:
        LOG.warning("DAILY_SUMMARY_FAILED | symbols=%d", len(final_prices))


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(message)s")
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

    _process_b1(dhan, state, ts)


if __name__ == "__main__":
    main()
