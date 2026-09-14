# NSE Momentum Scanner — B1 ORB + RVOL

An NSE intraday momentum scanner using **DhanHQ**, **Telegram**, and **GitHub Actions**.

The current production strategy is **B1 ORB + RVOL**. The scanner evaluates the first completed 15-minute candle that breaks the 09:15 Opening Range and applies RSI, RVOL, quality, risk, and T1-block filters before sending a Telegram alert.

> **Important:** This project generates research/educational alerts. It does **not** place orders.

---

## Current Production Strategy

```text
Previous-day filters
        │
        ├── Previous-day close > ₹350
        └── Previous-day volume > 500,000
        │
        ▼
09:15–09:30 Opening Range
        │
        ├── ORB High
        ├── ORB Low
        └── ORB Close
        │
        ▼
Wait for completed 15M candles
        │
        ▼
First completed 15M close outside ORB
        │
        ├── BUY  → close > ORB High
        └── SELL → close < ORB Low
        │
        ▼
First breakout is consumed
        │
        ▼
B1 quality filters
        │
        ├── RSI
        ├── RVOL ≥ 1.2
        └── Quality Score ≥ 3
        │
        ▼
Risk validation
        │
        ├── Minimum stop distance ≥ 0.50%
        └── T1-block check
        │
        ▼
Telegram alert
        │
        ├── Entry = completed 15M breakout close
        ├── SL = 09:15 ORB close
        ├── T1 = 2R
        ├── T2 = 3R
        └── T3 = 4R
```

### BUY conditions

A BUY candidate requires:

- Previous-day close > ₹350
- Previous-day volume > 500,000
- First subsequent completed 15M candle closes **strictly above the 09:15 ORB high**
- RSI > 55 and < 70
- RSI is rising versus the previous completed 15M candle
- 15M RVOL ≥ 1.2
- Quality Score ≥ 3
- Minimum stop distance ≥ 0.50%
- T1 is not blocked

### SELL conditions

A SELL candidate requires:

- Previous-day close > ₹350
- Previous-day volume > 500,000
- First subsequent completed 15M candle closes **strictly below the 09:15 ORB low**
- RSI > 30 and < 45
- RSI is falling versus the previous completed 15M candle
- 15M RVOL ≥ 1.2
- Quality Score ≥ 3
- Minimum stop distance ≥ 0.50%
- T1 is not blocked

---

## Important Candle Timing

Dhan intraday candle timestamps represent the **candle start time**.

Therefore a 15-minute candle beginning at 09:30 is actionable only after it completes at 09:45.

Example:

```text
09:15 candle
    │
    └── completes at 09:30
          │
          ▼
09:30 candle
    │
    └── completes at 09:45
          │
          ▼
First possible B1 breakout decision
```

The scanner uses completed-candle filtering so an incomplete 15M candle is not used for a signal.

The 09:15 ORB is selected specifically from the **current trading day**, even though Dhan data may contain multiple days of historical candles.

---

## ORB Rules

The opening range is the completed 09:15–09:30 15-minute candle.

```text
ORB High = 09:15 candle high
ORB Low  = 09:15 candle low
ORB Close = 09:15 candle close
```

Only the **first** completed 15M close outside the ORB is considered.

If the first breakout fails the RSI, RVOL, quality, risk, or T1-block filters, the breakout is still consumed.

There is no second-chance breakout later in the day.

---

## RVOL

RVOL is calculated using the completed 15M confirmation candle:

```text
RVOL =
current completed 15M volume
────────────────────────────
mean of previous 20 completed 15M volumes
```

Production threshold:

```text
RVOL >= 1.20
```

RVOL is a production filter, not merely a diagnostic.

---

## RSI

### BUY

```text
55 < RSI < 70
RSI[current] > RSI[previous]
```

### SELL

```text
30 < RSI < 45
RSI[current] < RSI[previous]
```

---

## Quality Score

The production B1 strategy requires:

```text
Quality Score >= 3
```

The score is used together with RSI and RVOL.

EMA/VWAP information may be retained for diagnostics, but they are **not additional B1 production gates**.

---

## Risk Management

The entry and initial stop are defined from the completed breakout candle and 09:15 ORB:

```text
Entry = completed breakout 15M close

BUY SL  = 09:15 ORB Close
SELL SL = 09:15 ORB Close
```

Minimum stop distance:

```text
0.50%
```

Target levels:

```text
T1 = 2R
T2 = 3R
T3 = 4R
```

The current production implementation uses a **fixed initial stop** and does not use progressive trailing-stop logic.

