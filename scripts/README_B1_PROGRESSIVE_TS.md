# NSE Momentum — B1 ORB Strategy

> **Note on this file's history:** this document previously described a
> "progressive trailing-stop" exit model and referenced backtest scripts
> that compared it against a fixed-target exit. That trailing-stop model
> was never wired into the live scanner (`app/main.py`), and the backtest
> scripts that describe it currently fail to import against the live
> `app/strategy.py` (they reference `evaluate_15m_setup` /
> `confirm_5m_breakout`, functions that no longer exist — see the
> **Backtest scripts** section at the bottom). This file has been rewritten
> to describe what the live scanner actually does today.

## Universe

Two layers build the scanned symbol list, both sourced from Dhan and a
static file — **no live calls to nseindia.com remain anywhere in this
codebase.**

1. **Base universe (`build_universe`):** loaded from
   `app/data/nifty500_constituents.json`, a static list of NIFTY 500
   constituent symbols. This file is a one-time export from NSE's public
   website ("Market Watch" CSV download for the NIFTY 500 index),
   converted to JSON — not a live API call. NSE Indices rebalances this
   index roughly twice a year (per its published methodology); refresh
   this file by hand every few months by downloading a fresh NIFTY 500
   CSV from NSE's site and regenerating the JSON (symbol list, `as_of`
   date, source filename).
2. **Dynamic additions (`refresh_dynamic_volume_gainers`):** every 10
   minutes during the scan window, a candidate pool of NSE equities
   (from Dhan's own security master, capped by
   `VOLUME_GAINER_CANDIDATE_LIMIT`) is compared against its own trailing
   `VOLUME_GAINER_BASELINE_DAYS`-day average daily volume (computed once
   per day and cached), scaled to the elapsed fraction of the trading
   day. Candidates whose volume-so-far clears `VOLUME_GAINER_RVOL_THRESHOLD`
   and the existing price/volume filters are added to the day's universe.
   This replaces what was previously a scrape of NSE's internal
   `live-analysis-volume-gainers` endpoint.

## Entry logic

1. **ORB (Opening Range Breakout):** the very first completed 15-minute
   candle of the day (09:15–09:30 IST) sets the fixed reference range —
   its `high` and `low`. This range does not update again for the rest of
   the day.
2. **15M setup candle:** every subsequent completed 15M candle is checked
   in chronological order. A candle whose `close` is above the ORB high
   is a `BUY` breakout candidate; below the ORB low is a `SELL` breakout
   candidate. A candle closing inside the range is `NO_BREAKOUT` and is
   skipped.
3. **Entry filters**, all of which must pass on that same 15M candle
   (`app/strategy.py::evaluate_b1_breakout`):
   - Daily close > `MIN_PRICE` (default 350) and daily volume >
     `MIN_DAILY_VOLUME` (default 500,000).
   - RSI(14) must sit inside a directional band **and** be moving the
     right way: `BUY` needs `BUY_RSI_MIN < RSI < BUY_RSI_MAX` (default
     55–70) and RSI rising vs. the previous candle; `SELL` needs
     `SELL_RSI_MIN < RSI < SELL_RSI_MAX` (default 30–45) and RSI falling.
   - 15M relative volume (`RVOL`, current volume vs. the trailing
     `RVOL_LOOKBACK`-candle average, default 20) must be ≥ `MIN_15M_RVOL`
     (default 1.2).
   - A demand/supply "trade quality score" (base-candle compactness +
     zone freshness + departure-candle strength, see `app/scoring.py`)
     must fall between `MIN_TRADE_SCORE` and `MAX_TRADE_SCORE` (default
     3–7).
   - If a candle breaks out but fails any filter, that specific candle is
     rejected and logged (`B1_FILTER_REJECTED`, with a specific reason —
     see below); the scanner keeps checking **later** 15M candles the
     same day for a fresh breakout, it does not stop at the first
     attempt.
4. Once a 15M candle clears every filter, it becomes the symbol's
   **accepted setup** for the day and the scanner moves to confirmation.
   No second setup is opened for that symbol while one is pending or
   already resolved.

## Confirmation and entry price

- After a setup is accepted, the scanner waits for a **completed 5-minute
  candle** (strictly after the setup 15M candle's completion time) whose
  close moves **strictly beyond** the setup candle's own high (`BUY`) or
  low (`SELL`) — equality does not confirm.
- **Entry price = that confirming 5M candle's close** (not the 15M
  breakout close).
- **Stop-loss = the 15M setup candle's own close** (`setup_15m_close`) —
  not the 09:15 ORB candle's close. These will usually be different
  prices, since the setup candle is, by definition, a later candle than
  the opening range.

## Targets and risk (fixed, not progressive)

Computed once at confirmation by `app/risk.py::build_risk_and_targets`:

- `risk = |entry − stop_loss|`; rejected if `risk / entry` is below
  `MIN_STOP_DISTANCE_PERCENT` (default 0.50%).
