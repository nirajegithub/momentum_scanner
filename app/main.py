from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .config import SETTINGS
from .calendar import is_trading_day
from .dhan_client import DhanClient
from .indicators import add_indicators
from .nse_universe import build_universe, refresh_dynamic_volume_gainers
from .risk import build_risk_and_targets
from .state import load, save, record_alert
from .strategy import evaluate_b1_breakout, t1_blocked
from .telegram import send, signal_message
from .candle_utils import completed_candles

LOG = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _now_ist() -> datetime:
    return datetime.now(IST)


def _as_ist_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    x = df.copy()
    idx = pd.to_datetime(x.index)
    if idx.tz is None:
        idx = idx.tz_localize(IST)
    else:
        idx = idx.tz_convert(IST)
    x.index = idx
    return x.sort_index()


def _orb_for_day(df15: pd.DataFrame, trading_day=None):
    if df15 is None or df15.empty:
        return None

    x = _as_ist_index(df15)

    if trading_day is None:
        trading_day = x.index[-1].date()

    rows = x[
        (x.index.date == trading_day)
        & (x.index.strftime("%H:%M") == "09:15")
    ]

    if rows.empty:
        return None

    r = rows.iloc[0]
    ts = rows.index[0]

    return {
        "timestamp": ts.isoformat(),
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
    }


def _reset_b1_state_for_day(state, trading_day):
    orb = state.get("orb")
    if not orb:
        return

    try:
        orb_day = pd.Timestamp(orb["timestamp"]).tz_convert(IST).date()
    except Exception:
        orb_day = None

    if orb_day != trading_day:
        state["status"] = "WAITING"
        state["last_processed_15m"] = None
        state["orb"] = None
        LOG.info(
            "B1_STATE_RESET | reason=NEW_TRADING_DAY | old_orb_date=%s | new_date=%s",
            orb_day,
            trading_day,
        )


def _hhmm(ts) -> int:
    return int(pd.Timestamp(ts).strftime("%H%M"))


def _scan_window(ts) -> bool:
    hhmm = _hhmm(ts)
    return SETTINGS.scan_start_hhmm <= hhmm <= SETTINGS.scan_end_hhmm


def _daily_values(dhan, item, trading_day):
    close = item.get("prev_close")
    volume = item.get("prev_volume")

    if close is not None and volume is not None:
        return float(close), float(volume)

    prev_day = trading_day
    try:
        from .calendar import previous_trading_day
        prev_day = previous_trading_day(trading_day)
    except Exception:
        pass

    df = dhan.historical_daily_df(
        security_id=item["security_id"],
        from_date=prev_day.isoformat(),
        to_date=(prev_day + pd.Timedelta(days=1)).date().isoformat(),
    )

    if df is None or df.empty:
        raise RuntimeError(f"{item['symbol']}: no previous-day daily data")

    rows = df[df.index.date == prev_day]
    if rows.empty:
        raise RuntimeError(f"{item['symbol']}: no candle for {prev_day}")

    row = rows.iloc[-1]
    return float(row["close"]), float(row["volume"])


def _prepare_15m(dhan, security_id, ts):
    raw = dhan.historical_intraday_df(
        security_id=security_id,
        interval=15,
        from_date=(pd.Timestamp(ts).date() - pd.Timedelta(days=10)).date().isoformat(),
        to_date=(pd.Timestamp(ts).date() + pd.Timedelta(days=1)).date().isoformat(),
    )

    if raw is None or raw.empty:
        return raw

    # dhan_client's 15M path is already session-aligned to 09:15 starts.
    x = completed_candles(raw, ts, 15)
    return add_indicators(x)


def _build_signal(dhan, item, candle_df, orb, trading_day):
    daily_close, daily_volume = _daily_values(dhan, item, trading_day)

    candidate = evaluate_b1_breakout(
        candle_df,
        orb,
        daily_close,
        daily_volume,
    )
    if candidate is None:
        return None

    signal = {
        "symbol": item["symbol"],
        "security_id": item["security_id"],
        **candidate,
    }

    risk = build_risk_and_targets(
        entry=float(candidate["setup_15m_close"]),
        stop_loss=float(orb["close"]),
        direction=candidate["direction"],
    )

    if not risk:
        LOG.info(
            "%s %s rejected: risk calculation returned no result",
            item["symbol"],
            candidate["direction"],
        )
        return None

    signal.update(risk)

    entry = float(signal["entry"])
    t1 = float(signal["t1"])

    # T1-block uses completed 5M history before the signal.
    try:
        raw5 = dhan.historical_intraday_df(
            security_id=item["security_id"],
            interval=5,
            from_date=(pd.Timestamp(candidate["setup_15m_timestamp"]).date() - pd.Timedelta(days=2)).isoformat(),
            to_date=(pd.Timestamp(candidate["setup_15m_timestamp"]).date() + pd.Timedelta(days=1)).isoformat(),
        )
        df5 = completed_candles(raw5, candidate["setup_15m_completion"], 5)
        if t1_blocked(
            df5,
            candidate["setup_15m_completion"],
            entry,
            t1,
            candidate["direction"],
        ):
            LOG.info(
                "%s %s rejected: T1_BLOCKED",
                item["symbol"],
                candidate["direction"],
            )
            return None
    except Exception as exc:
        LOG.warning(
            "%s T1 block diagnostic failed; continuing: %s",
            item["symbol"],
            exc,
        )

    signal["setup_5m_timestamp"] = signal["setup_15m_completion"]
    signal["status"] = "CANDIDATE"
    return signal


