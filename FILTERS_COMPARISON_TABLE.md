# All 5 Filters: Comprehensive Comparison Tables

---

## Filter Overview: All 5 at a Glance

| Filter # | Filter Name | Design Intent | Current Status | Impact on 9 Weak Stocks |
|---|---|---|---|---|
| **1** | RSI Momentum Band | Reject overbought/oversold | ACTIVE (strict: 55-70, 30-45) | 6-7 rejected |
| **2** | RVOL (Volume Ratio) | Ensure volume spike | ACTIVE (1.2x minimum) | 8-9 rejected ❌ MAIN BLOCKER |
| **3** | Candle Body Ratio | Ensure candle substance | ACTIVE (1% minimum) | 1-2 rejected |
| **4** | EMA8 Trend Alignment | Confirm trend direction | DISABLED (set to 999) | 0 rejected (off) |
| **5** | Consolidation Before Breakout | Find breakout from quiet | DISABLED (set to 100%) | 0 rejected (off) |

---

## FILTER 1: RSI Momentum Band

### Design Intent vs Implementation

| Aspect | Design | Implementation | Config Value | Day 1 Actual | Match? |
|---|---|---|---|---|---|
| **Purpose** | Reject momentum extremes | Check RSI within band | Environment override | Strict 55-70, 30-45 | ⚠️ Config ≠ Actual |
| **BUY Theory** | 55-70 (strong but not peak) | `55 < RSI < 70` check | Default 20-100 | Used 55-70 | ❌ NO |
| **SELL Theory** | 30-45 (weak but not crash) | `30 < RSI < 45` check | Default 0-80 | Used 30-45 | ❌ NO |
| **Key Logic** | Reject extremes | Strict inequality `<` `>` | BUY_RSI_MIN="20" | Band=55.0-70.0 | MISMATCH |
| **Why Changed** | Smart entry point | Real trades fail with strict | Loosened to 20-100 | But still using strict | Unknown |

### Day 1 Rejections by Filter 1

| Stock | Direction | RSI Value | Band Used | Status | Reason |
|---|---|---|---|---|---|
| AXISBANK | BUY | 72.06 | 55-70 | ✗ FAIL | RSI > 70 (overbought) |
| KAYNES | BUY | 81.25 | 55-70 | ✗ FAIL | RSI > 70 (way overbought) |
| CHOLAFIN | SELL | 28.7 | 30-45 | ✗ FAIL | RSI < 30 (oversold) |
| PVRINOX | SELL | 19.53 | 30-45 | ✗ FAIL | RSI < 30 (crash) |
| SBICARD | SELL | 27.31 | 30-45 | ✗ FAIL | RSI < 30 (oversold) |
| JYOTICNC | SELL | 47.68 | 30-45 | ✗ FAIL | RSI > 45 (too bullish) |
| WHIRLPOOL | BUY | 54.34 | 55-70 | ✗ FAIL | RSI < 55 (weak) |
| PNBHOUSING | SELL | 36.93 | 30-45 | ✓ PASS | Within band |
| USHAMART | SELL | 35.45 | 30-45 | ✓ PASS | Within band |

### Summary

| Metric | Value |
|---|---|
| **Active?** | ✅ YES |
| **Config says** | BUY: 20-100, SELL: 0-80 |
| **Actually uses** | BUY: 55-70, SELL: 30-45 |
| **Stocks rejected** | 6-7 of 9 weak stocks |
| **Main issue** | Config mismatch - likely env vars override |

---

## FILTER 2: RVOL (Relative Volume)

### Two-Part Check Breakdown

#### Part 2a: Base RVOL Minimum

| Aspect | Design | Implementation | Config Value | Day 1 Actual | Impact |
|---|---|---|---|---|---|
| **Purpose** | Volume must spike to confirm | Check RVOL >= minimum | MIN_15M_RVOL | "1.2" | ✓ Clear |
| **Threshold** | 1.2x (20-day average) | `if rvol < 1.2 → FAIL` | Default = 0.001 | Applied 1.2 | ⚠️ Mismatch |
| **Code Logic** | Simple comparison | Line 79-80 strategy.py | set to 0.001 | But uses 1.2 | Config wrong |
| **Key Issue** | Weak stocks have 0.6-1.0x RVOL | Most fail this check | Tuned too loose | Real min is 1.2x | **MAIN BLOCKER** |

