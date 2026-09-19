from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import json
import logging

from .config import SETTINGS
from .calendar import previous_trading_day
from .dhan_client import DhanClient


LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Base universe: a static NIFTY 500 constituent list, refreshed by hand
# every few months (NSE Indices rebalances it twice a year), instead of
# a live nseindia.com call. Drop a new NSE "Market Watch" CSV export for
# NIFTY 500 into app/data/ and update NIFTY500_FILE / re-run the loader
# script to refresh it.
# ---------------------------------------------------------------------
NIFTY500_FILE = Path(__file__).parent / "data" / "nifty500_constituents.json"

# ---------------------------------------------------------------------
# Dynamic "volume gainer" discovery — computed from Dhan's own market
# feed instead of scraping nseindia.com. This compares each candidate's
# cumulative traded volume so far today against its own historical daily
# average (scaled to the same point in the trading day), rather than
# relying on NSE's website's internal ranking endpoint.
# ---------------------------------------------------------------------
MARKET_OPEN_MINUTES = 9 * 60 + 15   # 09:15 IST
MARKET_CLOSE_MINUTES = 15 * 60 + 30  # 15:30 IST
TRADING_MINUTES_PER_DAY = MARKET_CLOSE_MINUTES - MARKET_OPEN_MINUTES  # 375

IST = ZoneInfo("Asia/Kolkata")