def create_universe(dhan, state):
    if state.get("universe"):
        LOG.info(
            "CREATE_UNIVERSE SKIPPED | universe already exists | size=%d",
            len(state["universe"]),
        )
        return False

    state["universe"] = build_universe(dhan)
    save(state)

    LOG.info("FINAL UNIVERSE: %d symbols", len(state["universe"]))
    return True


def refresh_universe(dhan, state, ts):
    before = len(state.get("universe", []))
    existing_ids = {
        str(x.get("security_id"))
        for x in state.get("universe", [])
        if x.get("security_id") is not None
    }
    existing_symbols = {
        str(x.get("symbol", "")).upper()
        for x in state.get("universe", [])
    }

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
        "UNIVERSE_REFRESH | before=%d | static_candidates=%d | static_added=%d | "
        "dynamic_changed=%s | dynamic_added=%d | total=%d",
        before,
        len(static_candidates),
        static_added,
        dynamic_changed,
        dynamic_added,
        len(state.get("universe", [])),
    )

    return True


def _process_b1(dhan, state, ts):
    trading_day = ts.date()

    _reset_b1_state_for_day(state, trading_day)

    orb = state.get("orb")

    # Build ORB from the current day's completed 15M data.
    if not orb:
        for item in state.get("universe", []):
            try:
                df15 = _prepare_15m(dhan, item["security_id"], ts)
                candidate_orb = _orb_for_day(df15, trading_day)
                if candidate_orb:
                    orb = candidate_orb
                    state["orb"] = orb
                    state["status"] = "WAITING"
                    LOG.info(
                        "B1_ORB | timestamp=%s | high=%.2f | low=%.2f | close=%.2f",
                        orb["timestamp"],
                        orb["high"],
                        orb["low"],
                        orb["close"],
                    )
                    break
            except Exception as exc:
                LOG.warning(
                    "%s ORB discovery failed: %s",
                    item.get("symbol"),
                    exc,
                )

    if not orb:
        LOG.info("B1_ORB_NOT_AVAILABLE | date=%s", trading_day)
        return

    # Only one first breakout is consumed for the entire trading day.
    if state.get("status") == "CONSUMED":
        LOG.info("FIRST_ORB_BREAKOUT_ALREADY_CONSUMED")
        return

    for item in state.get("universe", []):
        try:
            df15 = _prepare_15m(dhan, item["security_id"], ts)
            if df15 is None or df15.empty:
                continue

            day15 = df15[df15.index.date == trading_day]
            if day15.empty:
                continue

            # Process only the newest completed 15M candle.
            latest_ts = day15.index[-1]
            latest_key = latest_ts.isoformat()

            if state.get("last_processed_15m") == latest_key:
                continue

            # The 09:15 ORB itself is not a breakout candle.
            if latest_ts.strftime("%H:%M") == "09:15":
                state["last_processed_15m"] = latest_key
                continue

            candidate = evaluate_b1_breakout(
                day15,
                orb,
                *_daily_values(dhan, item, trading_day),
            )

            # If the latest completed candle closes outside the ORB, that
            # breakout is consumed even if RSI/RVOL/quality/risk rejects it.
            close = float(day15.iloc[-1]["close"])
            breakout = (
                close > float(orb["high"])
                or close < float(orb["low"])
            )

            state["last_processed_15m"] = latest_key

            if breakout:
                state["status"] = "CONSUMED"

                if candidate is None:
                    LOG.info(
                        "%s FIRST_ORB_BREAKOUT_CONSUMED | filters=REJECTED",
                        item["symbol"],
                    )
                    break

                signal = _build_signal(
                    dhan,
                    item,
                    day15,
                    orb,
                    trading_day,
                )

                if signal is None:
                    LOG.info(
                        "%s FIRST_ORB_BREAKOUT_CONSUMED | risk_or_t1=REJECTED",
                        item["symbol"],
                    )
                    break

                message = signal_message(signal)
                sent = send(message, parse_mode="HTML")

                if sent:
                    record_alert(signal)
                    LOG.info(
                        "ALERT_SENT | symbol=%s | direction=%s | entry=%.2f",
                        signal["symbol"],
                        signal["direction"],
                        signal["entry"],
                    )
                else:
                    LOG.warning(
                        "ALERT_NOT_SENT | symbol=%s | direction=%s",
                        signal["symbol"],
                        signal["direction"],
                    )
                break

        except Exception as exc:
            LOG.exception(
                "%s B1 processing failed: %s",
                item.get("symbol"),
                exc,
            )

    save(state)


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    ts = _now_ist()
    if not is_trading_day(ts.date()):
        LOG.info("Not an NSE trading day")
        return

    dhan = DhanClient()
    state = load()
    action = os.getenv("SCANNER_ACTION", "scan").strip().lower()

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
        state = load()

    if _scan_window(ts):
        try:
            if refresh_dynamic_volume_gainers(dhan, state, ts):
                save(state)
        except Exception as exc:
            LOG.warning("Dynamic universe refresh failed: %s", exc)

        _process_b1(dhan, state, ts)
    else:
        LOG.info(
            "Outside scan window | now=%s | window=%s-%s",
            ts.strftime("%H:%M"),
            SETTINGS.scan_start_hhmm,
            SETTINGS.scan_end_hhmm,
        )


if __name__ == "__main__":
    main()
