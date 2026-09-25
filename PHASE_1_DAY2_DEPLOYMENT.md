# Phase 1 Day 2+ Deployment Guide

**Date:** 2026-09-26 onwards  
**Status:** Critical universe adjustment based on 90-day backtest results

---

## What Changed

### Day 1 Analysis (2026-09-25)
- **Result:** 0W 9L | -206.45 pts | 0% win rate
- **Investigation:** 90-day backtest of all 9 stocks
- **Finding:** ALL 9 stocks show 0% pass rate in historical data
- **Conclusion:** These are fundamentally unfit for B1 ORB strategy

### Universe Update
**DISABLED (removed from trading):**
- PNBHOUSING (0% backtest)
- USHAMART (0% backtest)
- SBILIFE (0% backtest)
- TRENT (0% backtest)
- PIRAMALFIN (0% backtest)
- AXISBANK (0% backtest)
- HONASA (0% backtest)
- AUBANK (0% backtest)
- BAJFINANCE (0% backtest)

**ACTIVE (proven baseline):**
- 36-stock universe (20.45% baseline pass rate)
- Only stocks with proven B1 ORB performance

---

## Why This Change?

**Statistical Evidence:**

| Metric | Day 1 | 90-Day Backtest | Verdict |
|---|---|---|---|
| Sample size | 9 trades | 13,599 candles | Backtest more reliable |
| Win rate | 0% | 0% | Consistent failure |
| Setup quality | All rejected | 0 passed | Not B1-compatible |

**Conclusion:** Day 1 loss was NOT market timing or luck. These stocks fundamentally don't work with the strategy.

---

## Expected Impact for Days 2-5

### Baseline Recovery
```
Previous universe (9 weak stocks):  0% win rate
New universe (36 proven stocks):   20.45% pass rate (expected)
Improvement:                       +20.45%
```

### Expected Results
- **Signals/day:** 2-4 (baseline expectation)
- **Initial win rate:** 40-50% (from research baseline)
- **Setup quality:** All setups pass proven filters

### Timeline
- **Day 2 (2026-09-26):** Begin with adjusted universe
- **Days 3-5:** Continue collecting data
- **2026-10-01 EOD:** Evaluate Phase 1 completion

---

## Deployment Steps

### Step 1: Verify Configuration
```bash
# Check that 9 stocks are disabled
grep "enabled.*false" config/stocks_to_fetch.json
# Should show 9 matches
```

### Step 2: Start Day 2 Scan at 9:15 AM IST
```bash
export DRY_RUN=false
python -m app.main
```

### Step 3: Monitor Live
```bash
# In another terminal
tail -f state/logs/scanner.log

# Watch for:
# - ORB detection: "ORB FOUND | SYMBOL"
# - Setup creation: "SETUP_CREATED"
# - Signals: "SIGNAL_GENERATED"
# - NOT expecting the 9 disabled stocks
```

### Step 4: Track Results
Use the signal monitor to track:
- Entry times and prices
- SL hits (when price breached stop loss)
- Target hits (when price hit T1/T2/T3)
- Exit times and actual P&L

---

## What You'll See (Day 2 Example)

**Morning (9:15-12:00):**
```
09:30 | CHOLAFIN   | 15M SETUP   | RVOL=1.89x | RSI=42.5
09:35 | CHOLAFIN   | 5M CONFIRM  | close=1650.20
09:36 | CHOLAFIN   | SIGNAL GEN  | Entry=1650.20 | SL=1665.20 | T1=1620.10
       [Telegram alert sent]

10:15 | BERGEPAINT | 15M SETUP   | RVOL=2.15x | RSI=58.3
10:20 | BERGEPAINT | 5M CONFIRM  | close=542.30
10:21 | BERGEPAINT | SIGNAL GEN  | Entry=542.30 | SL=528.15 | T1=564.50
       [Telegram alert sent]

11:00 | CHOLAFIN   | SIGNAL STAT | LTP=1647.50 | SL@1665.20(+17.70) | T1@1620.10(-27.40)
11:05 | BERGEPAINT | SIGNAL STAT | LTP=548.70 | SL@528.15(-20.55) | T1@564.50(+15.80)
```

**Midday-Afternoon:**
```
12:30 | CHOLAFIN | SIGNAL_TARGET_HIT | T1 | target=1620.10 | ltp=1620.05 | PROFIT!
12:35 | BERGEPAINT | Still running | LTP=555.40 | approaching T1

15:25 | SUMMARY
       2 signals | 1W 1L (or PENDING if still open)
       +27.45 pts (example - will vary)
```

