# Logging Troubleshooting Guide

Quick reference for interpreting logs and debugging common issues.

---

## Issue: "All stocks showing 15M_DATA_UNAVAILABLE"

### Log Pattern
```
AEGISLOG | DATA_STAGE | status=15M_DATA_UNAVAILABLE
ANANTRAJ | DATA_STAGE | status=15M_DATA_UNAVAILABLE
ANURAS | DATA_STAGE | status=15M_DATA_UNAVAILABLE
... (all 256 symbols)
```

### Summary Stats Show
```
Data Stage: unavailable=256 | orb_missing=0
Breakout Stage: no_breakout=0 | filter_rejected=0 | setups=0
Confirmation Stage: confirmed=0 | signals=0
```

### Likely Causes
1. **Dhan API authentication failed**
   - Check `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` env vars
   - Verify API credentials are still valid

2. **Market is closed**
   - Scanner runs during market hours (9:30 AM - 3:30 PM IST)
   - Check if today is a trading day

3. **Network connectivity issue**
   - Check internet connection
   - Verify Dhan API endpoints are reachable

4. **API rate limit exceeded**
   - Dhan may have rate limiting
   - Wait a few minutes and retry

### Debug Steps
```bash
# Test Dhan connection
python -c "from app.dhan_client import DhanClient; c = DhanClient(); print(c.get_funds())"

# Check if market was open
python -c "from app.calendar import is_nse_trading_day; print(is_nse_trading_day('2026-09-23'))"

# Check logs for API errors
tail -f logs/scanner.log | grep -i "error\|exception\|failed"
```

---

## Issue: "No breakouts detected today"

### Log Pattern
```
AEGISLOG | ORB_DETECTED | time=2026-09-22T09:15 | high=1528.70 | low=1470.40 | close=1489.20
AEGISLOG | 15M_CANDLE | time=2026-09-22T14:30 | close=1495.00 | status=NO_BREAKOUT (in_range)
ANANTRAJ | ORB_DETECTED | time=2026-09-22T09:15 | high=607.45 | low=588.90 | close=591.25
ANANTRAJ | 15M_CANDLE | time=2026-09-22T14:30 | close=595.50 | status=NO_BREAKOUT (in_range)
```

### Summary Stats Show
```
Data Stage: unavailable=0 | orb_missing=0
Breakout Stage: no_breakout=240 | filter_rejected=16 | setups=0
Confirmation Stage: confirmed=0 | signals=0
```

### What This Means
- ✅ Data was available
- ✅ ORB (Opening Range 9:15-9:30) was detected
- ✗ During 12:00 PM - 3:30 PM, no stock closed ABOVE the ORB high or BELOW the ORB low

### Possible Reasons
1. **Market consolidating** - Prices staying within ORB range (normal)
2. **Low volatility day** - Limited price movement
3. **Market trend opposite to typical patterns** - Bull/bear momentum weak

### Is This a Problem?
**No, this is normal.** Not every day has breakout opportunities. The scanner correctly identifies this.

---

## Issue: "Breakouts detected but no setups created"

### Log Pattern
```
HONASA | 15M_CANDLE | time=2026-09-21T14:45 | close=474.75 | breakout=BUY
B1_FILTER_REJECTED | symbol=HONASA | reason=RSI_OUT_OF_BAND | direction=BUY | rsi=52.41 | band=55-70
B1_FILTER_REJECTED | symbol=HONASA | reason=RVOL_TOO_LOW | rvol=0.95 | min_15m_rvol=1.2
B1_FILTER_REJECTED | symbol=HONASA | reason=SCORE_OUT_OF_RANGE | score=2.5 | min_trade_score=3 | max_trade_score=7
```

### Summary Stats Show
```
Data Stage: unavailable=0 | orb_missing=0
Breakout Stage: no_breakout=200 | filter_rejected=56 | setups=0
Confirmation Stage: confirmed=0 | signals=0
```

### What This Means
- ✅ Breakouts happened (56 total)
- ✗ All failed quality filter checks

### Common Rejection Reasons

| Reason | Means | Solution |
|--------|-------|----------|
| `RSI_OUT_OF_BAND` | RSI not in sweet spot | Market lacks momentum at breakout point |
| `RVOL_TOO_LOW` | Low volume on breakout | Need volume spike to confirm move |
| `SCORE_OUT_OF_RANGE` | Setup quality score low | Structure/pattern not meeting quality criteria |
| `PRICE_TOO_LOW` | Stock < ₹350 | Can adjust MIN_PRICE if needed |
| `DAILY_VOLUME_TOO_LOW` | Low previous day volume | Stock lacks liquidity |

### If This is Frequent
Consider tuning thresholds (in workflow env vars):
- Lower `MIN_15M_RVOL` (currently 1.2) to catch quieter breakouts
- Widen RSI ranges (currently BUY: 55-70, SELL: 30-45)
- Lower `MIN_TRADE_SCORE` (currently min 3) to allow lower-quality setups

---

## Issue: "Setups created but no confirmation"

### Log Pattern
```
HONASA | SETUP_CREATED | direction=BUY | time=2026-09-21T14:45 | rvol=5.11 | rsi=59.27 | score=5.00
HONASA | CONFIRMATION_STAGE | status=WAITING_FOR_5M
HONASA | CONFIRMATION_STAGE | status=WAITING_FOR_5M
HONASA | CONFIRMATION_STAGE | status=WAITING_FOR_5M
(later...)
HONASA | 5M_CANDLE | time=2026-09-21T14:50 | close=470.50 | threshold=474.75 | direction=BUY | status=NO_CONFIRMATION
```