def load_nifty500_constituents() -> dict:
    """Load the static NIFTY 500 symbol list from app/data/.

    Raises FileNotFoundError with a clear message if the file is missing,
    rather than silently returning an empty universe.
    """
    if not NIFTY500_FILE.exists():
        raise FileNotFoundError(
            f"NIFTY 500 constituent file not found at {NIFTY500_FILE}. "
            "Export the NIFTY 500 list from NSE's website (Market Watch "
            "CSV download) and regenerate this file."
        )

    with open(NIFTY500_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    symbols = sorted({str(s).strip().upper() for s in data.get("symbols", [])})
    if not symbols:
        raise ValueError(f"NIFTY 500 constituent file at {NIFTY500_FILE} has no symbols.")

    return {"symbols": symbols, "as_of": data.get("as_of"), "index": data.get("index")}


def _elapsed_trading_fraction(ts) -> float:
    """Fraction of the trading day elapsed at ts, clamped to (small, 1.0].

    Used so a stock isn't unfairly flagged as a "volume gainer" simply
    because it's 9:35 AM and cumulative volume naturally looks small next
    to a full day's average.
    """
    minutes = ts.hour * 60 + ts.minute - MARKET_OPEN_MINUTES
    fraction = minutes / TRADING_MINUTES_PER_DAY
    return max(0.05, min(fraction, 1.0))


def _candidate_pool(dhan: DhanClient) -> list[dict]:
    """NSE cash-equity candidates from Dhan's own security master.

    Capped by SETTINGS.volume_gainer_candidate_limit to keep the once-daily
    baseline pull (one historical_daily_df call per candidate) practical.
    Verify this limit against your Dhan plan's rate limits and raise it if
    you have headroom and want broader universe coverage.
    """
    df = dhan.security_master()

    required = ["EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        LOG.warning("Volume gainer candidate pool: missing master columns %s", missing)
        return []

    mask = (
        (df["EXCH_ID"].astype(str).str.upper() == "NSE")
        & (df["SEGMENT"].astype(str).str.upper() == "E")
        & (df["INSTRUMENT"].astype(str).str.upper() == "EQUITY")
    )
    # If a series column is present, restrict to the plain "EQ" series
    # (avoid SME/other series that trade too thinly to be useful).
    for series_col in ("SERIES", "SM_SYMBOL_SERIES"):
        if series_col in df.columns:
            mask &= df[series_col].astype(str).str.upper() == "EQ"
            break

    df = df.loc[mask].copy()
    df = df.drop_duplicates(subset=["UNDERLYING_SYMBOL"])
    df = df.sort_values("UNDERLYING_SYMBOL").head(SETTINGS.volume_gainer_candidate_limit)

    return [
        {
            "symbol": str(row["UNDERLYING_SYMBOL"]).strip().upper(),
            "security_id": str(row["SECURITY_ID"]),
        }
        for _, row in df.iterrows()
    ]


def _build_volume_baseline(dhan: DhanClient, candidates: list[dict], prev_day) -> dict[str, dict]:
    """Once-per-day average daily volume + latest close, per candidate.

    One historical_daily_df call per candidate over the trailing
    VOLUME_GAINER_BASELINE_DAYS trading days. Failures for individual
    symbols are skipped rather than aborting the whole baseline build.
    """
    from_date = (prev_day - timedelta(days=SETTINGS.volume_gainer_baseline_days * 2)).isoformat()
    to_date = (prev_day + timedelta(days=1)).isoformat()

    baseline: dict[str, dict] = {}
    for item in candidates:
        symbol = item["symbol"]
        try:
            df = dhan.historical_daily_df(item["security_id"], from_date, to_date)
        except Exception as exc:
            LOG.warning("Volume gainer baseline failed for %s: %s", symbol, exc)
            continue

        if df.empty:
            continue

        df = df.tail(SETTINGS.volume_gainer_baseline_days)
        avg_volume = float(df["volume"].mean())
        last_close = float(df["close"].iloc[-1])
        if avg_volume > 0:
            baseline[symbol] = {
                "avg_volume": avg_volume,
                "last_close": last_close,
                "security_id": item["security_id"],
            }

    LOG.info("Volume gainer baseline built: %d/%d candidates", len(baseline), len(candidates))
    return baseline


def refresh_dynamic_volume_gainers(dhan: DhanClient, state, ts):
    """Refresh the volume-gainer universe every 10 minutes, via Dhan only.

    Existing universe entries are preserved. Only genuinely new symbols
    are added, so intraday scanner state is not replaced or reset.
    """
    minute_bucket = ts.replace(minute=(ts.minute // 10) * 10, second=0, microsecond=0)
    bucket_key = minute_bucket.isoformat()

    if state.get("volume_gainers_last_refresh") == bucket_key:
        return False

    today = ts.date()
    baseline = state.get("volume_gainer_baseline")
    if not isinstance(baseline, dict) or baseline.get("date") != today.isoformat():
        prev_day = previous_trading_day(today)
        candidates = _candidate_pool(dhan)
        if not candidates:
            LOG.warning("Volume gainer refresh skipped: empty candidate pool")
            return False
        built = _build_volume_baseline(dhan, candidates, prev_day)
        baseline = {"date": today.isoformat(), "symbols": built}
        state["volume_gainer_baseline"] = baseline

    symbol_baseline = baseline.get("symbols", {})
    if not symbol_baseline:
        LOG.warning("Volume gainer refresh skipped: empty baseline")
        return False

    security_ids = [row["security_id"] for row in symbol_baseline.values()]
    try:
        quotes = dhan.quote_batch(security_ids)
    except Exception as exc:
        LOG.warning("Volume gainer quote fetch failed: %s", exc)
        return False

    elapsed_fraction = _elapsed_trading_fraction(ts)
    symbols = []
    for symbol, row in symbol_baseline.items():
        quote = quotes.get(row["security_id"])
        if not quote:
            continue

        price = quote["ltp"]
        volume_so_far = quote["volume"]
        expected_by_now = row["avg_volume"] * elapsed_fraction
        if expected_by_now <= 0:
            continue

        rvol = volume_so_far / expected_by_now
        if (
            price >= SETTINGS.min_price
            and volume_so_far > SETTINGS.min_prev_volume
            and rvol >= SETTINGS.volume_gainer_rvol_threshold
        ):
            symbols.append(symbol)

    symbols = sorted(set(symbols))

    existing = {str(item.get("symbol", "")).upper() for item in state.get("universe", [])}
    new_symbols = [symbol for symbol in symbols if symbol not in existing]

    if not new_symbols:
        state["volume_gainers_last_refresh"] = bucket_key
        LOG.info("Volume Gainers refresh | eligible=%d | new=0 | universe=%d", len(symbols), len(existing))
        return True

    added = 0
    for symbol in new_symbols:
        row = symbol_baseline.get(symbol)
        if not row:
            continue
        state.setdefault("universe", []).append(
            {
                "symbol": symbol,
                "security_id": row["security_id"],
                "exchange_segment": "NSE_EQ",
                "instrument": "EQUITY",
                "indices": ["VOLUME_GAINERS"],
                "membership_count": 1,
                "universe_source": "DHAN_VOLUME_GAINERS",
                "volume_gainer_added_at": ts.isoformat(),
            }
        )
        added += 1

    state["volume_gainers_last_refresh"] = bucket_key

    LOG.info(
        "Volume Gainers refresh | eligible=%d | new=%d | added=%d | universe=%d",
        len(symbols), len(new_symbols), added, len(state.get("universe", [])),
    )

    return True


def build_universe(dhan: DhanClient, as_of_date=None):

    # ---------------------------------------------------------
    # 1. Load the NIFTY 500 constituent list (static, not live NSE)
    # ---------------------------------------------------------

    constituents = load_nifty500_constituents()
    symbols = constituents["symbols"]
    membership = {symbol: {"NIFTY500"} for symbol in symbols}

    LOG.info(
        "NIFTY 500 universe loaded from %s (as_of=%s): %d symbols",
        NIFTY500_FILE.name,
        constituents.get("as_of", "unknown"),
        len(symbols),
    )

    # ---------------------------------------------------------
    # 2. Dhan Security ID mapping
    # ---------------------------------------------------------

    mapping = dhan.build_symbol_map(symbols)

    candidates = []

    for symbol in symbols:

        meta = mapping.get(symbol)

        if not meta:

            LOG.warning(
                "Missing Dhan security_id: %s",
                symbol,
            )

            continue

        candidates.append(
            {
                "symbol": symbol,
                **meta,
                "indices": sorted(
                    membership[symbol]
                ),
                "membership_count": len(
                    membership[symbol]
                ),
            }
        )

    LOG.info(
        "Dhan-mapped candidates: %d",
        len(candidates),
    )

    # ---------------------------------------------------------
    # 3. Previous trading day
    # ---------------------------------------------------------

    if as_of_date:
        if isinstance(as_of_date, str):
            today = datetime.strptime(
                as_of_date,
                "%Y-%m-%d",
            ).date()
        else:
            today = as_of_date
    else:
        today = datetime.now(IST).date()
    
    prev_day = previous_trading_day(today)

    LOG.info(
        "Using previous trading day: %s",
        prev_day.isoformat(),
    )

    # Dhan's toDate is non-inclusive.
    from_date = prev_day.isoformat()
    to_date = (
        prev_day + timedelta(days=1)
    ).isoformat()

    LOG.info(
        "Daily historical range: from=%s to=%s",
        from_date,
        to_date,
    )

    # ---------------------------------------------------------
    # 4. Apply price + previous-day volume filters
    # ---------------------------------------------------------

    result = []

    price_rejected = 0
    volume_rejected = 0
    data_failed = 0

    for item in candidates:

        symbol = item["symbol"]
        security_id = item["security_id"]

        try:

            df = dhan.historical_daily_df(
                security_id=security_id,
                from_date=from_date,
                to_date=to_date,
            )

            if df.empty:

                LOG.warning(
                    "%s: no daily data",
                    symbol,
                )

                data_failed += 1
                continue

            # Find the previous trading-day candle.
            prev_rows = df[
                df.index.date == prev_day
            ]

            if prev_rows.empty:

                LOG.warning(
                    "%s: no candle for %s",
                    symbol,
                    prev_day.isoformat(),
                )

                data_failed += 1
                continue

            candle = prev_rows.iloc[-1]

            close_price = float(
                candle["close"]
            )

            prev_volume = int(
                candle["volume"]
            )

            # -------------------------------------------------
            # Price filter
            # -------------------------------------------------

            if close_price <= SETTINGS.min_price:

                price_rejected += 1

                LOG.info(
                    "%s rejected: price %.2f <= %.2f",
                    symbol,
                    close_price,
                    SETTINGS.min_price,
                )

                continue

            # -------------------------------------------------
            # Previous-day volume filter
            # -------------------------------------------------

            if prev_volume <= SETTINGS.min_prev_volume:

                volume_rejected += 1

                LOG.info(
                    "%s rejected: volume %d <= %d",
                    symbol,
                    prev_volume,
                    SETTINGS.min_prev_volume,
                )

                continue

            # -------------------------------------------------
            # Passed both filters
            # -------------------------------------------------

            item["prev_close"] = close_price
            item["prev_volume"] = prev_volume
            item["prev_trading_day"] = (
                prev_day.isoformat()
            )

            result.append(item)

            LOG.info(
                "%s PASSED: price=%.2f volume=%d",
                symbol,
                close_price,
                prev_volume,
            )

        except Exception as exc:

            data_failed += 1

            LOG.exception(
                "%s daily filter failed: %s",
                symbol,
                exc,
            )

    # ---------------------------------------------------------
    # 5. Final summary
    # ---------------------------------------------------------

    LOG.info(
        "Price filter rejected: %d",
        price_rejected,
    )

    LOG.info(
        "Volume filter rejected: %d",
        volume_rejected,
    )

    LOG.info(
        "Daily data failures: %d",
        data_failed,
    )

    LOG.info(
        "FINAL UNIVERSE: %d symbols",
        len(result),
    )

    return result