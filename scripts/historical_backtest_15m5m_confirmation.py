from __future__ import annotations

"""Offline replay for the repository's 15M setup -> 5M confirmation strategy.

This script intentionally does not import app.main.scan().  It replays the
strategy components directly with historical candle-start timestamps and
models when each candle becomes knowable.  It is research-only and never
connects to Dhan or Telegram.

Canonical timing used here:
  * a 15M candle stamped HH:MM is knowable at HH:MM+15m
  * a 5M candle stamped HH:MM is knowable at HH:MM+5m
  * a 5M confirmation must be a candle whose completion time is after the
    setup 15M candle's completion time; this prevents using 5M candles that
    happened while the setup candle was still forming.

Daily filters are approximated from the previous day's supplied 5M data:
previous-day close = last 5M close; previous-day volume = sum of 5M volume.
"""

import argparse
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.candle_utils import as_ist_index
from app.config import SETTINGS
from app.indicators import add_indicators
from app.risk import build_risk_and_targets
from app.strategy import evaluate_b1_breakout

IST = ZoneInfo("Asia/Kolkata")


def parse_args():
    p = argparse.ArgumentParser(description="Historical 15M setup -> 5M confirmation replay")
    p.add_argument("--data-5m", required=True, help="CSV with symbol,timestamp,open,high,low,close,volume")
    p.add_argument("--data-15m", required=True, help="CSV with symbol,timestamp,open,high,low,close,volume")
    p.add_argument("--out", default="backtest/15m5m_confirmation_trades.csv")
    p.add_argument("--start", help="Inclusive YYYY-MM-DD")
    p.add_argument("--end", help="Inclusive YYYY-MM-DD")
    p.add_argument("--min-stop-pct", type=float, default=SETTINGS.min_stop_distance_percent)
    p.add_argument("--verbose", action="store_true", help="Print every replayed trade")
    return p.parse_args()


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    df["symbol"] = df["symbol"].astype(str)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(IST)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(IST)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def previous_day_filters(df5: pd.DataFrame) -> dict[tuple[str, object], tuple[float, float]]:
    x = df5.copy()
    x["date"] = x["timestamp"].dt.date
    daily = x.groupby(["symbol", "date"], sort=True).agg(
        prev_close=("close", "last"),
        prev_volume=("volume", "sum"),
    ).reset_index()
    out = {}
    for symbol, g in daily.groupby("symbol", sort=False):
        g = g.sort_values("date")
        previous = None
        for row in g.itertuples(index=False):
            if previous is not None:
                out[(symbol, row.date)] = (float(previous.prev_close), float(previous.prev_volume))
            previous = row
    return out


def completed_time(start_ts: pd.Timestamp, minutes: int) -> pd.Timestamp:
    return start_ts + pd.Timedelta(minutes=minutes)


def in_date_range(ts: pd.Timestamp, start: str | None, end: str | None) -> bool:
    d = ts.date()
    if start and d < pd.Timestamp(start).date():
        return False
    if end and d > pd.Timestamp(end).date():
        return False
    return True


