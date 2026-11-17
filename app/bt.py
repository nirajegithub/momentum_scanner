"""Standalone B1 ORB backtest — replays historical 5M candles through live strategy logic.

Usage:
    python -m app.bt --from 2026-10-07 --to 2026-11-17
    python -m app.bt --from 2026-10-07 --to 2026-11-17 --workers 5 --out results/bt.json
    python -m app.bt --from 2026-10-07 --to 2026-11-17 --symbols RELIANCE,TCS,INFY

Exit model (qty = 1 share):
    Signal fires on 5M candle close. For each subsequent 5M candle:
      BUY : low  <= sl   → exit at sl   (full loss)
            high >= t1   → exit at t1   (win)
      SELL: high >= sl   → exit at sl   (full loss)
            low  <= t1   → exit at t1   (win)
    If still open at the last 5M candle before 15:30 → EOD square-off at close.
    SL wins (checked first) so adverse gap-opens are captured correctly.

Parameters respected:
    MIN_TRADE_SCORE, MIN_RR, MAX_STOP_DISTANCE_PERCENT, MIN_STOP_DISTANCE_PERCENT,
    MIN_15M_RVOL, MAX_15M_RVOL, BUY_RSI_MIN/MAX, SELL_RSI_MIN/MAX,
    MIN_PRICE, MIN_DAILY_VOLUME, SCAN_END_HHMM, MAX_ENTRY_HHMM,
    MAX_OPEN_POSITIONS, DAILY_LOSS_HALT_INR, T1_RR, MIN_RR,
    RVOL_LOOKBACK
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .calendar import previous_trading_day
from .candle_utils import as_ist_index
from .config import SETTINGS
from .dhan_client import DhanClient
from .indicators import add_indicators
from .risk import build_risk_and_targets
from .strategy import evaluate_b1_breakout

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

MARKET_OPEN = "09:15"
SCAN_START_HHMM = int(os.getenv("SCAN_START_HHMM", "930"))
SCAN_END_HHMM = SETTINGS.scan_end_hhmm
MAX_ENTRY_HHMM = int(os.getenv("MAX_ENTRY_HHMM", str(SETTINGS.scan_end_hhmm)))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "12"))
DAILY_LOSS_HALT = float(os.getenv("DAILY_LOSS_HALT_INR", "-400"))
BT_WORKERS = int(os.getenv("SCAN_WORKERS", "3"))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trading_days(from_date: date, to_date: date) -> list[date]:
    """Return calendar days in [from_date, to_date] that are likely trading days.

    Uses the same `previous_trading_day` calendar logic as the live scanner.
    We generate a candidate range and filter out weekends; NSE holidays are not
    separately encoded here — days with no data for any symbol will simply
    produce zero trades and are excluded from summary stats automatically.
    """
    days = []
    cur = from_date
    while cur <= to_date:
        if cur.weekday() < 5:  # Mon–Fri
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _hhmm(ts: pd.Timestamp) -> int:
    return ts.hour * 100 + ts.minute


def _load_universe_from_state(state_path: Path) -> list[dict]:
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return data.get("universe", [])
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol data fetch
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_5m(dhan: DhanClient, item: dict, from_date: date, to_date: date) -> tuple[str, pd.DataFrame]:
    sym = item["symbol"]
    sid = item["security_id"]
    # Fetch a few extra days before from_date for RVOL warm-up (indicator lookback)
    fetch_from = (from_date - timedelta(days=30)).isoformat()
    fetch_to = (to_date + timedelta(days=1)).isoformat()
    try:
        df = dhan.historical_intraday_df(
            security_id=sid,
            from_date=fetch_from,
            to_date=fetch_to,
            interval=5,
        )
        if df is not None and not df.empty:
            df = as_ist_index(df)
        return sym, df if df is not None else pd.DataFrame()
    except Exception as exc:
        LOG.warning("%s fetch failed: %s", sym, exc)
        return sym, pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Single-day simulation for one symbol
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_day(sym: str, df5_all: pd.DataFrame, trading_date: date, prev_close: float, prev_volume: float) -> dict | None:
    """Return a signal dict (with pnl/exit fields) or None if no signal fired."""

    if df5_all.empty:
        return None
    day_mask = df5_all.index.date == trading_date
    day_df = df5_all[day_mask]
    if len(day_df) < 6:
        return None

    # ORB: the 09:15 candle
    orb_rows = day_df[day_df.index.time == pd.Timestamp("09:15").time()]
    if orb_rows.empty:
        return None
    orb_row = orb_rows.iloc[0]
    orb = {
        "high": float(orb_row["high"]),
        "low": float(orb_row["low"]),
        "close": float(orb_row["close"]),
        "timestamp": orb_row.name.isoformat(),
        "date": str(trading_date),
        "time": "09:15",
    }

    # Include prior day data for RVOL / indicator warm-up
    prior_mask = df5_all.index.date < trading_date
    prior_df = df5_all[prior_mask].tail(300)  # keep last 300 candles (~5 days)

    # Walk scan window: 09:30 onwards up to SCAN_END_HHMM
    scan_candles = day_df[day_df.index.time >= pd.Timestamp("09:30").time()]

    for i in range(len(scan_candles)):
        candle_ts = scan_candles.index[i]
        hhmm = _hhmm(candle_ts)
        if hhmm > SCAN_END_HHMM:
            break
        if hhmm > MAX_ENTRY_HHMM:
            break

        # Build rolling window including today's candles up to and including current
        today_slice = day_df[day_df.index <= candle_ts]
        df_window = pd.concat([prior_df, today_slice])
        if len(df_window) < 30:
            continue

        try:
            df_ind = add_indicators(df_window, rvol_lookback=SETTINGS.rvol_lookback)
        except Exception:
            continue
        if df_ind.empty:
            continue

        setup = evaluate_b1_breakout(
            df_ind,
            orb=orb,
            daily_close=prev_close,
            daily_volume=prev_volume,
            symbol=sym,
        )
        if setup is None:
            continue

        direction = setup["direction"]
        entry = float(setup["setup_15m_close"])  # entry at close of signal candle
        sl = float(orb["low"]) if direction == "BUY" else float(orb["high"])

        risk_obj, err = build_risk_and_targets(
            direction=direction,
            entry=entry,
            sl=sl,
            min_stop_distance_percent=SETTINGS.min_stop_distance_percent,
            max_stop_distance_percent=SETTINGS.max_stop_distance_percent,
            t1_rr=SETTINGS.t1_rr,
            t2_rr=SETTINGS.t2_rr,
            t3_rr=SETTINGS.t3_rr,
            min_rr=SETTINGS.min_rr,
        )
        if risk_obj is None:
            continue

        # Signal accepted — simulate exit on remaining candles of the day
        t1 = risk_obj["t1"]
        future = day_df[day_df.index > candle_ts]

        exit_price = None
        exit_reason = "EOD_SQUARE_OFF"
        exit_ts = None

        for _, fc in future.iterrows():
            fc_ts = fc.name
            if fc_ts.time() >= pd.Timestamp("15:30").time():
                break
            fc_low = float(fc["low"])
            fc_high = float(fc["high"])
            if direction == "BUY":
                if fc_low <= sl:
                    exit_price = sl
                    exit_reason = "SL_HIT"
                    exit_ts = fc_ts
                    break
                if fc_high >= t1:
                    exit_price = t1
                    exit_reason = "T1_HIT"
                    exit_ts = fc_ts
                    break
            else:
                if fc_high >= sl:
                    exit_price = sl
                    exit_reason = "SL_HIT"
                    exit_ts = fc_ts
                    break
                if fc_low <= t1:
                    exit_price = t1
                    exit_reason = "T1_HIT"
                    exit_ts = fc_ts
                    break

        if exit_price is None:
            # EOD square-off at last candle's close before 15:30
            eod = day_df[day_df.index.time < pd.Timestamp("15:30").time()]
            if not eod.empty:
                exit_price = float(eod.iloc[-1]["close"])
                exit_ts = eod.index[-1]

        if exit_price is None:
            continue

        pnl = round((exit_price - entry) if direction == "BUY" else (entry - exit_price), 2)

        return {
            "symbol": sym,
            "date": str(trading_date),
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "t1": t1,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "exit_ts": exit_ts.isoformat() if exit_ts is not None else None,
            "pnl": pnl,
            "trade_quality_score": float(setup.get("trade_quality_score", 0)),
            "rvol": float(setup.get("setup_15m_rvol", 0)),
            "rsi": float(setup.get("setup_15m_rsi14", 0)),
            "risk_percent": risk_obj["risk_percent"],
            "signal_ts": candle_ts.isoformat(),
        }

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Full backtest
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(
    dhan: DhanClient,
    universe: list[dict],
    from_date: date,
    to_date: date,
    workers: int = BT_WORKERS,
) -> dict:
    days = _trading_days(from_date, to_date)
    LOG.info("Backtest | %s → %s | %d candidate days | %d symbols | workers=%d",
             from_date, to_date, len(days), len(universe), workers)

    # ── Step 1: Fetch 5M data for all symbols in parallel ──────────────────
    LOG.info("Fetching 5M intraday data ...")
    symbol_data: dict[str, pd.DataFrame] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch_5m, dhan, item, from_date, to_date): item["symbol"]
                for item in universe}
        for fut in as_completed(futs):
            sym, df = fut.result()
            if df is not None and not df.empty:
                # Add indicators once for the full range (efficient)
                try:
                    df = add_indicators(df, rvol_lookback=SETTINGS.rvol_lookback)
                    symbol_data[sym] = df
                except Exception as exc:
                    LOG.warning("%s indicator build failed: %s", sym, exc)
            else:
                LOG.info("%s: no data", sym)

    LOG.info("Data ready: %d/%d symbols", len(symbol_data), len(universe))

    # Build a quick lookup: symbol → prev_close/prev_volume (from universe)
    sym_meta = {item["symbol"]: item for item in universe}

    # ── Step 2: Day-by-day simulation ──────────────────────────────────────
    all_trades: list[dict] = []
    daily_summaries: list[dict] = []

    for trading_date in days:
        prev_day = previous_trading_day(trading_date)
        day_signals: list[dict] = []
        daily_pnl = 0.0

        for sym, df5 in symbol_data.items():
            meta = sym_meta.get(sym, {})
            # Use prev_close / prev_volume from live daily data where possible,
            # otherwise fall back to universe snapshot (may be stale for older dates).
            prev_df_rows = df5[df5.index.date == prev_day]
            if not prev_df_rows.empty:
                prev_close = float(prev_df_rows.iloc[-1]["close"])
                prev_volume = float(prev_df_rows["volume"].sum())
            else:
                prev_close = float(meta.get("prev_close", 500))
                prev_volume = float(meta.get("prev_volume", 500000))

            if prev_close <= SETTINGS.min_price:
                continue
            if prev_volume <= SETTINGS.min_prev_volume:
                continue

            trade = _simulate_day(sym, df5, trading_date, prev_close, prev_volume)
            if trade:
                day_signals.append(trade)

        # Sort by score desc, apply MAX_OPEN_POSITIONS cap
        day_signals.sort(key=lambda x: -x["trade_quality_score"])
        accepted = day_signals[:MAX_OPEN_POSITIONS]

        # Apply DAILY_LOSS_HALT: skip further entries once halt crossed
        for trade in accepted:
            if daily_pnl <= DAILY_LOSS_HALT:
                trade = {**trade, "exit_reason": "DAILY_HALT_SKIPPED", "pnl": 0.0}
            else:
                daily_pnl += trade["pnl"]
            all_trades.append(trade)

        real_trades = [t for t in accepted if t.get("exit_reason") != "DAILY_HALT_SKIPPED"]
        wins = [t for t in real_trades if t["pnl"] > 0]
        losses = [t for t in real_trades if t["pnl"] < 0]
        day_pnl = sum(t["pnl"] for t in real_trades)

        if real_trades:
            daily_summaries.append({
                "date": str(trading_date),
                "pnl": round(day_pnl, 2),
                "wins": len(wins),
                "losses": len(losses),
                "total": len(real_trades),
                "win_rate": round(len(wins) / len(real_trades) * 100, 1),
                "best": max(real_trades, key=lambda x: x["pnl"])["symbol"],
                "best_pnl": max(real_trades, key=lambda x: x["pnl"])["pnl"],
                "worst": min(real_trades, key=lambda x: x["pnl"])["symbol"],
                "worst_pnl": min(real_trades, key=lambda x: x["pnl"])["pnl"],
            })
            LOG.info("%-12s  trades=%2d  W=%2d  L=%2d  WR=%5.1f%%  PnL=%+8.2f",
                     trading_date, len(real_trades), len(wins), len(losses),
                     len(wins) / len(real_trades) * 100, day_pnl)
        else:
            LOG.info("%-12s  no trades", trading_date)

    # ── Step 3: Aggregate stats ─────────────────────────────────────────────
    real = [t for t in all_trades if t.get("exit_reason") != "DAILY_HALT_SKIPPED"]
    win_trades = [t for t in real if t["pnl"] > 0]
    loss_trades = [t for t in real if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in real)
    total_win = sum(t["pnl"] for t in win_trades)
    total_loss = abs(sum(t["pnl"] for t in loss_trades))

    stats = {
        "from_date": str(from_date),
        "to_date": str(to_date),
        "trading_days": len(daily_summaries),
        "total_trades": len(real),
        "wins": len(win_trades),
        "losses": len(loss_trades),
        "win_rate": round(len(win_trades) / len(real) * 100, 2) if real else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(total_win / len(win_trades), 2) if win_trades else 0,
        "avg_loss": round(-total_loss / len(loss_trades), 2) if loss_trades else 0,
        "profit_factor": round(total_win / total_loss, 3) if total_loss else float("inf"),
        "expectancy_per_trade": round(total_pnl / len(real), 2) if real else 0,
        "winning_days": len([d for d in daily_summaries if d["pnl"] > 0]),
        "losing_days": len([d for d in daily_summaries if d["pnl"] < 0]),
        "params": {
            "MIN_TRADE_SCORE": SETTINGS.min_trade_score,
            "MIN_RR": SETTINGS.min_rr,
            "T1_RR": SETTINGS.t1_rr,
            "T2_RR": SETTINGS.t2_rr,
            "T3_RR": SETTINGS.t3_rr,
            "MIN_15M_RVOL": SETTINGS.min_15m_rvol,
            "MAX_STOP_DISTANCE_PERCENT": SETTINGS.max_stop_distance_percent,
            "MAX_OPEN_POSITIONS": MAX_OPEN_POSITIONS,
            "DAILY_LOSS_HALT_INR": DAILY_LOSS_HALT,
            "SCAN_END_HHMM": SCAN_END_HHMM,
        },
    }

    return {
        "stats": stats,
        "daily": daily_summaries,
        "trades": real,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _setup_logging():
    class _ISTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from datetime import datetime as _dt
            t = _dt.fromtimestamp(record.created, tz=IST)
            return t.strftime("%Y-%m-%d %H:%M:%S IST")
    h = logging.StreamHandler()
    h.setFormatter(_ISTFormatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logging.root.addHandler(h)
    logging.root.setLevel(logging.INFO)


def main():
    _setup_logging()

    p = argparse.ArgumentParser(description="B1 ORB standalone backtest")
    p.add_argument("--from", dest="from_date", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=str(date.today()), help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--symbols", default="", help="Comma-separated symbol list (overrides universe)")
    p.add_argument("--workers", type=int, default=BT_WORKERS, help=f"Parallel fetch workers (default {BT_WORKERS})")
    p.add_argument("--out", default="backtest_results.json", help="Output JSON path (default: backtest_results.json)")
    p.add_argument("--state", default="state/runtime_state_paper.json", help="Universe source state file")
    args = p.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)

    dhan = DhanClient()

    if args.symbols:
        raw_syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        LOG.info("Building symbol map for %d custom symbols ...", len(raw_syms))
        mapping = dhan.build_symbol_map(raw_syms)
        universe = [{"symbol": s, **v} for s, v in mapping.items()]
    else:
        universe = _load_universe_from_state(Path(args.state))
        if not universe:
            LOG.info("State file empty — building universe from scratch (slower) ...")
            from .nse_universe import build_universe
            universe = build_universe(dhan)

    if not universe:
        LOG.error("Empty universe — aborting")
        sys.exit(1)

    LOG.info("Universe: %d symbols | date range: %s → %s", len(universe), from_date, to_date)

    t0 = time.time()
    results = run_backtest(dhan, universe, from_date, to_date, workers=args.workers)
    elapsed = time.time() - t0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    s = results["stats"]
    LOG.info("")
    LOG.info("═" * 65)
    LOG.info("  BACKTEST RESULTS  %s → %s", s["from_date"], s["to_date"])
    LOG.info("═" * 65)
    LOG.info("  Trading days : %d  (winning %d / losing %d)",
             s["trading_days"], s["winning_days"], s["losing_days"])
    LOG.info("  Total trades : %d  (W=%d  L=%d  WR=%.1f%%)",
             s["total_trades"], s["wins"], s["losses"], s["win_rate"])
    LOG.info("  Net P&L      : %+.2f", s["total_pnl"])
    LOG.info("  Avg win      : %+.2f    Avg loss : %.2f",
             s["avg_win"], s["avg_loss"])
    LOG.info("  Profit factor: %.3f", s["profit_factor"])
    LOG.info("  Expectancy   : %+.2f / trade", s["expectancy_per_trade"])
    LOG.info("  Run time     : %.0fs", elapsed)
    LOG.info("═" * 65)
    LOG.info("  Full results → %s", out_path)
    LOG.info("═" * 65)

    # Also write a simple CSV for spreadsheet review
    if results["trades"]:
        csv_path = out_path.with_suffix(".csv")
        rows = results["trades"]
        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)
        LOG.info("  Trade detail → %s", csv_path)


if __name__ == "__main__":
    main()
