# B1 ORB Breakout: 5-Filter Logic (Detailed)

**Strategy:** Entry on 15M ORB breakout with 5M confirmation  
**Goal:** Filter out 80% of fakeouts to find high-probability setups

---

## Overview: The 5 Active Filters

When a 15M candle breaks beyond the 09:15 ORB, it must pass ALL 5 filters:

```
Breakout Detected
       ↓
Filter 1: RSI Momentum Check
Filter 2: RVOL (Volume Ratio) Check
Filter 3: Candle Body Quality Check
Filter 4: EMA8 Trend Alignment Check
Filter 5: Consolidation Before Breakout Check
       ↓
PASSED ALL 5? → Setup Created (wait for 5M confirmation)
FAILED ANY? → Rejected (setup discarded)
```

---

## Filter 1: RSI Momentum Band ✓

**Purpose:** Ensure price is moving with momentum, not at exhaustion

**Current Settings:**
```
BUY:  RSI must be between 20 and 100
SELL: RSI must be between 0 and 80
```

**How It Works:**
```
BUY Breakout:
  if 20 < RSI < 100 → PASS ✓
  if RSI <= 20     → FAIL ✗ (oversold, weak momentum)
  if RSI >= 100    → FAIL ✗ (not possible, RSI max is 100)

SELL Breakout:
  if 0 < RSI < 80  → PASS ✓
  if RSI >= 80     → FAIL ✗ (overbought, weak downside)
  if RSI < 0       → FAIL ✗ (not possible, RSI min is 0)
```

**Example from Day 1:**
```
AXISBANK BUY breakout:
  RSI = 74.67
  Band = 55-70
  Result: REJECTED (74.67 > 70) - too overbought
  
KAYNES BUY breakout:
  RSI = 81.25
  Band = 55-70
  Result: REJECTED (81.25 > 70) - way too overbought
```

**Why Weak Stocks Fail:**
- These 9 stocks often have RSI at band edges (too overbought/oversold)
- Possible reason: Low-quality breakouts that overshoot quickly

---

## Filter 2: RVOL (Relative Volume) ✓

**Purpose:** Ensure volume spike supports the breakout (not a dead cat bounce)

**Two-Part Check:**

### Part 2a: Minimum RVOL Baseline
```
Current Setting: MIN_15M_RVOL = 1.2
(Volume must be 1.2x the 20-day average)

Breakout Volume Check:
  if RVOL >= 1.2  → PASS ✓
  if RVOL < 1.2   → FAIL ✗ (volume too low, weak breakout)
```

**Example from Day 1:**
```
HBLENGINE BUY breakout:
  RVOL = 0.79
  Required = 1.2
  Result: REJECTED (0.79 < 1.2) - insufficient volume
  
HONASA SELL breakout:
  RVOL = 0.6
  Required = 1.2
  Result: REJECTED (0.6 < 1.2) - weak volume
```

### Part 2b: Time-Based RVOL Threshold
```
Check time slot and apply different threshold:

09:15-10:00 AM:    RVOL >= 0.001 (morning rush)
10:00-12:00 PM:    RVOL >= 0.001 (mid-morning)
12:00-02:00 PM:    RVOL >= 0.001 (midday)
02:00-03:30 PM:    RVOL >= 0.001 (close)

(All tuned to 0.001 after Phase 1 optimization)
```

**Why Weak Stocks Fail:**
- Average RVOL = 0.6-1.0x (BELOW 1.2x threshold)
- These stocks have naturally lower volume spikes
- Breakouts happen on light volume (fakeout risk)

---

## Filter 3: Candle Body Ratio ✓

**Purpose:** Ensure the candle has substance (not a wick with no body)

**Current Setting:**
```
MIN_CANDLE_BODY_RATIO = 0.01
(Body must be at least 1% of candle height)
```

**How It Works:**
```
Candle Body = |close - open|
Candle Height = high - low

Body Ratio = Candle Body / Candle Height

Check:
  if Body Ratio >= 0.01 → PASS ✓
  if Body Ratio < 0.01  → FAIL ✗ (mostly wicks, no real movement)
```

**Visual Example:**
```
Good Candle (PASS):          Bad Candle (FAIL):
    high ━━                      high ━━ (wick)
          ┃                            ┃
    ┏━━━━┫                       ┏┫
    ┃ 70% ┃ (body = 70% of      ┃┃ (body = 2% of
    ┗━━━━┫   height)            ┗┫   height)
          ┃                            ┃
    low ━━━                      low ━━━
    
Body Ratio = 0.70              Body Ratio = 0.02
PASS ✓                         FAIL ✗
```

