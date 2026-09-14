from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import pandas as pd

from .calendar import is_nse_trading_day
from .config import SETTINGS
from .dhan_client import DhanClient
from .indicators import add_indicators
from .nse_universe import build_universe
from .risk import build_risk_and_targets
from .state import load, save, signal_key, record_alert, backup_and_clear, active_for_symbol
from .summary import build_summary
from .strategy import evaluate_b1_breakout, t1_blocked
from .candle_utils import completed_candles
from .telegram import send, signal_message, stop_update_message, exit_message

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)
ORB_TIME = time(9, 15)


def now():
    return datetime.now(IST)


def ltp_batch(dhan, ids):
    if not ids:
        return {}
    response = dhan.dhan.ohlc_data(securities={"NSE_EQ": [int(x) if str(x).isdigit() else str(x) for x in ids]})
    data = response.get("data", response) if isinstance(response, dict) else {}
    block = data.get("NSE_EQ", {}) if isinstance(data, dict) else {}
    return block if isinstance(block, dict) else {}


def _intraday_range(ts):
    return (ts - timedelta(days=10)).strftime("%Y-%m-%d"), (ts + timedelta(days=1)).strftime("%Y-%m-%d")


def _orb_for_day(df15, day):
    if df15 is None or df15.empty:
        return None
    x = df15[df15.index.date == day]
    x = x[x.index.strftime("%H:%M") == "09:15"]
    if x.empty:
        return None
    r = x.iloc[-1]
    ts = x.index[-1]
    return {
        "timestamp": ts.isoformat(),
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
    }


def _b_state(state, symbol):
    return state.setdefault("orb", {}).setdefault(symbol, {
        "status": "WAITING",
        "last_processed_15m": None,
        "orb": None,
    })


def _build_signal(item, candidate, risk):
    ts = candidate["setup_15m_timestamp"]
    return {
        "symbol": item["symbol"],
        "security_id": item["security_id"],
        "direction": candidate["direction"],
        "setup": "B1_ORB_15M_CLOSE_RVOL",
        "signal_key": signal_key(item["symbol"], candidate["direction"], ts),
        "setup_time": ts,
        "signal_time": candidate["setup_15m_completion"],
        "setup_15m_timestamp": ts,
        "setup_15m_completion": candidate["setup_15m_completion"],
        "signal_price": risk["entry"],
        "status": "ACTIVE",
        "risk": risk,
        "initial_risk": risk["risk"],
        "breakout_level": candidate["breakout_level"],
        "orb_timestamp": candidate["orb_timestamp"],
        "orb_high": candidate["orb_high"],
        "orb_low": candidate["orb_low"],
        "orb_close": candidate["orb_close"],
        "setup_15m_high": candidate["setup_15m_high"],
        "setup_15m_low": candidate["setup_15m_low"],
        "setup_15m_close": candidate["setup_15m_close"],
        "setup_15m_volume": candidate["setup_15m_volume"],
        "setup_15m_rvol": candidate["setup_15m_rvol"],
        "setup_15m_rsi14": candidate["setup_15m_rsi14"],
        "setup_15m_previous_rsi14": candidate["setup_15m_previous_rsi14"],
        "trade_quality_score": candidate["trade_quality_score"],
        "curve_context": candidate["curve_context"],
        "highest_target_hit": None,
    }


