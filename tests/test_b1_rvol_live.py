import pandas as pd
from app.strategy import evaluate_b1_breakout, t1_blocked


def frame():
    idx = pd.date_range("2026-09-14 09:15", periods=35, freq="15min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        "open": [100.0]*35, "high": [101.0]*35, "low": [99.0]*35,
        "close": [100.0]*35, "volume": [1000.0]*35,
        "ema9": [100.0]*35, "ema20": [100.0]*35, "vwap": [100.0]*35,
        "rsi14": [50.0]*35, "rvol": [1.0]*35,
    }, index=idx)
    # 09:15 ORB
    df.iloc[0, df.columns.get_loc("high")] = 105
    df.iloc[0, df.columns.get_loc("low")] = 95
    df.iloc[0, df.columns.get_loc("close")] = 100
    # breakout on the newest completed 15M candle
    df.iloc[-1, df.columns.get_loc("close")] = 106
    df.iloc[-1, df.columns.get_loc("high")] = 107
    df.iloc[-1, df.columns.get_loc("rsi14")] = 60
    df.iloc[-1, df.columns.get_loc("rvol")] = 1.3
    df.iloc[-2, df.columns.get_loc("rsi14")] = 59
    return df


def test_b1_rvol_candidate_passes_without_ema_or_vwap_gate(monkeypatch):
    df = frame()
    monkeypatch.setattr("app.strategy.score_trade_quality", lambda df, direction: {"trade_quality_score": 3.0, "curve_context": "HIGH"})
    orb = {"timestamp": df.index[0].isoformat(), "high":105, "low":95, "close":100}
    out = evaluate_b1_breakout(df, orb, 500, 1000000)
    assert out is not None
    assert out["direction"] == "BUY"
    assert out["setup_15m_rvol"] >= 1.2


def test_b1_rvol_rejects_low_rvol(monkeypatch):
    df = frame(); df.iloc[-1, df.columns.get_loc("rvol")] = 1.19
    monkeypatch.setattr("app.strategy.score_trade_quality", lambda df, direction: {"trade_quality_score": 3.0, "curve_context": "HIGH"})
    orb = {"timestamp": df.index[0].isoformat(), "high":105, "low":95, "close":100}
    assert evaluate_b1_breakout(df, orb, 500, 1000000) is None


def test_t1_block_matches_research_rule():
    idx = pd.date_range("2026-09-14 09:15", periods=20, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({"high":[100.0]*20,"low":[99.0]*20}, index=idx)
    assert t1_blocked(df, idx[-1], 100, 110, "BUY") is False
    df.iloc[-2, df.columns.get_loc("high")] = 105
    assert t1_blocked(df, idx[-1], 100, 110, "BUY") is True
