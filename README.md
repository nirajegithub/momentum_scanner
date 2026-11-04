# Momentum Scanner — B1 ORB Strategy

Automated intraday scanner and trade executor for NSE equities using the
**B1 Opening Range Breakout (ORB)** strategy. Runs on GitHub Actions,
sends signals and trade updates via Telegram, and places/manages orders
through the Dhan API.

---

## How it works — end to end

```
09:15–09:30  ORB candle locks  →  high & low fixed for the day
09:30 onward  Every 5M candle checked for breakout (close > ORB high = BUY, close < ORB low = SELL)
              ↓ filters pass
              Telegram alert sent  +  LIMIT order placed inline (same process, zero delay)
              ↓ paper mode
              Fill confirmed immediately  →  SL-M placed  →  ACTIVE
              ↓ live mode
              Scanner moves on (fire-and-forget)
              trade_manager step (after scan) polls fill  →  SL-M placed  →  ACTIVE
Every 15 min  Telegram live status: open positions + live LTP + unrealised P&L
15:10 IST     Status updates stop
15:15 IST     Square-off workflow closes all open positions
```

---

## Entry logic

### 1. Opening Range (ORB)
The **first completed 15-minute candle** of the session (09:15–09:30 IST)
sets the day's fixed range. Its `high` and `low` do not change again.

### 2. 5M breakout scan
Every completed 5M candle **after** the ORB candle is checked in
chronological order:

- `close > ORB high` → **BUY** candidate
- `close < ORB low` → **SELL** candidate
- close inside range → skipped, next candle checked

### 3. Entry filters (`app/strategy.py::evaluate_b1_breakout`)
All must pass on the confirming 5M candle:

| Filter | Default |
|--------|---------|
| Daily close | ≥ `MIN_PRICE` (450) |
| Previous day volume | ≥ `MIN_PREV_VOLUME` (500,000) |
| Today's cumulative volume | ≥ `MIN_DAILY_VOLUME` (100,000) |
| RSI(14) — BUY | `BUY_RSI_MIN`–`BUY_RSI_MAX` (50–100) |
| RSI(14) — SELL | `SELL_RSI_MIN`–`SELL_RSI_MAX` (0–50) |
| 5M RVOL | ≥ `MIN_15M_RVOL` (1.5) and ≤ `MAX_15M_RVOL` (8.0) |
| Trade quality score | `MIN_TRADE_SCORE`–`MAX_TRADE_SCORE` (3–7) |
| Market trend alignment | Nifty 5M trend must agree with direction |

A candle that fails any filter is skipped; later candles in the same day
are still checked. Once a signal fires for a symbol, that symbol is
locked (`CONSUMED`) for the rest of the day.

### 4. Risk & targets (`app/risk.py`)

- **Entry** = close of the confirming 5M candle
- **Stop-loss** = ORB low (BUY) or ORB high (SELL)
- **Stop distance** must be between `MIN_STOP_DISTANCE_PERCENT` (0.50%)
  and `MAX_STOP_DISTANCE_PERCENT` (3.0%) of entry — wide stops (e.g.
  7.9%) and noise stops (e.g. 0.16%) are both rejected
- `T1 = entry ± T1_RR × risk` (default 1.0×)
- `T2 = entry ± T2_RR × risk` (default 2.0×)
- `T3 = entry ± T3_RR × risk` (default 3.0×)
- Rejected if T1 R:R < `MIN_RR` (1.0)

### 5. T1-blocked safety check
Before sending the alert, `t1_blocked()` checks whether price already
touched T1 on any of the 5M candles between the ORB and the confirming
candle. If so, the signal is rejected (`T1_BLOCKED`) — the trade is
already "late."

---

## Order placement (inline, zero delay)

Orders are placed **immediately after the Telegram alert** in the same
scanner process — no separate workflow trigger needed.

### Paper mode (current)
Full synchronous flow in one pass:

```
Alert sent → place_entry_order() → wait_for_fill() → place_sl_order() → ACTIVE
```

### Live mode
Fire-and-forget to avoid blocking the scan of remaining symbols:

```
Alert sent → place_entry_order() → signal status = ENTRY_PLACED → next symbol
             (trade_manager step after scan: wait_for_fill() → place_sl_order() → ACTIVE)
```

### Chase limit (`ENTRY_CHASE_LIMIT_PCT = 0.015`)
If LTP has moved more than 1.5% past the entry price by order time, the
trade is skipped (`ENTRY_MISSED`) — the limit order is unlikely to fill
cleanly at that distance.

### Pre-entry guards
`pre_trade_ok()` blocks an order if:
- Daily loss halt has fired (`DAILY_LOSS_HALT_INR`)
- Current time > `MAX_ENTRY_HHMM` (13:30)
- Signal age > `MAX_SIGNAL_AGE_MIN` (30 min)
- Open positions ≥ `MAX_OPEN_POSITIONS` (35)

---

## Trade management (`app/trade_manager.py`)

After entry fills, the trade manager runs a TSL (trailing stop-loss) loop:

| Trigger | Action |
|---------|--------|
| T1 hit | SL moved to breakeven |
| T2 hit | SL moved to T1 |
| T3 hit | SL moved to T2 + partial exit (50% qty) |
| SL hit | Position marked EXITED |
| SL order cancelled externally | SL re-placed automatically |

---

## Telegram notifications

| Event | Message |
|-------|---------|
| Breakout detected | Signal details — entry, SL, T1/T2/T3, R:R, RVOL |
| Order placed | Symbol, qty, price, order ID |
| Fill confirmed | Fill price, SL level |
| Target hit | Tier (T1/T2/T3), unrealised P&L, new SL |
| SL hit | Exit price, final P&L |
| Skipped signal | Reason (ENTRY_MISSED, STALE, DAILY_LOSS_HALT, …) |
| **Live status** (every 15 min) | All open positions + live LTP + unrealised P&L + day P&L |
| Square-off | Each position closed at EOD |
| Daily summary | Win rate, gross/net P&L, best/worst trade |

Live status sends every `STATUS_INTERVAL_MIN` (15) minutes while any
ACTIVE position exists, stopping at `STATUS_SQUAREOFF_HHMM` (15:10) or
when all positions close — whichever comes first.

---

## GitHub Actions workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `momentum-scan.yml` | `workflow_dispatch` | Scan + inline order + fill/SL step |
| `live-trade.yml` | `workflow_dispatch` | Standalone trade manager cycle |
| `square-off.yml` | `workflow_dispatch` | EOD square-off + daily summary |
| `momentum-universe.yml` | `workflow_dispatch` | Refresh stock universe |
| `momentum-summary.yml` | `workflow_dispatch` | Build scan summary report |
| `pnl-check.yml` | `workflow_dispatch` | P&L check / reporting |
| `dhan-token-management.yml` | `workflow_dispatch` | Refresh Dhan API token |

All workflows use a **cached virtualenv** (keyed on `requirements.txt`
hash) and `fetch-depth: 1` for fast startup — typically 30–55 s saved
per run vs. a cold pip install with full history fetch.

The scanner and trade_manager steps share the `dhan-api-access`
concurrency group so parallel runs never conflict on API rate limits or
state file writes.

### Switching to live

Change these two lines in `momentum-scan.yml`:

```yaml
PAPER_MODE: "false"   # scanner step
PAPER_MODE: "false"   # fill+SL step
```