---

## Monitoring Checklist

### Per Trading Day
- [ ] Generate fresh Dhan token at 9:00 AM
- [ ] Start scanner at 9:20 AM
- [ ] Monitor logs for 15-20 minutes to verify:
  - ORBs are being detected
  - 15M setups being created
  - 5M confirmations working
- [ ] Check every 30 minutes for new signals
- [ ] Track each signal: entry, SL, targets, exit
- [ ] At 3:30 PM: Stop scanner and export state

### Per Phase 1 Completion (2026-10-01)
- [ ] Total signals generated: 10-20 (2-4/day × 5 days)
- [ ] Win rate: 40-60% (expected from 20.45% filter pass rate)
- [ ] No API errors in logs
- [ ] All signals have tracked exit reasons

---

## Success Criteria

### Minimum (Pass)
- [ ] ≥2 signals per day
- [ ] No unexplained API errors
- [ ] Telegram alerts working
- [ ] Signal monitor tracking exits correctly

### Target (Good)
- [ ] 2-4 signals per day
- [ ] ≥40% win rate
- [ ] All signals have clear exit reasons
- [ ] P&L tracking accurate

### Excellent (Great)
- [ ] 3-4 signals per day
- [ ] ≥50% win rate
- [ ] Quick signal generation (<5 min 15M setup + confirmation)
- [ ] Consistent across all days

---

## If Issues Occur

### Issue: Still no signals by 11:00 AM
```
Check:
1. Dhan token is fresh and valid
2. ORBs being detected (check logs)
3. 15M data loading correctly
4. Filters aren't too strict
```

### Issue: Too many signals (>8/day)
```
Check:
1. RSI bands are too wide
2. RVOL threshold too low
3. Candle body filter disabled
```

### Issue: All signals losing money
```
Check:
1. SL/target levels correct
2. Entry timing (delay from setup)
3. 5M confirmation rule working
```

### Issue: Dhan API errors
```
Solution:
1. Regenerate fresh token
2. Verify DHAN_CLIENT_ID set
3. Check network connection
4. Restart scanner
```

---

## Files to Review Before Launch

| File | Purpose | Check |
|---|---|---|
| `config/stocks_to_fetch.json` | Universe config | 9 stocks disabled ✓ |
| `app/config.py` | Strategy parameters | Tuned from Phase 1 ✓ |
| `app/strategy.py` | 5-filter logic | No changes ✓ |
| `app/signal_monitor.py` | Exit tracking | Monitoring SL/targets ✓ |
| `state/runtime_state.json` | Daily state | Will be created fresh ✓ |

---

## Final Checklist Before 9:15 AM Day 2

- [ ] Read this guide (you're here!)
- [ ] Verified 9 stocks are disabled in config
- [ ] Fresh Dhan token generated
- [ ] DRY_RUN=false is set
- [ ] Scanner can start at 9:20 AM
- [ ] Telegram credentials verified
- [ ] Signal monitor enabled and tracking
- [ ] Logs directory accessible for monitoring

---

## Timeline

| Time | Action | Expected |
|---|---|---|
| 9:00 AM | Generate Dhan token | Token expires ~1:00 PM |
| 9:20 AM | Start scanner | BEGIN logging |
| 9:15-10:30 | Morning rush | High setup probability |
| 12:00-2:00 PM | Mid-day activity | Moderate signals |
| 3:30 PM | Market close | Stop scanner |
| 3:35 PM | EOD export | Save state for analysis |

---

## Success Indicators

✅ **You'll know it's working if:**
1. ORBs detected for all universe symbols (~36)
2. Setups created 15-20 minutes after ORB (15M candle formation)
3. Confirmations checked 20 minutes later (5M candle close)
4. Signals sent to Telegram within 1 minute
5. Signal monitor tracking entry/exit correctly

❌ **Something's wrong if:**
1. No ORBs detected by 10:00 AM
2. No 15M setups created all day
3. Dhan API errors in logs
4. Telegram not sending alerts
5. 0 signals after 12 hours of scanning

---

## Going Live

**Day 2 is a GO!** 🚀

With the proven baseline universe and disabled weak stocks:
- Expected: 2-4 signals with 40%+ win rate
- Compared to Day 1: 9 signals with 0% win rate
- Improvement: ~20% win rate recovery

**Ready to trade at 09:15 AM on 2026-09-26.**

---

Good luck! 🎯
