"""Quick backtest with sample data for 5-10 stocks, 5 days."""
from __future__ import annotations

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import SETTINGS
from .indicators import add_indicators
from .strategy import evaluate_b1_breakout

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


def generate_sample_data(symbol: str, days: int = 5, candles_per_day: int = 50) -> pd.DataFrame:
    """Generate synthetic 5M candle data for backtesting."""

    np.random.seed(hash(symbol) % 2**32)
    base_price = np.random.uniform(400, 2000)

    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    current_date = datetime.now(IST).date() - timedelta(days=days)
    current_time = datetime(current_date.year, current_date.month, current_date.day, 9, 15, tzinfo=IST)

    for day in range(days):
        current_time = datetime(current_date.year, current_date.month, current_date.day, 9, 15, tzinfo=IST)
        for candle in range(candles_per_day):
            if 9 <= current_time.hour < 15 or (current_time.hour == 15 and current_time.minute < 30):
                price_move = np.random.normal(0, 0.3)
                o = base_price + price_move
                h = o + abs(np.random.normal(0, 0.5))
                l = o - abs(np.random.normal(0, 0.5))
                c = np.random.uniform(l, h)

                # Simulate volume spikes
                base_vol = 50000
                if np.random.random() < 0.2:
                    vol = base_vol * np.random.uniform(1.5, 3.0)  # Volume spike
                else:
                    vol = base_vol

                timestamps.append(current_time)
                opens.append(o)
                highs.append(h)
                lows.append(l)
                closes.append(c)
                volumes.append(int(vol))

                base_price = c  # Next candle starts where last ended
                current_time += timedelta(minutes=5)

        current_date += timedelta(days=1)
        current_time = datetime(current_date.year, current_date.month, current_date.day,
                               9, 15, tzinfo=IST)

    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    }, index=timestamps)

    return add_indicators(df, rvol_lookback=SETTINGS.rvol_lookback)


def quick_backtest(symbols: list = None, days: int = 5):
    """Run quick backtest on sample data."""

    if symbols is None:
        symbols = ["HINDALCO", "RELIANCE", "TCS", "INFY", "WIPRO", "ICICIBANK", "HDFC", "LT", "BAJAJ-AUTO", "MARUTI"]

    symbols = symbols[:10]  # Limit to 10

    LOG.info("=" * 80)
    LOG.info("QUICK BACKTEST | Symbols=%d | Days=%d", len(symbols), days)
    LOG.info("=" * 80)

    total_candles = 0
    total_rejections = 0
    total_setups = 0

    rejection_reasons = {
        "candle_body": 0,
        "ema8_upslope": 0,
        "ema8_downslope": 0,
        "price_vs_ema8": 0,
        "rvol_time_based": 0,
        "consolidation": 0,
        "other": 0,
    }

    for symbol in symbols:
        LOG.info("\n[%s] Generating sample data...", symbol)

        df = generate_sample_data(symbol, days=days)

        if df.empty:
            LOG.info("[%s] No data generated", symbol)
            continue

        LOG.info("[%s] Processing %d candles...", symbol, len(df))

        # Create dummy ORB (09:15 candle)
        orb_candles = df[df.index.strftime("%H:%M") == "09:15"]
        if not orb_candles.empty:
            first_candle = orb_candles.iloc[0]
            orb = {
                "high": float(first_candle["high"]),
                "low": float(first_candle["low"]),
            }
        else:
            orb = {"high": df["high"].iloc[0], "low": df["low"].iloc[0]}

        symbol_setups = 0
        symbol_rejections = 0

        # Test each candle as potential setup
        for idx in range(5, len(df)):  # Need at least 5 previous candles for indicators
            df_subset = df.iloc[:idx+1].copy()

            current_candle = df_subset.iloc[-1]
            close = float(current_candle["close"])

            # Only check if it's a potential breakout
            if close > orb["high"] or close < orb["low"]:
                total_candles += 1

                setup = evaluate_b1_breakout(
                    df_subset,
                    orb=orb,
                    daily_close=float(df_subset["close"].iloc[0]),
                    daily_volume=int(df_subset["volume"].sum()),
                    symbol=symbol,
                )

                if setup is not None:
                    symbol_setups += 1
                    total_setups += 1
                    direction = setup.get("direction")
                    timestamp = df_subset.index[-1]
                    LOG.info("[%s] ✅ SETUP | time=%s | direction=%s | rvol=%.2f",
                            symbol, timestamp.strftime("%H:%M"), direction,
                            float(setup.get("setup_15m_rvol", 0)))
                else:
                    symbol_rejections += 1
                    total_rejections += 1

        LOG.info("[%s] Summary | Breakouts checked: %d | Setups generated: %d | Rejected: %d",
                symbol, total_candles, symbol_setups, symbol_rejections)

    LOG.info("\n" + "=" * 80)
    LOG.info("QUICK BACKTEST SUMMARY")
    LOG.info("=" * 80)
    LOG.info("Total Breakouts Checked: %d", total_candles)
    LOG.info("Total Setups Generated:  %d", total_setups)
    LOG.info("Total Rejections:        %d", total_rejections)

    if total_candles > 0:
        pass_rate = 100 * total_setups / total_candles
        LOG.info("\nSetups Pass Rate: %.1f%% (target: 20-30%% for strict mode)", pass_rate)

    LOG.info("\n" + "=" * 80)
    LOG.info("INTERPRETATION")
    LOG.info("=" * 80)
    LOG.info("✓ Strict mode = 20-30%% of breakouts pass all 5 filters")
    LOG.info("✓ This means: 70-80%% of breakouts are REJECTED (fakeouts filtered)")
    LOG.info("✓ Expected: 2-4 high-quality setups per trading day")
    LOG.info("=" * 80)

    return {
        "total_candles": total_candles,
        "setups_generated": total_setups,
        "rejections": total_rejections,
        "pass_rate": (100 * total_setups / total_candles) if total_candles > 0 else 0,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    symbols = ["HINDALCO", "RELIANCE", "TCS", "INFY", "WIPRO", "ICICIBANK", "HDFC", "LT", "BAJAJ-AUTO", "MARUTI"]
    results = quick_backtest(symbols=symbols, days=5)

    LOG.info("\n✅ Quick backtest complete!")
    LOG.info("Results: %s", results)
