# Enhanced Logging Guide

## What Changed

Created a new `app/logging_utils.py` module with better logging utilities and integrated them into `main.py` for more informative logs.

## Log Stages & Examples

### Stage 1: Data Retrieval
```
AEGISLOG | DATA_STAGE | status=15M_DATA_UNAVAILABLE
ANANTRAJ | DATA_STAGE | status=ORB_NOT_AVAILABLE
ATGL | ORB_DETECTED | time=2026-09-22T09:15 | high=642.95 | low=630.50 | close=635.00
```

### Stage 2: 15M Breakout Detection
```
BHARTIARTL | 15M_CANDLE | time=2026-09-21T13:30 | close=1834.20 | breakout=SELL
HONASA | 15M_CANDLE | time=2026-09-21T14:45 | close=470.00 | status=NO_BREAKOUT (in_range)
```

### Stage 3: Quality Filter Checks
The strategy filters are evaluated here and logged as rejections:
```
B1_FILTER_REJECTED | symbol=BHARTIARTL | reason=RSI_OUT_OF_BAND | direction=SELL | rsi=42.01 | band=30-45
B1_FILTER_REJECTED | symbol=BHARTIARTL | reason=RVOL_TOO_LOW | rvol=1.76 | min_15m_rvol=1.2
B1_FILTER_REJECTED | symbol=BHARTIARTL | reason=SCORE_OUT_OF_RANGE | score=3.0 | min_trade_score=3 | max_trade_score=7
```

### Stage 4: Setup Creation
```
HONASA | SETUP_CREATED | direction=BUY | time=2026-09-21T14:45 | rvol=5.11 | rsi=59.27 | score=5.00 | EARLY_MOMENTUM_SURGE=true
EXIDEIND | SETUP_CREATED | direction=BUY | time=2026-09-21T14:45 | rvol=2.48 | rsi=55.88 | score=3.50
```

### Stage 5: 5M Confirmation
```
COCHINSHIP | CONFIRMATION_STAGE | status=WAITING_FOR_5M
BHARTIARTL | CONFIRMATION_STAGE | status=WAITING_FOR_5M (EARLY_MOMENTUM_SURGE)
SYNGENE | 5M_CANDLE | time=2026-09-21T12:30 | close=382.85 | threshold=381.20 | direction=BUY | status=CONFIRMED
```

### Stage 6: Signal Generation
```
SYNGENE | SIGNAL_GENERATED | direction=BUY | entry=382.85 | sl=379.55 | t1=389.45 | rvol=3.20 | rsi=65.46 | time=2026-09-21T12:30
```

### End-of-Scan Summary
```
================================================================================
SCAN_SUMMARY | total_symbols=256
  Data Stage: unavailable=10 | orb_missing=5
  Breakout Stage: no_breakout=180 | filter_rejected=45 | setups=16
  Confirmation Stage: confirmed=3 | signals=3
================================================================================
```

## Filter Rejection Reasons

The strategy filters in `app/strategy.py` log rejections with specific reasons:

| Reason | What It Means |
|--------|---------------|
| `NO_CANDLE_DATA` | No 15M data available |
| `INDICATORS_UNAVAILABLE` | RSI/RVOL calculation failed |
| `DAILY_DATA_UNAVAILABLE` | Previous day close/volume missing |
| `PRICE_TOO_LOW` | Price below MIN_PRICE setting (default: ₹350) |
| `DAILY_VOLUME_TOO_LOW` | Volume below MIN_DAILY_VOLUME (default: 500k) |
| `RSI_OUT_OF_BAND` | RSI not in acceptable range (BUY: 55-70, SELL: 30-45) |
| `RSI_MOMENTUM_NOT_ALIGNED` | RSI not moving in breakout direction |
| `RVOL_TOO_LOW` | Relative volume < MIN_15M_RVOL (default: 1.2) |
| `SCORE_OUT_OF_RANGE` | Trade quality score outside MIN/MAX range (default: 3-7) |
| `MARKET_TREND_NOT_ALIGNED` | Nifty50 market structure not aligned with trade direction |

## Configuration

Filtering thresholds from workflow environment variables:

```
MIN_PRICE: 350
MIN_PREV_VOLUME: 500000
MIN_DAILY_VOLUME: 500000
BUY_RSI_MIN: 55
BUY_RSI_MAX: 70
SELL_RSI_MIN: 30
SELL_RSI_MAX: 45
MIN_15M_RVOL: 1.2
MIN_TRADE_SCORE: 3
MAX_TRADE_SCORE: 7
```

## How to Use These Logs

1. **Debug data issues**: Look for `15M_DATA_UNAVAILABLE` or `ORB_NOT_AVAILABLE` entries
2. **Track filter performance**: Use the summary to see how many stocks pass/fail each stage
3. **Understand rejections**: Each rejection explains why (RSI, RVOL, Score, etc.)
4. **Monitor signal generation**: Watch `SIGNAL_GENERATED` lines to confirm real signals

## Example: Debugging Why No Signals Today

If all 256 stocks show `15M_DATA_UNAVAILABLE`:
- Check: Dhan API authentication, market hours, network connectivity
- Logs tell you the STAGE where failure happens

If you see many rejections at `SCORE_OUT_OF_RANGE`:
- Logs show the actual scores (e.g., 2.8 when min is 3.0)
- You can adjust MIN_TRADE_SCORE in settings if appropriate