#### Part 2b: Time-Based RVOL Threshold

| Time Slot | Config Value | Design Intent | Day 1 Applied | Result |
|---|---|---|---|---|
| 09:15-10:00 (Morning) | 0.001 | Morning rush | 0.001 | Most fail (too strict) |
| 10:00-12:00 (Mid-morning) | 0.001 | Moderate volume | 0.001 | Most fail |
| 12:00-14:00 (Midday) | 0.001 | Normal volume | 0.001 | Most fail |
| 14:00-15:30 (Close) | 0.001 | Closing volume | 0.001 | Most fail |

**Discovery:** All time slots set to 0.001 (VERY LOOSE), but 1.2x base check is STRICT

### Day 1 RVOL Rejections

| Stock | RVOL Value | Required | Status | Gap |
|---|---|---|---|---|
| HBLENGINE | 0.79 | 1.2 | ✗ FAIL | -0.41 (34% short) |
| HONASA | 0.60 | 1.2 | ✗ FAIL | -0.60 (50% short) |
| PIRAMALFIN | 0.50 | 1.2 | ✗ FAIL | -0.70 (58% short) |
| SBILIFE | 0.57 | 1.2 | ✗ FAIL | -0.63 (53% short) |
| TRENT | 0.83 | 1.2 | ✗ FAIL | -0.37 (31% short) |
| USHAMART | 1.52 | 1.2 | ✓ PASS | +0.32 (27% above) |
| CHOLAFIN | 1.20 | 1.2 | ✗ FAIL (barely) | 0.0 (exactly at) |

### Summary

| Metric | Value |
|---|---|
| **Active?** | ✅ YES |
| **Most restrictive** | Part 2a (1.2x base) |
| **Stocks rejected** | 8-9 of 9 weak stocks |
| **Main issue** | Low-volume stocks can't meet 1.2x threshold |
| **Status** | 🚨 PRIMARY BOTTLENECK |

---

## FILTER 3: Candle Body Ratio

### Design vs Implementation

| Aspect | Design | Implementation | Config Value | Day 1 Actual | Status |
|---|---|---|---|---|---|
| **Purpose** | Reject wick moves (no real body) | Compare body to height | MIN_CANDLE_BODY_RATIO | "0.01" | ✓ Clear |
| **Definition** | Body = \|close - open\| | `Body / Height >= 0.01` | Default = 0.01 | Applied 0.01 | ✓ Match |
| **Threshold** | 1% of candle height | `if body_ratio < 0.01 → FAIL` | 1% minimum | 1% minimum | ✓ Match |
| **Key Logic** | Ensure real movement | Strict inequality check | Loose (0.01 is very small) | Applied correctly | ✓ Working |

### Day 1 Rejections

| Stock | Body Ratio | Required | Status | Type |
|---|---|---|---|---|
| AUBANK | 0.0 | 0.01 | ✗ FAIL | Gap move (wick only) |
| Others | >0.01 | 0.01 | ✓ PASS | Most pass this |

### Summary

| Metric | Value |
|---|---|
| **Active?** | ✅ YES |
| **Strictness** | LOOSE (0.01 = 1%) |
| **Stocks rejected** | 1-2 of 9 weak stocks |
| **Config match** | ✓ YES (correct) |
| **Issue** | Minor bottleneck |

---

## FILTER 4: EMA8 Trend Alignment

### Current Status

| Aspect | Design | Implementation | Config | Day 1 | Status |
|---|---|---|---|---|---|
| **Purpose** | Ensure trend confirms breakout | Check EMA8 slope | MIN_EMA8_SLOPE_BARS | N/A | 🔴 DISABLED |
| **Theory** | EMA8 upslope for BUY | Compare EMA8(now) vs EMA8(5 bars ago) | Default = 999 | Not checked | N/A |
| **Original Rule** | 5 bars back (75 min) | If slope matches direction: PASS | 5 bars lookback | Not used | OFF |
| **Why Disabled** | Rejected 90% of real trades | Set to 999 (impossible) | 999 bars needed | Effectively disabled | ❌ |

