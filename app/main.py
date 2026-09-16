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
from .strategy import evaluate_b1_breakout, t1_blocked
from .candle_utils import completed_candles
from .telegram import send, signal_message

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
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=15,
        from_date=(pd.Timestamp(ts).date() - pd.Timedelta(days=10)).isoformat(),
        to_date=(pd.Timestamp(ts).date() + pd.Timedelta(days=1)).isoformat(),
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    x = completed_candles(raw, ts, 15)
    return add_indicators(x, rvol_lookback=SETTINGS.rvol_lookback)


def _prepare_5m(dhan, security_id, signal_completion):
    ts = pd.Timestamp(signal_completion)
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=5,
        from_date=(ts.date() - pd.Timedelta(days=2)).isoformat(),
        to_date=(ts.date() + pd.Timedelta(days=1)).isoformat(),
    )
    return completed_candles(raw, signal_completion, 5)


def _build_signal(dhan, item, candle_df, orb, trading_day):
    daily_close, daily_volume = _daily_values(dhan, item, trading_day)
    candidate = evaluate_b1_breakout(candle_df, orb, daily_close, daily_volume)
    if candidate is None:
        return None

    risk, reject = build_risk_and_targets(
        direction=candidate["direction"],
        entry=float(candidate["setup_15m_close"]),
        sl=float(orb["close"]),
        min_stop_distance_percent=SETTINGS.min_stop_distance_percent,
        t1_rr=SETTINGS.t1_rr,
        t2_rr=SETTINGS.t2_rr,
        t3_rr=SETTINGS.t3_rr,
        min_rr=SETTINGS.min_rr,
    )
    if risk is None:
        LOG.info("%s %s rejected | %s", item["symbol"], candidate["direction"], reject)
        return None

    signal = {"symbol": item["symbol"], "security_id": item["security_id"], **candidate}
    signal.update(risk)
    signal["risk"] = risk
    signal["entry"] = risk["entry"]
    signal["sl"] = risk["sl"]
    signal["t1"] = risk["t1"]
    signal["t2"] = risk["t2"]
    signal["t3"] = risk["t3"]

    # T1 block is diagnostic/safety filter based only on completed 5M history.
    try:
        df5 = _prepare_5m(dhan, item["security_id"], candidate["setup_15m_completion"])
        if t1_blocked(df5, candidate["setup_15m_completion"], risk["entry"], risk["t1"], candidate["direction"]):
            LOG.info("%s %s rejected | T1_BLOCKED", item["symbol"], candidate["direction"])
            return None
    except Exception as exc:
        LOG.warning("%s T1 block check failed; continuing | %s", item["symbol"], exc)

    # Compatibility with the existing state schema.
    signal["setup_5m_timestamp"] = candidate["setup_15m_completion"]
    signal["confirmation_5m_timestamp"] = candidate["setup_15m_completion"]
    signal["status"] = "ACTIVE"
    return signal


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


def _process_b1(dhan, state, ts):
    trading_day = ts.date()

    for item in state.get("universe", []):
        symbol = item.get("symbol")
        if not symbol or item.get("security_id") is None:
            continue
        ss = _state_for_symbol(state, symbol)

        try:
            df15 = _prepare_15m(dhan, item["security_id"], ts)
            if df15.empty:
                continue
            day15 = df15[df15.index.date == trading_day]
            if day15.empty:
                continue

            orb = _orb_for_day(day15, trading_day)
            if orb is None:
                continue
            if ss.get("orb") is None or ss["orb"].get("timestamp") != orb["timestamp"]:
                ss["orb"] = orb
                ss["status"] = "WAITING"
                ss["last_processed_15m"] = None
                LOG.info("B1_ORB | symbol=%s | timestamp=%s | high=%.2f | low=%.2f | close=%.2f", symbol, orb["timestamp"], orb["high"], orb["low"], orb["close"])

            if ss.get("status") == "CONSUMED":
                continue

            # Find the newest completed 15M candle after the 09:15 ORB.
            candidates = day15[day15.index > pd.Timestamp(orb["timestamp"])]
            if candidates.empty:
                continue
            latest_ts = candidates.index[-1]
            latest_key = latest_ts.isoformat()
            if ss.get("last_processed_15m") == latest_key:
                continue

            ss["last_processed_15m"] = latest_key
            close = float(candidates.iloc[-1]["close"])
            breakout = close > float(orb["high"]) or close < float(orb["low"])
            if not breakout:
                continue

            # The first completed 15M candle that closes outside the ORB is consumed,
            # even when RSI/RVOL/quality/risk/T1 rejects it.
            ss["status"] = "CONSUMED"
            candidate = evaluate_b1_breakout(day15.loc[:latest_ts], orb, *_daily_values(dhan, item, trading_day))
            if candidate is None:
                LOG.info("%s FIRST_ORB_BREAKOUT_CONSUMED | filters=REJECTED", symbol)
                continue

            signal = _build_signal(dhan, item, day15.loc[:latest_ts], orb, trading_day)
            if signal is None:
                LOG.info("%s FIRST_ORB_BREAKOUT_CONSUMED | risk_or_t1=REJECTED", symbol)
                continue

            sent = send(signal_message(signal))
            if sent:
                record_alert(state, signal, ts)
                state.setdefault("signals", {})[f"{symbol}|{signal['direction']}|{signal['setup_15m_timestamp']}"] = signal
                LOG.info("ALERT_SENT | symbol=%s | direction=%s | entry=%.2f", symbol, signal["direction"], signal["entry"])
            else:
                LOG.warning("ALERT_NOT_SENT | symbol=%s | direction=%s", symbol, signal["direction"])

        except Exception as exc:
            LOG.exception("%s B1 processing failed | %s", symbol, exc)

    save(state)


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
    if action != "scan":
        LOG.info("Unknown SCANNER_ACTION=%s", action)
        return

    if not state.get("universe"):
        create_universe(dhan, state)
        state = load(ts.date())

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
