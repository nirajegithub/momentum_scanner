#!/usr/bin/env python3
"""Alert on high-momentum stocks to avoid missing opportunities."""

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .dhan_client import DhanClient
from .nse_universe import build_universe
from .indicators import add_indicators
from .candle_utils import completed_candles
from .state import load
from .telegram import send
from .calendar import previous_trading_day

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

# Alert thresholds
RVOL_THRESHOLD = 5.0  # 5x relative volume = high momentum
RSI_MIN = 30
RSI_MAX = 70


def get_orb_data(dhan, security_id, trading_day):
    """Get ORB for today, fallback to previous day if missing."""
    try:
        raw = dhan.historical_intraday_df(
            security_id=security_id,
            interval=15,
            from_date=trading_day.isoformat(),
            to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
        )

        if raw is None or raw.empty:
            return None, None

        df = pd.DataFrame(raw)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize(IST)

        # Look for 9:15 AM candle today
        rows = df[df.index.strftime("%H:%M") == "09:15"]
        if not rows.empty:
            r = rows.iloc[0]
            return {
                "date": trading_day.isoformat(),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }, "TODAY"

        # Fallback: use previous trading day's ORB
        prev_day = previous_trading_day(trading_day)
        raw_prev = dhan.historical_intraday_df(
            security_id=security_id,
            interval=15,
            from_date=prev_day.isoformat(),
            to_date=(prev_day + pd.Timedelta(days=1)).isoformat(),
        )

        if raw_prev is None or raw_prev.empty:
            return None, None

        df_prev = pd.DataFrame(raw_prev)
        df_prev.index = pd.to_datetime(df_prev.index)
        if df_prev.index.tz is None:
            df_prev.index = df_prev.index.tz_localize(IST)

        rows_prev = df_prev[df_prev.index.strftime("%H:%M") == "09:15"]
        if not rows_prev.empty:
            r = rows_prev.iloc[0]
            return {
                "date": prev_day.isoformat(),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }, "PREVIOUS_DAY"

        return None, None

    except Exception as exc:
        LOG.debug("Failed to get ORB for security_id %s: %s", security_id, exc)
        return None, None


def check_high_momentum_stocks():
    """Scan for high-momentum stocks and send alert."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    ts = datetime.now(IST)
    trading_day = ts.date()

    # Only run during market hours (9:15 AM to 3:30 PM)
    current_time = ts.time()
    market_open = datetime.strptime("09:15", "%H:%M").time()
    market_close = datetime.strptime("15:30", "%H:%M").time()

    if not (market_open <= current_time <= market_close):
        LOG.info("Outside market hours. Skipping high-momentum check.")
        return

    dhan = DhanClient()
    state = load(trading_day)

    if not state.get("universe"):
        LOG.warning("Universe not populated.")
        return

    high_momentum_stocks = []

    for item in state.get("universe", []):
        symbol = item.get("symbol")
        security_id = item.get("security_id")

        if not symbol or security_id is None:
            continue

        try:
            # Fetch 15M data for today
            raw = dhan.historical_intraday_df(
                security_id=security_id,
                interval=15,
                from_date=trading_day.isoformat(),
                to_date=(trading_day + pd.Timedelta(days=1)).isoformat(),
            )

            if raw is None or raw.empty:
                continue

            df15 = completed_candles(raw, ts, 15)
            if df15.empty:
                continue

            df15 = add_indicators(df15, rvol_lookback=20)

            # Get latest 15M candle
            latest = df15.iloc[-1]
            rvol = float(latest.get("rvol", 0))
            rsi = float(latest.get("rsi14", 50))
            close = float(latest["close"])

            # Check for high momentum
            if rvol >= RVOL_THRESHOLD and RSI_MIN <= rsi <= RSI_MAX:
                # Get ORB (today or previous day)
                orb_data, orb_source = get_orb_data(dhan, security_id, trading_day)

                if orb_data:
                    # Check for breakout
                    breakout_side = None
                    if close > orb_data["high"]:
                        breakout_side = "BUY"
                    elif close < orb_data["low"]:
                        breakout_side = "SELL"

                    high_momentum_stocks.append({
                        "symbol": symbol,
                        "rvol": rvol,
                        "rsi": rsi,
                        "close": close,
                        "breakout": breakout_side,
                        "orb_high": orb_data["high"],
                        "orb_low": orb_data["low"],
                        "orb_source": orb_source,
                    })

        except Exception as exc:
            LOG.debug("Error checking %s: %s", symbol, exc)
            pass

    if not high_momentum_stocks:
        LOG.info("No high-momentum stocks found (RVOL >= %.1f)", RVOL_THRESHOLD)
        return

    # Sort by RVOL
    high_momentum_stocks.sort(key=lambda x: x["rvol"], reverse=True)

    # Build alert message
    alert_lines = [
        "<b>⚡ HIGH MOMENTUM STOCKS DETECTED</b>",
        f"<b>Time:</b> {ts.strftime('%H:%M IST')}",
        "",
        f"Found {len(high_momentum_stocks)} high-momentum stocks (RVOL ≥ {RVOL_THRESHOLD}x):",
        "",
    ]

    for i, stock in enumerate(high_momentum_stocks[:10], 1):  # Top 10
        breakout_emoji = "📈" if stock["breakout"] == "BUY" else "📉" if stock["breakout"] == "SELL" else "—"
        orb_note = " (prev day ORB)" if stock["orb_source"] == "PREVIOUS_DAY" else ""

        alert_lines.append(
            f"<b>{i}. {stock['symbol']}</b> {breakout_emoji}"
        )
        alert_lines.append(
            f"   RVOL: <b>{stock['rvol']:.2f}x</b> | RSI: <b>{stock['rsi']:.1f}</b> | "
            f"Price: ₹{stock['close']:.2f}"
        )
        if stock["breakout"]:
            alert_lines.append(
                f"   {stock['breakout']} breakout - ORB [{stock['orb_low']:.2f}, {stock['orb_high']:.2f}]{orb_note}"
            )
        alert_lines.append("")

    alert_lines.append(
        "<i>⚠️ These stocks have high momentum but may not meet full strategy criteria yet. "
        "Monitor for setup confirmation.</i>"
    )

    alert_message = "\n".join(alert_lines)

    # Send alert
    LOG.info("Sending high-momentum alert for %d stocks", len(high_momentum_stocks))
    sent = send(alert_message)

    if sent:
        LOG.info("✓ High-momentum alert sent successfully")
    else:
        LOG.warning("Failed to send high-momentum alert")


if __name__ == "__main__":
    check_high_momentum_stocks()
