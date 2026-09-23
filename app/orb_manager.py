"""Smart ORB data fetching with fallback to previous day's last hour."""

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
    1. Try today's ORB (09:15-09:30)
    2. If missing, retry up to max_retries times (data might not be indexed yet)
    3. Fall back to PREVIOUS day's 15:30 (last hour close) if today's ORB not available
    """
    from .calendar import previous_trading_day

    def fetch_orb_candle(date_to_fetch):
        """Fetch and return ORB candle (09:15-09:30)."""
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
            first_time = df.index[0].strftime("%H:%M")

            # Try 09:15 first, then 09:30 (in case Dhan uses close time)
            for target_time in ["09:15", "09:30"]:
                rows = df[times_hhmm == target_time]
                if not rows.empty:
                    r = rows.iloc[0]
                    return {
                        "date": date_to_fetch.isoformat(),
                        "time": target_time,
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                    }, f"FOUND_AT_{target_time}"

            # If we have early data but not 9:15/9:30, data might not be ready yet
            if first_time < "10:00":
                return None, f"INCOMPLETE_DATA_STARTS_AT_{first_time}"
            else:
                return None, f"NO_EARLY_DATA_STARTS_AT_{first_time}"

        except Exception as exc:
            LOG.debug("Failed to fetch ORB for %s: %s", date_to_fetch, exc)
            return None, f"ERROR_{str(exc)[:20]}"

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

    for attempt in range(1, max_retries + 1):
        orb_data, reason = fetch_orb_candle(trading_day)

        if orb_data:
            LOG.info(
                "✓ ORB found for %s at attempt %d: %s",
                trading_day, attempt, reason
            )
            return orb_data, "TODAY_ORB"

        # If during market hours and data incomplete, retry (data might not be indexed yet)
        market_open = datetime.strptime("09:15", "%H:%M").time()
        market_close = datetime.strptime("15:30", "%H:%M").time()

        if market_open <= current_time <= market_close:
            if attempt < max_retries:
                wait_time = 30 * attempt  # 30s, 60s, 90s retries
                LOG.debug(
                    "During market hours, retrying ORB fetch in %ds (attempt %d/%d): %s",
                    wait_time, attempt, max_retries, reason
                )
                time.sleep(wait_time)
                continue
        else:
            # After market close, don't retry - use fallback
            LOG.debug("After market hours, not retrying: %s", reason)
            break

    # Strategy 2: Fall back to PREVIOUS day's last hour (15:15-15:30)
    prev_day = previous_trading_day(trading_day)

    LOG.warning(
        "ORB not available for today (%s), falling back to previous day's last hour (%s)",
        trading_day, prev_day
    )

    last_hour_data, reason = fetch_last_hour_range(prev_day)

    if last_hour_data:
        LOG.info(
            "✓ Using previous day's last hour as fallback for %s: %s",
            trading_day, reason
        )
        return last_hour_data, "PREVIOUS_DAY_LAST_HOUR"

    # No usable data available
    LOG.error(
        "No ORB available for today (%s) or previous day's last hour (%s): %s",
        trading_day, prev_day, reason
    )
    return None, None