def _monitor_trade(dhan, state, signal, ts):
    if signal.get("status") != "ACTIVE":
        return False
    risk = signal["risk"]
    direction = signal["direction"]
    entry = float(risk["entry"])
    initial_risk = float(signal.get("initial_risk", risk["risk"]))
    quotes = ltp_batch(dhan, [signal["security_id"]])
    q = quotes.get(str(signal["security_id"]), {})
    ltp = q.get("last_price", q.get("ltp"))
    if ltp is None:
        LOG.info("%s | LTP_UNAVAILABLE", signal["symbol"])
        return False
    ltp = float(ltp)

    # B1 production management stays aligned with the tested fixed-stop model.
    sl_hit = (direction == "BUY" and ltp <= float(risk["sl"])) or (direction == "SELL" and ltp >= float(risk["sl"]))
    t3_hit = (direction == "BUY" and ltp >= float(risk["t3"])) or (direction == "SELL" and ltp <= float(risk["t3"]))
    if sl_hit or t3_hit:
        signal["status"] = "EXITED"
        signal["exit_price"] = float(risk["sl"] if sl_hit else risk["t3"])
        signal["exit_time"] = ts.isoformat()
        signal["exit_reason"] = "SL_HIT" if sl_hit else "T3_HIT"
        signal["r_multiple"] = ((signal["exit_price"] - entry) / initial_risk if direction == "BUY" else (entry - signal["exit_price"]) / initial_risk)
        try:
            send(exit_message(signal, signal["exit_price"], signal["exit_reason"], ts.strftime("%H:%M:%S")))
        except Exception:
            LOG.exception("%s | exit Telegram failed", signal["symbol"])
        return True

    changed = False
    hit = None
    if direction == "BUY":
        if ltp >= float(risk["t3"]): hit = "T3_HIT"
        elif ltp >= float(risk["t2"]): hit = "T2_HIT"
        elif ltp >= float(risk["t1"]): hit = "T1_HIT"
    else:
        if ltp <= float(risk["t3"]): hit = "T3_HIT"
        elif ltp <= float(risk["t2"]): hit = "T2_HIT"
        elif ltp <= float(risk["t1"]): hit = "T1_HIT"
    rank = {None: 0, "T1_HIT": 1, "T2_HIT": 2, "T3_HIT": 3}
    if hit and rank[hit] > rank.get(signal.get("highest_target_hit"), 0):
        signal["highest_target_hit"] = hit
        changed = True
        LOG.info("%s | %s | target milestone", signal["symbol"], hit)
    return changed


def create_universe(dhan, state):
    state["universe"] = build_universe(dhan)
    state["signals"] = {}
    state["orb"] = {}
    state["daily_filters"] = {}
    state["alert_state"] = {}
    state["pending_setups"] = {}
    save(state)
    LOG.info("UNIVERSE_INITIAL | size=%d", len(state["universe"]))


def refresh_universe(dhan, state):
    candidates = build_universe(dhan)
    existing = {str(x.get("security_id")) for x in state.get("universe", [])}
    for item in candidates:
        if str(item.get("security_id")) not in existing:
            state["universe"].append(item)
            existing.add(str(item.get("security_id")))
    save(state)
    LOG.info("UNIVERSE_REFRESH | total=%d", len(state["universe"]))


def _process_b1(state, item, df5, df15):
    symbol = item["symbol"]
    st = _b_state(state, symbol)
    orb = st.get("orb")
    if orb is None:
        orb = _orb_for_day(df15, df15.index[-1].date())
        if orb is None:
            LOG.info("%s | ORB_WAITING | 09:15 candle unavailable", symbol)
            return False
        st["orb"] = orb
        LOG.info("%s | ORB_ARMED | high=%.2f | low=%.2f | close=%.2f", symbol, orb["high"], orb["low"], orb["close"])

    if st.get("status") == "CONSUMED":
        return False

    latest_ts = df15.index[-1]
    if st.get("last_processed_15m") == latest_ts.isoformat():
        return False
    st["last_processed_15m"] = latest_ts.isoformat()

    orb_ts = pd.Timestamp(orb["timestamp"])
    if latest_ts <= orb_ts:
        return True

    close = float(df15.iloc[-1]["close"])
    direction = "BUY" if close > orb["high"] else "SELL" if close < orb["low"] else None
    if direction is None:
        return True

    # FIRST ORB BREAKOUT IS CONSUMED REGARDLESS OF WHETHER FILTERS ACCEPT IT.
    st["status"] = "CONSUMED"
    LOG.info("%s | B1_FIRST_ORB_BREAKOUT | direction=%s | close=%.2f | orb_high=%.2f | orb_low=%.2f", symbol, direction, close, orb["high"], orb["low"])

    candidate = evaluate_b1_breakout(df15, orb, float(item["prev_close"]), float(item["prev_volume"]))
    if candidate is None:
        LOG.info("%s | B1_REJECTED | first ORB breakout failed RSI/Quality/RVOL filter", symbol)
        return True

    risk, reject = build_risk_and_targets(
        direction, close, orb["close"], SETTINGS.min_stop_distance_percent,
        SETTINGS.t1_rr, SETTINGS.t2_rr, SETTINGS.t3_rr, SETTINGS.min_rr,
    )
    if reject:
        LOG.info("%s | B1_REJECTED | reason=%s", symbol, reject)
        return True

    if t1_blocked(df5, latest_ts, risk["entry"], risk["t1"], direction):
        LOG.info("%s | B1_REJECTED | reason=T1_BLOCKED", symbol)
        return True

    signal = _build_signal(item, candidate, risk)
    if signal["signal_key"] in state.get("signals", {}):
        LOG.info("%s | B1_DUPLICATE_SUPPRESSED", symbol)
        return True

    if send(signal_message(signal)):
        state.setdefault("signals", {})[signal["signal_key"]] = signal
        record_alert(state, signal, pd.Timestamp(candidate["setup_15m_completion"]).to_pydatetime())
        LOG.info(
            "%s | B1_ALERT_SENT | %s | signal_completion=%s | entry=%.2f | sl=%.2f | rvol=%.2f | rsi=%.2f | quality=%.1f",
            symbol, direction, candidate["setup_15m_completion"], close, risk["sl"],
            candidate["setup_15m_rvol"], candidate["setup_15m_rsi14"], candidate["trade_quality_score"],
        )
    return True