def replay_symbol(symbol: str, df5_raw: pd.DataFrame, df15_raw: pd.DataFrame, daily, args) -> list[dict]:
    """Replay one symbol with a chronological pending-setup state machine."""
    d5 = df5_raw.set_index("timestamp").sort_index()
    d15 = df15_raw.set_index("timestamp").sort_index()
    if d5.empty or d15.empty:
        return []

    d15_ind = add_indicators(d15, SETTINGS.rvol_lookback)
    if d15_ind.empty:
        return []
    min_bars = max(SETTINGS.min_15m_candles, SETTINGS.rvol_lookback + 1, 2)

    # Build qualifying 15M setup events once. This avoids repeatedly scanning
    # the same history and keeps the replay fast enough for multi-month data.
    setups = []
    for i, (setup_ts, row) in enumerate(d15_ind.iterrows()):
        if not in_date_range(setup_ts, args.start, args.end):
            continue
        if i + 1 < min_bars:
            continue
        filters = daily.get((symbol, setup_ts.date()))
        if filters is None:
            continue
        prev = d15_ind.iloc[i - 1]
        daily_close, daily_volume = filters
        # Cheap vectorized-style prefilter before invoking the quality scorer.
        # This preserves the exact evaluate_15m_setup rules while avoiding a
        # full dataframe slice for every historical 15M bar.
        rsi = float(row["rsi14"])
        if not (
            (float(row["ema9"]) > float(row["ema20"]) and SETTINGS.buy_rsi_min < rsi < SETTINGS.buy_rsi_max and rsi > float(prev["rsi14"]) and float(row["close"]) > float(row["vwap"]) and float(row["close"]) > float(row["ema20"]) and float(daily_close) > SETTINGS.min_price and float(daily_volume) > SETTINGS.min_daily_volume and float(row["rvol"]) >= SETTINGS.min_15m_rvol)
            or
            (float(row["ema9"]) < float(row["ema20"]) and SETTINGS.sell_rsi_min < rsi < SETTINGS.sell_rsi_max and rsi < float(prev["rsi14"]) and float(row["close"]) < float(row["vwap"]) and float(row["close"]) < float(row["ema20"]) and float(daily_close) > SETTINGS.min_price and float(daily_volume) > SETTINGS.min_daily_volume and float(row["rvol"]) >= SETTINGS.min_15m_rvol)
        ):
            continue
        history = d15_ind.iloc[: i + 1]
        setup = evaluate_15m_setup(history, daily_close, daily_volume)
        if setup is None:
            continue
        setup["symbol"] = symbol
        setup["_setup_complete"] = completed_time(setup_ts, SETTINGS.setup_timeframe)
        setup["_expires"] = setup["_setup_complete"] + pd.Timedelta(
            minutes=15 * SETTINGS.pending_setup_max_15m_candles
        )
        setups.append(setup)

    if not setups:
        return []

    # Only fully completed 5M bars in the requested period are confirmation
    # events. The latest qualifying 15M setup becomes the pending setup when
    # its completion has passed, matching the live replacement behavior.
    five = [(ts, row) for ts, row in d5.iterrows()
            if (not args.start or ts.date() >= pd.Timestamp(args.start).date())
            and (not args.end or ts.date() <= pd.Timestamp(args.end).date())]
    five.sort(key=lambda z: z[0])
    setups.sort(key=lambda x: x["_setup_complete"])

    trades = []
    si = 0
    pending = None

    for candle_ts, row in five:
        candle_complete = completed_time(candle_ts, SETTINGS.entry_timeframe)

        # Introduce every setup that is known by this 5M candle's completion.
        while si < len(setups) and setups[si]["_setup_complete"] <= candle_complete:
            pending = setups[si]
            si += 1

        if pending is None:
            continue
        if candle_complete <= pending["_setup_complete"]:
            continue
        if candle_complete > pending["_expires"]:
            pending = None
            continue

        close = float(row["close"])
        if not confirm_5m_breakout(pending, candle_ts, close):
            continue

        risk, reject = build_risk_and_targets(
            pending["direction"], close, pending["setup_15m_close"],
            args.min_stop_pct, SETTINGS.t1_rr, SETTINGS.t2_rr,
            SETTINGS.t3_rr, SETTINGS.min_rr,
        )
        # First breakout consumes the pending setup, even if risk rejects it.
        setup = pending
        pending = None
        if reject:
            continue

        trades.append({
            "symbol": symbol,
            "direction": setup["direction"],
            "setup_15m_timestamp": setup_ts_from_pending(setup),
            "setup_15m_completion": setup["_setup_complete"].isoformat(),
            "confirmation_5m_timestamp": candle_ts.isoformat(),
            "confirmation_5m_completion": candle_complete.isoformat(),
            "setup_15m_open": setup["setup_15m_open"],
            "setup_15m_high": setup["setup_15m_high"],
            "setup_15m_low": setup["setup_15m_low"],
            "setup_15m_close": setup["setup_15m_close"],
            "entry": risk["entry"],
            "sl": risk["sl"],
            "risk": risk["risk"],
            "risk_percent": risk["risk_percent"],
            "t1": risk["t1"],
            "t2": risk["t2"],
            "t3": risk["t3"],
            "trade_quality_score": setup["trade_quality_score"],
            "rvol": setup["setup_15m_rvol"],
            "rsi14": setup["setup_15m_rsi14"],
            "daily_close": setup["daily_close"],
            "daily_volume": setup["daily_volume"],
            "curve_context": setup["curve_context"],
        })

    return trades

def setup_ts_from_pending(pending: dict) -> str:
    return str(pending["setup_15m_timestamp"])

def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame([{"trades": 0}])
    # This replay intentionally records entries only. Exit-path validation is
    # separate because the live monitor uses LTP and progressive TS logic.
    return pd.DataFrame([{
        "trades": len(trades),
        "buy_trades": int((trades.direction == "BUY").sum()),
        "sell_trades": int((trades.direction == "SELL").sum()),
        "avg_initial_risk_pct": round(float(trades.risk_percent.mean()), 4),
        "avg_quality": round(float(trades.trade_quality_score.mean()), 3),
        "avg_rvol": round(float(trades.rvol.mean()), 3),
    }])


def main():
    args = parse_args()
    d5 = load_csv(args.data_5m)
    d15 = load_csv(args.data_15m)
    daily = previous_day_filters(d5)

    trades = []
    for symbol in sorted(set(d5.symbol) & set(d15.symbol)):
        trades.extend(replay_symbol(
            symbol,
            d5[d5.symbol == symbol],
            d15[d15.symbol == symbol],
            daily,
            args,
        ))

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df = trades_df.sort_values(["confirmation_5m_timestamp", "symbol"]).reset_index(drop=True)
    trades_df.to_csv(out, index=False)

    summary = summarize(trades_df)
    summary_path = out.with_name(out.stem + "_summary.csv")
    summary.to_csv(summary_path, index=False)

    print(f"Trades: {len(trades_df)}")
    if args.verbose and not trades_df.empty:
        print(trades_df.to_string(index=False))
    print(f"\nTrade file: {out}")
    print(f"Summary:    {summary_path}")


if __name__ == "__main__":
    main()