### Summary Stats Show
```
Data Stage: unavailable=0 | orb_missing=0
Breakout Stage: no_breakout=200 | filter_rejected=0 | setups=16
Confirmation Stage: confirmed=3 | signals=3
```

### What This Means
- ✅ 16 setups were created and waiting
- ✗ Only 3 got confirmed on 5M
- ✓ 3 signals were generated

### Is This a Problem?
**No, this is expected.** Not every setup confirms. The 5M confirmation is strict:
- For BUY: 5M candle must close ABOVE the 15M high
- For SELL: 5M candle must close BELOW the 15M low

This filters out false breakouts.

### Monitor Ratio
```
Confirmation rate = confirmed / setups
Example: 3 confirmed / 16 setups = 18.75% confirmation rate
```

If rate drops below 10%, market might be choppy. If above 50%, might be too loose.

---

## Issue: "Signals created but not sent"

### Log Pattern
```
ANURAS | SIGNAL_GENERATED | direction=BUY | entry=1196.70 | sl=1189.80 | t1=1210.50 | rvol=4.80 | rsi=64.64 | time=2026-09-22T12:20
WARNING | SIGNAL_NOT_SENT | confirmation_5m=2026-09-22T12:20:00+05:30
```

### Summary Stats Show
```
Confirmation Stage: confirmed=1 | signals=0
```

### Likely Causes
1. **Telegram bot not configured**
   - Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`

2. **DRY_RUN mode enabled**
   - If `DRY_RUN=true`, signals generate but don't send
   - Set `DRY_RUN=false` to actually send

3. **Network issue with Telegram**
   - Check internet connectivity to Telegram API

### Debug
```bash
# Test Telegram
python -c "from app.telegram import send; print(send('Test message'))"

# Check DRY_RUN setting
echo $DRY_RUN  # Should be false
```

---

## Issue: "T1_BLOCKED rejection"

### Log Pattern
```
BHARTIARTL | 5M_CANDLE | time=2026-09-21T13:30 | close=1833.60 | threshold=1833.90 | direction=SELL | status=CONFIRMED
B1_5M | symbol=BHARTIARTL | candle=2026-09-21T13:30:00+05:30 | status=CONFIRMED_BUT_REJECTED | reason=T1_BLOCKED
```

### What This Means
- ✅ Confirmed on 5M
- ✗ T1 (Target 1) price already exceeded
- Setup is rejected because T1 is not reachable

### Why This Happens
Market moved so fast that:
1. 15M setup was created (Setup 12:00 PM)
2. Waiting for 5M confirmation (12:00 PM - 12:20 PM)
3. By the time 5M confirmed (12:20 PM), price already reached T1
4. No point entering - target already taken

### Is This a Problem?
**No, this is a safety feature.** It prevents entries where you can't make the target anymore.

---

## Issue: "MARKET_TREND_NOT_ALIGNED rejection"

### Log Pattern
```
BHARTIARTL | BREAKOUT_STAGE | status=MARKET_TREND_REJECTED | direction=BUY
```

### What This Means
- ✅ Stock broke above ORB high (BUY setup)
- ✗ But Nifty50 is in downtrend (SELL structure)
- Setup rejected due to market structure mismatch

### Why This Happens
The scanner checks if Nifty50 structure aligns with the stock:
- BUY setup needs Nifty in uptrend or neutral
- SELL setup needs Nifty in downtrend or neutral

This prevents counter-trend trades.

### To Disable
Edit `app/strategy.py` line ~289:
```python
# Change from:
if not trend_aligned:
    continue

# To (not recommended):
# Trend alignment optional
```

---

## Summary Statistics Interpretation

```
SCAN_SUMMARY | total_symbols=256
  Data Stage: unavailable=10 | orb_missing=5
  Breakout Stage: no_breakout=180 | filter_rejected=45 | setups=16
  Confirmation Stage: confirmed=3 | signals=3
```

**Read as a funnel:**
- Started: 256 symbols
- Made it past data stage: 241 (256 - 10 - 5)
- Had breakouts: 61 (241 - 180)
- Passed quality filters: 16 (61 - 45)
- Confirmed on 5M: 3 (16 - 13)
- Signals sent: 3

**Healthy funnel looks like:** ✅ Few at each stage, few rejections

**Problem funnels:**
- Most fail at data stage → API/network issue
- Most fail at breakout detection → Low volatility day
- Most fail at filter stage → Market conditions not matching setup rules
- Setups created but none confirm → 5M confirmation too strict

---

## Quick Debug Checklist

When something seems wrong:

- [ ] Check SCAN_SUMMARY first - where did flow stop?
- [ ] Search logs for "ERROR" or "EXCEPTION"
- [ ] Look for stage where symbols stop appearing (data, breakout, confirmation?)
- [ ] Check if any specific stocks keep getting rejected (unusual?)
- [ ] Verify env vars set correctly (Dhan token, Telegram token, etc.)
- [ ] Confirm market hours (9:30 AM - 3:30 PM IST for NSE)
- [ ] Check if it's a trading day