def scan(dhan, state, ts):
    if not state.get("universe"):
        LOG.warning("Universe missing; refusing to scan")
        return
    changed = False
    start, end = _intraday_range(ts)
    hhmm = ts.hour * 100 + ts.minute
    if not (SETTINGS.scan_start_hhmm <= hhmm <= SETTINGS.scan_end_hhmm):
        return

    for item in list(state["universe"]):
        try:
            raw5 = dhan.intraday_df(item["security_id"], 5, start, end)
            raw15 = dhan.intraday_df(item["security_id"], 15, start, end)
            df5 = completed_candles(raw5, ts, 5)
            df15 = completed_candles(raw15, ts, 15)
            if df5.empty or df15.empty:
                continue
            df15 = add_indicators(df15, SETTINGS.rvol_lookback)
            if df15.empty or len(df15) < max(SETTINGS.min_15m_candles, SETTINGS.rvol_lookback + 1, 3):
                continue

            for signal in list(state.get("signals", {}).values()):
                if signal.get("symbol") == item["symbol"] and signal.get("status") == "ACTIVE":
                    changed |= _monitor_trade(dhan, state, signal, ts)

            if not active_for_symbol(state, item["symbol"]):
                changed |= _process_b1(state, item, df5, df15)
        except Exception:
            LOG.exception("Scan failed: %s", item.get("symbol"))
    if changed:
        save(state)


def summary(dhan, state, ts):
    active = [s for s in state.get("signals", {}).values() if s.get("status") == "ACTIVE"]
    prices = {}
    if active:
        quotes = ltp_batch(dhan, [s["security_id"] for s in active])
        for s in active:
            q = quotes.get(str(s["security_id"]), {})
            px = q.get("last_price", q.get("ltp"))
            if px is not None:
                px = float(px)
                s["status"] = "CLOSED_EOD"
                s["exit_price"] = px
                s["exit_time"] = ts.isoformat()
                s["exit_reason"] = "END_OF_DAY"
                prices[s["symbol"]] = px
    send(build_summary(state, prices))
    backup_and_clear(state, ts.date())


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(message)s")
    ts = now()
    if not is_nse_trading_day(ts.date()):
        LOG.info("Not an NSE trading day")
        return
    dhan = DhanClient()
    state = load(ts.date())
    action = os.getenv("SCANNER_ACTION", "scan").strip().lower()
    if action == "universe":
        create_universe(dhan, state); return
    if action == "universe_refresh":
        refresh_universe(dhan, state) if state.get("universe") else create_universe(dhan, state); return
    if action == "summary":
        summary(dhan, state, ts); return
    if action in {"monitor", "scan"}:
        scan(dhan, state, ts); return
    LOG.warning("Unknown SCANNER_ACTION=%s", action)

if __name__ == "__main__":
    main()