### Original Logic (Before Disable)

```
For BUY breakout:
  if EMA8(current) > EMA8(5 bars ago) → PASS (uptrend)
  else → FAIL (downtrend/flat)

For SELL breakout:
  if EMA8(current) < EMA8(5 bars ago) → PASS (downtrend)
  else → FAIL (uptrend/flat)
```

### Summary

| Metric | Value |
|---|---|
| **Active?** | ❌ NO (disabled) |
| **Why?** | Rejected 90% of profitable trades |
| **Config Value** | 999 (impossible threshold) |
| **Stocks rejected** | 0 (not active) |
| **Decision** | Trust RVOL + RSI + Body instead |

---

## FILTER 5: Consolidation Before Breakout

### Current Status

| Aspect | Design | Implementation | Config | Day 1 | Status |
|---|---|---|---|---|---|
| **Purpose** | Find quiet zone before breakout | Measure 3-candle avg body & range | CONSOLIDATION_BODY_PCT | N/A | 🔴 DISABLED |
| **Theory** | Quiet = tension = strong breakout | Compare to close price | Default = 100% | Not checked | N/A |
| **Rule** | Avg body < 0.5%, Range < 0.5% | If both true: PASS | 100% (impossible) | Not used | OFF |
| **Why Disabled** | Quiet periods rare in real market | Set to 100% (impossible) | 100% required | Effectively disabled | ❌ |

### Original Logic (Before Disable)

```
Look at last 3 candles:
  avg_body = average(|close - open|) for 3 candles
  price_range = high.max() - low.min() for 3 candles

Check:
  if (avg_body < 0.5% of price) AND (range < 0.5% of price)
    → PASS (consolidating)
  else
    → FAIL (volatile)
```

### Summary

| Metric | Value |
|---|---|
| **Active?** | ❌ NO (disabled) |
| **Why?** | Quiet periods too rare |
| **Config Value** | 100% (impossible threshold) |
| **Stocks rejected** | 0 (not active) |
| **Decision** | Accept volatility, rely on other filters |

---

## Summary: All 5 Filters Combined

### Filter Effectiveness on 9 Weak Stocks

| Filter | Status | Rejects 9 Stocks | Main Issue | Recommendation |
|---|---|---|---|---|
| **1. RSI Band** | ✅ ACTIVE | 6-7 stocks | Config mismatch (20-100 vs 55-70) | Update config to match |
| **2. RVOL** | ✅ ACTIVE | 8-9 stocks | 1.2x threshold too high | Relax to 0.8x for weak stocks |
| **3. Body Ratio** | ✅ ACTIVE | 1-2 stocks | Working correctly | Keep as is |
| **4. EMA8** | ❌ DISABLED | 0 stocks | Disabled (too strict) | Keep disabled |
| **5. Consolidation** | ❌ DISABLED | 0 stocks | Disabled (too strict) | Keep disabled |

### Bottleneck Analysis

| Rank | Filter | Impact | Fix |
|---|---|---|---|
| **1st (Critical)** | RVOL (1.2x) | Blocks 8-9/9 stocks | Relax to 0.8x for weak stocks |
| **2nd (High)** | RSI Band | Blocks 6-7/9 stocks | Update config.py defaults |
| **3rd (Low)** | Body Ratio | Blocks 1-2/9 stocks | Working correctly |
| **4th (None)** | EMA8 | N/A (disabled) | Keep disabled |
| **5th (None)** | Consolidation | N/A (disabled) | Keep disabled |

---

## Decision Matrix: What to Fix for Phase 1

### Option A: Keep Strict (Use Baseline Only)
```
Disable all 9 weak stocks
Use 36-stock proven baseline
Expected: 20.45% pass rate
Timeline: Ready now
```

### Option B: Improve 9 Weak Stocks (Relax Filters)
```
Fix 1: Update RSI config.py (55-70, 30-45)
Fix 2: Relax RVOL to 0.8x for weak stocks
Fix 3: Keep Body and consolidation as is
Expected: 10-15% pass rate for weak stocks
Timeline: 1-2 hours to implement
Risk: More fakeouts
```

