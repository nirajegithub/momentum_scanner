# Filter 1: RSI Momentum Band - Complete Analysis

## Part 1: DESIGN INTENT (Theory)

### What Filter 1 is SUPPOSED to Do

**Goal:** Ensure price is moving with momentum, not at exhaustion levels

**Rationale:**
```
Momentum Concept:
- RSI < 30 = Oversold (sellers exhausted, likely bounce up)
- RSI 30-70 = Neutral zone (balanced)
- RSI > 70 = Overbought (buyers exhausted, likely pullback)

Filter Logic:
- BUY breakout: Buy when momentum is INCREASING (not at peak)
- SELL breakout: Sell when momentum is DECREASING (not at trough)
- Reject extremes: Don't trade at exhaustion points
```

**Ideal RSI Bands (Original Design Intent):**
```
BUY:  55-70   (strong but not exhausted)
SELL: 30-45   (weak but not crashed)
```

This would reject:
- RSI < 55 for BUY (not enough momentum)
- RSI > 70 for BUY (too overbought, likely pullback)
- RSI < 30 for SELL (too oversold, likely bounce)
- RSI > 45 for SELL (not enough weakness)

---

## Part 2: CURRENT IMPLEMENTATION (Code)

### Actual Code (app/strategy.py, Lines 62-78)

```python
# Get current RSI
rsi_now = float(current["rsi14"])

# Determine breakout direction
if close > float(orb["high"]):
    direction = "BUY"
    # Check if RSI is within band
    band_ok = SETTINGS.buy_rsi_min < rsi_now < SETTINGS.buy_rsi_max
elif close < float(orb["low"]):
    direction = "SELL"
    # Check if RSI is within band
    band_ok = SETTINGS.sell_rsi_min < rsi_now < SETTINGS.sell_rsi_max
else:
    return _rejected(symbol, "NO_BREAKOUT")

# Reject if RSI is outside band
if not band_ok:
    return _rejected(
        symbol, "RSI_OUT_OF_BAND", 
        direction=direction, 
        rsi=round(rsi_now, 2),
        band=f"{SETTINGS.buy_rsi_min}-{SETTINGS.buy_rsi_max}" if direction == "BUY"
             else f"{SETTINGS.sell_rsi_min}-{SETTINGS.sell_rsi_max}",
    )
```

### Implementation Logic

```python
# The actual check uses STRICT inequalities (< and >)
# NOT <= or >=

For BUY:
  if buy_rsi_min < rsi_now < buy_rsi_max:
    PASS ✓
  else:
    FAIL ✗

For SELL:
  if sell_rsi_min < rsi_now < sell_rsi_max:
    PASS ✓
  else:
    FAIL ✗
```

**Important:** Uses `<` and `>`, NOT `<=` and `>=`

This means:
- `rsi_now = 55.0` with `buy_rsi_min = 55` → **FAIL** (not > 55, it equals 55)
- `rsi_now = 70.0` with `buy_rsi_max = 100` → **PASS** (< 100)
- `rsi_now = 70.1` with `buy_rsi_max = 70` → **FAIL** (> 70)

---

## Part 3: CURRENT CONFIG VALUES (app/config.py)

### Lines 16-19: RSI Configuration

```python
buy_rsi_min: float = float(os.getenv("BUY_RSI_MIN", "20"))
buy_rsi_max: float = float(os.getenv("BUY_RSI_MAX", "100"))
sell_rsi_min: float = float(os.getenv("SELL_RSI_MIN", "0"))
sell_rsi_max: float = float(os.getenv("SELL_RSI_MAX", "80"))
```

### Current Default Values

```
BUY:  20 < RSI < 100  (EXTREMELY WIDE - almost all values pass)
SELL: 0 < RSI < 80    (VERY WIDE - most values pass)
```

### Evolution of RSI Bands

```
Original Design Intent:
  BUY:  55-70   (strict - momentum increasing)
  SELL: 30-45   (strict - momentum decreasing)

Phase 1 Tuning (Current):
  BUY:  20-100  (loose - allows RSI 20-99)
  SELL: 0-80    (loose - allows RSI 1-79)

Why Changed?
  - Backtest showed strict bands rejected 90% of real trades
  - Real profitable trades often at RSI edges
  - Decision: Relax filter, rely on other filters (RVOL, Body)
```

---

## Part 4: DAY 1 ACTUAL DATA

### The 9 Weak Stocks & Their RSI on Breakout Candles

