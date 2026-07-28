# Event-Driven Backtester with Realistic Execution Costs

An event-driven (not vectorized) backtesting engine that models slippage,
latency, and partial fills — and **runs itself**. A scheduled GitHub Actions
job pulls fresh market data, re-runs the backtest, and republishes the
tearsheet automatically, with no manual trigger required.

**Live tearsheet:** published to GitHub Pages from `/reports` after every
scheduled run → `https://<username>.github.io/event-driven-backtester/`

---

## Why event-driven, not vectorized

Most portfolio backtests are vectorized: apply a signal array to a returns
array with `pandas`/`numpy` in one shot. That's fast, but it makes it
easy to accidentally use information that wouldn't have been available yet
(a shifted window applied the wrong direction, a same-bar fill at the same
bar's close), and it has no natural place to put *execution realism* —
there's no "order" or "fill" object, just an array multiply.

This project instead runs a literal event queue: `MarketEvent` →
`SignalEvent` → `OrderEvent` → `FillEvent`, processed one at a time, in
timestamp order. A strategy component physically cannot see a bar before
its `MarketEvent` has been dispatched. This is what makes it possible to
model, honestly:

- **Latency** — a decision made on bar *t* doesn't fill instantly.
- **Slippage** — spread cost + a square-root market-impact model, so larger
  orders in thinner names cost more.
- **Partial fills** — an order bigger than a participation-rate cap of that
  bar's volume only partially executes; the remainder carries forward.

Every run also computes an **idealized, frictionless shadow portfolio** in
parallel, so the tearsheet shows exactly how much of the idealized P&L got
eaten by realistic execution costs.

## Real-World Finance Use Case

Portfolio managers and quant researchers routinely overestimate strategy
performance because vectorized backtests assume free, instant, unlimited
liquidity. This engine is a template for the pre-deployment sanity check
every systematic strategy needs: *does this still work once you have to pay
the spread, move the market, and wait for your fill?* The same
architecture (event queue, execution simulator, walk-forward harness)
extends directly to a live/paper-trading execution layer, which is why the
strategy interface is deliberately signal-agnostic — swap in any real
signal-generation module without touching the execution or reporting code.

---

## System Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │        GitHub Actions (scheduled, cron)      │
                    │  1. checkout  2. install  3. run pipeline    │
                    │  4. commit reports/  5. deploy to Pages      │
                    │  6. alert (issue/Slack) on failure           │
                    └───────────────────┬───────────────────────────┘
                                         │ triggers
                                         ▼
┌───────────────┐   ┌──────────────┐   ┌────────────┐   ┌──────────────┐
│ DataHandler    │──▶│ Event Queue  │──▶│ Strategy   │──▶│ Portfolio    │
│ (fetch+cache,  │   │ (Market→     │   │ (signals)  │   │ (sizing,     │
│  retry/backoff)│   │  Signal→     │   └────────────┘   │  P&L, ideal  │
└───────────────┘   │  Order→Fill) │        ▲            │  shadow port)│
                     └──────┬───────┘        │            └──────┬───────┘
                            │                 │                    │
                            ▼                 │                    ▼
                   ┌──────────────────┐       │           ┌────────────────┐
                   │ ExecutionHandler │───────┘           │ Performance +  │
                   │ (latency, slip-  │                   │ Tearsheet gen  │
                   │  page, partial   │                   │ (PNG + HTML)   │
                   │  fills)          │                   └────────────────┘
                   └──────────────────┘
```

The automation layer (top box) is not an afterthought bolted onto a
notebook — `run_backtest.py` is the single entrypoint both a human and CI
call, so "runs locally" and "runs unattended on schedule" are the same code
path.

---

## Required APIs and Data Sources

Configured via `config/config.yaml` → `data.provider`. All three support
unattended, credential-based pulls (no manual download step):

| Provider | Key required? | Notes |
|---|---|---|
| **Yahoo Finance** (`yfinance`) | No | Default. Free, no key management needed, good enough for daily-bar research. |
| **Polygon.io** | Yes (`POLYGON_API_KEY`) | Swap-in for intraday bars / higher data quality. |
| **Alpaca Market Data** | Yes (`ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`) | Same account can later be used for paper-trading execution — see Upgrades. |

All keys are read from environment variables (injected from **GitHub
Actions Secrets** in CI, or a local `.env` you never commit) — never
hardcoded, never logged.

## Required Python Libraries

```
pandas, numpy, yfinance, matplotlib, pyyaml, pyarrow, pytest, pytest-cov
```
See `requirements.txt` for pinned minimum versions.

---

## Repo Structure

```
event-driven-backtester/
├── run_backtest.py                  # single entrypoint (local + CI)
├── config/
│   └── config.yaml                  # symbols, dates, capital, cost params
├── src/
│   ├── data/
│   │   └── data_handler.py          # fetch + retry/backoff + parquet cache
│   ├── engine/
│   │   ├── events.py                # Market/Signal/Order/Fill events
│   │   ├── backtest.py              # the event queue loop
│   │   └── portfolio.py             # sizing, P&L, idealized shadow port
│   ├── execution/
│   │   └── execution_handler.py     # latency, slippage, partial fills
│   ├── strategies/
│   │   └── sma_crossover.py         # example signal generator
│   ├── validation/
│   │   └── walk_forward.py          # walk-forward windows + leakage checks
│   └── reporting/
│       ├── performance.py           # Sharpe, Sortino, drawdown, turnover...
│       └── tearsheet.py             # PNG charts + self-contained HTML
├── tests/                           # pytest unit tests, run in CI
├── reports/                         # auto-committed tearsheet output
├── cache/                           # auto-refreshed parquet data cache
└── .github/workflows/
    ├── ci.yml                       # tests on every push/PR
    └── scheduled_backtest.yml       # cron: fetch → backtest → publish
```

---

## Step-by-Step Build Guide

1. **Events & queue** — define the four event types, build a `queue.Queue`
   consumer loop that dispatches by type (`src/engine/events.py`,
   `src/engine/backtest.py`).
2. **Data layer** — stream historical bars in timestamp order; separately,
   make acquisition unattended-safe (retries, backoff, parquet cache,
   graceful degradation to stale cache) (`src/data/data_handler.py`).
3. **Strategy** — a minimal signal generator to prove the pipeline
   end-to-end (`src/strategies/sma_crossover.py`).
4. **Portfolio** — turn signals into sized orders; track cash, positions,
   equity curve, and a frictionless shadow portfolio for comparison
   (`src/engine/portfolio.py`).
5. **Execution simulation** — the core of "realistic costs": latency
   sampling, spread + square-root market-impact slippage, participation-cap
   partial fills (`src/execution/execution_handler.py`).
6. **Validation** — walk-forward window generator + a runtime look-ahead
   assertion checker (`src/validation/walk_forward.py`).
7. **Reporting** — compute metrics, render matplotlib charts, write a
   single self-contained `index.html` tearsheet (`src/reporting/`).
8. **Wire it together** — `run_backtest.py` as the one entrypoint that
   loads config, runs the pipeline, and writes the report; must exit
   non-zero on failure so CI can detect it.
9. **Tests** — unit-test the execution model, portfolio sizing, and
   performance/validation math in isolation from network calls
   (`tests/`).
10. **Automation** — CI workflow for tests on every push; a separate cron
    workflow for the scheduled data→backtest→report cycle, with commit-back
    and Pages deploy steps, and a failure-alerting step.

---

## Automation Design

**Trigger:** `.github/workflows/scheduled_backtest.yml` runs on a cron
schedule (`30 21 * * 1-5` — 21:30 UTC, weekdays, after US market close),
plus a manual `workflow_dispatch` button for debugging.

**Pipeline steps (all unattended):**
1. Checkout + install deps.
2. `python run_backtest.py` — fetches fresh data (retry/backoff built into
   `YFinanceDataHandler`, falls back to cached parquet if the vendor is
   down), re-runs the full event-driven backtest, recomputes metrics,
   regenerates the tearsheet PNGs + `index.html`.
3. **Commit results back to the repo** (`reports/`, `cache/`) so the
   history of a public GitHub profile shows real, dated, automated commits
   — not a static demo.
4. **Deploy `reports/` to GitHub Pages** so the tearsheet is viewable at a
   stable public URL that's never more than one cron cycle stale.
5. **Failure handling:** if any step fails, a dedicated step runs
   regardless (`if: failure()`), which posts to a Slack webhook (if
   `SLACK_WEBHOOK_URL` secret is set) and opens/updates a GitHub issue
   labeled `backtest-failure` — so a data-vendor outage produces a visible
   alert instead of a silently stale report.

**Secrets management:** all credentials (`POLYGON_API_KEY`,
`ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `SLACK_WEBHOOK_URL`) live in
**GitHub Actions repository secrets**, injected as environment variables at
run time. Nothing sensitive is committed to `config.yaml` or the codebase.

