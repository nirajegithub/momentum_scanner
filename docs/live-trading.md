# Live Trading Implementation — NSE ORB Scanner × DhanHQ

> **Status**: Phase 1 — Paper Trade 🟢 LIVE (crons active, running)
> **Strategy**: Opening Range Breakout · Intraday MIS · Breakeven + TSL at T1 · Partial exit at T3 · Telegram command control
> **Last updated**: 2026-10-28

---

## Project Status

### Confirmed Working (2026-10-28)

| # | Item | File | Status |
|---|------|------|--------|
| 1 | Signal status changed `ACTIVE → NEW` so trade_manager sees fresh signals | `app/main.py` | ✅ Done |
| 2 | `signal_time` added on signal creation (age guard) | `app/main.py` | ✅ Done |
| 3 | `original_sl` locked at signal creation (never changes) | `app/main.py` | ✅ Done |
| 4 | `live_managed` guard — prevents signal_monitor overwriting SL when trade_manager owns it | `app/signal_monitor.py` | ✅ Done |
| 5 | Trade engine — entry, fill poll, SL-M placement, TSL, emergency exit | `app/trade_manager.py` | ✅ Done |
| 6 | Position reconciler — manual exit detection, manual trade adoption, F-3 duplicate guard | `app/position_tracker.py` | ✅ Done |
| 7 | EOD square-off + daily P&L summary to Telegram | `app/square_off.py` | ✅ Done |
| 8 | Live trade workflow — `workflow_dispatch`, `PAPER_MODE=true` default | `.github/workflows/live-trade.yml` | ✅ Done |
| 9 | Square-off workflow — `workflow_dispatch` | `.github/workflows/square-off.yml` | ✅ Done |
| 10 | Telegram notifications — all trade events (17 message types) | `app/telegram_notify.py` | ✅ Done |
| 11 | Edge case matrix — 24 scenarios, 4 categories, priority tiers | `docs/live-trading.md §8.9` | ✅ Done |
| 12 | Telegram reuse — same chat as token management (`TELEGRAM_TOKEN_ALERT_CHAT_ID`) | `live-trade.yml env` | ✅ Done |
| 13 | Unit tests — 54 tests, all passing | `tests/test_trade_manager.py` | ✅ Done |
| 14 | GHA run confirmed clean — market hours guard works, no errors | `live-trade.yml` run log | ✅ Verified |
| 15 | External cron — live-trade `*/5 9-14 * * 1-5` (IST) configured | External cron | ✅ Active |
| 16 | External cron — square-off `15:05 IST` Mon–Fri configured | External cron | ✅ Active |
| 17 | `daily_summary()` signature mismatch fixed | `app/square_off.py` | ✅ Fixed |
| 18 | Scanner alert window confirmed: 09:30–13:30 IST | `momentum-scan.yml` | ✅ Confirmed |
| 19 | `MAX_SIGNAL_AGE_MIN` extended 15 → **30 min** (GHA startup buffer) | `live-trade.yml` | ✅ Done |
| 20 | `MAX_ENTRY_HHMM` extended 12:30 → **13:00** (more entry window) | `live-trade.yml` | ✅ Done |
| 21 | `MAX_OPEN_POSITIONS` raised 5 → **35** (for ₹1L capital, qty=1) | `live-trade.yml` | ✅ Done |
| 22 | Partial exit at T3 — **50% qty market exit**, trail remaining 50% | `app/trade_manager.py` | ✅ Done |
| 23 | **Daily loss halt** — `DAILY_LOSS_HALT_INR=-1000` halts new entries if P&L ≤ -₹1,000 (1% of ₹1L) | `app/trade_manager.py` | ✅ Done |
| 24 | **SL order health check** — verifies each ACTIVE signal's SL is still PENDING every 5-min cycle; re-places if missing | `app/position_tracker.py` | ✅ Done |
| 25 | **Actual Dhan brokerage formula** — min(₹20, 0.03%×turnover)×2 + STT + exchange + GST + stamp (~₹1.62 at qty=1) | `app/telegram_notify.py` | ✅ Done |
| 26 | **Brokerage breakdown** in daily Telegram summary — gross P&L, brokerage cost, net P&L | `app/telegram_notify.py` | ✅ Done |
| 27 | **Telegram command system** — `/halt` `/resume` `/squareoff` `/status` polled each cycle | `app/telegram_cmd.py` | ✅ Done |

---

### Schedule Overview

```
09:00 IST  ┌── live-trade cron starts (*/5 9-14)
09:15 IST  │   market opens
09:30 IST  ├── scanner fires first signals → NEW status in state
09:30 IST  ├── trade_manager picks up → paper LIMIT entries placed
           │   every 5 min: new signals → entries + TSL on ACTIVE positions
13:30 IST  ├── last scanner signal (entry window closes)
13:30 IST  ├── trade_manager: TSL monitoring only
14:59 IST  └── last live-trade cycle
15:05 IST  └── square-off fires → market close all MIS + daily summary to Telegram
```

---

### What Is Left

| # | Item | File | Priority |
|---|------|------|----------|
| 1 | `security_id` in signal — verify scanner writes it (needed for live orders) | `app/main.py` | 🔴 High |
| 2 | `app/symbol_map.py` — fallback lookup from `dhan_instruments.csv` | `app/symbol_map.py` | 🟡 Medium |
| 3 | `data/dhan_instruments.csv` — download Dhan scrip master | `data/` | 🟡 Medium |
| 4 | `.github/workflows/refresh-instruments.yml` — auto-refresh CSV at 08:00 IST | `.github/workflows/` | 🟡 Medium |
| 5 | Switch `PAPER_MODE=false` when paper run completes 5 clean days | `live-trade.yml` | 🔵 When ready |

---

### Planning — Future Phases

| Phase | What | Status |
|-------|------|--------|
| **Phase 1** | Paper trading — 3–5 days, verify signal→order→SL→TSL→square-off via Telegram | 🟢 Running |
| **Phase 2** | Live trading, qty=1 — max ~₹300/day at risk, 1 clean week target | After Phase 1 passes |
| **Phase 3** | WebSocket monitor (`app/ws_monitor.py`) — real-time SL/TSL, eliminates 5-min blind window | After Phase 2 stable |
| **Phase 4** | MCP server (`app/mcp_server.py`) — query positions/P&L via Claude in plain English | After Phase 3 |
| **Phase 5** | Multi-account support — run same signals on 2+ Dhan accounts (family / capital split) | Future |
| **Phase 6** | Dynamic qty sizing — size proportional to RVOL score and SL tightness | Future |
| **Phase 7** | Dashboard — live positions, P&L curve, signal log | Future |

---

### Graduate Phase 1 → Phase 2 When

