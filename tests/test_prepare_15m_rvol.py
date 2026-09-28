"""
Regression test for 15M_DATA_UNAVAILABLE caused by RVOL lookback dropping all rows.

_prepare_15m previously fetched only today's intraday data. add_indicators uses
rolling(rvol_lookback, min_periods=rvol_lookback) which requires rvol_lookback prior
candles. Early in the session (< rvol_lookback completed 15M candles) avg_volume is
NaN for every row, and the final dropna wipes the dataframe clean — causing
15M_DATA_UNAVAILABLE for all symbols until well into the trading day.

Fix: fetch from previous_trading_day so yesterday's candles seed the rolling window.
"""
import pandas as pd
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _make_candles(start_str, periods, freq="15min"):
    idx = pd.date_range(start_str, periods=periods, freq=freq, tz=IST)
    # Alternate close prices so RSI (which divides avg_gain/avg_loss) is computable.
    # Constant close → avg_loss == 0 → rs = 0/NaN → rsi14 NaN → dropna removes all rows.
    closes = [100.0 + (i % 2) * 0.5 for i in range(periods)]
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": closes,
            "volume": 1000.0,
        },
        index=idx,
    )


def test_add_indicators_drops_all_rows_with_only_today_data():
    """Confirms the bug: only today's few candles → avg_volume all NaN → empty result."""
    from app.indicators import add_indicators

    df = _make_candles("2026-09-28 09:15", periods=5)  # 5 candles, 10:35 IST
    result = add_indicators(df, rvol_lookback=10)
    assert result.empty, "With only 5 candles and rvol_lookback=10, all rows should be dropped"


def test_add_indicators_keeps_today_rows_with_prior_day_context():
    """Confirms the fix: yesterday's candles seed the window, today's rows survive."""
    from app.indicators import add_indicators

    yesterday = _make_candles("2026-09-27 09:15", periods=25)  # full previous day
    today = _make_candles("2026-09-28 09:15", periods=5)
    df = pd.concat([yesterday, today]).sort_index()

    result = add_indicators(df, rvol_lookback=10)
    today_rows = result[result.index.date == pd.Timestamp("2026-09-28").date()]
    assert not today_rows.empty, "Today's candles should survive after seeding with yesterday's data"
    assert len(today_rows) == 5


def test_prepare_15m_fetches_from_previous_trading_day():
    """_prepare_15m must start its date range from previous_trading_day, not today."""
    from app.main import _prepare_15m

    yesterday = _make_candles("2026-09-25 09:15", periods=25)  # Fri (prev trading day)
    today = _make_candles("2026-09-28 09:15", periods=5)
    combined = pd.concat([yesterday, today]).sort_index()

    mock_dhan = MagicMock()
    mock_dhan.historical_intraday_df.return_value = combined

    ts = pd.Timestamp("2026-09-28 10:35:00", tz=IST)

    with patch("app.main.SETTINGS") as mock_settings:
        mock_settings.rvol_lookback = 10
        result = _prepare_15m(mock_dhan, "12345", ts)

    call_kwargs = mock_dhan.historical_intraday_df.call_args
    from_date = call_kwargs.kwargs.get("from_date") or call_kwargs.args[1]
    assert from_date == "2026-09-25", (
        f"from_date should be previous trading day '2026-09-25', got '{from_date}'"
    )

    today_rows = result[result.index.date == pd.Timestamp("2026-09-28").date()]
    assert not today_rows.empty, "Today's rows must not be dropped after the fix"