---

## Data Collection Pipeline

`YFinanceDataHandler` (`src/data/data_handler.py`):
- Exponential backoff retry (default 4 attempts) around every vendor call.
- Falls back to the last good local parquet cache if all retries fail, so a
  transient vendor outage degrades to "stale data + logged warning" instead
  of crashing the scheduled job.
- Refreshes the parquet cache on every successful pull.
- Reindexes/forward-fills all symbols onto one shared timeline so
  cross-symbol strategies never see a bar for one symbol that doesn't exist
  for another.

## Data Cleaning & Feature Engineering

Column normalization (lower-cased OHLCV, timezone-aware timestamp index),
forward-fill alignment across symbols, and empty-response validation happen
in the data layer before a single bar reaches the event queue. Feature
engineering is intentionally strategy-owned (see `sma_crossover.py`) — the
engine itself is signal-agnostic.

## Core Event-Driven Engine Design

See "Why event-driven, not vectorized" above and `src/engine/backtest.py`.
Event queue order per bar: `MARKET → SIGNAL → ORDER → FILL`, all consumed
before the next bar's `MarketEvent` is dispatched.

## Execution Cost Modeling

Implemented in `src/execution/execution_handler.py`:
- **Spread cost** — half the configured bid-ask spread (bps), applied
  against the order.
