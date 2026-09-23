# Logging Enhancement: Before vs After

## Before (Current)

```
2026-09-23 04:55:30,222 | INFO | AEGISLOG | 15M_DATA_UNAVAILABLE
2026-09-23 04:55:30,520 | INFO | ANANTRAJ | 15M_DATA_UNAVAILABLE
2026-09-23 04:55:30,813 | INFO | ANURAS | 15M_DATA_UNAVAILABLE
2026-09-23 04:55:31,114 | INFO | ATGL | 15M_DATA_UNAVAILABLE
...
(No visibility into what passed/failed or why)
```

**Problems:**
- All symbols log only "15M_DATA_UNAVAILABLE" with no context
- No breakdown of failure reasons (API error? Market closed? No data?)
- No tracking of setups created vs rejected
- No summary statistics
- Can't distinguish between:
  - Data fetch failures
  - Breakout detection failures  
  - Quality filter failures
  - Confirmation failures

---

## After (New)

```
2026-09-23 04:55:30.222 | INFO | AEGISLOG | DATA_STAGE | status=15M_DATA_UNAVAILABLE
2026-09-23 04:55:30.520 | INFO | ANANTRAJ | DATA_STAGE | status=ORB_NOT_AVAILABLE
2026-09-23 04:55:30.813 | INFO | ANURAS | ORB_DETECTED | time=2026-09-22T09:15 | high=1172.40 | low=1142.00 | close=1144.40
2026-09-23 04:55:31.114 | INFO | ANURAS | 15M_CANDLE | time=2026-09-22T12:00 | close=1189.90 | breakout=BUY
2026-09-23 04:55:31.415 | INFO | ANURAS | SETUP_CREATED | direction=BUY | time=2026-09-22T12:00 | rvol=4.80 | rsi=64.64 | score=4.50
2026-09-23 04:55:31.516 | INFO | ANURAS | CONFIRMATION_STAGE | status=WAITING_FOR_5M
2026-09-23 04:55:32.217 | INFO | ANURAS | 5M_CANDLE | time=2026-09-22T12:20 | close=1196.70 | threshold=1189.90 | direction=BUY | status=CONFIRMED
2026-09-23 04:55:32.318 | INFO | ANURAS | SIGNAL_GENERATED | direction=BUY | entry=1196.70 | sl=1189.80 | t1=1210.50 | rvol=4.80 | rsi=64.64 | time=2026-09-22T12:20

2026-09-23 04:55:33.450 | INFO | BHARTIARTL | ORB_DETECTED | time=2026-09-21T09:15 | high=1854.80 | low=1840.50 | close=1848.70
2026-09-23 04:55:33.650 | INFO | BHARTIARTL | 15M_CANDLE | time=2026-09-21T13:30 | close=1834.20 | breakout=SELL
2026-09-23 04:55:33.851 | INFO | B1_FILTER_REJECTED | symbol=BHARTIARTL | reason=RSI_OUT_OF_BAND | direction=SELL | rsi=42.01 | band=30-45

2026-09-23 04:55:34.250 | INFO | HONASA | ORB_DETECTED | time=2026-09-21T09:15 | high=472.00 | low=465.55 | close=470.30
2026-09-23 04:55:34.450 | INFO | HONASA | 15M_CANDLE | time=2026-09-21T14:45 | close=474.10 | breakout=BUY
2026-09-23 04:55:34.651 | INFO | HONASA | SETUP_CREATED | direction=BUY | time=2026-09-21T14:45 | rvol=5.11 | rsi=59.27 | score=5.00 | EARLY_MOMENTUM_SURGE=true
2026-09-23 04:55:34.852 | INFO | HONASA | CONFIRMATION_STAGE | status=WAITING_FOR_5M (EARLY_MOMENTUM_SURGE)
2026-09-23 04:55:35.153 | INFO | HONASA | 5M_CANDLE | time=2026-09-21T14:50 | close=475.50 | threshold=474.10 | direction=BUY | status=CONFIRMED
2026-09-23 04:55:35.254 | INFO | HONASA | SIGNAL_GENERATED | direction=BUY | entry=475.50 | sl=469.65 | t1=481.65 | rvol=5.11 | rsi=59.27 | time=2026-09-21T14:50

================================================================================
SCAN_SUMMARY | total_symbols=256
  Data Stage: unavailable=10 | orb_missing=5
  Breakout Stage: no_breakout=180 | filter_rejected=45 | setups=16
  Confirmation Stage: confirmed=3 | signals=3
================================================================================
```

**Improvements:**
- ✅ Each stock's journey is visible through all stages
- ✅ Clear stage labels: DATA_STAGE → ORB_DETECTED → 15M_CANDLE → SETUP_CREATED → CONFIRMATION_STAGE → 5M_CANDLE → SIGNAL_GENERATED
- ✅ Detailed rejection reasons (RSI, RVOL, Score, etc. with actual values)
- ✅ All relevant metrics logged (RVOL, RSI, Score, Entry, SL, T1, etc.)
- ✅ End-of-scan summary showing total flow
- ✅ Easy to spot patterns (e.g., "45 stocks rejected at filter stage")
- ✅ Can now identify if issue is:
  - Data fetching (15M_DATA_UNAVAILABLE)
  - Setup detection (no_breakout)
  - Quality checks (filter_rejected)
  - 5M confirmation (fewer confirmed than setups)

---

## Real-World Debug Scenario

### Scenario: "Why are there no signals today?"

**Before:** All you see is "15M_DATA_UNAVAILABLE" with no other info.

**After:** You can see:
```
✓ Data available: 246/256 symbols have 15M data and ORB
✓ Breakouts detected: 16 symbols generated setups
✓ Quality passed: 16 setups created (none rejected)
✓ 5M confirmation: Only 3/16 confirmed
✗ Issue identified: Confirmation stage filtering is strict today
```

Or if it's a data issue:
```
✗ Data stage: 250/256 symbols have 15M_DATA_UNAVAILABLE
→ Action: Check Dhan API connection, market hours, network
```

---

## Files Added/Modified

- **New:** `app/logging_utils.py` - Enhanced logging utilities
- **Modified:** `app/main.py` - Integrated enhanced logging with stats tracking
- **New:** `LOGGING_GUIDE.md` - Complete logging reference
- **New:** `LOGGING_BEFORE_AFTER.md` - This file

## How to Enable

Simply commit these changes. No configuration needed. Logging is automatically enabled.

## Backward Compatibility

The new logging is fully backward compatible. All existing functionality remains unchanged.
