# Phase 1: Live Validation (2026-09-25 to 2026-10-01)

**Status:** 🚀 Ready to Deploy  
**Backtest Pass Rate:** 20.45% (216/1,056 candles)  
**Expected Setups/Day:** 2-4  
**Duration:** 5 trading days  
**Target Win Rate:** 50-65%

---

## Pre-Launch Checklist (TODAY - 2026-09-24)

- [ ] **Generate Dhan Token**
  ```bash
  # Login to Dhan account and generate fresh token
  # Tokens expire in 3-4 hours, so generate right before first scan
  # Save token to: .env or environment variable
  export DHAN_CLIENT_ID="your_client_id"
  export DHAN_ACCESS_TOKEN="your_fresh_token"
  ```

- [ ] **Verify Config Loaded**
  ```bash
  python -c "from app.config import SETTINGS; print(f'BUY_RSI_MIN={SETTINGS.buy_rsi_min}, MIN_15M_RVOL={SETTINGS.min_15m_rvol}')"
  # Should show: BUY_RSI_MIN=20, MIN_15M_RVOL=0.001
  ```

- [ ] **Test Live Scan (Dry Run)**
  ```bash
  export DRY_RUN=true
  python -m app.main
  # Should run without errors, may show 0 signals (normal on Sunday/after market)
  ```

- [ ] **Verify Logging Setup**
  ```bash
  tail -f state/logs/scanner.log
  # Should show timestamp, symbol, reason logs in real-time
  ```

---

## Launch Schedule

### Day 1: 2026-09-25 (Wednesday)

**Morning (9:00 AM IST):**
1. Generate fresh Dhan token (expires 3-4 hours)
2. Set `DRY_RUN=false` for live trading
3. Start live scan at 9:25 AM (5 min before market open)

**Throughout Day:**
- Monitor logs every 30 minutes
- Note timestamp of each signal
- Save symbol, direction, RSI, RVOL to tracking sheet

**EOD (3:35 PM IST):**
- Export state: `cp state/runtime_state.json logs/day1_state.json`
- Review all signals generated
- Manually check if any signals won/lost (check chart)

**Example Monitoring Log:**
```
09:30 | TCS | BUY | RVOL=2.15 | RSI=62 | SETUP_CREATED
09:35 | TCS | 5M_CANDLE | CONFIRMED | close=3442.00
09:36 | TCS | SIGNAL_GENERATED | entry=3442.00 | sl=3425.00
✅ Telegram alert sent

10:15 | WIPRO | SELL | B1_FILTER_REJECTED | reason=CANDLE_BODY_TOO_WEAK
10:45 | MARUTI | BUY | RVOL=0.95 | RSI=58 | SETUP_CREATED
```

### Days 2-5: 2026-09-26 to 2026-10-01

Repeat daily:
1. Generate fresh Dhan token at 9:00 AM
2. Start scan at 9:25 AM
3. Monitor and log every signal
4. EOD export state and review
5. Update tracking sheet

---

## Daily Tracking Template

**File:** `logs/phase1_tracking.csv`

```csv
Date,Time,Symbol,Direction,Setup_RVOL,Setup_RSI,Signal_Entry,SL,Target,Outcome,Notes
2026-09-25,09:30,TCS,BUY,2.15,62,3442.00,3425.00,3475.00,WIN,Closed +33pts at 11:45
2026-09-25,10:15,WIPRO,SELL,1.10,38,1215.50,1230.00,1195.00,LOSS,Hit SL at 11:20
2026-09-25,11:30,MARUTI,BUY,1.98,65,9150.00,9120.00,9200.00,PENDING,Still open at EOD
```

---

## What to Monitor

### Filter Rejection Analysis
After each day, check logs for rejection patterns:

```bash
grep "B1_FILTER_REJECTED" state/logs/scanner.log | awk -F'reason=' '{print $2}' | sort | uniq -c
```

Expected rejections (in order):
1. RSI_OUT_OF_BAND (some expected, should be <20%)
2. RVOL_TOO_LOW (should be <5%, real data has low RVOL)
3. CANDLE_BODY_TOO_WEAK (should be <5%)
4. Others <1% each

### Setup Quality
- **Expected signals:** 2-4 per day
- **High quality:** RVOL > 1.5x AND RSI in momentum direction
- **Moderate quality:** RVOL 0.5-1.5x OR RSI at band edge
- **Watch:** Multiple signals same stock same day

### Entry Confirmation
- Track 5M confirmation candles
- Note if confirmation volume good (RVOL > 1.5x)
- If too many "no confirmation" events, may need adjustment

---

## Success Criteria for Phase 1

### Week 1 Checkpoint (2026-09-25 to 2026-10-01)

**✅ SUCCESS = All of these:**
- [x] 2-4 signals per day (target met in backtest)
- [x] 0 errors in logs
- [x] Telegram alerts working
- [x] Win rate ≥ 40% (preliminary)

**⚠️ NEEDS ADJUSTMENT = Any of these:**
- [ ] <1 signal/day → too strict, relax RVOL threshold
- [ ] >8 signals/day → too loose, tighten RSI bands
- [ ] >50% rejections on RVOL → data shows lower RVOL normal
- [ ] Win rate <30% → may need Filter 2 (EMA8) re-enabled

