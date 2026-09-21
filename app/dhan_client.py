from __future__ import annotations

import logging
import os
import time

import pandas as pd
import requests

from .candle_utils import resample_session_ohlcv
from dhanhq import DhanContext, dhanhq


LOG = logging.getLogger(__name__)


DHAN_DETAILED_MASTER_URL = (
    "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
)

DHAN_HISTORICAL_URL = (
    "https://api.dhan.co/v2/charts/historical"
)

IST = "Asia/Kolkata"

MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"

# Dhan's rate-limit response (HTTP 429, errorCode DH-904) was previously
# being treated identically to genuine "no data" — logged once and given
# up on immediately. This retries specifically on 429 with backoff before
# falling back to the old give-up behavior, so a rate-limited symbol gets
# a real second chance instead of silently vanishing from that run.
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BASE_DELAY_SECONDS = 1.5


def _post_with_rate_limit_retry(url, headers, json_payload, timeout, log_context):
    """POST with retry-and-backoff specifically for HTTP 429 responses.

    Any other status code (200 or a genuine error) is returned immediately,
    unchanged from the previous behavior — only 429 gets retried.
    """
    delay = RATE_LIMIT_BASE_DELAY_SECONDS
    last_response = None

    for attempt in range(1, RATE_LIMIT_MAX_RETRIES + 2):  # +1 initial try, +1 for range inclusivity
        response = requests.post(url, headers=headers, json=json_payload, timeout=timeout)
        last_response = response

        if response.status_code != 429:
            return response

        if attempt > RATE_LIMIT_MAX_RETRIES:
            LOG.error(
                "Dhan rate limit (429) — exhausted %d retries, giving up | %s",
                RATE_LIMIT_MAX_RETRIES, log_context,
            )
            return response

        LOG.warning(
            "Dhan rate limit (429) — retry %d/%d in %.1fs | %s",
            attempt, RATE_LIMIT_MAX_RETRIES, delay, log_context,
        )
        time.sleep(delay)
        delay *= 2  # exponential backoff: 1.5s, 3s, 6s

    return last_response


