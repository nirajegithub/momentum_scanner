# Backtest Framework for Strategy Improvements

## Overview
Before implementing any new feature, backtest it against 3-6 months of historical data to validate actual impact.

---

## Key Metrics to Track

### Primary Metrics
| Metric | Target | Formula |
|--------|--------|---------|
| **Win Rate %** | 55%+ | (Winning Trades / Total Trades) × 100 |
| **Profit Factor** | 2.0+ | Gross Profit / Gross Loss |
| **Sharpe Ratio** | 1.5+ | (Avg Daily Return / Std Dev) × √252 |
| **Avg Win/Loss** | 2:1+ | Avg Winning Points / Avg Losing Points |
| **Max Drawdown %** | <10% | Largest Peak-to-Trough decline |

### Secondary Metrics
- **Total Trades**: How many signals generated
- **Best Trade**: Highest points won
- **Worst Trade**: Largest points lost
- **Consecutive Losses**: Worst losing streak
- **Recovery Factor**: Net Profit / Max Drawdown

---

## Backtest Procedure

### Step 1: Run Baseline (Current Strategy)
```bash
python scripts/historical_backtest_15m5m_confirmation.py \
  --data-5m data/5m_candles.csv \
  --data-15m data/15m_candles.csv \
  --start 2026-04-01 \
  --end 2026-09-22 \
  --out backtest/baseline_results.csv \
  --verbose
```

### Step 2: Analyze Baseline Results
```bash
python scripts/analyze_backtest.py backtest/baseline_results.csv
```

Expected Output:
```
╔════════════════════════════════════════════════╗
║     NSE MOMENTUM SCANNER - BACKTEST RESULTS    ║
╠════════════════════════════════════════════════╣
║ Period: 2026-04-01 to 2026-09-22 (144 days)   ║
║ Trading Days: 96 (excl. weekends/holidays)    ║
╠════════════════════════════════════════════════╣
║ Total Trades: 247                              ║
║ Winning Trades: 142 (57.5%)                   ║
║ Losing Trades: 105 (42.5%)                    ║
╠════════════════════════════════════════════════╣
║ Total Points: +1,245.30 pts                    ║
║ Avg Win: +12.45 pts                            ║
║ Avg Loss: -8.30 pts                            ║
║ Profit Factor: 2.14x                           ║
╠════════════════════════════════════════════════╣
║ Max Drawdown: -8.2%                            ║
║ Sharpe Ratio: 1.67                             ║
║ Recovery Factor: 151.8                         ║
╠════════════════════════════════════════════════╣
║ Best Day: +145.20 pts                          ║
║ Worst Day: -95.50 pts                          ║
║ Consecutive Losses: 7                          ║
╚════════════════════════════════════════════════╝
```

### Step 3: Test One Improvement
Modify code for ONE feature (e.g., Trailing Stop Loss)
```bash
python scripts/historical_backtest_15m5m_confirmation.py \
  --data-5m data/5m_candles.csv \
  --data-15m data/15m_candles.csv \
  --start 2026-04-01 \
  --end 2026-09-22 \
  --trailing-stop 5 \
  --out backtest/trailing_stop_5pct.csv
```

### Step 4: Compare Results
```bash
python scripts/compare_backtest.py \
  backtest/baseline_results.csv \
  backtest/trailing_stop_5pct.csv
```

Expected Output:
```
IMPROVEMENT COMPARISON
═══════════════════════════════════════════════════════

Baseline         vs    Trailing Stop 5%    Δ Change
────────────────────────────────────────────────────
Total Trades: 247      Total Trades: 241    ↓ 2.4%
Win Rate: 57.5%        Win Rate: 61.2%      ↑ 3.7%  ✅
Avg Win: 12.45 pts     Avg Win: 14.20 pts   ↑ 14.0% ✅
Avg Loss: -8.30 pts    Avg Loss: -6.80 pts  ↑ 18.1% ✅
Profit Factor: 2.14x   Profit Factor: 2.48x ↑ 15.9% ✅
Total Points: +1245.3  Total Points: +1389  ↑ 11.5% ✅
Sharpe Ratio: 1.67     Sharpe Ratio: 1.85   ↑ 10.8% ✅
Max Drawdown: -8.2%    Max Drawdown: -7.1%  ↓ 13.4% ✅

✅ VERDICT: IMPROVEMENT VALIDATED
Implement this change!
```

---

## Improvements to Test (In Priority Order)

### 🔥 High Priority (Quick Wins)