Confirm GitHub secrets are set:
`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

---

## Configuration reference

All variables are environment variables set in the workflow and defaulted
in `app/config.py`. The table below shows the **workflow values** (which
override the code defaults).

### Scanner filters

| Variable | Workflow value | Purpose |
|----------|---------------|---------|
| `MIN_PRICE` | 450 | Minimum stock price |
| `MIN_PREV_VOLUME` | 500,000 | Min previous-day volume |
| `MIN_DAILY_VOLUME` | 100,000 | Min today's cumulative volume |
| `BUY_RSI_MIN` / `BUY_RSI_MAX` | 50 / 100 | RSI band for BUY |
| `SELL_RSI_MIN` / `SELL_RSI_MAX` | 0 / 50 | RSI band for SELL |
| `MIN_15M_RVOL` / `MAX_15M_RVOL` | 1.5 / 8.0 | Relative volume range |
| `RVOL_LOOKBACK` | 20 | Candles for RVOL average |
| `MIN_TRADE_SCORE` / `MAX_TRADE_SCORE` | 3 / 7 | Trade quality score |
| `MIN_STOP_DISTANCE_PERCENT` | 0.50 | Tightest allowed stop (% of entry) |
| `MAX_STOP_DISTANCE_PERCENT` | 3.0 | Widest allowed stop (% of entry) |
| `T1_RR` / `T2_RR` / `T3_RR` | 1.0 / 2.0 / 3.0 | Target R:R multiples |
| `MIN_RR` | 1.0 | Minimum T1 R:R to accept signal |
| `SCAN_START_HHMM` / `SCAN_END_HHMM` | 930 / 1330 | Active scan window (IST) |

### Trade execution

| Variable | Default | Purpose |
|----------|---------|---------|
| `PAPER_MODE` | `true` | `false` = live orders via Dhan API |
| `TRADE_QTY` | 1 | Shares per trade |
| `MAX_ENTRY_HHMM` | 1330 | No new entries after this time |
| `MAX_SIGNAL_AGE_MIN` | 30 | Skip signals older than this |
| `MAX_OPEN_POSITIONS` | 35 | Halt new entries at this count |
| `DAILY_LOSS_HALT_INR` | -1000 | Halt trading after this day loss (₹) |
| `ENTRY_CHASE_LIMIT_PCT` | 0.015 | Skip order if LTP > entry + 1.5% |
| `STATUS_INTERVAL_MIN` | 15 | Minutes between live status Telegrams |
| `STATUS_SQUAREOFF_HHMM` | 1510 | Stop sending status after this time |

---

## State file

`state/runtime_state.json` is committed to the repo after every scan run.
It persists the ORB for each symbol (so it is not re-fetched on the next
run), all signal states, and the last status timestamp. The git commit
step retries push with rebase up to 3 times to handle concurrent runs.

---

## Key log lines

| Log line | Meaning |
|----------|---------|
| `B1_ORB` | ORB range locked for this symbol |
| `B1_5M ... NO_BREAKOUT` | 5M close inside ORB range, skipped |
| `B1_FILTER_REJECTED` | Breakout candle failed a filter (reason included) |
| `CONFIRMED_BUT_REJECTED` | Passed breakout but failed risk or T1-blocked check |
| `T1_BLOCKED` | T1 already touched before confirmation |
| `ALERT_SENT` | Telegram alert fired |
| `INLINE_ORDER_FAILED` | Exception during order placement (order not placed) |
| `ENTRY_MISSED` | LTP ran > 1.5% past entry before order could be placed |
| `BREAKOUT_FAILED` | LTP crossed original SL — signal invalidated |
| `ENTRY_PLACED` | Live order fired; fill polling deferred to trade_manager |
| `DAILY_LOSS_HALT` | Day loss threshold crossed, no more entries |

---

## Project structure

```
app/
  main.py            — scanner: ORB fetch, 5M breakout scan, inline order placement
  trade_manager.py   — fill polling, SL placement, TSL loop, live status report
  strategy.py        — evaluate_b1_breakout, t1_blocked, market_trend_aligned
  risk.py            — build_risk_and_targets (entry/SL/T1/T2/T3 + filters)
  dhan_client.py     — Dhan API wrapper (candles, quotes, orders, margin)
  telegram_notify.py — all Telegram message formatters
  telegram_cmd.py    — inbound Telegram command polling (halt/resume/status/squareoff)
  signal_monitor.py  — paper-mode SL/target monitoring
  position_tracker.py — live order reconciliation, manual trade adoption
  square_off.py      — EOD market-order close of all positions
  state.py           — load/save runtime_state.json
  config.py          — SETTINGS dataclass (all env-var defaults)
state/
  runtime_state.json — persisted scan + trade state (committed each run)
  pnl_history.json   — historical daily P&L log
tests/               — 141 pytest tests
.github/workflows/   — GitHub Actions (scanner, trade manager, square-off, …)
```