**Example from Day 1:**
```
AUBANK BUY breakout:
  Body Ratio = 0.0
  Required = 0.01
  Result: REJECTED - gap/wick move, no body
```

**Why Weak Stocks Fail:**
- Often gap up/down on volume (wick without body)
- Suggests manipulation or overnight news
- Real breakouts have substantial candle bodies

---

## Filter 4: EMA8 Trend Alignment ✓

**Purpose:** Ensure 8-period moving average is aligned with breakout direction

**Current Setting:**
```
MIN_EMA8_SLOPE_BARS = 999
(Effectively DISABLED - no candles can reach 999 bars)
```

**How It Worked (Before Disable):**
```
For BUY breakout:
  if EMA8(current) > EMA8(5 bars ago) → PASS ✓ (uptrend)
  if EMA8(current) <= EMA8(5 bars ago) → FAIL ✗ (downtrend/flat)

For SELL breakout:
  if EMA8(current) < EMA8(5 bars ago) → PASS ✓ (downtrend)
  if EMA8(current) >= EMA8(5 bars ago) → FAIL ✗ (uptrend/flat)
```

**Why It Was Disabled:**
- In live trading (2026-09-25), this rejected 90% of real trades
- Turned out: Many profitable breakouts happen against the trend
- Decision: Trust volume + RSI + body quality instead

**Status:** Currently DISABLED

---

## Filter 5: Consolidation Before Breakout ✓

**Purpose:** Ensure quiet period before breakout (shows tension release)

**Current Setting:**
```
CONSOLIDATION_BODY_PCT = 100
(Effectively DISABLED)
```

**How It Worked (Before Disable):**
```
Look at last 3 candles:
  - Calculate average candle body
  - Calculate price range (high-low)
  
Check:
  if (avg_body < 0.5% of price) AND (range < 0.5% of price)
    → PASS ✓ (quiet/consolidating)
  else
    → FAIL ✗ (volatile/trending)
```

**Why It Was Disabled:**
- In real trading: Quiet periods are RARE
- Rejected too many valid breakouts
- Decision: Accept volatility, use other filters

**Status:** Currently DISABLED

---

## The Problem: Why 9 Stocks Show 0% Pass Rate

### Current Filter Settings (Very Loose):
```
Filter 1: RSI      20-100 (BUY) / 0-80 (SELL)   [Very wide]
Filter 2: RVOL     1.2x minimum                  [Moderate]
Filter 3: Body     0.01 (1%)                     [Very loose]
Filter 4: EMA8     Disabled                      [Off]
Filter 5: Consol   Disabled                      [Off]
```

### Why These 9 Stocks Fail:

**Hypothesis:** Filter 2 (RVOL) is the bottleneck

Actual RVOL data for 9 weak stocks:
```
USHAMART:   RVOL = 0.15-0.6x   (need 1.2x) ✗
HONASA:     RVOL = 0.04-0.6x   (need 1.2x) ✗
PIRAMALFIN: RVOL = 0.5x        (need 1.2x) ✗
TRENT:      RVOL = 0.83-1.19x  (need 1.2x) ✗✗ (so close!)
SBILIFE:    RVOL = 0.39-0.57x  (need 1.2x) ✗

Result: ~80-95% of breakouts rejected due to RVOL
```

**Key Finding:**
- These 9 stocks have LOW average volume
- Breakouts don't generate 1.2x volume spike
- Currently NO setup qualifies (0% pass rate)

---

## How to Fix: Three Options

### Option 1: Lower RVOL Threshold for Weak Stocks
```python
# Current
MIN_15M_RVOL = 1.2  # All stocks

# Change to
if symbol in WEAK_STOCKS:
    MIN_15M_RVOL = 0.8  # Relax for these stocks
else:
    MIN_15M_RVOL = 1.2  # Keep strict for others

# Expected result: 10-15% pass rate (some improvement)
```

