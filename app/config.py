from dataclasses import dataclass
import os


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    min_price: float = float(os.getenv("MIN_PRICE", "350"))
    min_prev_volume: int = int(os.getenv("MIN_PREV_VOLUME", "500000"))
    min_daily_move_percent: float = float(os.getenv("MIN_DAILY_MOVE_PERCENT", "2.0"))
    min_daily_volume: int = int(os.getenv("MIN_DAILY_VOLUME", "500000"))

    buy_rsi_min: float = float(os.getenv("BUY_RSI_MIN", "55"))
    buy_rsi_max: float = float(os.getenv("BUY_RSI_MAX", "70"))
    sell_rsi_min: float = float(os.getenv("SELL_RSI_MIN", "30"))
    sell_rsi_max: float = float(os.getenv("SELL_RSI_MAX", "45"))
    rvol_lookback: int = int(os.getenv("RVOL_LOOKBACK", "20"))
    min_15m_rvol: float = float(os.getenv("MIN_15M_RVOL", "1.2"))
    require_ema_crossover: bool = _bool("REQUIRE_EMA_CROSSOVER", "false")

    setup_timeframe: int = int(os.getenv("SETUP_TIMEFRAME", "5"))
    entry_timeframe: int = int(os.getenv("ENTRY_TIMEFRAME", "5"))
    min_15m_candles: int = int(os.getenv("MIN_15M_CANDLES", "90"))
    min_5m_candles: int = int(os.getenv("MIN_5M_CANDLES", "30"))

    min_trade_score: float = float(os.getenv("MIN_TRADE_SCORE", "3"))
    max_trade_score: float = float(os.getenv("MAX_TRADE_SCORE", "7"))

    t1_rr: float = float(os.getenv("T1_RR", "2.0"))
    t2_rr: float = float(os.getenv("T2_RR", "3.0"))
    t3_rr: float = float(os.getenv("T3_RR", "4.0"))
    min_rr: float = float(os.getenv("MIN_RR", "2.0"))
    min_stop_distance_percent: float = float(os.getenv("MIN_STOP_DISTANCE_PERCENT", "0.50"))
    risk_percent: float = float(os.getenv("RISK_PERCENT", "1.0"))
    scan_start_hhmm: int = int(os.getenv("SCAN_START_HHMM", "930"))
    scan_end_hhmm: int = int(os.getenv("SCAN_END_HHMM", "1505"))
    dry_run: bool = _bool("DRY_RUN", "true")

    volume_gainer_candidate_limit: int = int(os.getenv("VOLUME_GAINER_CANDIDATE_LIMIT", "800"))
    volume_gainer_rvol_threshold: float = float(os.getenv("VOLUME_GAINER_RVOL_THRESHOLD", "2.0"))
    volume_gainer_baseline_days: int = int(os.getenv("VOLUME_GAINER_BASELINE_DAYS", "10"))

    enable_progressive_ts: bool = _bool("ENABLE_PROGRESSIVE_TS", "false")

    min_candle_body_ratio: float = float(os.getenv("MIN_CANDLE_BODY_RATIO", "0.60"))
    min_ema8_slope_bars: int = int(os.getenv("MIN_EMA8_SLOPE_BARS", "5"))
    consolidation_body_pct: float = float(os.getenv("CONSOLIDATION_BODY_PCT", "0.5"))
    consolidation_range_pct: float = float(os.getenv("CONSOLIDATION_RANGE_PCT", "0.3"))
    consolidation_candles: int = int(os.getenv("CONSOLIDATION_CANDLES", "3"))

    rvol_morning_0915_1000: float = float(os.getenv("RVOL_MORNING_0915_1000", "2.0"))
    rvol_morning_1000_1200: float = float(os.getenv("RVOL_MORNING_1000_1200", "1.8"))
    rvol_midday_1200_1400: float = float(os.getenv("RVOL_MIDDAY_1200_1400", "2.2"))
    rvol_close_1400_1530: float = float(os.getenv("RVOL_CLOSE_1400_1530", "1.5"))

    min_followthrough_volume_rvol: float = float(os.getenv("MIN_FOLLOWTHROUGH_VOLUME_RVOL", "1.5"))


DISCLAIMER = "<b>⚠️ Educational content. Not investment advice. Trade at your own risk.</b>"
SETTINGS = Settings()