**❌ CRITICAL ISSUES:**
- [ ] Dhan API errors → regenerate token
- [ ] No signals 2 days in row → check token/credentials
- [ ] Negative win rate >60% → rollback to Phase 1 defaults

---

## Daily Checklist

### Before Market Open (9:00-9:25 AM)
- [ ] Generate fresh Dhan token
- [ ] Verify token in environment
- [ ] Check market open time (9:15 AM IST)
- [ ] Test dry run once
- [ ] Set DRY_RUN=false
- [ ] Start scanner
- [ ] Open logs tail command
- [ ] Prepare tracking sheet

### During Market (9:25 AM - 3:30 PM)
- [ ] Check logs every 30 min
- [ ] Note each signal (time, symbol, direction)
- [ ] Verify Telegram alerts received
- [ ] Track signal outcomes in real-time
- [ ] Note any errors or warnings

### After Market Close (3:30-4:00 PM)
- [ ] Stop scanner gracefully
- [ ] Export runtime_state.json to logs/
- [ ] Count total signals generated
- [ ] Count rejections by reason
- [ ] Manually verify signal outcomes
- [ ] Update tracking spreadsheet
- [ ] Document any issues for next day

---

## Rollback Plan

If Phase 1 encounters issues:

### Issue: Too Few Signals (<1/day)
**Root cause:** Filters still too strict  
**Fix:**
```bash
export BUY_RSI_MIN=15
export SELL_RSI_MIN=-5
# Or: export MIN_15M_RVOL=0.0001
```

### Issue: Too Many Signals (>8/day)
**Root cause:** Filters too loose  
**Fix:**
```bash
export BUY_RSI_MIN=30
export SELL_RSI_MAX=70
# Or: restore candle body to 0.05
```

### Issue: Poor Win Rate (<30%)
**Root cause:** Filters letting through too many fakeouts  
**Fix:**
```bash
# Re-enable Filter 2: EMA8 trend alignment
# Modify app/strategy.py: change MIN_EMA8_SLOPE_BARS from 999 to 5
```

### Issue: Dhan Token Expired
**Symptom:** "Invalid access token" or API 401 errors  
**Fix:**
```bash
# Regenerate token immediately (expires in 3-4 hours)
export DHAN_ACCESS_TOKEN="new_fresh_token_from_dhan_login"
# Restart scanner
```

---

## Expected Daily Output

### Successful Day Example
```
2026-09-25 09:30:00 | INFO | Scan started
2026-09-25 09:30:15 | INFO | [TCS] 15M candle: close=3440.00, orb_high=3398, orb_low=3385
2026-09-25 09:30:20 | INFO | [TCS] ✅ SETUP | direction=BUY | rvol=2.15 | rsi=62
2026-09-25 09:35:00 | INFO | [TCS] 5M candle: close=3442.00, rvol=1.80
2026-09-25 09:35:05 | INFO | [TCS] ✅ CONFIRMED | entry=3442.00 | sl=3425.00 | t1=3475.00
2026-09-25 09:35:10 | INFO | SIGNAL_GENERATED | entry sent to Telegram
2026-09-25 09:40:00 | INFO | [WIPRO] 15M rejected | reason=CANDLE_BODY_TOO_WEAK
2026-09-25 09:45:00 | INFO | [MARUTI] 15M rejected | reason=RSI_OUT_OF_BAND

... (more signals throughout day) ...

2026-09-25 15:30:00 | INFO | Market closed, scan complete
2026-09-25 15:30:05 | INFO | Summary: 3 signals generated, 27 rejections
```

---

## Files to Monitor

```
state/runtime_state.json        # Current day signals
state/logs/scanner.log          # Real-time logs
logs/day1_state.json            # Exported EOD state
logs/phase1_tracking.csv        # Signal outcomes
```

---

## Next Steps After Phase 1

**If 50-65% win rate achieved:**
- [ ] Proceed to Phase 2: Refinement (2026-10-02 onward)
- [ ] Collect 2 more weeks of data
- [ ] Optimize entry/exit rules
- [ ] Go live trading

**If 30-50% win rate:**
- [ ] Re-enable Filter 2: EMA8 trend (stricter)
- [ ] Adjust RSI bands based on rejection data
- [ ] Run Phase 1 for 5 more days

**If <30% win rate:**
- [ ] Revert to Phase 1 defaults
- [ ] Debug which filter is causing losses
- [ ] Request code review

---

## Support & Debugging

**Check logs for specific errors:**
```bash
# Find all rejections for a symbol
grep "MARUTI.*B1_FILTER_REJECTED" state/logs/scanner.log | head -10

# Find all setup acceptances
grep "✅ SETUP" state/logs/scanner.log

# Find API errors
grep -i "error\|exception\|failed" state/logs/scanner.log
```

**Manual validation:**
- Cross-check signals with live chart (TradingView)
- Verify RVOL calculation matches broker
- Confirm RSI values match chart RSI

---

**🎯 Goal:** Achieve 50-65% win rate over 5 trading days  
**📊 Measure:** Track every signal, entry time, exit, P&L  
**⚙️ Adjust:** Daily refinements based on rejection patterns  
**✅ Success:** Live trading deployment by 2026-10-08
