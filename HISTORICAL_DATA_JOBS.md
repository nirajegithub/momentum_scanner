# Historical Data Fetch & Backtest Jobs

Reusable job system for fetching 90-day historical data and running backtests anytime.

---

## Overview

| Job | Purpose | Input | Output |
|---|---|---|---|
| **fetch_historical_data** | Fetch 90-day 15M candle data from Dhan API | `config/stocks_to_fetch.json` | `data/historical/fetched_YYYYMMDD_HHMM.csv` |
| **backtest_fetched_data** | Run B1 ORB strategy backtest on fetched data | CSV file path | `backtest_results_*.csv` + console report |

---

## Step 1: Configure Stocks to Fetch

Edit `config/stocks_to_fetch.json`:

```json
{
  "fetch_config": {
    "stocks": [
      {
        "symbol": "NEWSTOCK",
        "security_id": 1234567,
        "enabled": true,
        "reason": "Add reason here"
      }
    ],
    "parameters": {
      "interval_minutes": 15,
      "days_back": 90
    }
  }
}
```

**To add a stock:**
1. Find the security ID from Dhan master data
2. Add entry to `stocks` array
3. Set `enabled: true`

**To disable a stock:**
- Set `enabled: false` (won't be fetched)

**To remove a stock:**
- Delete the entire object from `stocks` array

---

## Step 2: Set Dhan Credentials

Before fetching data, set environment variables:

### Linux/Mac:
```bash
export DHAN_CLIENT_ID="your_client_id_here"
export DHAN_ACCESS_TOKEN="your_fresh_token_here"
```

### Windows (PowerShell):
```powershell
$env:DHAN_CLIENT_ID="your_client_id_here"
$env:DHAN_ACCESS_TOKEN="your_fresh_token_here"
```

### Windows (CMD):
```cmd
set DHAN_CLIENT_ID=your_client_id_here
set DHAN_ACCESS_TOKEN=your_fresh_token_here
```

**Note:** Access tokens expire in 3-4 hours. Generate a fresh one from Dhan login.

---

## Step 3: Fetch Data

### Fetch using default config:
```bash
cd C:\Projects\momentum_scanner_repo
python -m app.job_fetch_historical_data
```

### Fetch using custom config:
```bash
python -m app.job_fetch_historical_data --config path/to/custom_config.json
```

### Output:
```
[OK] PNBHOUSING     (ID: 2031296) | 2026-06-24 to 2026-09-24
  [OK] 1578 candles | 2026-06-24 09:15:00 to 2026-09-24 15:25:00

[RESULT] 8/8 stocks fetched successfully

[SAVED] data/historical/fetched_20260925_1430.csv
  Total records: 12,341
  Symbols: 8
  Date range: 2026-06-24 09:15:00+05:30 to 2026-09-24 15:25:00+05:30
```

---

## Step 4: Run Backtest

### Backtest the fetched data:
```bash
python -m app.job_backtest_fetched_data data/historical/fetched_20260925_1430.csv
```

### Output:
```
Stock          Candles   Passed  Pass Rate  Strength
--------------------------------------------------
PNBHOUSING       1578       315     19.96%   AVERAGE
SBILIFE          1425       289     20.28%   AVERAGE
TRENT            1502       310     20.64%   AVERAGE
AXISBANK         1487       298     20.05%   AVERAGE
BAJFINANCE       1450       291     20.07%   AVERAGE
PIRAMALFIN       1490       312     20.94%   AVERAGE
HONASA           1412       280     19.83%   WEAK
AUBANK           1397       289     20.68%   AVERAGE
--------------------------------------------------
TOTAL           11742      2384     20.30%

Verdict: GOOD - These stocks perform at baseline
Recommendation: Safe to trade in Phase 1
```

---

## Usage Examples

### Example 1: Initial 8-Stock Fetch (Current)
```bash
# Use default config (stocks_to_fetch.json)
python -m app.job_fetch_historical_data

# Backtest results
python -m app.job_backtest_fetched_data data/historical/fetched_20260925_1430.csv
```

### Example 2: Add New Stocks Later
```bash
# Edit config/stocks_to_fetch.json
# Add new stocks to the "stocks" array

# Fetch (only fetches enabled stocks)
python -m app.job_fetch_historical_data

# Backtest
python -m app.job_backtest_fetched_data data/historical/fetched_20260926_0900.csv
```

### Example 3: Weekly Historical Data Refresh
```bash
# Create cron job to run every Sunday 10:00 PM IST
# 22:30 IST = 17:00 UTC

# Cron schedule:
0 17 * * 0 cd /path/to/repo && python -m app.job_fetch_historical_data
0 18 * * 0 cd /path/to/repo && python -m app.job_backtest_fetched_data data/historical/fetched_*.csv
```

---

## File Structure

```
project/
├── config/
│   └── stocks_to_fetch.json          # Stock config for fetching
├── data/
│   └── historical/
│       ├── 15m_last_90d_2026-09-22.csv    # Existing baseline data
│       ├── fetched_20260925_1430.csv      # Newly fetched data
│       └── backtest_results_fetched_*.csv # Backtest results
├── app/
│   ├── job_fetch_historical_data.py       # Fetch job
│   ├── job_backtest_fetched_data.py       # Backtest job
│   └── strategy.py                        # B1 ORB strategy
```

---

## Troubleshooting

### Error: "Dhan credentials not set"
```
Solution: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables
See Step 2 above for instructions
```

### Error: "No data returned for SYMBOL"
```
Possible causes:
1. Wrong security_id in config
2. Stock didn't trade during date range
3. Dhan API temporarily unavailable
4. Rate limiting

Solution:
- Verify security_id from Dhan master data
- Try again later
- Check Dhan API status
```

### Error: "Failed to load config"
```
Solution:
- Verify config/stocks_to_fetch.json exists
- Check JSON syntax (use online JSON validator)
- Ensure file has read permissions
```

### Slow fetch (takes 5+ minutes)
```
Normal behavior - depends on:
- Number of stocks
- Date range (90 days = ~1,500 candles per stock)
- Dhan API speed
- Network latency

Expected time: ~30 seconds per stock
```

---

## Integration with Cron Jobs

Add to your cron-job.org scheduler:

```
Job Name: Fetch Historical Data
Schedule: Weekly (Sunday 10:00 PM IST = 17:00 UTC)
Command: cd /path/to/repo && python -m app.job_fetch_historical_data

Job Name: Backtest Historical Data
Schedule: Weekly (Sunday 10:30 PM IST = 17:00 UTC, 30 min after fetch)
Command: cd /path/to/repo && python -m app.job_backtest_fetched_data data/historical/fetched_*.csv
```

---

## Automating the Workflow

Create a shell script `scripts/fetch_and_backtest.sh`:

```bash
#!/bin/bash

cd C:\Projects\momentum_scanner_repo

echo "[$(date)] Fetching 90-day data..."
python -m app.job_fetch_historical_data

# Get latest fetched file
LATEST=$(ls -t data/historical/fetched_*.csv 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    echo "[ERROR] No fetched data found"
    exit 1
fi

echo "[$(date)] Backtesting: $LATEST"
python -m app.job_backtest_fetched_data "$LATEST"

echo "[$(date)] Complete!"
```

Run it anytime:
```bash
bash scripts/fetch_and_backtest.sh
```

---

## Next Steps

1. ✅ Review `config/stocks_to_fetch.json` - already configured for 8 Day 1 stocks
2. ✅ Set Dhan credentials
3. ✅ Run: `python -m app.job_fetch_historical_data`
4. ✅ Backtest: `python -m app.job_backtest_fetched_data data/historical/fetched_*.csv`
5. 📊 Compare results against 20.45% baseline
6. 🎯 Decide which stocks to use for Phase 1 Day 2+

---

## Summary

| Task | Time | Frequency |
|---|---|---|
| Fetch 90-day data | 5-10 min | Weekly or as needed |
| Backtest results | 2-5 min | Same day as fetch |
| Update config | 1 min | When adding/removing stocks |

**With this system, you can validate any stock anytime without code changes!** 🚀