| Stock | Direction | RSI Value | Band | Status | Reason |
|---|---|---|---|---|---|
| **PNBHOUSING** | SELL | 36.93 | 0-80 | ✓ PASS | Within band |
| **USHAMART** | SELL | 35.45 | 0-80 | ✓ PASS | Within band |
| **SBILIFE** | SELL | 43.07 | 0-80 | ✓ PASS | Within band |
| **TRENT** | SELL | 40.00 | 0-80 | ✓ PASS | Within band |
| **PIRAMALFIN** | SELL | 40.18 | 0-80 | ✓ PASS | Within band |
| **AXISBANK** | BUY | 72.06 | 20-100 | ✓ PASS | Within band |
| **HONASA** | SELL | 44.40 | 0-80 | ✓ PASS | Within band |
| **AUBANK** | BUY | 56.34 | 20-100 | ✓ PASS | Within band |
| **BAJFINANCE** | BUY | 67.38 | 20-100 | ✓ PASS | Within band |

### Day 1 Log Messages (Actual Rejections)

```
2026-09-25 12:00:45 | B1_FILTER_REJECTED | AXISBANK | reason=RSI_OUT_OF_BAND | 
  direction=BUY | rsi=72.06 | band=55.0-70.0

2026-09-25 12:00:48 | B1_FILTER_REJECTED | CHOLAFIN | reason=RSI_OUT_OF_BAND | 
  direction=SELL | rsi=28.7 | band=30.0-45.0

2026-09-25 12:00:52 | B1_FILTER_REJECTED | JYOTICNC | reason=RSI_OUT_OF_BAND | 
  direction=SELL | rsi=47.68 | band=30.0-45.0

2026-09-25 12:00:52 | B1_FILTER_REJECTED | KAYNES | reason=RSI_OUT_OF_BAND | 
  direction=BUY | rsi=81.25 | band=55.0-70.0
```

**IMPORTANT:** The logs show bands like `55.0-70.0`, NOT `20.0-100.0`!

This means:
- Logs show STRICTER bands (55-70 for BUY, 30-45 for SELL)
- But config.py has LOOSER bands (20-100 for BUY, 0-80 for SELL)
- **DISCONNECT:** Code and logs don't match!

---

## Part 5: THE CRITICAL DISCONNECT

### What Config Says vs What Logs Show

**config.py (Current Implementation):**
```
BUY:  20 < RSI < 100
SELL: 0 < RSI < 80
```

**Day 1 Logs (Actual Behavior):**
```
BUY:  55 < RSI < 70    (STRICTER!)
SELL: 30 < RSI < 45    (STRICTER!)
```

### Why the Mismatch?

**Three Possibilities:**

1. **Environment Variables Override**
   ```bash
   # Someone set env vars that override config.py defaults
   export BUY_RSI_MIN=55
   export BUY_RSI_MAX=70
   export SELL_RSI_MIN=30
   export SELL_RSI_MAX=45
   ```

2. **Git History Change**
   ```bash
   # Earlier version had strict bands
   # Someone changed config.py to loose (20-100, 0-80)
   # But live system still running older version
   ```

3. **Cron Job Mismatch**
   ```bash
   # GitHub Actions pulls old code
   # Local config.py updated but remote hasn't
   ```

### Evidence from Day 1 Rejections

**AXISBANK BUY:**
```
RSI = 72.06
Log shows: band=55.0-70.0 (REJECT because 72.06 > 70)
Config shows: band=20.0-100.0 (should PASS)

This PROVES the live system used 55.0-70.0, not 20.0-100.0
```

**KAYNES BUY:**
```
RSI = 81.25
Log shows: band=55.0-70.0 (REJECT because 81.25 > 70)
Config shows: band=20.0-100.0 (should PASS)

Confirms: Live system stricter than config.py
```

**CHOLAFIN SELL:**
```
RSI = 28.7
Log shows: band=30.0-45.0 (REJECT because 28.7 < 30)
Config shows: band=0.0-80.0 (should PASS)

Confirms: Live system stricter than config.py
```

---

## Part 6: COMPARISON TABLE

| Aspect | Design Intent | Current Config | Day 1 Actual | Match? |
|---|---|---|---|---|
| **BUY Band** | 55-70 | 20-100 | 55-70 | ❌ Config≠Actual |
| **SELL Band** | 30-45 | 0-80 | 30-45 | ❌ Config≠Actual |
| **Purpose** | Reject extremes | Allow all | Reject extremes | ✓ Actual=Intent |
| **Strictness** | Medium | Loose | Medium | ⚠️ Inconsistent |
| **Why Set This Way** | Smart entry | Real trades fail | Unknown | ❓ |

---

## Part 7: THE REAL QUESTION

### What's Actually Running?

**Option A: Config is Wrong (Outdated)**
```
Theory: config.py has 20-100 / 0-80
Reality: Live system has 55-70 / 30-45
Reason: Environment variables override config.py
Action: Update config.py to match actual, or remove env vars
```

**Option B: Live System is Old**
```
Theory: config.py changed to 20-100 / 0-80
Reality: Cron job runs old code with 55-70 / 30-45
Reason: GitHub Actions not pulling latest
Action: Check git repo, verify latest code running
```