#### 1. Trailing Stop Loss
```
Test Cases:
- 3% trailing stop
- 5% trailing stop
- 7% trailing stop

Expected Impact: +5-15% on total points, -10-15% on losses
```

#### 2. Partial Profit Taking
```
Test Cases:
- Take 1/3 profit at T1, hold 2/3 to T2/T3
- Take 1/2 profit at T1, hold 1/2 to T2/T3
- Take all at first target hit

Expected Impact: Smoother equity curve, lower drawdown
```

#### 3. Daily Loss Limit
```
Test Cases:
- Stop after -100 points daily loss
- Stop after -150 points daily loss
- Stop after 3 consecutive losses

Expected Impact: -20-30% fewer losses, smaller max drawdown
```

---

### 📊 Medium Priority

#### 4. Market Trend Filter (Nifty50)
```
Test Cases:
- Only BUY if Nifty50 is green (up today)
- Only SELL if Nifty50 is red (down today)
- Skip signals during sideways markets

Expected Impact: +5-10% win rate, fewer false signals
```

#### 5. Momentum Surge Filter (Already Implemented ✅)
```
Test Cases:
- RVOL > 3.5 + RSI > 60 (current)
- RVOL > 3.0 + RSI > 55 (looser)
- RVOL > 4.0 + RSI > 65 (stricter)

Expected Impact: Measure if earlier entries improve or worsen results
```

---

### 📈 Lower Priority

#### 6. Time-Based Exit
```
Test Cases:
- Exit after 60 min if no movement >1%
- Exit after 30 min if no movement >2%
- Exit at 3:15 PM regardless

Expected Impact: Capture intraday moves, reduce holding time
```

#### 7. Alternative Setup (B2 ORB)
```
Test Cases:
- Breakout after first pullback (B2)
- Multiple breakout patterns

Expected Impact: More trading opportunities, validate quality
```

---

## Backtest Template

```python
# backtest/test_improvement.py
def test_trailing_stop():
    """Test trailing stop loss improvement."""
    
    # Run baseline
    baseline = run_backtest(
        strategy="b1_orb",
        trailing_stop=None,  # Baseline
        start_date="2026-04-01",
        end_date="2026-09-22"
    )
    
    # Run with improvement
    improved = run_backtest(
        strategy="b1_orb",
        trailing_stop=5,  # 5% trailing stop
        start_date="2026-04-01",
        end_date="2026-09-22"
    )
    
    # Compare metrics
    comparison = {
        "total_points": improved["total"] - baseline["total"],
        "win_rate": improved["win_rate"] - baseline["win_rate"],
        "sharpe": improved["sharpe"] - baseline["sharpe"],
        "max_drawdown": improved["max_dd"] - baseline["max_dd"],
    }
    
    # Verdict: implement if all metrics improve
    verdict = all(v > 0 for k, v in comparison.items() if k != "max_drawdown")
    
    return {
        "improvement": "Trailing Stop 5%",
        "comparison": comparison,
        "verdict": "IMPLEMENT" if verdict else "REJECT"
    }
```

---

## Data Requirements

### What You Need
1. **5M Candles**: symbol, timestamp, open, high, low, close, volume
2. **15M Candles**: symbol, timestamp, open, high, low, close, volume
3. **Date Range**: Minimum 3 months, ideally 6 months
4. **Trading Calendar**: NSE holidays/non-trading days

### Where to Get Data
```bash
# Export from your Dhan historical API
python scripts/export_historical_data.py \
  --symbols AARTIIND,ACMESOLAR,ADANIGREEN \
  --start 2026-04-01 \
  --end 2026-09-22 \
  --output data/
```

---

## Decision Rules

✅ **Implement if:**
- Win Rate increases by 3%+
- Profit Factor increases by 10%+
- Total Points increase by 5%+
- Sharpe Ratio increases
- Max Drawdown decreases

❌ **Reject if:**
- Any metric gets worse
- Total trades decrease >20%
- Max consecutive losses increase significantly
- Sharpe Ratio decreases

🤔 **Investigate further if:**
- Metrics are mixed (some good, some bad)
- Performance varies significantly by timeframe
- Performance by sector is inconsistent

---

## Next Steps

1. **Export 6 months of historical data** from Dhan
2. **Run baseline backtest** on current strategy
3. **Pick top 3 improvements** to test
4. **Test each independently** (one at a time)
5. **Compare results** against baseline
6. **Implement only validated improvements**
7. **Re-test combined improvements** (trailing stop + daily limit + trend filter)

This ensures every change is data-driven and validated! 📊