---

## T1 Block

Before an alert is sent, the scanner checks whether the theoretical T1 level is already blocked by recent completed 5-minute price action.

If T1 is blocked:

```text
B1_REJECTED | reason=T1_BLOCKED
```

No Telegram alert is sent.

---

## Scanner Schedule

The GitHub Actions workflow runs the scanner approximately every five minutes during the configured intraday window.

The production workflow is configured for:

```text
09:30 – 15:05 IST
```

The scanner only acts on completed candles.

Universe creation and summary are handled by their respective workflows/actions.

---

## Universe

Universe discovery uses the configured NSE discovery sources and maps symbols to Dhan security IDs.

The scanner applies the previous-day price and volume filters before evaluating intraday B1 signals.

Security IDs are obtained from the Dhan security master rather than hard-coded in the strategy.

---

## Telegram Alerts

A successful signal contains the important B1 decision information, including:

- Symbol
- Direction
- Entry
- Stop loss
- T1/T2/T3
- ORB information
- 15M RVOL
- RSI
- Quality score
- Signal completion time

Example:

```text
🚀 BUY ALERT

SYMBOL

Entry: ₹500.00
SL: ₹495.00

T1: ₹510.00
T2: ₹515.00
T3: ₹520.00

RSI: 62.4
RVOL: 1.48x
Quality: 4/7
```

Every Telegram message includes the project's educational/research disclaimer.

---

## GitHub Actions

The main production workflow is:

```text
.github/workflows/nse-momentum-scan.yml
```

The repository also contains separate workflows for universe management and daily summary.

Required GitHub repository secrets:

```text
DHAN_CLIENT_ID
DHAN_ACCESS_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Never commit credentials, tokens, or `.env` files.

---

## Local Installation

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run tests:

```powershell
pytest -q
```

Compile-check the application:

```powershell
python -m compileall -q app scripts tests
```

Run the scanner locally:

```powershell
python -m app.main
```

---

## Testing

The repository contains unit and regression tests covering the production strategy and candle-completion behavior.

Before committing production changes:

```powershell
pytest -q
python -m compileall -q app scripts tests
git diff --check
```

The B1 implementation includes a regression test ensuring that, when multiple days of 15M data are present, the scanner selects the **current day's 09:15 ORB** rather than an older day's ORB.

---

## Repository Structure

```text
nse_momentum/
│
├── .github/
│   └── workflows/
│       ├── nse-momentum-scan.yml
│       ├── nse-momentum-universe.yml
│       └── nse-momentum-summary.yml
│
├── app/
│   ├── candle_utils.py
│   ├── config.py
│   ├── dhan_client.py
│   ├── indicators.py
│   ├── main.py
│   ├── nse_universe.py
│   ├── risk.py
│   ├── scoring.py
│   ├── state.py
│   ├── strategy.py
│   ├── summary.py
│   └── telegram.py
│
├── scripts/
│   └── historical_backtest_15m5m_confirmation.py
│
├── tests/
│   ├── test_b1_rvol_live.py
│   └── test_candle_completion.py
│
├── data/
├── state/
├── requirements.txt
├── .env.example
└── README.md
```

---

## Research / Validation

B1 + RVOL was selected from historical filter-ablation work as the current production candidate.

The historical results are **not a guarantee of profitability** and the sample size is limited.

The purpose of the current deployment is controlled live validation of the implementation and signal behavior.

Do not modify production strategy rules based on a single trading day.

---

## Production Validation Checklist

For each trading day, inspect the GitHub Actions logs for:

```text
ORB_ARMED
        ↓
B1_FIRST_ORB_BREAKOUT
        ↓
RSI result
        ↓
RVOL result
        ↓
Quality result
        ↓
Risk validation
        ↓
T1_BLOCK result
        ↓
B1_ALERT_SENT / B1_REJECTED
```

For an alert, verify:

- The 09:15 ORB belongs to the current trading day.
- The breakout candle is completed.
- Entry equals the completed 15M close.
- SL equals the 09:15 ORB close.
- RVOL is at least 1.2.
- RSI is within the correct directional range.
- Quality score is at least 3.
- Stop distance is at least 0.50%.
- T1 is not blocked.

---

## Important

This scanner is for research and educational purposes only.

It does not place trades.

Market data, broker APIs, exchange responses, timestamps, and external services can change. Always validate the live logs before relying on generated alerts.

**Never commit API credentials, access tokens, Telegram tokens, runtime secrets, or private data to the repository.**