- `T1 = entry ± T1_RR × risk`, `T2 = entry ± T2_RR × risk`,
  `T3 = entry ± T3_RR × risk` (defaults 2.0 / 3.0 / 4.0).
- Rejected if `T1_RR < MIN_RR` (default 2.0).
- **There is no trailing stop, break-even shift, or structure-based
  ratchet in the live code.** Every alert carries this same fixed
  entry/SL/T1/T2/T3 for its full life. (`app/config.py` still defines an
  `ENABLE_PROGRESSIVE_TS` flag, but nothing in `app/` reads it — it is
  currently a dead setting.)

## T1-blocked safety check

Before an alert is sent, `app/strategy.py::t1_blocked` checks the 5M
candles between the setup and the confirmation candle: if price already
touched T1 *before* the trade would have technically been confirmed, the
signal is rejected (`CONFIRMED_BUT_REJECTED | reason=T1_BLOCKED`) rather
than sent as an alert that's already "late."

## One resolved outcome per symbol per day

A symbol can have multiple **rejected setup attempts** in one day (each
logged, each simply skipped). But once a setup is accepted and reaches
the confirmation phase, that symbol is locked for the rest of the day
once confirmation resolves — whether that resolution is a sent alert, a
risk rejection, or a T1-blocked rejection. It will not be re-evaluated
again that trading day after that point.

## Key log lines to look for

| Log line | Meaning |
|---|---|
| `B1_ORB` | The day's opening range has been fixed for this symbol |
| `B1_15M ... NO_BREAKOUT` | Candle closed back inside the ORB range |
| `B1_FILTER_REJECTED` | A breakout candle failed a specific filter (reason + numbers included) |
| `B1_SETUP_ACCEPTED` | A 15M candle passed every filter; now waiting for 5M confirmation |
| `B1_5M ... NO_CONFIRMATION` | A later 5M candle didn't yet cross the setup high/low |
| `B1_5M ... CONFIRMED` | A 5M candle crossed the threshold |
| `CONFIRMED_BUT_REJECTED` | Confirmed, but rejected by risk sizing or the T1-blocked check |
| `ALERT_SENT` | A Telegram alert was actually sent |

## Configuration reference

All of the above thresholds are environment variables, set in
`.github/workflows/nse-momentum-scan.yml` and defaulted in
`app/config.py`:

| Variable | Default | Purpose |
|---|---|---|
| `MIN_PRICE` | 350 | Minimum daily close to be considered |
| `MIN_DAILY_VOLUME` | 500000 | Minimum daily volume |
| `BUY_RSI_MIN` / `BUY_RSI_MAX` | 55 / 70 | RSI band for BUY setups |
| `SELL_RSI_MIN` / `SELL_RSI_MAX` | 30 / 45 | RSI band for SELL setups |
| `RVOL_LOOKBACK` | 20 | Candles used for the RVOL average |
| `MIN_15M_RVOL` | 1.2 | Minimum 15M relative volume |
| `MIN_TRADE_SCORE` / `MAX_TRADE_SCORE` | 3 / 7 | Accepted trade-quality score range |
| `T1_RR` / `T2_RR` / `T3_RR` | 2.0 / 3.0 / 4.0 | Target reward multiples |
| `MIN_RR` | 2.0 | Minimum required T1 reward:risk |
| `MIN_STOP_DISTANCE_PERCENT` | 0.50 | Minimum stop distance as % of entry |
| `SCAN_START_HHMM` / `SCAN_END_HHMM` | 930 / 1505 | Scan window (IST, 24h HHMM) |
| `DRY_RUN` | true | If true, alerts are logged but not sent to Telegram |
| `VOLUME_GAINER_CANDIDATE_LIMIT` | 800 | How many NSE equities to baseline daily for the volume-gainer scan |
| `VOLUME_GAINER_RVOL_THRESHOLD` | 2.0 | Relative-volume multiple (vs. expected-by-this-time-of-day) to flag a candidate |
| `VOLUME_GAINER_BASELINE_DAYS` | 10 | Trailing days averaged to compute each candidate's baseline volume |

## Backtest scripts (`scripts/`) — currently outdated

The scripts in this folder (`historical_backtest_15m5m_confirmation.py`,
`historical_backtest_4_methods_ORB_STATE_MACHINE.py`,
`historical_backtest_orb_ts_engine.py`,
`historical_backtest_orb_1_11.py`) all import `evaluate_15m_setup` and
`confirm_5m_breakout` from `app/strategy.py`. Neither function exists
anymore — the live strategy module now exposes `evaluate_b1_breakout`
and `t1_blocked` instead. **Every one of these scripts currently fails
immediately on import** and will not run as-is.

Separately, `historical_backtest_orb_1_11.py`'s default `--script`
argument points at `scripts/historical_backtest_4_methods.py`, which does
not exist in this repository under that name at all.

If you want a working backtest against the current live logic, the
scripts need to be updated to call `evaluate_b1_breakout` /
`t1_blocked` with the current function signatures — they are not
currently usable out of the box.