class DhanClient:
    def __init__(self) -> None:
        client_id = os.environ["DHAN_CLIENT_ID"]
        token = os.environ["DHAN_ACCESS_TOKEN"]

        self.access_token = token
        self.context = DhanContext(client_id, token)
        self.dhan = dhanhq(self.context)

    # ------------------------------------------------------------------
    # Dhan Security Master
    # ------------------------------------------------------------------

    def security_master(self) -> pd.DataFrame:
        df = pd.read_csv(
            DHAN_DETAILED_MASTER_URL,
            low_memory=False,
        )

        LOG.info(
            "Dhan detailed master: %d rows loaded",
            len(df),
        )

        return df

    def build_symbol_map(
        self,
        symbols: list[str],
    ) -> dict[str, dict]:

        df = self.security_master()

        required = [
            "EXCH_ID",
            "SEGMENT",
            "SECURITY_ID",
            "INSTRUMENT",
            "UNDERLYING_SYMBOL",
        ]

        missing = [
            column
            for column in required
            if column not in df.columns
        ]

        if missing:
            raise RuntimeError(
                f"Missing Dhan master columns: {missing}"
            )

        # NSE cash-equity instruments only.
        df = df[
            (df["EXCH_ID"].astype(str).str.upper() == "NSE")
            & (
                df["SEGMENT"]
                .astype(str)
                .str.upper()
                == "E"
            )
            & (
                df["INSTRUMENT"]
                .astype(str)
                .str.upper()
                == "EQUITY"
            )
        ].copy()

        wanted = {
            str(symbol).strip().upper()
            for symbol in symbols
        }

        df["UNDERLYING_SYMBOL"] = (
            df["UNDERLYING_SYMBOL"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        matched = df[
            df["UNDERLYING_SYMBOL"].isin(wanted)
        ]

        result: dict[str, dict] = {}

        for _, row in matched.iterrows():
            symbol = row["UNDERLYING_SYMBOL"]

            result[symbol] = {
                "security_id": str(row["SECURITY_ID"]),
                "exchange_segment": "NSE_EQ",
                "instrument": "EQUITY",
            }

        LOG.info(
            "Dhan Security ID mapping: %d/%d symbols matched",
            len(result),
            len(wanted),
        )

        return result

    # ------------------------------------------------------------------
    # Live Market Feed (quote) — batched, used for the Dhan-based
    # volume-gainer universe scan instead of scraping nseindia.com.
    # ------------------------------------------------------------------

    def quote_batch(self, security_ids: list[str], chunk_size: int = 400) -> dict[str, dict]:
        """Fetch current LTP + today's cumulative volume for many securities.

        Dhan's marketfeed/quote endpoint accepts a batch of security IDs per
        exchange segment. NOTE: batch-size and rate limits are enforced by
        Dhan and may change — verify the current limit against your own
        account/plan and adjust ``chunk_size`` if you see errors or
        truncated responses. This defensively parses a couple of plausible
        field-name variants since the exact response schema should be
        confirmed against a live account before relying on it in production.
        """
        result: dict[str, dict] = {}
        ids = [str(s) for s in security_ids]

        for start in range(0, len(ids), chunk_size):
            chunk = ids[start:start + chunk_size]
            try:
                payload = self.dhan.quote_data({"NSE_EQ": chunk})
            except Exception as exc:
                LOG.warning("Dhan quote_data batch failed (chunk %d-%d): %s", start, start + len(chunk), exc)
                continue

            if not isinstance(payload, dict):
                LOG.warning("Dhan quote_data returned non-dict payload for chunk %d-%d", start, start + len(chunk))
                continue

            data = payload.get("data", payload)
            segment_rows = data.get("NSE_EQ", {}) if isinstance(data, dict) else {}
            if not isinstance(segment_rows, dict):
                LOG.warning("Dhan quote_data NSE_EQ payload not a dict for chunk %d-%d", start, start + len(chunk))
                continue

            for sec_id, row in segment_rows.items():
                if not isinstance(row, dict):
                    continue
                ltp = row.get("last_price") or row.get("LTP") or row.get("ltp")
                volume = (
                    row.get("volume")
                    or row.get("total_traded_volume")
                    or row.get("totalTradedVolume")
                )
                try:
                    ltp = float(ltp) if ltp is not None else None
                    volume = float(volume) if volume is not None else None
                except (TypeError, ValueError):
                    ltp, volume = None, None
                if ltp is not None and volume is not None:
                    result[str(sec_id)] = {"ltp": ltp, "volume": volume}

        return result

    # ------------------------------------------------------------------
    # Intraday Historical Data
    # ------------------------------------------------------------------

    def historical_intraday_df(
        self,
        security_id: str,
        from_date: str,
        to_date: str,
        interval: int,
    ) -> pd.DataFrame:
        """Fetch historical intraday candles from Dhan's V2 API.

        Dhan supports 1/5/15/25/60 minute intervals. The backtester uses
        5M and 15M only. Timestamps returned by Dhan are converted to IST.
        """
        if int(interval) not in (1, 5, 15, 25, 60):
            raise ValueError("interval must be one of 1, 5, 15, 25, 60")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": self.access_token,
        }
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "interval": str(int(interval)),
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        }
        try:
            response = _post_with_rate_limit_retry(
                "https://api.dhan.co/v2/charts/intraday",
                headers,
                payload,
                30,
                f"security_id={security_id} interval={interval}",
            )
            if response.status_code != 200:
                LOG.error(
                    "Dhan intraday API failed: security_id=%s interval=%s HTTP=%s response=%s",
                    security_id, interval, response.status_code, response.text,
                )
                return pd.DataFrame()

            data = response.json()
            required = ["timestamp", "open", "high", "low", "close", "volume"]
            missing = [key for key in required if key not in data]
            if missing:
                LOG.error("Dhan intraday response missing fields: security_id=%s missing=%s", security_id, missing)
                return pd.DataFrame()

            n = min(len(data[key]) for key in required)
            if n == 0:
                return pd.DataFrame()

            df = pd.DataFrame({key: data[key][:n] for key in required})
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST)
            df = df.set_index("timestamp").sort_index()
            return df[~df.index.duplicated(keep="last")]
        except requests.RequestException as exc:
            LOG.error("Dhan intraday HTTP exception: security_id=%s interval=%s error=%s", security_id, interval, exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Daily Historical Data
    # ------------------------------------------------------------------

    def historical_daily_df(
        self,
        security_id: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:

        headers = {
            "Content-Type": "application/json",
            "access-token": self.access_token,
        }

        payload = {
            "securityId": str(security_id),
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        }

        try:
            response = _post_with_rate_limit_retry(
                DHAN_HISTORICAL_URL,
                headers,
                payload,
                20,
                f"security_id={security_id}",
            )

            if response.status_code != 200:
                LOG.error(
                    "Dhan historical API failed: "
                    "security_id=%s HTTP=%s response=%s",
                    security_id,
                    response.status_code,
                    response.text,
                )

                return pd.DataFrame()

            data = response.json()

            required = [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]

            missing = [
                key
                for key in required
                if key not in data
            ]

            if missing:
                LOG.error(
                    "Dhan historical response missing fields: "
                    "security_id=%s missing=%s response=%s",
                    security_id,
                    missing,
                    data,
                )

                return pd.DataFrame()

            n = min(
                len(data[key])
                for key in required
            )

            if n == 0:
                LOG.warning(
                    "Dhan historical API returned no candles: "
                    "security_id=%s from=%s to=%s",
                    security_id,
                    from_date,
                    to_date,
                )

                return pd.DataFrame()

            df = pd.DataFrame(
                {
                    "timestamp": data["timestamp"][:n],
                    "open": data["open"][:n],
                    "high": data["high"][:n],
                    "low": data["low"][:n],
                    "close": data["close"][:n],
                    "volume": data["volume"][:n],
                }
            )

            df["timestamp"] = pd.to_datetime(
                df["timestamp"],
                unit="s",
                utc=True,
            ).dt.tz_convert(IST)

            df = (
                df
                .set_index("timestamp")
                .sort_index()
            )

            df = df[
                ~df.index.duplicated(
                    keep="last"
                )
            ]

            return df

        except requests.RequestException as exc:
            LOG.error(
                "Dhan historical HTTP exception: "
                "security_id=%s error=%s",
                security_id,
                exc,
            )

            return pd.DataFrame()

        except Exception as exc:
            LOG.exception(
                "Dhan historical API exception: "
                "security_id=%s error=%s",
                security_id,
                exc,
            )

            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Intraday Data
    # ------------------------------------------------------------------

    def intraday_df(
        self,
        security_id: str,
        interval: int,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:

        try:
            payload = self.dhan.intraday_minute_data(
                security_id=str(security_id),
                exchange_segment="NSE_EQ",
                instrument_type="EQUITY",
                from_date=from_date,
                to_date=to_date,
                interval=1,
            )

        except Exception as exc:
            LOG.exception(
                "Dhan intraday API exception: "
                "security_id=%s error=%s",
                security_id,
                exc,
            )

            return pd.DataFrame()

        if not isinstance(payload, dict):
            LOG.error(
                "Dhan intraday response is not a dict: "
                "security_id=%s type=%s",
                security_id,
                type(payload).__name__,
            )

            return pd.DataFrame()

        status = payload.get("status")

        if status != "success":
            LOG.error(
                "Dhan intraday API unsuccessful: "
                "security_id=%s status=%s remarks=%s",
                security_id,
                status,
                payload.get("remarks", ""),
            )

            return pd.DataFrame()

        # Dhan returns OHLCV inside the "data" object.
        data = payload.get("data")

        if not isinstance(data, dict):
            LOG.error(
                "Dhan intraday response missing data object: "
                "security_id=%s",
                security_id,
            )

            return pd.DataFrame()

        keys = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        if str(security_id) == "21614":
            LOG.info(
                "Dhan intraday response validated: "
                "security_id=%s data_keys=%s",
                security_id,
                list(data.keys()),
            )

            LOG.info(
                "Dhan intraday candle counts: "
                "security_id=%s counts=%s",
                security_id,
                {
                    key: len(data[key])
                    for key in data
                    if isinstance(data[key], list)
                },
            )

        missing = [
            key
            for key in keys
            if key not in data
        ]

        if missing:
            LOG.error(
                "Dhan intraday data missing fields: "
                "security_id=%s missing=%s",
                security_id,
                missing,
            )

            return pd.DataFrame()

        if not all(
            isinstance(data[key], list)
            for key in keys
        ):
            LOG.error(
                "Dhan intraday OHLCV fields are not lists: "
                "security_id=%s",
                security_id,
            )

            return pd.DataFrame()

        n = min(
            len(data[key])
            for key in keys
        )

        if n == 0:
            LOG.warning(
                "Dhan intraday API returned no candles: "
                "security_id=%s from=%s to=%s",
                security_id,
                from_date,
                to_date,
            )

            return pd.DataFrame()

        df = pd.DataFrame(
            {
                key: data[key][:n]
                for key in keys
            }
        )

        # Epoch seconds -> IST.
        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            unit="s",
            utc=True,
        ).dt.tz_convert(IST)

        df = (
            df
            .set_index("timestamp")
            .sort_index()
        )

        # Remove duplicate timestamps.
        df = df[
            ~df.index.duplicated(
                keep="last"
            )
        ]

        # --------------------------------------------------------------
        # Keep only NSE regular trading session.
        # --------------------------------------------------------------

        df = filter_market_session(df)

        if df.empty:
            LOG.warning(
                "No NSE regular-session candles after filtering: "
                "security_id=%s",
                security_id,
            )

            return pd.DataFrame()

        if str(security_id) == "21614":
            LOG.info(
                "Dhan 1M dataframe after session filter: "
                "security_id=%s rows=%d first=%s last=%s",
                security_id,
                len(df),
                df.index.min(),
                df.index.max(),
            )

        # --------------------------------------------------------------
        # Return requested timeframe.
        # --------------------------------------------------------------

        if interval == 5:
            result = resample_ohlcv(
                df,
                "5min",
            )

            if str(security_id) == "21614":
                log_resample_validation(
                    security_id,
                    "5M",
                    result,
                )

            return result

        if interval == 15:
            # B1 requires candle-start timestamps, with the first candle
            # explicitly anchored at 09:15-09:30. Dhan's minute data is the
            # source of truth; do not depend on Dhan's direct 15M labels.
            result = resample_session_ohlcv(df, 15)

            if str(security_id) == "21614":
                log_resample_validation(
                    security_id,
                    "15M",
                    result,
                )

            return result

        return df


# ----------------------------------------------------------------------
# NSE regular-session filter
# ----------------------------------------------------------------------

def filter_market_session(
    df: pd.DataFrame,
) -> pd.DataFrame:

    if df.empty:
        return df

    # Work with local IST timestamps.
    local_time = df.index.time

    market_open = pd.Timestamp(
        MARKET_OPEN
    ).time()

    market_close = pd.Timestamp(
        MARKET_CLOSE
    ).time()

    mask = (
        (local_time >= market_open)
        & (local_time < market_close)
    )

    return df.loc[mask].copy()


# ----------------------------------------------------------------------
# OHLCV resampling
# ----------------------------------------------------------------------

def resample_ohlcv(
    df: pd.DataFrame,
    rule: str,
) -> pd.DataFrame:

    if df.empty:
        return df

    # --------------------------------------------------------------
    # IMPORTANT:
    #
    # We use closed="left" and label="right".
    #
    # Therefore:
    #
    # 09:15, 09:16, 09:17, 09:18, 09:19
    #        ↓
    #      09:20
    #
    # and:
    #
    # 09:20 ... 09:24
    #        ↓
    #      09:25
    #
    # This prevents the incorrect 09:15 partial candle.
    # --------------------------------------------------------------

    out = (
        df.resample(
            rule,
            origin="start_day",
            offset="15min",
            label="right",
            closed="left",
        )
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
            ]
        )
    )

    # --------------------------------------------------------------
    # Keep only candles whose labels are valid NSE candle closes.
    # --------------------------------------------------------------

    if rule == "5min":
        valid_minutes = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}

        out = out[
            out.index.minute.isin(valid_minutes)
        ]

    elif rule == "15min":
        valid_minutes = {0, 15, 30, 45}

        out = out[
            out.index.minute.isin(valid_minutes)
        ]

    # No candle should be labelled after 15:30.
    out = out[
        out.index.time
        <= pd.Timestamp("15:30").time()
    ]

    return out


