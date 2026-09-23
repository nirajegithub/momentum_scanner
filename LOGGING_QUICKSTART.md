# Logging Quick Start

You asked: **"Can we make the log more informative?"**

**✅ Done!** Here's what changed:

---

## What Changed

### Before
```
2026-09-23 04:55:30,222 | INFO | AEGISLOG | 15M_DATA_UNAVAILABLE
2026-09-23 04:55:30,520 | INFO | ANANTRAJ | 15M_DATA_UNAVAILABLE
2026-09-23 04:55:30,813 | INFO | ANURAS | 15M_DATA_UNAVAILABLE
```

### After
```
AEGISLOG | DATA_STAGE | status=15M_DATA_UNAVAILABLE
ANANTRAJ | DATA_STAGE | status=ORB_NOT_AVAILABLE  
ANURAS | ORB_DETECTED | time=2026-09-22T09:15 | high=1172.40 | low=1142.00 | close=1144.40
ANURAS | 15M_CANDLE | time=2026-09-22T12:00 | close=1189.90 | breakout=BUY
ANURAS | SETUP_CREATED | direction=BUY | time=2026-09-22T12:00 | rvol=4.80 | rsi=64.64 | score=4.50
ANURAS | CONFIRMATION_STAGE | status=WAITING_FOR_5M
ANURAS | 5M_CANDLE | time=2026-09-22T12:20 | close=1196.70 | threshold=1189.90 | direction=BUY | status=CONFIRMED
ANURAS | SIGNAL_GENERATED | direction=BUY | entry=1196.70 | sl=1189.80 | t1=1210.50 | rvol=4.80 | rsi=64.64

================================================================================
SCAN_SUMMARY | total_symbols=256
  Data Stage: unavailable=10 | orb_missing=5
  Breakout Stage: no_breakout=180 | filter_rejected=45 | setups=16
  Confirmation Stage: confirmed=3 | signals=3
================================================================================
```

---

## Key Improvements

✅ **Stage-based logging** - See each stock's journey through 6 stages  
✅ **Detailed metrics** - RVOL, RSI, Score, Entry, SL, T1 all logged  
✅ **Filter rejection reasons** - Know exactly why a stock didn't qualify  
✅ **End-of-scan summary** - See overall funnel and statistics  
✅ **Fully backward compatible** - No changes to existing functionality  

---

## Files Added

| File | Purpose |
|------|---------|
| `app/logging_utils.py` | New logging utilities |
| `LOGGING_GUIDE.md` | Complete reference |
| `LOGGING_BEFORE_AFTER.md` | Visual comparison |
| `LOGGING_TROUBLESHOOTING.md` | Common issues & solutions |
| `LOGGING_IMPLEMENTATION_SUMMARY.md` | Technical summary |
| `LOGGING_QUICKSTART.md` | This file |

---

## Next Steps

1. **Commit the changes**
   ```bash
   cd C:\Projects\momentum_scanner_repo
   git add app/logging_utils.py app/main.py LOGGING_*.md
   git commit -m "Add enhanced logging for better visibility"
   ```

2. **Run next scan** and check logs

3. **Read LOGGING_TROUBLESHOOTING.md** if logs show unexpected patterns

---

## Log Stages Explained

| Stage | What Happens | Good Sign | Problem Sign |
|-------|--------------|-----------|--------------|
| **DATA_STAGE** | Fetching 15M data & ORB | ORB_DETECTED | 15M_DATA_UNAVAILABLE for all |
| **15M_CANDLE** | Detecting breakout | breakout=BUY/SELL | status=NO_BREAKOUT (price in range) |
| **SETUP_CREATED** | Quality filters pass | SETUP_CREATED logged | B1_FILTER_REJECTED with reason |
| **CONFIRMATION_STAGE** | Waiting for 5M cross | 5M_CANDLE logged | status=WAITING_FOR_5M (endless) |
| **5M_CANDLE** | Checking 5M confirmation | status=CONFIRMED | status=NO_CONFIRMATION |
| **SIGNAL_GENERATED** | Alert sent to Telegram | SIGNAL_GENERATED | (None - signal created) |

---

## Reading the Summary

```
SCAN_SUMMARY | total_symbols=256
  Data Stage: unavailable=10 | orb_missing=5
  Breakout Stage: no_breakout=180 | filter_rejected=45 | setups=16
  Confirmation Stage: confirmed=3 | signals=3
```

**Funnel flow:**
```
256 symbols started
  ├─ 10 had no data
  ├─ 5 had no ORB
  └─ 241 had data
      ├─ 180 had no breakout
      ├─ 45 breakouts rejected by filters
      └─ 16 setups created
          ├─ 13 not confirmed on 5M
          └─ 3 confirmed
              └─ 3 signals sent to Telegram
```

**Interpretation:**
- Few at data stage = Good data connection ✅
- Many at breakout stage = Normal (no breakouts today)
- Many filter rejections = Market conditions not matching setup rules
- Few confirmations = 5M confirmation is strict filter (good for quality)

---

## Common Scenarios

### Scenario 1: "No signals today"
```
Check summary:
- unavailable=250? → API/network issue
- no_breakout=240? → Market consolidating (normal)
- filter_rejected=50? → Quality filters are strict today
- setups=0, confirmed=0? → No trades matched criteria
```

### Scenario 2: "Why was HONASA rejected?"
```
Search logs for "HONASA":
B1_FILTER_REJECTED | symbol=HONASA | reason=RVOL_TOO_LOW | rvol=0.8 | min_15m_rvol=1.2
→ Breakout lacked volume. Correct filter working.
```

### Scenario 3: "Setup created but never confirmed"
```
Look for:
HONASA | SETUP_CREATED | ... 
HONASA | CONFIRMATION_STAGE | status=WAITING_FOR_5M
HONASA | CONFIRMATION_STAGE | status=WAITING_FOR_5M
HONASA | 5M_CANDLE | ... | status=NO_CONFIRMATION
→ 5M never crossed the 15M threshold. Price didn't sustain breakout.
```

---

## Environment Variables (No Changes Needed)

Logging works with existing settings:
```
MIN_PRICE: 350
MIN_DAILY_VOLUME: 500000
BUY_RSI_MIN: 55
BUY_RSI_MAX: 70
SELL_RSI_MIN: 30
SELL_RSI_MAX: 45
MIN_15M_RVOL: 1.2
MIN_TRADE_SCORE: 3
MAX_TRADE_SCORE: 7
```

---

## Tips

1. **Pipe to file for later analysis**
   ```bash
   python -m app.main > scanner_$(date +%Y%m%d_%H%M%S).log 2>&1
   ```

2. **Search for specific patterns**
   ```bash
   grep "SIGNAL_GENERATED" scanner.log        # Find signals
   grep "FILTER_REJECTED" scanner.log         # Find rejections
   grep "SCAN_SUMMARY" scanner.log            # Find summary
   ```

3. **Monitor in real-time**
   ```bash
   tail -f scanner.log | grep -E "SETUP_CREATED|SIGNAL_GENERATED"
   ```

4. **Debug a specific stock**
   ```bash
   grep "^HONASA" scanner.log
   ```

---

## Questions?

- **Understanding a log message?** → Read `LOGGING_GUIDE.md`
- **Confused by a pattern?** → Check `LOGGING_TROUBLESHOOTING.md`
- **Want full technical details?** → See `LOGGING_IMPLEMENTATION_SUMMARY.md`
- **Visual comparison?** → Look at `LOGGING_BEFORE_AFTER.md`

---

That's it! Your logs are now **much more informative** 📊
