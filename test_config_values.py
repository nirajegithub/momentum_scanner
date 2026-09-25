"""Test what config values are actually being used."""

from app.config import SETTINGS

print("\n" + "="*60)
print("CURRENT CONFIG VALUES")
print("="*60)
print(f"min_daily_volume: {SETTINGS.min_daily_volume}")
print(f"min_15m_rvol: {SETTINGS.min_15m_rvol}")
print(f"buy_rsi_min: {SETTINGS.buy_rsi_min}")
print(f"buy_rsi_max: {SETTINGS.buy_rsi_max}")
print(f"sell_rsi_min: {SETTINGS.sell_rsi_min}")
print(f"sell_rsi_max: {SETTINGS.sell_rsi_max}")
print(f"min_candle_body_ratio: {SETTINGS.min_candle_body_ratio}")
print(f"min_ema8_slope_bars: {SETTINGS.min_ema8_slope_bars}")
print(f"consolidation_body_pct: {SETTINGS.consolidation_body_pct}")
print("="*60 + "\n")