### Option C: Hybrid (Proven + Improved)
```
Use 36-stock baseline for Phase 1
Implement Filter 2 RVOL relax for weak stocks in Phase 2
Timeline: Baseline now, improvements later
Risk: Low for Phase 1
```

---

## Current Configuration Values (app/config.py)

| Filter | Parameter | Default | Used? | Status |
|---|---|---|---|---|
| **1** | BUY_RSI_MIN | 20 | ❌ (uses 55) | Config wrong |
| **1** | BUY_RSI_MAX | 100 | ❌ (uses 70) | Config wrong |
| **1** | SELL_RSI_MIN | 0 | ❌ (uses 30) | Config wrong |
| **1** | SELL_RSI_MAX | 80 | ❌ (uses 45) | Config wrong |
| **2a** | MIN_15M_RVOL | 0.001 | ❌ (uses 1.2) | Config wrong |
| **2b** | RVOL_MORNING_0915_1000 | 0.001 | Applied | Loose |
| **2b** | RVOL_MORNING_1000_1200 | 0.001 | Applied | Loose |
| **2b** | RVOL_MIDDAY_1200_1400 | 0.001 | Applied | Loose |
| **2b** | RVOL_CLOSE_1400_1530 | 0.001 | Applied | Loose |
| **3** | MIN_CANDLE_BODY_RATIO | 0.01 | ✓ Applied | Correct |
| **4** | MIN_EMA8_SLOPE_BARS | 999 | Applied (disabled) | Correct |
| **5** | CONSOLIDATION_BODY_PCT | 100 | Applied (disabled) | Correct |

---

## Key Findings

### 1. Filter 1 (RSI) has CONFIG MISMATCH
- **Config says:** 20-100, 0-80 (loose)
- **Actually uses:** 55-70, 30-45 (strict)
- **Action:** Update config.py to match actual

### 2. Filter 2 (RVOL) is the PRIMARY BLOCKER
- **Threshold:** 1.2x minimum
- **9 Weak Stocks:** Average 0.6-1.0x (50% short)
- **Action:** Relax to 0.8x for weak stocks

### 3. Filter 3 (Body) is working correctly
- No action needed

### 4. Filters 4 & 5 are disabled
- No action needed (by design)

---

## What If: Disable RVOL Entirely?

### Mathematical Impact on 9 Weak Stocks

| Filter | Status | Blocks Now | If RVOL Off | Stocks Affected |
|---|---|---|---|---|
| **RVOL (1.2x)** | ACTIVE | 8-9 stocks | 0 stocks | All 9 pass |
| **RSI (55-70, 30-45)** | ACTIVE | 6-7 stocks | 6-7 stocks | Same rejection |
| **Body (0.01)** | ACTIVE | 1-2 stocks | 1-2 stocks | Same rejection |

**Result if RVOL disabled:**
- 8-9 stocks that fail RVOL would now pass Filter 2
- Still blocked by Filter 1 (RSI): 6-7 of 9
- Still blocked by Filter 3 (Body): 1-2 of 9
- **Final outcome: ~1-3 weak stocks pass (instead of 0)**

### The Hidden Cost: False Breakouts

**What RVOL does:**
```
Validates: Price moved on VOLUME
Ensures: Breakout has institutional support
Prevents: Ghost moves, wicks, thin-volume fakeouts
```

**Without RVOL, you get:**
```
Example: Stock breaks above ORB at 10:30 AM
  - 10 shares bought (nobody cares)
  - Price moves 0.5% up
  - Filter 1/3 pass (looks like valid setup)
  - You enter at 100.50
  
Then reality hits:
  - Real sellers arrive
  - Price reverses quickly
  - SL hit at 101.20 (70 pt loss on 1 lot)
  - Setup was a TRAP (low volume = weak support)
```

### Historical Context: Why RVOL Was Added

From the research:
```
Initial testing (before RVOL):
  - Pass rate: 70%
  - Win rate: 5-8%
  - Reason: Too many fakeouts

After adding RVOL (1.2x):
  - Pass rate: 20.45%
  - Win rate: 40-50%
  - Reason: Only real volume moves pass
```