- [ ] Paper P&L within ±5% of `pnl-check.yml` over 5 consecutive days
- [ ] Zero duplicate orders in GHA logs
- [ ] Every `ACTIVE` signal has a matching SL log entry
- [ ] Telegram fires for all events: signal, skip, fill, SL, square-off, summary
- [ ] No `ENTRY_PLACED` signals stuck > 15 min without resolution

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Signal Lifecycle](#2-signal-lifecycle)
3. [DhanHQ Setup](#3-dhanhq-setup)
4. [New Files](#4-new-files)
5. [Entry Price Logic](#5-entry-price-logic)
6. [Order Flow](#6-order-flow)
7. [TSL Strategy](#7-tsl-strategy)
8. [Manual Trade Handling](#8-manual-trade-handling)
9. [Telegram Notifications](#9-telegram-notifications)
10. [WebSocket Monitor](#10-websocket-monitor)
11. [Security ID Lookup](#11-security-id-lookup)
12. [GitHub Actions Workflows](#12-github-actions-workflows)
13. [Phased Rollout](#13-phased-rollout)
14. [Risk Controls](#14-risk-controls)
15. [Environment Variables](#15-environment-variables)
16. [Known Limitations](#16-known-limitations)
17. [Emergency Runbook](#17-emergency-runbook)
18. [Local Testing](#18-local-testing)
19. [Next Steps](#19-next-steps)

---

## 1. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     GitHub Actions (every 5 min)                      │
│                                                                        │
│  09:15–13:30   SCAN phase                                              │
│  ├── scanner.py          signal generated → runtime_state.json        │
│  └── trade_manager.py    entry price check → LIMIT order via DhanHQ   │
│                                                                        │
│  09:15–15:05   MONITOR phase  (every GHA invocation)                  │
│  ├── signal_monitor.py   detect T1/T2/T3 / SL hit                     │
│  └── trade_manager.py    modify SL (BE at T1, step-up at T2/T3)       │
│                                                                        │
│  15:05         SQUARE-OFF  (dedicated cron workflow)                   │
│  └── square_off.py       market-exit all open intraday positions       │
└──────────────────────────────────────────────────────────────────────┘

            ┌──────────────────────────────────────────┐
            │   Optional: WebSocket Monitor             │
            │   (VPS / long-running GHA job)            │
            │   websocket_monitor.py                    │
            │   → tick-level TSL trailing               │
            │   → real-time BE move the moment T1 hit   │
            └──────────────────────────────────────────┘

            ┌──────────────────────────────────────────┐
            │   Telegram Private Channel                │
            │   → every order event pushed in real time │
            └──────────────────────────────────────────┘
```

**State file (`runtime_state.json`) — signal shape:**

```jsonc
{
  "symbol": "ATHERENERG",
  "direction": "BUY",
  "status": "ACTIVE",       // NEW | ENTRY_PLACED | ACTIVE | SKIPPED | EXITED
  "signal_time": "2026-10-26T09:20:00+05:30",
  "risk": {
    "entry": 1411.0,
    "sl": 1411.0,           // updated live (BE move, TSL steps)
    "original_sl": 1395.0,  // locked at signal creation — never changes
    "t1": 1427.0,
    "t2": 1443.0,
    "t3": 1459.0
  },
  "highest_target_hit": "T1_HIT",
  "trailing_active": true,
  "trail_distance": 16.0,   // entry - original_sl, locked when T1 hit
  "entry_order_id": "112233",
  "sl_order_id": "112244",
  "qty": 5,
  "rvol_15m": 2.3
}
```

> `original_sl` and `signal_time` must be written in `scanner.py` when the signal is first created.

---

## 2. Signal Lifecycle

```
              ┌──────────────┐
  scanner.py  │     NEW      │  signal written to state
              └──────┬───────┘
                     │ should_place_entry(signal, ltp)
            ┌────────┴─────────┐
       skip │                  │ place
  ┌─────────▼────────┐  ┌──────▼───────┐
  │     SKIPPED      │  │ ENTRY_PLACED │  LIMIT order in market @ entry price
  │ price ≤ SL /     │  └──────┬───────┘
  │ stale / timeout  │         │ wait_for_fill() — poll every 30s
  └──────────────────┘         │ timeout → cancel → SKIPPED
                        ┌──────▼───────┐
                        │    ACTIVE    │◄────────────────────┐
                        └──┬───┬───┬──┘                      │
                           │   │   │                          │
               SL hit      │   │   │ T1 hit         T2/T3 hit│ TSL trail
                           │   │   │ SL→breakeven             │
               ┌───────────▼┐  │   └──► trailing_active=True─┘
               │   EXITED   │  │
               │  (SL hit)  │  │ 15:05 square-off
               └────────────┘  │
                        ┌──────▼───────┐
                        │    EXITED    │  market order sent
                        │ (square-off) │
                        └──────────────┘
```

**Rules:**
- Status transitions are one-way — never go backwards
- `SKIPPED` signals are archived — never re-attempted
- `EXITED` signals are kept for daily P&L calculation

---

## 3. DhanHQ Setup

### Install SDK

```bash
pip install dhanhq
```

Add to `requirements.txt`:
```
dhanhq>=2.0.0
requests>=2.31.0
```

### Auth

```python
from dhanhq import DhanContext, dhanhq
import os

ctx  = DhanContext(
    client_id    = os.environ["DHAN_CLIENT_ID"],
    access_token = os.environ["DHAN_ACCESS_TOKEN"],
)
dhan = dhanhq(ctx)
```

> **Token expiry**: DhanHQ access tokens expire daily at midnight. Update GitHub secret `DHAN_ACCESS_TOKEN` each morning before 09:15 IST.

### Key REST Endpoints

| Action | Method | Endpoint |
|--------|--------|----------|
| Place order | POST | `/v2/orders` |
| Modify order | PUT | `/v2/orders/{orderId}` |
| Cancel order | DELETE | `/v2/orders/{orderId}` |
| Order status | GET | `/v2/orders/{orderId}` |
| All today's orders | GET | `/v2/orders` |
| Open positions | GET | `/v2/positions` |
| Available margin | GET | `/v2/fundlimit` |
| Market quote (LTP) | GET | `/v2/marketfeed/quote` |

### WebSocket Feed

```python
from dhanhq import marketfeed

instruments = [
    (marketfeed.NSE, "1333", marketfeed.Ticker),  # security_id, not symbol
]
feed = marketfeed.DhanFeed(ctx, instruments, marketfeed.Ticker)
```

---

## 4. New Files

```
app/
├── trade_manager.py        ← entry checks, order placement, SL modify, TSL, emergency exit, daily halt
├── position_tracker.py     ← reconcile DhanHQ positions vs state; SL health check (#9)
├── telegram_cmd.py         ← /halt /resume /squareoff /status command polling (new)
├── telegram_notify.py      ← all trade events + brokerage breakdown in daily summary
├── websocket_monitor.py    ← live tick feed + continuous TSL trailing
├── square_off.py           ← 15:05 market-exit all open intraday positions
└── symbol_map.py           ← NSE symbol → DhanHQ security_id lookup

.github/workflows/
├── live-trade.yml          ← workflow_dispatch, PAPER_MODE=true default
├── square-off.yml          ← cron 15:05 IST daily Mon–Fri
└── refresh-instruments.yml ← downloads dhan_instruments.csv at 08:00 IST

data/
└── dhan_instruments.csv    ← DhanHQ scrip master, refreshed every morning
```

---

## 5. Entry Price Logic

**Rule: place LIMIT at exactly the signal's entry price. Never chase.**

The entry price is the ORB breakout level confirmed by the scanner. Entering at any other price invalidates the SL distance, the R:R, and the backtest. The signal entry is the only valid price.

### What happens when price has moved

```
09:20  Signal:  ATHERENERG BUY  entry=1411  SL=1395  T1=1427

09:25  GHA runs order placement. Three cases:
```

| LTP at order time | Situation | Action |
|------------------|-----------|--------|
| 1411–1415 | Near entry | ✅ LIMIT at **1411** |
| 1425 (above entry) | Price ran up | ✅ LIMIT at **1411** — wait for retest |
| 1398 (below entry, above SL) | Mild pullback | ✅ LIMIT at **1411** — wait for return |
| 1392 (at or below SL) | Breakout failed | ❌ **SKIP** |

**Why LIMIT at 1411 even when LTP is 1425?**

A retest of the breakout level is a valid ORB entry. If price returns to 1411 it confirms the level held. If it never returns, the order doesn't fill and gets cancelled — no harm done.

**Why never chase to 1425?**
Risk = 1425 − 1395 = 30 pts. Reward to T1 = 1427 − 1425 = 2 pts. R:R = 0.07. The trade that was backtested no longer exists.

### Skip condition

```
BUY:   skip if  LTP ≤ original_sl
SELL:  skip if  LTP ≥ original_sl
```

Price through the SL means the breakout premise is gone. In every other case — even if price is far above entry — place LIMIT at the signal entry and wait.

### Guards

```python
MAX_SIGNAL_AGE_MIN = 30   # skip if signal is older than 30 min (was 15 — extended for GHA startup buffer)
MAX_ENTRY_HHMM     = 1300 # no new entries after 13:00 (was 12:30)
MAX_PENDING_MIN    = 15   # cancel unfilled LIMIT after 15 min
MAX_OPEN_POSITIONS = 35   # max simultaneous ACTIVE positions (qty=1, ₹1L capital)
```

### `should_place_entry()`

```python
# app/trade_manager.py
from datetime import datetime
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

MAX_SIGNAL_AGE_MIN = 30
MAX_ENTRY_HHMM     = 1300
MAX_PENDING_MIN    = 15

def should_place_entry(signal, ltp):
    """Returns (ok: bool, reason: str). Order price is always signal entry."""
    direction = signal["direction"]
    sl        = float(signal["risk"]["original_sl"])

    # Guard 1 — breakout failed (price through SL)
    if direction == "BUY" and ltp <= sl:
        return False, f"BREAKOUT_FAILED ltp={ltp:.2f} ≤ sl={sl:.2f}"
    if direction == "SELL" and ltp >= sl:
        return False, f"BREAKOUT_FAILED ltp={ltp:.2f} ≥ sl={sl:.2f}"

    # Guard 2 — too late in the day
    if int(datetime.now(IST).strftime("%H%M")) > MAX_ENTRY_HHMM:
        return False, "TOO_LATE past 12:30"

    # Guard 3 — stale signal
    sig_time = datetime.fromisoformat(signal["signal_time"])
    age_min  = (datetime.now(IST) - sig_time).total_seconds() / 60
    if age_min > MAX_SIGNAL_AGE_MIN:
        return False, f"STALE {age_min:.0f} min old"

    return True, "OK"
```

### Decision summary

| Situation | Order placed? | Price |
|-----------|:------------:|-------|
| LTP anywhere above SL (BUY) | ✅ | Exactly signal entry |
| LTP at or below SL (BUY) | ❌ | — |
| Signal older than 30 min | ❌ | — |
| After 13:00 IST | ❌ | — |
| LIMIT not filled in 15 min | ❌ cancelled | — |
| Daily P&L ≤ -₹1,000 (loss halt) | ❌ | — |
| `MAX_OPEN_POSITIONS` (35) reached | ❌ | — |

---

## 6. Order Flow

### 6.1 Pre-trade Checks

Run before placing any order:

```python
BLACKLIST    = {"NETWEB"}   # persistent losers
MAX_OPEN     = 15           # max simultaneous open positions
MAX_SL_PCT   = 3.0          # skip if stop > 3% from entry

def pre_trade_ok(signal, open_count, day_pnl_pts, qty):
    sym    = signal["symbol"]
    entry  = float(signal["risk"]["entry"])
    sl     = float(signal["risk"]["original_sl"])
    sl_pct = abs(entry - sl) / entry * 100
    # qty-aware daily loss halt: ₹100/share baseline
    if sym in BLACKLIST:
        return False, "BLACKLISTED"
    if open_count >= MAX_OPEN:
        return False, "MAX_POSITIONS"
    if day_pnl_pts * qty < -(100 * qty):
        return False, f"DAILY_LOSS_HALT ₹{day_pnl_pts * qty:.0f}"
    if sl_pct > MAX_SL_PCT:
        return False, f"SL_TOO_WIDE {sl_pct:.1f}%"
    return True, "OK"
```

### 6.2 Entry Order

```python
def place_entry_order(dhan, signal, qty, ltp, paper=True):
    from app.telegram_notify import order_placed, signal_skipped

    # Entry price check (§5)
    ok, reason = should_place_entry(signal, ltp)
    if not ok:
        LOG.info("SKIP_ENTRY | %s | %s", signal["symbol"], reason)
        signal["status"] = "SKIPPED"
        signal_skipped(signal, reason, ltp)
        return False

    entry  = float(signal["risk"]["entry"])   # always the signal entry
    sec_id = get_security_id(signal["symbol"])

    if paper:
        oid = f"PAPER-{signal['symbol']}-{int(time.time())}"
        signal["entry_order_id"] = oid
        signal["status"]         = "ENTRY_PLACED"
        order_placed(signal, qty, oid, paper=True)
        return True

    # Margin check
    funds     = dhan.get_fund_limits()
    available = float(funds["data"]["availabelBalance"])
    required  = entry * qty * 0.20        # 20% MIS
    if available < required * 1.10:       # 10% buffer
        LOG.warning("MARGIN_FAIL | %s | need=%.0f | have=%.0f",
                    signal["symbol"], required, available)
        signal_skipped(signal, f"MARGIN_FAIL need=₹{required:.0f}", ltp)
        return False

    resp = dhan.place_order(
        security_id      = sec_id,
        exchange_segment = dhan.NSE_EQ,
        transaction_type = dhan.BUY if signal["direction"] == "BUY" else dhan.SELL,
        quantity         = qty,
        order_type       = dhan.LIMIT,
        product_type     = dhan.INTRADAY,
        price            = entry,
    )
    oid = resp["data"]["orderId"]
    signal["entry_order_id"] = oid
    signal["status"]         = "ENTRY_PLACED"
    order_placed(signal, qty, oid, paper=False)
    return True
```

### 6.3 Fill Confirmation

Poll every 30 s. Cancel and mark `SKIPPED` if not filled within `MAX_PENDING_MIN`:

```python
def wait_for_fill(dhan, signal, qty, paper=True):
    from app.telegram_notify import order_filled, signal_skipped

    if paper:
        fill_price = float(signal["risk"]["entry"])
        signal["status"] = "ACTIVE"
        order_filled(signal, qty, fill_price, paper=True)
        return True, fill_price

    order_id = signal["entry_order_id"]
    deadline = time.time() + MAX_PENDING_MIN * 60

    while time.time() < deadline:
        data   = dhan.get_order_by_id(order_id)["data"]
        status = data["orderStatus"]
        if status == "TRADED":
            fill_price = float(data.get("price", signal["risk"]["entry"]))
            signal["status"] = "ACTIVE"
            order_filled(signal, qty, fill_price, paper=False)
            return True, fill_price
        if status in ("CANCELLED", "REJECTED"):
            signal["status"] = "SKIPPED"
            return False, 0.0
        time.sleep(30)

    # Timeout — cancel pending order
    LOG.warning("FILL_TIMEOUT | %s | cancelling %s", signal["symbol"], order_id)
    try:
        dhan.cancel_order(order_id)
    except Exception:
        pass
    signal["status"] = "SKIPPED"
    signal_skipped(signal, f"FILL_TIMEOUT {MAX_PENDING_MIN} min", ltp=None)
    return False, 0.0
```

### 6.4 SL Order (placed immediately after fill)

```python
def place_sl_order(dhan, signal, qty, paper=True):
    from app.telegram_notify import sl_placed
    sl     = float(signal["risk"]["original_sl"])
    sec_id = get_security_id(signal["symbol"])
    opp    = dhan.SELL if signal["direction"] == "BUY" else dhan.BUY

    if paper:
        oid = f"PAPER-SL-{signal['symbol']}"
        signal["sl_order_id"] = oid
        sl_placed(signal, sl, oid, paper=True)
        return True

    try:
        resp = dhan.place_order(
            security_id      = sec_id,
            exchange_segment = dhan.NSE_EQ,
            transaction_type = opp,
            quantity         = qty,
            order_type       = dhan.SL_M,
            product_type     = dhan.INTRADAY,
            trigger_price    = sl,
            price            = 0,
        )
        oid = resp["data"]["orderId"]
        signal["sl_order_id"] = oid
        sl_placed(signal, sl, oid, paper=False)
        return True
    except Exception as exc:
        LOG.error("SL_PLACE_FAIL | %s | %s", signal["symbol"], exc)
        _emergency_exit(dhan, signal, qty)
        return False
```

> **If SL placement fails → call `_emergency_exit()` immediately.** Never hold an open position without an SL in the market.

```python
def _emergency_exit(dhan, signal, qty):
    from app.telegram_notify import error_alert
    sec_id = get_security_id(signal["symbol"])
    opp    = dhan.SELL if signal["direction"] == "BUY" else dhan.BUY
    try:
        dhan.place_order(
            security_id      = sec_id,
            exchange_segment = dhan.NSE_EQ,
            transaction_type = opp,
            quantity         = qty,
            order_type       = dhan.MARKET,
            product_type     = dhan.INTRADAY,
            price            = 0,
        )
    except Exception as exc:
        LOG.critical("EMERGENCY_EXIT_FAILED | %s | %s", signal["symbol"], exc)
    signal["status"] = "EXITED"
    error_alert("SL placement failed — emergency exit", signal["symbol"])
```

### 6.5 SL Modification

```python
def modify_sl_order(dhan, signal, new_trigger, paper=True):
    if paper or not signal.get("sl_order_id"):
        LOG.info("PAPER_MODIFY_SL | %s | trigger=%.2f",
                 signal["symbol"], new_trigger)
        return
    dhan.modify_order(
        order_id      = signal["sl_order_id"],
        order_type    = "SL-M",
        leg_name      = "STOP_LOSS_LEG",
        quantity      = signal["qty"],
        price         = 0,
        trigger_price = new_trigger,
        validity      = "DAY",
    )
    LOG.info("SL_MODIFIED | %s | trigger=%.2f", signal["symbol"], new_trigger)
```

---

## 7. TSL Strategy

### Stage map

```
Entry filled at signal entry price
│
SL-M placed at original_sl
│
T1 hit ──► SL → entry (breakeven)
│          trailing_active = True
│          trail_distance  = entry − original_sl   ← locked here
│
On each tick / 5-min poll (if trailing_active):
│   BUY:   candidate = ltp − trail_distance
│   SELL:  candidate = ltp + trail_distance
│   if improves SL by ≥ 2 pts → modify SL order
│
T2 hit ──► SL floor jumps to T1  (override if trail still below T1)
│
T3 hit ──► SL floor jumps to T2
│          PARTIAL_EXIT_T3=true: exit 50% qty at market immediately
│          Remaining 50% continues trailing from T2 floor
│          (skipped if qty=1 — cannot split)
│
15:05  ──► market-exit all → square_off()
```

**Env var:** `PARTIAL_EXIT_T3=true` (default). Set `false` to disable partial exit and trail full qty through T3.

### Implementation in `signal_monitor.py`

```python
from app import trade_manager
from app.telegram_notify import target_hit, sl_hit

MIN_TRAIL_INC = 2.0   # minimum pts improvement before calling modify_order

# ── BUY direction ─────────────────────────────────────────────────────
if direction == "BUY":

    if ltp <= sl:
        signal["status"]     = "EXITED"
        signal["exit_price"] = sl
        signal["sl_hit"]     = True
        sl_hit(signal, exit_price=sl, qty=qty)

    else:
        prev = signal.get("highest_target_hit")

        if ltp >= t3 and prev != "T3_HIT":
            signal["highest_target_hit"] = "T3_HIT"
            new_floor = t2
            if float(signal["risk"]["sl"]) < new_floor:
                signal["risk"]["sl"] = new_floor
                trade_manager.modify_sl_order(dhan, signal, new_floor, paper)
            target_hit(signal, "T3_HIT", ltp, qty, new_sl=new_floor)

        elif ltp >= t2 and prev not in ("T2_HIT", "T3_HIT"):
            signal["highest_target_hit"] = "T2_HIT"
            new_floor = t1
            if float(signal["risk"]["sl"]) < new_floor:
                signal["risk"]["sl"] = new_floor
                trade_manager.modify_sl_order(dhan, signal, new_floor, paper)
            target_hit(signal, "T2_HIT", ltp, qty, new_sl=new_floor)

        elif ltp >= t1 and prev not in ("T1_HIT", "T2_HIT", "T3_HIT"):
            signal["highest_target_hit"] = "T1_HIT"
            signal["risk"]["sl"]         = entry
            signal["trailing_active"]    = True
            signal["trail_distance"]     = entry - float(signal["risk"]["original_sl"])
            trade_manager.modify_sl_order(dhan, signal, entry, paper)
            target_hit(signal, "T1_HIT", ltp, qty, new_sl=entry)

        _apply_trailing(dhan, signal, ltp, paper)


def _apply_trailing(dhan, signal, ltp, paper):
    if not signal.get("trailing_active"):
        return
    trail  = float(signal["trail_distance"])
    cur_sl = float(signal["risk"]["sl"])

    if signal["direction"] == "BUY":
        cand = ltp - trail
        if cand > cur_sl + MIN_TRAIL_INC:
            signal["risk"]["sl"] = round(cand, 2)
            trade_manager.modify_sl_order(dhan, signal, cand, paper)
    else:
        cand = ltp + trail
        if cand < cur_sl - MIN_TRAIL_INC:
            signal["risk"]["sl"] = round(cand, 2)
            trade_manager.modify_sl_order(dhan, signal, cand, paper)
```

> SELL direction mirrors BUY — `>=` becomes `<=`, `>` becomes `<`.

---

## 8. Manual Trade Handling

The bot manages trades it places. But the user may also:

| Scenario | Description |
|----------|-------------|
| **A — Manual entry** | User places a trade directly in DhanHQ app — bot has no record of it |
| **B — Modified qty** | Bot placed qty=5, user added more shares manually |
| **C — Modified entry price** | Bot placed LIMIT at ₹1,411, user changed it to ₹1,415 in the app |
| **D — Fill-price slippage** | Bot's LIMIT at ₹1,411 filled at ₹1,411.05 (normal exchange rounding) |
| **E — User closed position early** | User exited a bot-managed trade manually before 15:05 |

All five are detected by **position reconciliation** — comparing DhanHQ open positions against `runtime_state.json` on every GHA run.

---

### 8.1 Position Reconciler

Runs at the start of every MONITOR phase, before TSL checks:

```python
# app/position_tracker.py

def reconcile(dhan, state, qty, paper=True):
    """
    Sync DhanHQ positions → runtime_state.json.
    Called every GHA run after the scan window.
    """
    if paper:
        return   # nothing to reconcile in paper mode

    positions   = dhan.get_positions()["data"]
    intraday    = {
        p["tradingSymbol"]: p
        for p in positions
        if p["positionType"] == "INTRADAY" and int(p["netQty"]) != 0
    }
    active_sigs = {
        s["symbol"]: s
        for s in state.get("signals", {}).values()
        if s.get("status") == "ACTIVE"
    }

    # ── Scenario A: position exists but no signal → manual trade ──────
    for sym, pos in intraday.items():
        if sym not in active_sigs:
            _adopt_manual(state, pos, qty)

    # ── Scenarios B/C/D/E: signal exists, check for drift ────────────
    for sym, sig in active_sigs.items():
        if sym not in intraday:
            # Scenario E — user closed position early
            _mark_manually_exited(sig)
        else:
            _check_drift(sig, intraday[sym], qty)
```

---

### 8.2 Scenario A — Manual Trade Adoption

Bot detects a DhanHQ position with no matching signal. It creates a **synthetic signal** so the same TSL and square-off logic applies.

```python
def _adopt_manual(state, pos, default_qty):
    from app.telegram_notify import manual_trade_adopted

    sym       = pos["tradingSymbol"]
    net_qty   = int(pos["netQty"])
    direction = "BUY" if net_qty > 0 else "SELL"
    entry     = float(pos.get("buyAvg" if direction == "BUY" else "sellAvg", 0))

    # Default SL: 1% from entry (user should adjust via Telegram/state file)
    default_sl_pct = 0.01
    sl = round(entry * (1 - default_sl_pct), 2) if direction == "BUY" \
         else round(entry * (1 + default_sl_pct), 2)

    # T1/T2/T3: 1× / 2× / 3× the default risk distance
    risk = abs(entry - sl)
    t1 = round(entry + risk, 2)   if direction == "BUY" else round(entry - risk, 2)
    t2 = round(entry + 2*risk, 2) if direction == "BUY" else round(entry - 2*risk, 2)
    t3 = round(entry + 3*risk, 2) if direction == "BUY" else round(entry - 3*risk, 2)

    sig_key = f"{sym}_MANUAL_{int(time.time())}"
    state.setdefault("signals", {})[sig_key] = {
        "symbol":            sym,
        "direction":         direction,
        "status":            "ACTIVE",
        "signal_time":       datetime.now(IST).isoformat(),
        "source":            "MANUAL",          # ← flag so reports show correctly
        "risk": {
            "entry":       entry,
            "sl":          sl,
            "original_sl": sl,
            "t1": t1, "t2": t2, "t3": t3,
        },
        "qty":               abs(net_qty),
        "entry_order_id":    pos.get("positionId", "MANUAL"),
        "sl_order_id":       None,              # bot will place SL immediately
        "trailing_active":   False,
    }
    LOG.warning("MANUAL_TRADE_ADOPTED | %s | %s | entry=%.2f | sl=%.2f (default 1%%)",
                sym, direction, entry, sl)
    manual_trade_adopted(sym, direction, entry, sl, abs(net_qty))
```

After adoption, the bot immediately places an SL-M order for the manual trade using `place_sl_order()`.

> **Note**: The default 1% SL is a safety net. Check the Telegram alert and update `runtime_state.json → risk.sl / risk.original_sl` to the correct level before the next GHA run.

---

### 8.3 Scenario B — Qty Mismatch

User added more shares to a bot-managed position:

```python
def _check_drift(sig, pos, expected_qty):
    from app.telegram_notify import trade_drift_alert

    sym          = sig["symbol"]
    actual_qty   = abs(int(pos["netQty"]))
    state_qty    = int(sig.get("qty", expected_qty))
    actual_entry = float(pos.get("buyAvg" if sig["direction"] == "BUY" else "sellAvg", 0))
    state_entry  = float(sig["risk"]["entry"])

    # Scenario B — qty changed
    if actual_qty != state_qty:
        LOG.warning("QTY_MISMATCH | %s | state=%d | broker=%d", sym, state_qty, actual_qty)
        sig["qty"] = actual_qty   # adopt broker qty — SL order qty may need update
        trade_drift_alert(sym, "QTY_MISMATCH",
                          f"state={state_qty} broker={actual_qty} — SL order qty may be stale")

    # Scenario C — entry price changed significantly (> 0.1%)
    if abs(actual_entry - state_entry) / state_entry > 0.001:
        LOG.warning("ENTRY_DRIFT | %s | state=%.2f | broker=%.2f", sym, state_entry, actual_entry)
        # Update entry and recalculate SL distances
        sig["risk"]["entry"] = actual_entry
        trade_drift_alert(sym, "ENTRY_DRIFT",
                          f"state=₹{state_entry:.2f} broker=₹{actual_entry:.2f}")

    # Scenario D — minor fill slippage (≤ 0.1%) → silent update, no alert
    elif abs(actual_entry - state_entry) > 0.01:
        sig["risk"]["entry"] = actual_entry
        LOG.info("FILL_SLIPPAGE | %s | %.2f → %.2f", sym, state_entry, actual_entry)
```

---

### 8.4 Scenario E — User Closed Position Early

Signal is `ACTIVE` in state but no matching position in DhanHQ.

**Critical**: the SL order is still sitting in the market — an orphaned SL order can trigger and create an accidental new position. Cancel it first.

```python
def _mark_manually_exited(dhan, sig):
    from app.telegram_notify import manual_exit_detected, error_alert

    # Cancel orphaned SL — must happen before marking EXITED
    sl_order_id  = sig.get("sl_order_id")
    sl_cancelled = False
    if sl_order_id:
        try:
            dhan.cancel_order(sl_order_id)
            sl_cancelled = True
            LOG.info("ORPHANED_SL_CANCELLED | %s | order_id=%s", sig["symbol"], sl_order_id)
        except Exception as exc:
            LOG.error("SL_CANCEL_FAILED | %s | order_id=%s | %s", sig["symbol"], sl_order_id, exc)
            error_alert(f"SL cancel failed — {sig['symbol']}", str(exc))

    sig["status"]      = "EXITED"
    sig["exit_reason"] = "MANUAL_CLOSE"
    sig["exit_price"]  = sig.get("last_ltp", sig["risk"]["entry"])
    LOG.warning("MANUAL_EXIT | %s | sl_cancelled=%s", sig["symbol"], sl_cancelled)
    manual_exit_detected(sig["symbol"], sig["direction"], sl_cancelled)
```

> The reconcile call must pass `dhan` here: `_mark_manually_exited(dhan, sig)`.

---

### 8.5 Scenario F — Entry Order Not Filled, User Fills Manually

Bot places a LIMIT entry order that doesn't fill within 15 min. Before or after the bot cancels it, the user manually takes the trade in DhanHQ. Four distinct sub-cases:

#### F-1 — User modifies bot's LIMIT price → fills

```
Bot places LIMIT @ ₹1,411 (signal entry)
Price doesn't retrace
User edits order price → ₹1,415 in DhanHQ app
Order fills @ ₹1,415
```

`wait_for_fill()` polls and sees `FILLED` at ₹1,415.

```python
drift_pct = abs(fill_price - signal_entry) / signal_entry  # 0.28%
if drift_pct > 0.001:
    telegram_notify.trade_drift_alert(
        sym, "ENTRY_DRIFT",
        f"Expected ₹{signal_entry:.2f}, filled ₹{fill_price:.2f} ({drift_pct*100:+.2f}%)"
    )
# Adopt regardless — SL still anchored to original_sl
```

SL is placed using `original_sl` (unchanged from signal creation). T1/T2/T3 remain at original levels.

#### F-2 — Bot cancels (timeout) → user then trades independently

```
Bot places LIMIT @ ₹1,411
15 min passes, not filled → bot cancels → marks SKIPPED
User sees Telegram signal, manually buys in DhanHQ app
```

Signal status = `SKIPPED`, but DhanHQ shows an open position.

`reconcile()` next cycle detects orphan position (no matching ACTIVE signal) → calls `_adopt_manual()` exactly as Scenario A.

```
🤝 MANUAL TRADE ADOPTED · ATHERENERG BUY
Entry: ₹1,415 | Default SL: ₹1,400.85 (1% fallback)
⚠️ No SL in market yet — placing now
```

#### F-3 — Bot's LIMIT still PENDING + user also buys separately (duplicate) ← most dangerous

```
Bot's LIMIT @ ₹1,411 still open (not yet timed out)
User manually buys 5 shares @ ₹1,415 in DhanHQ app
Broker now: 5 shares open (user fill) + LIMIT order still live
If LIMIT fills → 10 shares total  ←  UNINTENDED DOUBLE POSITION
```

`reconcile()` detects: signal is `ENTRY_PLACED` (pending LIMIT) but broker already shows a position.

```python
# In reconcile() — check for ENTRY_PLACED signals with existing broker position
for sym, sig in entry_placed_sigs.items():
    if sym in intraday:
        # Position already exists — cancel our pending LIMIT to prevent doubling
        dhan.cancel_order(sig["entry_order_id"])
        sig["status"]     = "ACTIVE"
        sig["fill_price"] = float(intraday[sym]["buyAvg"])
        sig["qty"]        = abs(int(intraday[sym]["netQty"]))
        telegram_notify.trade_drift_alert(
            sym, "DUPLICATE_ENTRY_PREVENTED",
            "Manual fill detected while LIMIT pending — LIMIT cancelled to avoid double position"
        )
```

#### F-4 — Bot cancels → user trades → reconcile hasn't run yet (gap window)

```
10:15 — Bot cancels LIMIT (timeout), signal marked SKIPPED
10:16 — User manually buys
10:20 — reconcile() runs next cycle
10:15–10:20 — 5-min gap: position open with NO SL in market
```

Handled identically to F-2 (`_adopt_manual()`). The Telegram alert includes:

```
⚠️ No SL in market yet — placing now
```

SL is placed immediately after adoption. The 5-min max exposure gap is acceptable for MIS — the WebSocket monitor (§10) eliminates this gap entirely.

#### F-4 Summary

| Sub-case | When | Bot order state | Detection | Action |
|----------|------|-----------------|-----------|--------|
| F-1 | User modifies bot's order price | PENDING → FILLED | `wait_for_fill()` sees fill | Adopt + drift alert |
| F-2 | Bot cancels → user trades independently | CANCELLED | `reconcile()` orphan position | `_adopt_manual()` |
| F-3 | Bot pending + user buys separately | PENDING still open | `reconcile()` ENTRY_PLACED + broker position | **Cancel LIMIT first**, then adopt |
| F-4 | Bot cancels → user trades → reconcile gap | CANCELLED | `reconcile()` next cycle | `_adopt_manual()` + "no SL yet" warning |

> **One rule covers all F sub-cases**: `reconcile()` must run at the **start** of every 5-min cycle, before any new order placement. This ensures F-3 (duplicate) is caught before the pending LIMIT fills and doubles the position.

---

### 8.6 Telegram Alerts for Manual Events

Add these to `app/telegram_notify.py`:

```python
def manual_trade_adopted(sym, direction, entry, sl, qty):
    _send(
        f"🤝 <b>MANUAL TRADE ADOPTED</b>  ·  {sym} {direction}\n"
        f"Entry: ₹{entry:,.2f}  |  Default SL: ₹{sl:,.2f}  (1%)\n"
        f"Qty: {qty}  |  ⚠️ Update SL in state file if incorrect\n"
        f"{_now_str()}"
    )

def trade_drift_alert(sym, drift_type, detail):
    _send(
        f"⚠️ <b>TRADE DRIFT</b>  ·  {sym}\n"
        f"Type: {drift_type}\n"
        f"Detail: {detail}\n"
        f"{_now_str()}"
    )

def manual_exit_detected(sym, direction, sl_cancelled=True):
    sl_note = "SL order cancelled ✓" if sl_cancelled else "⚠️ SL cancel FAILED — cancel manually in DhanHQ"
    _send(
        f"👤 <b>MANUAL EXIT</b>  ·  {sym} {direction}\n"
        f"Position closed outside bot — {sl_note}\n"
        f"Signal archived  |  {_now_str()}"
    )
```

---

### 8.7 Reconciliation in the Main Loop

```python
# main.py — at the start of every MONITOR phase

from app.position_tracker import reconcile
from app.state import load, save

state = load()
reconcile(dhan, state, qty=TRADE_QTY, paper=PAPER_MODE)
save(state)

# ... then normal signal_monitor loop ...
```

---

### 8.8 Summary

| Scenario | Detected by | Bot action | Telegram |
|----------|------------|------------|---------|
| A — Manual entry | Position in DhanHQ, not in state | Adopt: synthetic signal + place SL | 🤝 MANUAL TRADE ADOPTED |
| B — Qty changed | `netQty` ≠ `sig["qty"]` | Update qty in state | ⚠️ TRADE DRIFT (QTY) |
| C — Entry price changed > 0.1% | `buyAvg` ≠ `sig.risk.entry` | Update entry, recalc | ⚠️ TRADE DRIFT (ENTRY) |
| D — Fill slippage ≤ 0.1% | `buyAvg` ≠ `sig.risk.entry` | Silent update to state | None |
| E — User exited early | Signal ACTIVE, no position | **Cancel orphaned SL first**, mark EXITED | 👤 MANUAL EXIT |
| F-1 — User edits LIMIT price | `wait_for_fill()` sees fill at wrong price | Adopt fill + drift alert | ⚠️ TRADE DRIFT (ENTRY) |
| F-2 — Bot cancels, user trades after | `reconcile()` orphan position, signal SKIPPED | `_adopt_manual()` | 🤝 MANUAL TRADE ADOPTED |
| F-3 — LIMIT pending + user buys (duplicate) | `reconcile()` ENTRY_PLACED + broker position | **Cancel LIMIT first**, adopt broker fill | ⚠️ DUPLICATE_ENTRY_PREVENTED |
| F-4 — Bot cancels, user trades before reconcile | `reconcile()` next cycle | `_adopt_manual()` + "no SL yet" | 🤝 MANUAL TRADE ADOPTED |

---

### 8.9 Complete Edge Case Matrix

All scenarios the live trading system must handle. Grouped by category with priority for implementation.

#### Order Lifecycle Failures

| # | Scenario | Risk | Handler |
|---|----------|------|---------|
| 1 | Entry order partially filled | Position qty < expected, SL covers wrong qty | Cancel remainder; place SL for filled qty only |
| 2 | Entry order not filled (timeout) | LIMIT pending 15+ min, price moved away | Cancel order, mark SKIPPED, `signal_skipped()` Telegram |
| 3 | Entry order rejected by broker | Insufficient margin, stock in circuit, bad security_id | Mark SKIPPED, `error_alert` |
| 4 | **SL order rejected after fill** | Position open with NO protection | `_emergency_exit()` immediately — market order |
| 5 | Ambiguous order state (network timeout) | Order may or may not be placed | Query order status before retrying — never assume |
| 6 | SL modify rejected | TSL update failed, SL at old level | Retry once; then `error_alert` — old SL still protects |

#### Position / State Conflicts

| # | Scenario | Risk | Handler |
|---|----------|------|---------|
| 7 | Manual entry (Scenario A) | No SL in market | `_adopt_manual()` — synthetic signal + place SL |
| 8 | Manual exit (Scenario E) | **Orphaned SL = accidental new position** | Cancel SL first, then mark EXITED |
| 9 | Qty changed by user (Scenario B) | SL covers wrong qty | `trade_drift_alert`, re-sync qty |
| 10 | Duplicate order (GHA double-fire) | Two entries for same signal | Check `entry_order_id` exists before placing — idempotency guard |
| 11 | State file lost / reset | Bot forgets all active positions | `reconcile()` detects orphan positions every cycle |
| 12 | Two signals same stock same day | Double entry | `status = "CONSUMED"` in b1 state prevents; reconcile verifies |
| F-1 | User edits bot's LIMIT price | Entry drift | `wait_for_fill()` detects, drift alert |
| F-2 | Bot cancels, user trades after | No SL for up to 5 min | `reconcile()` orphan → `_adopt_manual()` |
| F-3 | LIMIT pending + user buys separately | **Double position** | Cancel pending LIMIT first, then adopt |
| F-4 | Bot cancels, user trades before reconcile | 5-min no-SL gap | `reconcile()` next cycle → `_adopt_manual()` |

#### Market / Broker Conditions

| # | Scenario | Risk | Handler |
|---|----------|------|---------|
| 13 | Stock hits circuit breaker | Can't exit — no liquidity | `error_alert`, manual intervention required |
| 14 | Stock enters F&O ban | Can't add new positions | Skip entry if ban detected; hold existing |
| 15 | Price gaps past SL | SL-M fills ₹10–₹20 worse than SL | Expected — log actual exit price vs SL |
| 16 | Market halt mid-day | Positions frozen, API errors | `error_alert` when API returns error |
| 17 | Race: T3 exit + SL triggers simultaneously | Both try to close same position | Cancel fails gracefully — check fill status |

#### Infrastructure Failures

| # | Scenario | Risk | Handler |
|---|----------|------|---------|
| 18 | DhanHQ API down | Can't place / modify / cancel | Retry ×2 with 3 s gap, then `error_alert` — existing SL still protects |
| 19 | **DhanHQ token expired mid-day** | All API calls fail with 401 | `system_halt` Telegram; manually trigger `dhan-token-management.yml` |
| 20 | GHA concurrency blocked | `live-trade.yml` queued behind stuck scan run | Both share `dhan-api-access` group; monitor GHA run durations |
| 21 | **Square-off fails at 15:05** | MIS open past 15:05; DhanHQ auto-squares 15:20 at worse price | Retry every 60 s from 15:05–15:15; `system_halt` if all retries fail |

#### Daily Risk Controls

| # | Scenario | Risk | Handler |
|---|----------|------|---------|
| 22 | Daily loss limit hit | Overtrading on bad day | Set `TRADING_HALTED=true` in state; skip all new entries; `system_halt` Telegram |
| 23 | Too many open positions | Capital overcommitted | Cap at `MAX_OPEN_POSITIONS=3`; skip new signals if limit hit |
| 24 | Blacklisted stock signals | Known loss-maker (e.g. NETWEB) | `BLACKLIST` env var check in `pre_trade_ok()` before `place_entry_order()` |

#### Implementation Priority

```
CRITICAL — must have before first live order:
  #4   SL rejection → _emergency_exit()
  #8   Manual exit → cancel orphaned SL
  #10  Duplicate order guard (idempotency)
  #19  Token expiry detection → system_halt
  #21  Square-off retry loop

HIGH — implement during paper phase:
  #1   Partial fill handling
  #2   Entry timeout + cancel
  F-3  Duplicate position prevention
  #13  Circuit breaker detection
  #22  Daily loss halt
  #23  Max open positions cap

MEDIUM — post-paper:
  #5   Ambiguous order state
  #15  SL slippage logging
  #17  Race condition (T3 + SL)
  #24  Blacklist check
```

---

## 9. Telegram Notifications  

Every trade event sends a message to a private channel. Module: `app/telegram_notify.py`.

### One-time Setup

**Step 1 — Create a bot**
1. Telegram → `@BotFather` → `/newbot` → copy token (`7123456789:AAF...`)

**Step 2 — Create private channel**
1. New Channel → Private → name it (e.g. `NSE ORB Signals`)
2. Add bot as **Administrator** with "Post Messages" permission

**Step 3 — Get chat_id**
```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
# Look for "chat":{"id":-100xxxxxxxxxx}   ← negative = channel
```

**Step 4 — GitHub secrets**
```
TELEGRAM_BOT_TOKEN  →  7123456789:AAF...
TELEGRAM_CHAT_ID    →  -100xxxxxxxxxx
```

### Message Types

| Event | Icon | Module |
|-------|------|--------|
| Signal detected | 🔍 | `scanner.py` |
| Signal skipped | ⏭ | `trade_manager.place_entry_order()` |
| Entry order placed | 📥 / 📝 | `trade_manager.place_entry_order()` |
| Entry filled | ✅ | `trade_manager.wait_for_fill()` |
| SL placed | 🛡 | `trade_manager.place_sl_order()` |
| T1 hit — SL → breakeven | 🎯 | `signal_monitor.py` |
| T2 hit — SL → T1 | 🎯🎯 | `signal_monitor.py` |
| T3 hit — SL → T2 | 🎯🎯🎯 | `signal_monitor.py` |
| SL hit (stopped out) | 🛑 | `signal_monitor.py` |
| Square-off | ⏰ | `square_off.py` |
| Daily summary | 📊 | `square_off.py` |
| Error / emergency | ⚠️ | any module |
| System start | 🟢 | `main.py` |
| Trading halted | 🔴 | `trade_manager.pre_trade_ok()` |

### Sample Messages

```
🔍 SIGNAL  ·  ATHERENERG BUY
Entry: ₹1,411.00  |  SL: ₹1,395.00  |  Risk: 16.0 pts
T1: ₹1,427.00  |  T2: ₹1,443.00  |  T3: ₹1,459.00
R:R → 1:1.0  |  RVOL: 2.3x  |  09:47 IST

⏭ SKIPPED  ·  ATHERENERG BUY
LTP: ₹1,392.00  →  Entry: ₹1,411.00
Reason: BREAKOUT_FAILED ltp=1392.00 ≤ sl=1395.00  |  09:48 IST

🎯 T1  ·  ATHERENERG BUY
LTP: ₹1,428.50  |  Target: ₹1,427.00
Unrealised: +17.5 pts  (+₹87.50  ×  5 shares)
✅ SL → breakeven  (trailing active)
09:53 IST

🛑 SL HIT  ·  ATHERENERG BUY  ·  was T1 ✓
Exit @ ₹1,411.00  |  P&L: 0.0 pts  (₹0.00)
10:12 IST

⏰ SQUARE-OFF  ·  ATHERENERG BUY  ·  T2
Exit @ ₹1,444.00  (15:05 auto)  |  5 shares
P&L: +33.0 pts  (+₹165.00)
15:05 IST

📊 DAY SUMMARY  ·  Mon 27 Oct
Trades: 12  |  8W/4L  |  WR: 67%
P&L: +89.5 pts  (+₹447.50  ×  qty 5)
Best:  ATHERENERG +33.0 pts
Worst: NETWEB -22.5 pts
```

### Telegram Commands (real-time control)

Send these to the bot's chat from any device during market hours. The bot polls `getUpdates` (non-blocking, `timeout=0`) at the **start of every 5-min GHA cycle** and processes any new commands.

| Command | Effect | Telegram reply |
|---------|--------|----------------|
| `/halt` | Sets `trading_halted=True` — no new entries placed until `/resume` | 🔴 TRADING HALTED |
| `/resume` | Clears `trading_halted` — entries re-enabled | 🟢 TRADING RESUMED |
| `/squareoff` | Closes all open positions at market immediately | ⏰ MANUAL SQUARE-OFF triggered |
| `/status` | Reports open positions + unrealised P&L + today's closed P&L + halt status | 📋 STATUS |

**Security**: commands from any chat ID other than `TELEGRAM_CHAT_ID` are silently dropped.

**Offset persistence**: last processed `update_id` is stored in `state["_tg_update_id"]` so commands are never replayed across GHA runs.

**Implementation**: `app/telegram_cmd.py` → `poll_and_process(dhan, state, paper)`, called as Step 0 in `trade_manager.run()`.

**Latency**: up to 5 min (next GHA cycle). For immediate action, use DhanHQ app directly.

---

### Rate Limit

Telegram allows 1 msg/s to the same chat. On peak days (33 signals), add a 0.5 s gap in `square_off.py`:
```python
for sig in active_signals:
    square_off(sig, exit_price, qty, paper=PAPER_MODE)
    time.sleep(0.5)
```

---

## 10. WebSocket Monitor

For continuous TSL trailing between 5-min GHA runs, run `websocket_monitor.py` as a persistent process.

```python
# app/websocket_monitor.py
import asyncio, os
from dhanhq import marketfeed
from app.state import load, save
from app.signal_monitor import _apply_trailing
from app.symbol_map import get_security_id

PAPER_MODE = os.environ.get("PAPER_MODE", "true").lower() == "true"

async def run_feed(ctx, dhan):
    state  = load()
    active = {
        s["symbol"]: s
        for s in state.get("signals", {}).values()
        if s.get("status") == "ACTIVE"
    }
    if not active:
        return

    instruments = [
        (marketfeed.NSE, get_security_id(sym), marketfeed.Ticker)
        for sym in active
    ]
    async with marketfeed.DhanFeed(ctx, instruments) as feed:
        async for tick in feed:
            sym = tick.get("symbol")
            ltp = tick.get("LTP")
            if sym and ltp and sym in active:
                _apply_trailing(dhan, active[sym], float(ltp), PAPER_MODE)
                save(state)
```

### Hosting Options

| Option | Cost/mo | Notes |
|--------|---------|-------|
| GitHub Actions (6h job, 09:00–15:15) | Free | One workflow per market day |
| Raspberry Pi / home PC | ₹0 | Needs stable internet |
| Railway / Render free tier | Free | Cold-start ~30s — launch at 09:00 |
| AWS t3.nano / DigitalOcean | ~₹350 | Most reliable |

GHA approach:
```yaml
- run: python -m app.websocket_monitor
  timeout-minutes: 380   # 6h 20m — covers full market day
```

---

## 11. Security ID Lookup

DhanHQ uses numeric `security_id` (e.g. RELIANCE = `"1333"`), not NSE symbols.

### `app/symbol_map.py`

```python
import pandas as pd

_CSV  = "data/dhan_instruments.csv"
# Download: https://images.dhan.co/api-data/api-scrip-master.csv

_MAP: dict[str, str] = {}

def build_map(path: str = _CSV) -> dict[str, str]:
    df  = pd.read_csv(path)
    nse = df[(df["SEM_EXM_EXCH_ID"] == "NSE") &
             (df["SEM_INSTRUMENT_NAME"] == "EQUITY")]
    return dict(zip(
        nse["SEM_TRADING_SYMBOL"],
        nse["SEM_SMST_SECURITY_ID"].astype(str),
    ))

def get_security_id(symbol: str) -> str:
    global _MAP
    if not _MAP:
        _MAP = build_map()
    sid = _MAP.get(symbol)
    if not sid:
        raise ValueError(f"security_id not found for {symbol!r} — refresh data/dhan_instruments.csv")
    return sid
```

### Daily refresh workflow

```yaml
# .github/workflows/refresh-instruments.yml
on:
  schedule:
    - cron: "30 2 * * 1-5"    # 08:00 IST Mon–Fri
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          curl -fsSo data/dhan_instruments.csv \
            https://images.dhan.co/api-data/api-scrip-master.csv
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: refresh DhanHQ instruments"
```

---

## 12. GitHub Actions Workflows

### `live-trade.yml`

```yaml
name: Live Trade
on:
  workflow_run:
    workflows: ["NSE Momentum Scanner"]
    types: [completed]

jobs:
  trade:
    runs-on: ubuntu-latest
    env:
      DHAN_CLIENT_ID:     ${{ secrets.DHAN_CLIENT_ID }}
      DHAN_ACCESS_TOKEN:  ${{ secrets.DHAN_ACCESS_TOKEN }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
      PAPER_MODE:         "true"    # ← "false" for live
      TRADE_QTY:          "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python -m app.trade_manager  # only acts on status == "NEW"
```

### `square-off.yml` — 15:05 IST (15 min before broker auto-square)

```yaml
name: Square Off
on:
  schedule:
    - cron: "35 9 * * 1-5"    # 15:05 IST = 09:35 UTC

jobs:
  squareoff:
    runs-on: ubuntu-latest
    env:
      DHAN_CLIENT_ID:     ${{ secrets.DHAN_CLIENT_ID }}
      DHAN_ACCESS_TOKEN:  ${{ secrets.DHAN_ACCESS_TOKEN }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
      PAPER_MODE:         "true"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python -m app.square_off
```

### `square_off.py`

```python
# app/square_off.py
import time
from app.telegram_notify import square_off as tg_sq, daily_summary

def square_off_all(dhan, state, qty, paper=True):
    active = [
        s for s in state.get("signals", {}).values()
        if s.get("status") == "ACTIVE"
    ]
    positions = dhan.get_positions()["data"] if not paper else []
    trade_log = []

    for sig in active:
        sym        = sig["symbol"]
        opp        = dhan.SELL if sig["direction"] == "BUY" else dhan.BUY
        exit_price = float(sig["risk"]["entry"])   # paper fallback

        if not paper:
            pos = next((p for p in positions if p["tradingSymbol"] == sym), None)
            if pos:
                exit_price = float(pos.get("dayBuyPrice", sig["risk"]["entry"]))
            dhan.place_order(
                security_id      = get_security_id(sym),
                exchange_segment = dhan.NSE_EQ,
                transaction_type = opp,
                quantity         = qty,
                order_type       = dhan.MARKET,
                product_type     = dhan.INTRADAY,
                price            = 0,
            )

        entry   = float(sig["risk"]["entry"])
        pnl_pts = (exit_price - entry) if sig["direction"] == "BUY" else (entry - exit_price)
        sig["status"]     = "EXITED"
        sig["exit_price"] = exit_price

        tg_sq(sig, exit_price, qty, paper=paper)
        trade_log.append({"symbol": sym, "pnl_pts": pnl_pts})
        time.sleep(0.5)   # Telegram 1 msg/s limit

    daily_summary(trade_log, qty, paper=paper)
```

---

## 13. Phased Rollout

### Phase 1 — Paper Trade (current)

`PAPER_MODE=true`, `TRADE_QTY=1`

**Graduate to Phase 2 when:**
- Paper P&L within ±5% of `pnl-check.yml` over 5 consecutive days
- Zero duplicate orders in `logs/paper_orders.jsonl`
- Every `ACTIVE` signal has a matching SL log entry
- Telegram fires for all events (signal, skip, fill, SL, square-off, summary)

---

### Phase 2 — Live, qty=1

`PAPER_MODE=false`, `TRADE_QTY=1`. Max capital at risk ~₹300/day.

**Daily checks:**
- DhanHQ order book matches `runtime_state.json`
- No `ENTRY_PLACED` stuck > 15 min without fill
- SL order exists for every `ACTIVE` position

**Graduate to Phase 3 when:** 1 clean week — no stuck states, no missed SL placements.

---

### Phase 3 — Live, qty=5 + WebSocket TSL

Enable `websocket_monitor.py`. Validate BE move happens within seconds of T1. Optional: partial exit at T3 (50% qty).

---

### Phase 4 — Full qty + dynamic sizing

Size qty proportional to RVOL score and SL tightness. Add recurring-loser exclusion list. Telegram alert if > 3 SL hits in one day.

---

## 14. Risk Controls

### Blacklist

```python
# app/config.py
BLACKLIST: set[str] = {
    "NETWEB",  # 3 trades Oct 7–26: 1W/2L, net -177.60 pts
}
```

### Limits

```python
MAX_OPEN_POSITIONS   = 35      # simultaneous ACTIVE signals (set for ₹1L capital, qty=1)
DAILY_LOSS_HALT_INR  = -1000   # halt new entries if daily P&L (pts × qty, rupees) ≤ -₹1,000
                                # = 1% daily loss limit on ₹1L capital
MAX_SIGNAL_AGE_MIN   = 30      # skip signal older than 30 min
MAX_ENTRY_HHMM       = 1300    # no new entries after 13:00 IST
MIN_TRAIL_INC        = 2.0     # minimum pts improvement before calling modify_order (rate-limit guard)
```

**Daily loss halt logic**: sums `(exit_price − entry) × qty` for all EXITED signals each cycle. When total ≤ `DAILY_LOSS_HALT_INR`, sets `state["trading_halted"] = True` and fires Telegram 🔴. Reset only by `/resume` command or manual state edit.

**Capital guidance**:

| Capital | Recommended qty | `DAILY_LOSS_HALT_INR` |
|---------|----------------|----------------------|
| ₹1,00,000 | 1 | -1000 (1%) |
| ₹5,00,000 | 3–5 | -5000 (1%) |
| ₹10,00,000 | 5–10 | -10000 (1%) |

### Key rule

**SL must always be in the market.** If `place_sl_order()` fails → `_emergency_exit()` immediately. No exceptions.

### Duplicate prevention

`trade_manager` only places orders on signals with `status == "NEW"`. Re-runs are safe.

---

## 15. Environment Variables

| Variable | Store as | Default | Description |
|----------|----------|---------|-------------|
| `DHAN_CLIENT_ID` | GitHub Secret | — | DhanHQ numeric client ID |
| `DHAN_ACCESS_TOKEN` | GitHub Secret | — | DhanHQ token — refresh daily before 09:15 |
| `TELEGRAM_BOT_TOKEN` | GitHub Secret | — | Bot token from `@BotFather` |
| `TELEGRAM_CHAT_ID` | GitHub Secret | — | Private channel / chat ID (used for both notifications and command input) |
| `PAPER_MODE` | Workflow env | `"true"` | `"true"` = paper, `"false"` = live |
| `TRADE_QTY` | Workflow env | `"1"` | Shares per signal |
| `MAX_SIGNAL_AGE_MIN` | Workflow env | `"30"` | Skip signals older than N min |
| `MAX_ENTRY_HHMM` | Workflow env | `"1300"` | No new entries after this HHMM (IST) |
| `MAX_PENDING_MIN` | Workflow env | `"15"` | Cancel unfilled LIMIT after N min |
| `MIN_TRAIL_INC` | Workflow env | `"2.0"` | Min pts improvement before SL modify |
| `MAX_OPEN_POSITIONS` | Workflow env | `"35"` | Max simultaneous ACTIVE positions |
| `PARTIAL_EXIT_T3` | Workflow env | `"true"` | Exit 50% qty at market when T3 hit |
| `DAILY_LOSS_HALT_INR` | Workflow env | `"-1000"` | Halt entries if daily P&L (₹) ≤ this |
| `BROKERAGE_PER_TRADE` | Workflow env | `"0"` | Override per-trade brokerage cost; `0` = auto-compute from Dhan formula |
| `LOG_LEVEL` | Workflow env | `"INFO"` | Python logging level |

**Live-trade.yml current values** (for ₹1L capital, qty=1):
```yaml
TRADE_QTY:          "1"
MAX_SIGNAL_AGE_MIN: "30"
MAX_ENTRY_HHMM:     "1300"
MAX_OPEN_POSITIONS: "35"
PARTIAL_EXIT_T3:    "true"
DAILY_LOSS_HALT_INR: "-1000"
```

**Local `.env`** (never commit — already in `.gitignore`):
```
DHAN_CLIENT_ID=12345678
DHAN_ACCESS_TOKEN=eyJ...
TELEGRAM_BOT_TOKEN=7123456789:AAF...
TELEGRAM_CHAT_ID=-100xxxxxxxxxx
PAPER_MODE=true
TRADE_QTY=1
MAX_SIGNAL_AGE_MIN=30
MAX_ENTRY_HHMM=1300
MAX_OPEN_POSITIONS=35
DAILY_LOSS_HALT_INR=-1000
```

---

## 16. Known Limitations

| # | Issue | Impact | Mitigation |
|---|-------|--------|-----------|
| 1 | DhanHQ token expires daily | All orders fail if stale | Update secret each morning before 09:15 |
| 2 | `security_id` missing for new listings | Order rejected | Daily instruments CSV refresh at 08:00 |
| 3 | GHA 6h limit — WebSocket monitor | TSL updates every 5 min only | Railway/Render/Pi for persistent process |
| 4 | LIMIT at entry may never fill | Signal waits → timeout cancel | 15-min pending timeout with cancel |
| 5 | SL-M rejected (price band / freeze) | Open position unprotected | Catch → `_emergency_exit()` immediately |
| 6 | Duplicate orders on GHA overlap | Double position | `status == "NEW"` check prevents re-entry |
| 7 | Partial fills on entry | `qty` in state > actual fill | Track `filled_qty` from fill response |
| 8 | DhanHQ API downtime | No orders placed | Telegram error alert; manual check |
| 9 | TSL modify rate limit | Some SL moves dropped | Only modify if SL improves ≥ 2 pts |
| 10 | Square-off GHA delay (up to 2 min) | Exit at 15:07 not 15:05 | Cron at 15:05; broker auto-squares at 15:20 |

---

## 17. Emergency Runbook

> Use this when automation fails during market hours.

### Check open positions manually

```bash
curl -H "access-token: $DHAN_ACCESS_TOKEN" \
     -H "client-id: $DHAN_CLIENT_ID" \
     https://api.dhan.co/v2/positions
```

Or: DhanHQ app → Positions → INTRADAY filter.

### Force square-off if GHA fails at 15:05

1. DhanHQ app → Positions → select all INTRADAY → Exit All
2. Broker auto-squares at 15:20 regardless — manual action only needed 15:05–15:20

### Signal stuck as `ENTRY_PLACED` with no fill

1. Find `entry_order_id` in `runtime_state.json`
2. Check DhanHQ order book — if pending, cancel manually
3. Set `signal["status"] = "SKIPPED"` in state file, commit, push

### SL order missing for an open position

1. Place SL-M manually in DhanHQ app immediately
2. Consider adding the stock to BLACKLIST if recurring

### Telegram alerts requiring action

| Alert | Required action |
|-------|----------------|
| `⚠️ ERROR · SL placement failed` | Urgent — place SL manually or exit |
| `⚠️ ERROR · EMERGENCY_EXIT_FAILED` | Critical — exit manually in DhanHQ immediately |
| `⚠️ SL order gone — {sym} — re-placing` | Bot detected missing SL and re-placed — verify in DhanHQ |
| `⚠️ MARGIN_FAIL` | Add funds or reduce `TRADE_QTY` |
| No `⏰ SQUARE-OFF` by 15:10 | Check GHA logs, exit manually in app |
| `🔴 TRADING HALTED` (daily loss) | Auto-halt — resumes next day or send `/resume` if intentional |
| `🔴 TRADING HALTED` (manual /halt) | You sent `/halt` — send `/resume` when ready |

### Real-time control via Telegram

```
/halt       → stop new entries immediately (takes effect next GHA cycle, ≤5 min)
/resume     → re-enable entries
/squareoff  → close all open positions now
/status     → see open positions + P&L summary
```

---

## 18. Local Testing

### Paper trade locally

```bash
export PAPER_MODE=true TRADE_QTY=1
python -m app.main

# Check paper orders
cat logs/paper_orders.jsonl | python -m json.tool

# Check state
cat runtime_state.json | python -m json.tool
```

### Verify Telegram

```python
python -c "from app.telegram_notify import system_start; system_start(paper=True)"
```

### Verify security_id lookup

```python
python -c "
from app.symbol_map import get_security_id
for s in ['RELIANCE','ATHERENERG','NETWEB','TATAELXSI']:
    print(s, '->', get_security_id(s))
"
```

### Simulate entry skip (breakout failed)

```python
from app.trade_manager import should_place_entry
signal = {
    "direction": "BUY",
    "signal_time": "2026-10-27T09:20:00+05:30",
    "risk": {"entry": 1411.0, "original_sl": 1395.0}
}
print(should_place_entry(signal, ltp=1392.0))  # → (False, 'BREAKOUT_FAILED ...')
print(should_place_entry(signal, ltp=1415.0))  # → (True,  'OK')
print(should_place_entry(signal, ltp=1425.0))  # → (True,  'OK')  wait for retest
```

---

## 19. Next Steps

### Code Complete (no action needed)
- [x] **Step 1** — `app/main.py`: status `NEW`, `signal_time`, `original_sl` added
- [x] **Step 2** — `app/signal_monitor.py`: `live_managed` guard on T1 SL write
- [x] **Step 3** — `app/trade_manager.py`: entry, fill, SL-M, TSL, emergency exit, daily loss halt
- [x] **Step 4** — `app/position_tracker.py`: reconcile, manual adopt, F-3 duplicate guard, SL health check
- [x] **Step 5** — `app/square_off.py`: EOD market exit + brokerage-aware daily summary
- [x] **Step 6** — `app/telegram_notify.py`: all event types + brokerage breakdown + Dhan fee formula
- [x] **Step 7** — `app/telegram_cmd.py`: `/halt` `/resume` `/squareoff` `/status` command polling
- [x] **Step 8** — `.github/workflows/live-trade.yml`: `workflow_dispatch`, all risk vars set
- [x] **Step 9** — `.github/workflows/square-off.yml`: 15:05 IST square-off
- [x] **Step 10** — `MAX_SIGNAL_AGE_MIN=30` (extended from 15 for GHA startup)
- [x] **Step 11** — `MAX_ENTRY_HHMM=1300` (extended from 12:30)
- [x] **Step 12** — `MAX_OPEN_POSITIONS=35` (raised from 5 for ₹1L capital)
- [x] **Step 13** — `PARTIAL_EXIT_T3=true` — 50% qty exit at T3, trail remaining
- [x] **Step 14** — `DAILY_LOSS_HALT_INR=-1000` — 1% daily loss limit on ₹1L
- [x] **Step 15** — 54 unit tests, all passing

### Before Going Live
- [ ] **Step 16** — Verify `security_id` is written by scanner for each signal
- [ ] **Step 17** — Download `data/dhan_instruments.csv` + create `app/symbol_map.py`
- [ ] **Step 18** — Run paper for 5 clean days; P&L within ±5% of `pnl-check.yml`
- [ ] **Step 19** — Set `PAPER_MODE=false`, `TRADE_QTY=1` → Phase 2 live

### Future
- [ ] **Step 20** — `app/ws_monitor.py` — WebSocket real-time SL/TSL (Phase 3)
- [ ] **Step 21** — `app/mcp_server.py` — Claude queries live state via MCP (Phase 4)
- [ ] **Step 22** — Multi-account loop in `trade_manager.run()` (Phase 5)