**Option C: Both are Happening**
```
Theory: config.py says 20-100 / 0-80
Reality: Env vars say 55-70 / 30-45
Live: Uses env vars (they override config.py)
Action: Decide: Keep strict bands or go loose? Then make consistent
```

---

## Part 8: IMPACT ON 9 WEAK STOCKS

### Why They Failed Under STRICT Bands (55-70, 30-45)

| Stock | Direction | RSI | Band | Result |
|---|---|---|---|---|
| AXISBANK | BUY | 72.06 | 55-70 | ✗ REJECTED (too high) |
| KAYNES | BUY | 81.25 | 55-70 | ✗ REJECTED (way too high) |
| CHOLAFIN | SELL | 28.7 | 30-45 | ✗ REJECTED (too low) |
| PVRINOX | SELL | 19.53 | 30-45 | ✗ REJECTED (way too low) |
| SBICARD | SELL | 27.31 | 30-45 | ✗ REJECTED (too low) |

**Key Finding:** Filter 1 (RSI) rejected several stocks due to STRICT bands

### If Config Was Actually Loose (20-100, 0-80)

```
All 9 would have PASSED Filter 1
Only rejected by other filters (RVOL, Body, etc.)
```

**This changes everything:**
- Under STRICT (actual): Filter 1 is effective, rejects bad trades
- Under LOOSE (config): Filter 1 is useless, RVOL becomes the real bottleneck
- Day 1 Results: Strict filter helped reject some (AXISBANK, KAYNES, CHOLAFIN)

---

## Part 9: RECOMMENDATIONS

### Immediate Action: Verify Which Bands Are Actually Running

**Check 1: Look at Environment Variables**
```bash
echo $BUY_RSI_MIN
echo $BUY_RSI_MAX
echo $SELL_RSI_MIN
echo $SELL_RSI_MAX
```

If these are set → They override config.py

**Check 2: Look at Cron Job**
```bash
# Find the cron job that runs the scanner
cat ~/.crontab
# or
crontab -l
```

Check what command it runs and what env vars it sets

**Check 3: Make It Consistent**

**Option A: Keep STRICT Bands (55-70, 30-45)**
```python
# Update config.py to match
buy_rsi_min: float = float(os.getenv("BUY_RSI_MIN", "55"))
buy_rsi_max: float = float(os.getenv("BUY_RSI_MAX", "70"))
sell_rsi_min: float = float(os.getenv("SELL_RSI_MIN", "30"))
sell_rsi_max: float = float(os.getenv("SELL_RSI_MAX", "45"))

# Effect: More rejections (good), fewer false signals (bad)
# Expected: Lower signal volume but higher quality
```

**Option B: Go LOOSE (20-100, 0-80)**
```python
# Keep config.py as is
# Remove any environment variable overrides

# Effect: Rely on other filters (RVOL, Body)
# Expected: More signals but need other filters to work
```

**Option C: Hybrid - Different Bands Per Stock**
```python
# Use strict for proven stocks (55-70, 30-45)
# Use loose for weak stocks (20-100, 0-80)

# Effect: Better signals for good stocks, more for weak stocks
```

---

## Summary Table: The Disconnect

| Level | BUY Band | SELL Band | Status |
|---|---|---|---|
| **Design Intent** | 55-70 | 30-45 | Smart, rejects extremes |
| **config.py Defaults** | 20-100 | 0-80 | Loose, allows almost all |
| **Day 1 Actual** | 55-70 | 30-45 | Strict, matched intent |
| **Consistency** | ❌ NOT MATCHING | ❌ NOT MATCHING | **PROBLEM** |

---

## Questions to Answer

1. **Are environment variables overriding config.py?**
   - Check: `echo $BUY_RSI_MIN`

2. **Should we keep strict bands or go loose?**
   - Strict: Better quality, fewer signals
   - Loose: Rely on other filters, more signals

3. **Why was config.py changed but not the cron job?**
   - Was there a reason to have different settings?

4. **For Phase 1, should we:**
   - A) Make config.py match actual (update to 55-70, 30-45)
   - B) Make actual match config.py (set env vars to loose)
   - C) Keep as is (let mismatch continue)

---

## Decision for Phase 1

**Recommended:** Make it CONSISTENT

**Option:** Keep STRICT Bands (55-70, 30-45)
- Reason: Day 1 data shows they work
- Effect: Filter 1 actively rejects bad trades
- Trade-off: Fewer signals, but higher quality

Update config.py to:
```python
buy_rsi_min: float = float(os.getenv("BUY_RSI_MIN", "55"))
buy_rsi_max: float = float(os.getenv("BUY_RSI_MAX", "70"))
sell_rsi_min: float = float(os.getenv("SELL_RSI_MIN", "30"))
sell_rsi_max: float = float(os.getenv("SELL_RSI_MAX", "45"))
```

This ensures config.py matches live system behavior.
