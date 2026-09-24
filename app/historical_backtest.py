"""90-day historical backtest on real NSE data."""
from __future__ import annotations

import logging
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from .config import SETTINGS
from .indicators import add_indicators
from .strategy import evaluate_b1_breakout

LOG = logging.getLogger(__name__)


def load_historical_data(csv_path: str) -> pd.DataFrame:
    """Load historical 15m data from CSV."""
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.set_index('timestamp')
    df = df.sort_index()
    return df


def historical_backtest(csv_path: str = "data/historical/15m_last_90d_2026-09-22.csv"):
    """Run backtest on 90 days of historical data."""

    hist_file = Path(csv_path)
    if not hist_file.exists():
        LOG.error("Historical data file not found: %s", csv_path)
        return

    LOG.info("=" * 80)
    LOG.info("HISTORICAL BACKTEST | 90 Days of Real NSE Data")
    LOG.info("=" * 80)
    LOG.info("Loading data from: %s", csv_path)

    df_all = load_historical_data(csv_path)
    LOG.info("Loaded %d total candles", len(df_all))

    # Group by symbol
    symbols = df_all['symbol'].unique()
    LOG.info("Symbols: %d", len(symbols))

    total_candles = 0
    total_setups = 0
    total_rejections = 0

    rejection_breakdown = defaultdict(int)
    setup_list = []
    rejection_list = []

    liquid_stocks = {"RELIANCE", "TCS", "INFY", "HDFC", "ICICIBANK", "WIPRO", "MARUTI", "BAJAJ-AUTO",
                     "LT", "SBIN", "HINDUNILVR", "ASIANPAINT", "BHARTIARTL", "DMART", "SUNPHARMA"}
    symbols_to_test = [s for s in sorted(symbols) if s in liquid_stocks]
    LOG.info("Testing %d high-liquid stocks: %s", len(symbols_to_test), ", ".join(symbols_to_test[:10]))

    for symbol in symbols_to_test:
        LOG.info("\n[%s] Processing...", symbol)

        df_sym = df_all[df_all['symbol'] == symbol].copy()
        if df_sym.empty or len(df_sym) < 100:
            LOG.info("[%s] Insufficient data (%d candles), skipping", symbol, len(df_sym))
            continue

        df_sym = df_sym.sort_index()

        # Process day by day
        dates = df_sym.index.date
        unique_dates = pd.Series(dates).unique()

        symbol_setups = 0
        symbol_rejections = 0
        symbol_candles = 0

        for date_idx, trading_date in enumerate(unique_dates[1:], 1):  # Skip first day (need ORB)
            day_data = df_sym[df_sym.index.date == trading_date].copy()
            if len(day_data) < 5:  # Need at least 5 candles for indicators
                continue

            # Get previous day's ORB
            prev_date = unique_dates[date_idx - 1] if date_idx > 0 else None
            if prev_date is None:
                continue

            prev_day = df_sym[df_sym.index.date == prev_date].copy()
            if prev_day.empty:
                continue

            # ORB is first 15m candle (09:15)
            orb_candle = prev_day[prev_day.index.strftime("%H:%M") == "09:15"]
            if orb_candle.empty:
                orb_candle = prev_day.iloc[0:1]

            if orb_candle.empty:
                continue

            orb = {
                "high": float(orb_candle.iloc[0]["high"]),
                "low": float(orb_candle.iloc[0]["low"]),
            }

            daily_close = float(prev_day["close"].iloc[-1])
            daily_volume = int(prev_day["volume"].sum())

            # Test each candle in current day
            for idx in range(5, len(day_data)):
                df_subset = pd.concat([prev_day, day_data.iloc[:idx+1]]).copy()

                if len(df_subset) < 10:
                    continue

                # Add indicators
                try:
                    df_subset = add_indicators(df_subset, rvol_lookback=SETTINGS.rvol_lookback)
                except Exception as e:
                    LOG.debug("[%s] Indicator error: %s", symbol, e)
                    continue

                if df_subset.empty or df_subset.index.empty:
                    continue

                current = df_subset.iloc[-1]
                close = float(current.get("close", 0))

                # Only check potential breakouts
                if close > orb["high"] or close < orb["low"]:
                    symbol_candles += 1
                    total_candles += 1

                    setup = evaluate_b1_breakout(
                        df_subset,
                        orb=orb,
                        daily_close=daily_close,
                        daily_volume=daily_volume,
                        symbol=symbol,
                    )

                    if setup is not None:
                        symbol_setups += 1
                        total_setups += 1
                        setup_list.append({
                            "symbol": symbol,
                            "date": df_subset.index[-1],
                            "direction": setup.get("direction"),
                            "rvol": setup.get("setup_15m_rvol"),
                            "rsi": setup.get("setup_15m_rsi14"),
                        })
                    else:
                        symbol_rejections += 1
                        total_rejections += 1
                        rejection_list.append({
                            "symbol": symbol,
                            "date": df_subset.index[-1],
                        })

        if symbol_candles > 0:
            pass_rate = 100 * symbol_setups / symbol_candles
            LOG.info("[%s] %d candles | %d setups | %.1f%% pass rate",
                    symbol, symbol_candles, symbol_setups, pass_rate)

    LOG.info("\n" + "=" * 80)
    LOG.info("BACKTEST RESULTS (90-DAY HISTORICAL DATA)")
    LOG.info("=" * 80)
    LOG.info("Total Breakout Candles:  %d", total_candles)
    LOG.info("Total Setups Generated:  %d", total_setups)
    LOG.info("Total Rejections:        %d", total_rejections)

    if total_candles > 0:
        pass_rate = 100 * total_setups / total_candles
        LOG.info("\n✓ Overall Pass Rate: %.2f%% (target: 20-30%% for strict mode)", pass_rate)

        if pass_rate > 40:
            LOG.info("⚠️  Filters too loose - adjust thresholds tighter")
        elif pass_rate < 5:
            LOG.info("⚠️  Filters too strict - adjust thresholds looser")
        else:
            LOG.info("✓ Filters in acceptable range")

    LOG.info("\n" + "=" * 80)
    LOG.info("SETUP QUALITY SAMPLE")
    LOG.info("=" * 80)

    if setup_list:
        for setup in setup_list[:10]:  # Show first 10 setups
            LOG.info("[%s] %s | %s | RVOL=%.2f | RSI=%.1f",
                    setup["symbol"],
                    setup["date"].strftime("%Y-%m-%d %H:%M"),
                    setup["direction"],
                    float(setup["rvol"]),
                    float(setup["rsi"]))

    LOG.info("\n" + "=" * 80)
    LOG.info("NEXT STEPS")
    LOG.info("=" * 80)

    if total_setups > 0:
        avg_per_day = total_setups / 90
        LOG.info("✓ Average setups per day: %.1f (target: 2-4)", avg_per_day)
        LOG.info("✓ Review setups above to validate filter quality")
        LOG.info("✓ Ready for live Phase 1 validation")
    else:
        LOG.info("⚠️  Zero setups generated - thresholds likely too strict")
        LOG.info("→ Adjust in Phase 2 using tuning matrix")

    LOG.info("=" * 80)

    return {
        "total_candles": total_candles,
        "setups_generated": total_setups,
        "rejections": total_rejections,
        "pass_rate": (100 * total_setups / total_candles) if total_candles > 0 else 0,
        "setups": setup_list,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    results = historical_backtest()
    LOG.info("\n✅ Historical backtest complete!")
    LOG.info("Results: %d setups from %d candles", results["setups_generated"], results["total_candles"])