### Option 2: Use Time-Based Thresholds More Aggressively
```python
# Current (all 0.001)
rvol_morning_0915_1000 = 0.001
rvol_morning_1000_1200 = 0.001
rvol_midday_1200_1400 = 0.001
rvol_close_1400_1530 = 0.001

# Change to
rvol_morning_0915_1000 = 0.8   # Morning rush (higher)
rvol_morning_1000_1200 = 0.6   # Mid-morning (moderate)
rvol_midday_1200_1400 = 0.4    # Midday (relaxed)
rvol_close_1400_1530 = 0.5     # Close (moderate)

# Expected result: 15-20% pass rate
```

### Option 3: Re-Enable EMA8 Trend Filter with Longer Period
```python
# Current
MIN_EMA8_SLOPE_BARS = 999  # Disabled

# Change to
MIN_EMA8_SLOPE_BARS = 20   # Check 20 candles back (75 min)
# Ensures breakout aligns with longer-term trend

# Expected result: Better quality setups (10-20% pass rate)
```

---

## Current Filter Flow Chart

```
Breakout Detected (15M candle breaks ORB)
    ↓
[Filter 1] RSI Check
  BUY:  20 < RSI < 100?
  SELL: 0 < RSI < 80?
  ✗ If no → REJECT (RSI_OUT_OF_BAND)
    ↓
[Filter 2a] Base RVOL Check
  RVOL >= 1.2x?
  ✗ If no → REJECT (RVOL_TOO_LOW)
    ↓
[Filter 2b] Time-Based RVOL Check
  RVOL >= time_threshold?
  ✗ If no → REJECT (RVOL_BELOW_TIME_THRESHOLD)
    ↓
[Filter 3] Candle Body Check
  Body Ratio >= 0.01?
  ✗ If no → REJECT (CANDLE_BODY_TOO_WEAK)
    ↓
[Filter 4] EMA8 Slope Check
  DISABLED (MIN_EMA8_SLOPE_BARS = 999)
  ✓ Automatically PASS
    ↓
[Filter 5] Consolidation Check
  DISABLED (CONSOLIDATION_BODY_PCT = 100)
  ✓ Automatically PASS
    ↓
✅ SETUP CREATED (wait for 5M confirmation)
```

---

## Why 9 Stocks Fail (Summary)

| Stock | Issue | Typical RVOL | Status |
|---|---|---|---|
| USHAMART | Very low volume | 0.15-0.60x | Blocked by Filter 2a |
| HONASA | Minimal volume | 0.04-0.60x | Blocked by Filter 2a |
| PIRAMALFIN | Low volume | 0.50-6.10x | Usually blocked by Filter 2a |
| TRENT | Low volume | 0.83-1.19x | Almost pass, occasional rejection |
| SBILIFE | Very low volume | 0.39-0.57x | Blocked by Filter 2a |
| AXISBANK | Overbought | High RSI | Blocked by Filter 1 (RSI > 70) |
| PNBHOUSING | Low volume | 0.50-1.50x | Usually blocked by Filter 2a |
| AUBANK | Weak candles | Low body ratio | Blocked by Filter 3 (body_ratio = 0) |
| BAJFINANCE | Low volume | 0.50-1.50x | Blocked by Filter 2a |

**Most Common Blocker:** Filter 2a (RVOL minimum 1.2x)

---

## Recommendations

### To Improve 9 Weak Stocks:
1. **Relax RVOL for low-volume stocks** (0.8x instead of 1.2x)
2. **Re-enable EMA8 with longer lookback** (20 bars instead of 5)
3. **Accept lower quality** (remove body ratio requirement for these stocks)

### Expected Outcome:
- Current pass rate: 0%
- After improvements: 10-20%
- Risk: More fakeouts

---

## Current Implementation Location

**File:** `app/strategy.py`

**Filter Locations:**
- Filter 1 (RSI): Lines 62-78
- Filter 2a (RVOL): Lines 79-80
- Filter 2b (Time RVOL): Lines 103-116
- Filter 3 (Body): Lines 82-85
- Filter 4 (EMA8): Lines 87-95 (disabled)
- Filter 5 (Consolidation): Lines 118-131 (disabled)

**Config Values:** `app/config.py`

---

## Next Step Decision

**A: Investigate & Improve**
- Modify filters to pass 10-15% of weak stock trades
- Higher risk but more volume of signals
- Time: 2-3 hours to test

**B: Disable & Use Baseline**
- Keep 36-stock proven universe (20.45% pass rate)
- Lower risk, immediate improvement
- Time: 0 hours (ready now)

**Recommendation:** B for Phase 1 (proven, immediate). Then A after Phase 1 if you want to add weak stocks back.
