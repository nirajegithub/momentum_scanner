"""Smart ORB data fetching with detailed diagnostic logging."""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


def get_orb_with_fallback(dhan, security_id, trading_day, max_retries=3):
    """Get ORB with smart fallback logic.

    Strategy:
    1. Try today's ORB (09:15-09:30) with detailed logging
    2. If missing, retry up to max_retries times (data might not be indexed yet)
    3. Fall back to PREVIOUS day's 15:30 (last hour close) if today's ORB not available
    """
    from .calendar import previous_trading_day

    def fetch_orb_candle(date_to_fetch):
        """Fetch and return ORB candle (09:15-09:30) with detailed diagnostics."""
        try:
            LOG.debug("ORB FETCH START | %s | security_id=%s", date_to_fetch, security_id)

            raw = dhan.historical_intraday_df(
                security_id=security_id,
                interval=15,
                from_date=date_to_fetch.isoformat(),
                to_date=(date_to_fetch + pd.Timedelta(days=1)).isoformat(),
            )

            if raw is None or raw.empty:
                LOG.warning("ORB NOT FOUND | %s | NO_DATA | Dhan API returned empty/None", date_to_fetch)
                return None, "NO_DATA_FROM_API"

            df = pd.DataFrame(raw)
            df.index = pd.to_datetime(df.index)

            if df.index.tz is None:
                df.index = df.index.tz_localize(IST)
            else:
                df.index = df.index.tz_convert(IST)

            times_hhmm = df.index.strftime("%H:%M")
            first_time = df.index[0].strftime("%H:%M")
            last_time = df.index[-1].strftime("%H:%M")
            total_candles = len(df)

            LOG.debug(
                "ORB DATA RECEIVED | %s | candles=%d | time_range=%s_to_%s",
                date_to_fetch, total_candles, first_time, last_time
            )

            # Check for 09:15 and 09:30
            has_915 = (times_hhmm == "09:15").any()
            has_930 = (times_hhmm == "09:30").any()

            LOG.debug(
                "ORB TIME CHECK | %s | has_09:15=%s | has_09:30=%s",
                date_to_fetch, has_915, has_930
            )

            # Try 09:15 first, then 09:30 (in case Dhan uses close time)
            for target_time in ["09:15", "09:30"]:
                rows = df[times_hhmm == target_time]
                if not rows.empty:
                    r = rows.iloc[0]
                    orb_data = {
                        "date": date_to_fetch.isoformat(),
                        "time": target_time,
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                    }
                    LOG.info(
                        "ORB FOUND | %s | time=%s | high=%.2f | low=%.2f | close=%.2f",
                        date_to_fetch, target_time,
                        orb_data["high"], orb_data["low"], orb_data["close"]
                    )
                    return orb_data, f"FOUND_AT_{target_time}"

            # ORB not found - detailed diagnostic logging
            all_times = sorted(times_hhmm.unique())
            first_15_times = ", ".join(all_times[:15])
            total_unique_times = len(all_times)

            if first_time < "10:00":
                LOG.warning(
                    "ORB NOT FOUND | %s | INCOMPLETE_DATA_EARLY_START | "
                    "data_starts=%s | data_ends=%s | total_candles=%d | unique_times=%d | "
                    "first_15_times=[%s] | missing_09:15_and_09:30",
                    date_to_fetch, first_time, last_time, total_candles, total_unique_times,
                    first_15_times
                )
                return None, "INCOMPLETE_DATA_EARLY_START"
            else:
                LOG.warning(
                    "ORB NOT FOUND | %s | NO_EARLY_DATA | "
                    "data_starts=%s (after_10:00) | data_ends=%s | total_candles=%d | "
                    "unique_times=%d | first_15_times=[%s] | morning_data_missing",
                    date_to_fetch, first_time, last_time, total_candles, total_unique_times,
                    first_15_times
                )
                return None, "NO_EARLY_DATA"

        except Exception as exc:
            LOG.error(
                "ORB FETCH ERROR | %s | Exception: %s | Type: %s",
                date_to_fetch, str(exc), type(exc).__name__, exc_info=True
            )
            return None, f"EXCEPTION_{type(exc).__name__}"

    def fetch_last_hour_range(date_to_fetch):
        """Fetch and return last hour (15:15-15:30) range."""
        try:
            raw = dhan.historical_intraday_df(
                security_id=security_id,
                interval=15,
                from_date=date_to_fetch.isoformat(),
                to_date=(date_to_fetch + pd.Timedelta(days=1)).isoformat(),
            )

            if raw is None or raw.empty:
                return None, None

            df = pd.DataFrame(raw)
            df.index = pd.to_datetime(df.index)

            if df.index.tz is None:
                df.index = df.index.tz_localize(IST)
            else:
                df.index = df.index.tz_convert(IST)

            times_hhmm = df.index.strftime("%H:%M")

            # Get last hour (15:15 and 15:30 candles)
            last_hour_rows = df[times_hhmm.isin(["15:15", "15:30"])]

            if last_hour_rows.empty:
                return None, "NO_15H_DATA"

            # Calculate high/low for the last hour
            high = float(last_hour_rows["high"].max())
            low = float(last_hour_rows["low"].min())
            close = float(last_hour_rows.iloc[-1]["close"])

            return {
                "date": date_to_fetch.isoformat(),
                "time": "15:30_LAST_HOUR",
                "high": high,
                "low": low,
                "close": close,
            }, "LAST_HOUR_RANGE"

        except Exception as exc:
            LOG.debug("Failed to fetch last hour for %s: %s", date_to_fetch, exc)
            return None, f"ERROR_{str(exc)[:20]}"

    # Strategy 1: Try to get today's ORB
    ts_now = datetime.now(IST)
    current_time = ts_now.time()

    LOG.info("ORB MANAGER START | trading_day=%s | current_time=%s | max_retries=%d",
             trading_day, current_time.strftime("%H:%M"), max_retries)

    for attempt in range(1, max_retries + 1):
        LOG.debug("ORB FETCH ATTEMPT | attempt=%d/%d | trading_day=%s",
                  attempt, max_retries, trading_day)

        orb_data, reason = fetch_orb_candle(trading_day)

        if orb_data:
            LOG.info("ORB SUCCESS | trading_day=%s | source=TODAY_ORB | attempt=%d",
                     trading_day, attempt)
            return orb_data, "TODAY_ORB"

        # If during market hours and data incomplete, retry
        market_open = datetime.strptime("09:15", "%H:%M").time()
        market_close = datetime.strptime("15:30", "%H:%M").time()

        if market_open <= current_time <= market_close:
            if attempt < max_retries:
                wait_time = 30 * attempt
                LOG.info(
                    "ORB RETRY | trading_day=%s | attempt=%d/%d | reason=%s | "
                    "retrying_in=%ds | during_market_hours=True",
                    trading_day, attempt, max_retries, reason, wait_time
                )
                time.sleep(wait_time)
                continue
        else:
            LOG.info("ORB RETRY SKIPPED | trading_day=%s | outside_market_hours=%s",
                     trading_day, current_time.strftime("%H:%M"))
            break

    # Strategy 2: Fall back to PREVIOUS day's last hour
    prev_day = previous_trading_day(trading_day)

    LOG.warning(
        "ORB FALLBACK | today=%s | using_previous_day=%s | using_last_hour_range",
        trading_day, prev_day
    )

    last_hour_data, reason = fetch_last_hour_range(prev_day)

    if last_hour_data:
        LOG.info(
            "ORB FALLBACK SUCCESS | trading_day=%s | source=PREVIOUS_DAY_LAST_HOUR | "
            "prev_day=%s | high=%.2f | low=%.2f | close=%.2f",
            trading_day, prev_day, last_hour_data["high"], last_hour_data["low"], last_hour_data["close"]
        )
        return last_hour_data, "PREVIOUS_DAY_LAST_HOUR"

    # No usable data available
    LOG.error(
        "ORB FAILED | trading_day=%s | no_data_available | "
        "today_orb=not_found | fallback=%s",
        trading_day, reason
    )
    return None, None
