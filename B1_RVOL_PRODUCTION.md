# B1 + RVOL Production Strategy

This package switches the live scanner to the B1 ORB + RVOL candidate selected from the repository's historical filter-ablation work.

## Entry rules

1. Previous trading day close > 350.
2. Previous trading day volume > 500,000.
3. Fixed 09:15 15M candle is the opening range (ORB).
4. Wait for the **first subsequent completed 15M candle** whose close is:
   - BUY: strictly above ORB high
   - SELL: strictly below ORB low
5. The first ORB breakout is consumed for that symbol/day even if later filters reject it.
6. RSI direction filter:
   - BUY: 55 < RSI14 < 70 and RSI rising
   - SELL: 30 < RSI14 < 45 and RSI falling
7. 15M RVOL >= 1.2, calculated against the previous 20 completed 15M volumes.
8. Trade Quality Score >= 3.
9. Initial risk:
   - Entry = completed breakout 15M close
   - SL = 09:15 ORB close
10. Reject if stop distance < 0.50%.
11. Reject if the T1-block condition is present in the previous 20 completed 5M candles.
12. Targets: T1=2R, T2=3R, T3=4R.

EMA and VWAP remain available as diagnostics but are **not live entry gates** for B1 + RVOL.

## Live timing

Dhan timestamps are candle-start timestamps. Therefore a 09:30 15M breakout candle becomes actionable only after its 09:45 completion. The implementation uses completed-candle filtering and never treats a forming 15M candle as complete.

## Position monitoring

The production monitor uses the fixed initial SL. T1/T2/T3 milestones are recorded. T3 is an exit milestone; EOD closes any remaining active signal in the existing summary workflow.

## Validation

Run before deployment:

```powershell
pytest -q
python -m compileall -q app scripts tests
```