- **Market impact** — square-root model,
  `impact ≈ coefficient × daily_vol_pct × sqrt(participation)`, so cost
  grows sub-linearly but meaningfully with order size relative to bar
  volume (standard Almgren-Chriss-style approximation).
- **Latency-based slippage** — a sampled latency (ms) is attached to every
  fill; the fill price is computed off the bar the order actually lands on
  post-latency, not the decision-time bar.
- **Partial fills** — capped at `max_participation_rate × bar volume`; the
  unfilled remainder is reported via `FillEvent.remaining_quantity` and
  (per config) carried to the next bar.

## Validation Methodology

- **Walk-forward windows** — `generate_walk_forward_windows()` produces
  rolling train/test splits so any real (parameterized) strategy is always
  scored only on data after its tuning window.
- **Look-ahead bias checks** — `LookAheadBiasChecker` is a runtime
  assertion layer: call `.observe(ts)` as each `MarketEvent` is dispatched
  and `.assert_visible(ts)` anywhere a component reads a timestamp, and it
  raises immediately if anything reads ahead of the dispatch clock.
- **Out-of-sample testing** — the same harness supports holding out a final
  slice of the date range entirely for a single train/test split when a
  full walk-forward sweep isn't needed.

## Visualizations & Reporting Components

Auto-generated on every run into `reports/` (`src/reporting/tearsheet.py`):
- `equity_curve.png` — realistic vs. idealized equity curves overlaid.
- `drawdown.png` — running drawdown %.
- `fill_quality.png` — latency and per-fill slippage distributions.
- `slippage_attribution.png` — total $ slippage vs. commission.
- `index.html` — single-page tearsheet embedding all charts + a metrics
  table, timestamped with the generation time.

## Performance Metrics

Sharpe ratio, Sortino ratio, max drawdown, annualized return, turnover
(dollar volume / average equity), and — the key comparison this project is
built around — **realistic P&L vs. idealized (frictionless) P&L**, with the
gap reported as both a dollar figure and a % of idealized P&L
(`src/reporting/performance.py`).

---

## Resume Description

> **Event-Driven Backtesting Engine with Realistic Execution Cost Modeling**
> Built a Python event-driven (not vectorized) backtester simulating
> latency, bid-ask spread, square-root market impact, and participation-cap
> partial fills; quantified execution cost drag by comparing realized P&L
> against an idealized frictionless shadow portfolio. Automated the full
> pipeline — data acquisition (with retry/backoff and caching), backtest
> execution, and tearsheet regeneration — via a GitHub Actions cron
> workflow with commit-back, GitHub Pages publishing, and failure alerting;
> validated with walk-forward testing and a runtime look-ahead-bias
> checker. Repo: `github.com/kaoruixv/event-driven-backtester`.

---

## Potential Upgrades

- **Live paper-trading extension** — swap `SimulatedExecutionHandler` for
  an `AlpacaExecutionHandler` that submits real paper orders; the event
  queue architecture needs no changes, only a new execution handler.
- **Multi-strategy scheduling** — parameterize the cron workflow with a
  matrix of config files so several strategies/universe combinations run
  and publish independent tearsheets on their own schedules.
- **Limit-order book level modeling** — replace the participation-rate
  partial-fill approximation with a synthetic order-book depth model for
  more granular impact estimates.
- **Intraday bars** — swap the data provider to Polygon/Alpaca minute bars
  for a more realistic latency/slippage regime than daily bars allow.
- **Portfolio-level risk constraints** — position limits, sector exposure
  caps, and a simple risk-parity sizing option in `Portfolio`.

---

## Running Locally

```bash
git clone https://github.com/kaoruixv/event-driven-backtester.git
cd event-driven-backtester
pip install -r requirements.txt
python run_backtest.py --config config/config.yaml
open reports/index.html   # or just open the file in a browser
```

## Running Tests

```bash
pytest -v --cov=src --cov-report=term-missing tests/
```

## License

MIT — see `LICENSE`.