# ----------------------------------------------------------------------
# Diagnostic validation
# ----------------------------------------------------------------------

def log_resample_validation(
    security_id: str,
    timeframe: str,
    df: pd.DataFrame,
) -> None:

    if df.empty:
        LOG.error(
            "Dhan %s dataframe EMPTY: security_id=%s",
            timeframe,
            security_id,
        )
        return

    LOG.info(
        "Dhan %s dataframe: "
        "security_id=%s rows=%d first=%s last=%s",
        timeframe,
        security_id,
        len(df),
        df.index.min(),
        df.index.max(),
    )

    first_timestamps = [
        ts.strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        for ts in df.index[:5]
    ]

    last_timestamps = [
        ts.strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        for ts in df.index[-5:]
    ]

    LOG.info(
        "Dhan %s first timestamps: %s",
        timeframe,
        first_timestamps,
    )

    LOG.info(
        "Dhan %s last timestamps: %s",
        timeframe,
        last_timestamps,
    )

    first = df.iloc[0]

    LOG.info(
        "Dhan %s first candle: "
        "timestamp=%s open=%s high=%s low=%s close=%s volume=%s",
        timeframe,
        df.index[0],
        first["open"],
        first["high"],
        first["low"],
        first["close"],
        first["volume"],
    )

    last = df.iloc[-1]

    LOG.info(
        "Dhan %s last candle: "
        "timestamp=%s open=%s high=%s low=%s close=%s volume=%s",
        timeframe,
        df.index[-1],
        last["open"],
        last["high"],
        last["low"],
        last["close"],
        last["volume"],
    )