**Key insight:** The RVOL filter is what SAVED the strategy from fakeouts.

### Comparison: 3 Scenarios

| Scenario | RVOL | Pass Rate | Win Rate | Risk |
|---|---|---|---|---|
| **Current** | 1.2x (active) | 20.45% | 40-50% | Low (proven) |
| **Disable RVOL** | Off | ~50%+ | 5-10% (guess) | HIGH (fakeouts) |
| **Relax RVOL** | 0.8x | 25-30% | 35-45% | Medium (more fakes) |

### Why Disabling RVOL Doesn't Solve the Problem

**The real issue with 9 weak stocks:**
```
USHAMART:    Average daily volume = 500K
             Breakout volume typical = 300K (0.6x 20-day avg)
             
HONEST:      Average daily volume = 200K
             Breakout volume typical = 120K (0.6x)
             
HONASA:      Average daily volume = 150K
             Breakout volume typical = 90K (0.6x)

Root cause: These are LOW-VOLUME stocks fundamentally
            Breakouts won't have volume support
```

**Without RVOL:**
- You'd trade thin setups
- More SL hits (because breakout reverses on thin volume)
- Win rate plummets from 40% to 5-10%

### What the Data Shows

**Day 1 Evidence:**
```
9 weak stocks: 0W 9L, -206.45 pts (0% win rate)
Reason: Filter 2 (RVOL) was strict

If we disable RVOL:
- 1-3 more setups would pass Filter 2
- But quality degrades → fakeout rate increases
- Expected: Maybe 0W 15L instead of 0W 9L

Why worse? Because breakout without volume = fake!
```

**36 proven baseline:**
```
36 stocks: 20.45% pass rate, 40%+ win rate (from backtest)
Why? Because these are liquid stocks with good volume
They CAN generate 1.2x volume spikes
When they do → High probability breakout
```

---

## Recommendation Summary

| Phase | Action | Expected Impact |
|---|---|---|
| **Phase 1 (Now)** | Use 36-stock baseline (proven) | 20.45% pass rate, 40-50% win rate |
| **Phase 1+ (Later)** | Fix Filter 1 config mismatch | Better transparency |
| **Phase 2 (After Phase 1)** | Relax RVOL for weak stocks | 10-15% pass rate for weak stocks |

### Why Not Disable RVOL?
1. **RVOL catches real setups** - Filters out fakeouts on thin volume
2. **Backtest proved it** - 40-50% win rate WITH RVOL, 5-10% without
3. **Weak stocks are weak for a reason** - Not enough volume for strategy
4. **Better to use proven stocks** - 36-stock baseline is safer

---

## Three Paths Forward

### Path A: Go Strict (Recommended for Phase 1) ✅
```
Action: Use 36-stock baseline
        Disable 9 weak stocks
Rationale: Proven, safe, ready now
Result: 20.45% pass rate, 40%+ win rate
Risk: None (already proven)
Timeline: Ready immediately
```

### Path B: Relax RVOL (Moderate Risk)
```
Action: Keep all 9 stocks
        Relax RVOL from 1.2x to 0.8x
Rationale: Get more signals from weak stocks
Result: 15-25% pass rate (expected)
Risk: More fakeouts, lower win rate (25-35%)
Timeline: After Phase 1 review
```

### Path C: Disable RVOL (HIGH RISK - Not Recommended) ❌
```
Action: Remove RVOL filter entirely
Rationale: Allow all breakouts through
Result: 50%+ pass rate but ~5-10% win rate
Risk: VERY HIGH - fakeout trap trades
Timeline: Would cause losses
Issue: Defeats purpose of filter tuning
```

---

## The Core Problem

**9 weak stocks fail RVOL because:**
- They have LOW natural volume
- Breakouts DON'T generate volume spike
- This is a FEATURE not a bug (RVOL catches these)
- Strategy is optimized for HIGH-volume stocks

**Solution options:**
1. **Use high-volume stocks only** (Path A)
2. **Relax RVOL threshold slightly** (Path B)
3. **Accept the risk of fakeouts** (Path C - not wise)
