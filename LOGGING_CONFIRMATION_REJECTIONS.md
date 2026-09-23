# Post-5M Confirmation Rejection Logging

## Overview

Enhanced logging for signals that pass 5M confirmation but fail at later validation stages. This helps answer: **"Why did I have 3 confirmed setups but 0 signals?"**

---

## Rejection Points After 5M Confirmation

After a setup confirms on the 5M candle, it can still be rejected at these stages:

### 1. Risk/Reward Validation

**Log Pattern:**
```
SYMBOL | RISK_VALIDATION_FAILED | direction=BUY | entry=382.85 | sl=379.55 | reason=SL_TOO_CLOSE | min_stop_distance_percent=0.50
```

**What It Means:**
- Risk/reward calculation failed
- Stop loss is too close to entry
- Minimum stop distance not met (default: 0.5%)

**Example Scenarios:**
- Entry: 100, SL: 99.4 (risk 0.6%) → Too close (min: 0.5%)
- T1 target unreachable given the SL distance
- Calculated RR below minimum (default: 2.0x)

**Action:** Adjust MIN_STOP_DISTANCE_PERCENT in settings if legitimate trades are being rejected.

---

### 2. T1 Already Blocked

**Log Pattern:**
```
SYMBOL | T1_BLOCKED | direction=BUY | entry=382.85 | t1=389.45 | current_close=390.00 | reason=TARGET_ALREADY_REACHED
```

**What It Means:**
- Price already reached or passed Target 1 (profit target)
- No point entering the trade - profit already taken by market
- This is a **safety feature** to avoid late entries

**Why This Happens:**
1. Setup confirmed very late in the candle
2. Price moved faster than expected
3. Multiple confirmation candles, price kept moving

**Action:** None - this is working as designed. Prevents bad entries.

---

### 3. Telegram Send Failed

**Log Pattern:**
```
SYMBOL | TELEGRAM_SEND_FAILED | direction=BUY | entry=382.85 | reason=SEND_FAILED
```

**What It Means:**
- Signal created successfully
- Risk/T1 validation passed
- But Telegram message failed to send

**Possible Causes:**
1. Telegram bot token invalid
2. Chat ID incorrect
3. Network connectivity issue
4. Telegram API rate limit
5. DRY_RUN mode enabled (signals created but not sent)

**Action:** 
- Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars
- Check `DRY_RUN` setting (should be `false`)
- Check internet connectivity

---

### 4. Other Rejections

**Log Pattern:**
```
SYMBOL | CONFIRMED_BUT_REJECTED | direction=BUY | time=2026-09-23T12:20 | reason=MARKET_TREND_NOT_ALIGNED
```

**Other Possible Reasons:**
- `MARKET_TREND_NOT_ALIGNED` - Nifty50 structure doesn't match trade direction
- Any other validation failure

---

## Real Example: Analyzing "3 Confirmed, 0 Signals"

```
SCAN_SUMMARY
  Confirmation Stage: confirmed=3 | signals=0
```

**To find out why:**

1. **Search logs for T1_BLOCKED:**
   ```bash
   grep "T1_BLOCKED" scanner.log
   # Result: 2 matches
   # → 2 trades had targets already reached
   ```

2. **Search logs for RISK_VALIDATION_FAILED:**
   ```bash
   grep "RISK_VALIDATION_FAILED" scanner.log
   # Result: 1 match
   # → 1 trade failed risk validation
   ```

3. **Search logs for TELEGRAM_SEND_FAILED:**
   ```bash
   grep "TELEGRAM_SEND_FAILED" scanner.log
   # Result: 0 matches
   # → Telegram wasn't the issue
   ```

**Conclusion:** 
- STOCK1: T1 already reached (market moved too fast)
- STOCK2: T1 already reached (same reason)
- STOCK3: Risk validation failed (SL too close to entry)

---

## Complete Flow: Setup → Signal

```
Setup Created (15M)
    ↓
  Waiting for 5M confirmation
    ↓
5M Candle Closes Above/Below 15M High/Low
    ↓ (log: 5M_CANDLE | status=CONFIRMED)
Risk/Reward Validation
    ├─ FAIL → log: RISK_VALIDATION_FAILED
    └─ PASS ↓
T1 Already Reached?
    ├─ YES → log: T1_BLOCKED
    └─ NO ↓
Send to Telegram
    ├─ FAIL → log: TELEGRAM_SEND_FAILED
    └─ SUCCESS → log: SIGNAL_GENERATED ✓
```

---

## Log Examples from a Live Scan

```
HONASA | 5M_CANDLE | time=2026-09-21T14:50 | close=475.50 | threshold=474.10 | direction=BUY | status=CONFIRMED
HONASA | SIGNAL_GENERATED | direction=BUY | entry=475.50 | sl=469.65 | t1=481.65 | rvol=5.11 | rsi=59.27 | time=2026-09-21T14:50
✓ SUCCESS

BHARTIARTL | 5M_CANDLE | time=2026-09-21T13:35 | close=831.00 | threshold=833.90 | direction=SELL | status=CONFIRMED
BHARTIARTL | T1_BLOCKED | direction=SELL | entry=831.00 | t1=822.40 | current_close=820.00 | reason=TARGET_ALREADY_REACHED
✗ REJECTED

EXIDEIND | 5M_CANDLE | time=2026-09-21T15:05 | close=435.50 | threshold=434.95 | direction=BUY | status=CONFIRMED
EXIDEIND | RISK_VALIDATION_FAILED | direction=BUY | entry=435.50 | sl=434.55 | reason=SL_TOO_CLOSE | min_stop_distance_percent=0.50
✗ REJECTED
```

---

## Debugging Checklist

### If confirmed=3 but signals=0:

- [ ] Check for `T1_BLOCKED` entries (market moving faster than expected)
- [ ] Check for `RISK_VALIDATION_FAILED` entries (SL too close to entry)
- [ ] Check for `TELEGRAM_SEND_FAILED` entries (notification issue)
- [ ] Search for `CONFIRMED_BUT_REJECTED` for other reasons
- [ ] Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- [ ] Verify `DRY_RUN=false` in environment

### If you see many `RISK_VALIDATION_FAILED`:

- Increase `MIN_STOP_DISTANCE_PERCENT` to be less strict
- Or adjust ORB stop loss levels (currently using ORB Low/High)

### If you see many `T1_BLOCKED`:

- This is normal on volatile market days
- Means market is moving faster than expected
- Not a problem - safety feature working correctly

---

## Summary

With this enhanced logging, you can now answer:

- **"Why no signals?"** → Check T1_BLOCKED, RISK_VALIDATION_FAILED, TELEGRAM_SEND_FAILED
- **"Which filter rejected it?"** → Look at the rejection log message
- **"What were the exact values?"** → All metrics logged (entry, sl, t1, risk_percent, etc.)

This transforms "3 confirmed, 0 signals" from a mystery into a clear diagnosis. 📊
