"""Backtest 5 filters on historical data to validate improvements."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .dhan_client import DhanClient
from .config import SETTINGS
from .indicators import add_indicators
from .strategy import evaluate_b1_breakout
from .candle_utils import completed_candles
from .nse_universe import build_universe

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


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


def backtest_filters(dhan: DhanClient, symbols: list, days_back: int = 30):
    """Backtest 5 filters on historical data."""
    end_date = datetime.now(IST).date()
    start_date = end_date - timedelta(days=days_back)

    LOG.info("=" * 80)
    LOG.info("BACKTEST START | period=%s to %s | symbols=%d | days=%d",
             start_date, end_date, len(symbols), days_back)
    LOG.info("=" * 80)

    results = {
        "total_candles_checked": 0,
        "setups_generated": 0,
        "filter_rejections": {
            "candle_body": 0,
            "ema8_upslope": 0,
            "ema8_downslope": 0,
            "price_vs_ema8": 0,
            "rvol_time_based": 0,
            "consolidation": 0,
            "other": 0,
        },
        "by_symbol": {},
    }

    for symbol_data in symbols:
        symbol = symbol_data.get("symbol")
        security_id = symbol_data.get("security_id")
        prev_close = symbol_data.get("prev_close")
        prev_volume = symbol_data.get("prev_volume")

        if not symbol or not security_id:
            continue

        LOG.info("\n[%s] Fetching 5M data...", symbol)

        try:
            raw = dhan.historical_intraday_df(
                security_id=security_id,
                interval=5,
                from_date=start_date.isoformat(),
                to_date=(end_date + timedelta(days=1)).isoformat(),
                retry_on_empty=True,
                max_retries=3,
                retry_delay_seconds=2.0,
            )

            if raw is None or raw.empty:
                LOG.info("[%s] No data available", symbol)
                continue

            df5 = completed_candles(raw, datetime.now(IST), 5)
            if df5.empty:
                LOG.info("[%s] No completed candles", symbol)
                continue

            df5 = add_indicators(df5, rvol_lookback=SETTINGS.rvol_lookback)
            df5 = _as_ist_index(df5)

            symbol_setups = 0
            symbol_rejections = {k: 0 for k in results["filter_rejections"].keys()}

            for idx in range(1, len(df5)):
                candle_ts = df5.index[idx]
                df_15m = df5.iloc[:idx+1].copy()

                setup = evaluate_b1_breakout(
                    df_15m,
                    orb={"high": 0, "low": 0},  # Dummy ORB for testing
                    daily_close=float(prev_close) if prev_close else 100,
                    daily_volume=int(prev_volume) if prev_volume else 1000000,
                    symbol=symbol,
                )

                if setup is not None:
                    symbol_setups += 1
                    LOG.info("[%s] SETUP GENERATED | time=%s | direction=%s",
                            symbol, candle_ts.strftime("%Y-%m-%d %H:%M"), setup.get("direction"))
                else:
                    results["total_candles_checked"] += 1

            results["setups_generated"] += symbol_setups
            results["by_symbol"][symbol] = symbol_setups

            if symbol_setups > 0:
                LOG.info("[%s] ✅ %d setups generated over %d days",
                        symbol, symbol_setups, days_back)
            else:
                LOG.info("[%s] ❌ No setups generated (all filters strict)", symbol)

        except Exception as exc:
            LOG.warning("[%s] Error during backtest: %s", symbol, exc)
            continue

    LOG.info("\n" + "=" * 80)
    LOG.info("BACKTEST SUMMARY")
    LOG.info("=" * 80)
    LOG.info("Total Candles Checked: %d", results["total_candles_checked"])
    LOG.info("Total Setups Generated: %d", results["setups_generated"])

    if results["by_symbol"]:
        LOG.info("\nSetups by Symbol:")
        for symbol, count in sorted(results["by_symbol"].items(), key=lambda x: -x[1]):
            LOG.info("  %s: %d", symbol, count)

    LOG.info("\n" + "=" * 80)
    LOG.info("NEXT STEPS:")
    LOG.info("  1. If setups < 1/day: Filters may be too strict")
    LOG.info("  2. If setups > 5/day: Filters may be too loose")
    LOG.info("  3. Expected: 2-4 setups/day = HIGH quality")
    LOG.info("=" * 80)

    return results


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        dhan = DhanClient()
        universe = build_universe(dhan)

        if not universe:
            LOG.error("Failed to build universe")
            sys.exit(1)

        # Backtest on 37 symbols, 30 days
        results = backtest_filters(dhan, universe, days_back=30)

    except Exception as exc:
        LOG.error("Backtest failed: %s", exc, exc_info=True)
        sys.exit(1)
