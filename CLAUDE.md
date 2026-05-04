# CLAUDE.md — techie-backtester

## Status

Working. Strategy registry + hot-reload + mark-to-market equity curve
all in place. Three strategies registered (BuyAndHold, SmaCrossover,
MomentumBreakout). Notebook-driven workflow proven end-to-end.

The build plan lives in
[`techie-trader/doc/dev/backtester/`](../techie-trader/doc/dev/backtester/):
- [README.md](../techie-trader/doc/dev/backtester/README.md) — increments
- [DECISIONS.md](../techie-trader/doc/dev/backtester/DECISIONS.md) — rationale

Read both before changing architecture.

## Pattern

This service follows the canonical
[cortex service pattern](../techie-cortex/doc/patterns/service.md).
Don't reinvent. Service-specific notes live in
[`doc/README.md`](doc/README.md).

## What goes here vs where

| Concern | Lives in |
|---|---|
| BacktestEngine wrapper, fill simulation, equity curve, drawdown | `src/techie_backtester/runner.py` |
| FastAPI app + cortex actions (`run_backtest`, `list_strategies`, `reload_strategies`, `health`) | `src/techie_backtester/server.py` |
| HTTP client for techie-historical-data | `src/techie_backtester/historical_client.py` |
| Strategy hot-reload | `src/techie_backtester/strategy_reload.py` |
| **Strategy classes themselves** | `techie-strategies-private` (separate, private repo) |
| Strategy registry / discovery | `techie-strategies-private/src/techie_strategies_private/registry.py` |
| Standalone Run-Backtest UI | `frontend/src/pages/Home.tsx` |
| Notebook integration (the primary consumer) | `techie-trader` |

## Conventions

- **Poetry** for Python deps (NOT uv — uv is only used for
  `techie-cortex/mcp`).
- **npm** for frontend.
- **Python 3.13**, type hints on all functions.
- **Functional React components**, named exports.
- **Tailwind** for styling — no CSS modules.
- Match the cortex service pattern. When in doubt, look at how
  `techie-historical-data` does the same thing.

## Tech stack

- **Backend**: Python 3.13, FastAPI, uvicorn, Poetry
- **Engine**: NautilusTrader 1.226 (LGPL, Rust core + Python bindings)
- **Strategies**: `techie-strategies-private` (editable path dep)
- **HTTP client**: httpx (for techie-historical-data calls)
- **Frontend**: React 19, TypeScript strict, Vite, Tailwind 4

## Ports

| What                 | Port |
|----------------------|------|
| Backend              | 8103 |
| Frontend (Vite dev)  | 5177 |

## Related projects

All under `C:\projects\github\`:

| Repo | Purpose | This service touches it? |
|---|---|---|
| `techie-cortex` | Framework all services build on | depend on it |
| `techie-historical-data` | Local DuckDB for bars + articles | YES — pulls bars via `get_bars` HTTP action |
| `techie-strategies-private` | **Private** — strategy implementations | YES — `import` strategies via the registry |
| `techie-trader` | Workstation / notebook hub | YES — notebook calls our actions, renders results in cells |
| `techie-live-data` | Droplet WS multiplexer | NO — only `techie-bot` will consume this |
| `techie-symbols` | Symbol metadata service on droplet | NO directly |
| `techie-bot` | Future droplet live runtime | NO yet — comes after backtester is solid |

## Sharp edges (the stuff you'll forget)

- **Nautilus's Rust FFI logger initializes once per Python process.**
  Without `LoggingConfig(bypass_logging=True)` the second
  `BacktestEngine()` call in the same process panics with "attempted
  to set a logger after the logging system was already initialized"
  and crashes the worker thread. Bypass is on by default in
  `runner.py`. Don't disable it.
- **Money strings.** Nautilus formats `realized_pnl` as `"6710.00
  USD"`. The `_safe_float` helper strips the currency suffix.
- **Equity curve is OURS, not Nautilus's.** Nautilus's
  `account_report` is per-cash-event (3 points for buy-and-hold).
  `_compute_equity_curve` walks bars chronologically + applies fills
  + marks position to market — produces one row per bar.
- **`max_drawdown_pct` is in percent units (5.0 = 5%).** It's
  computed from our equity curve, not from Nautilus's
  `Max Drawdown (Returns)` stat (which uses Nautilus's broken series
  and reports 0.0 for buy-and-hold).
- **Daily timeframe only.** `runner.py` hardcodes
  `BarType.from_str(f"{symbol}.XNAS-1-DAY-LAST-EXTERNAL")`. Minute
  support means parameterizing this on timeframe.
- **Strategy hot-reload uses `importlib.invalidate_caches()` +
  `importlib.reload(strategies_pkg)`.** New `.py` files require BOTH
  — `iter_modules` only sees them after the package itself is
  reloaded.
- **Windows strategy file writes need `encoding="utf-8"`.** Default
  cp1252 encodes em-dashes as 0x97 which Python's source loader
  rejects on import.
- **`BacktestEngine.run()` is sync + CPU-bound.** We wrap with
  `asyncio.to_thread` so the FastAPI event loop doesn't block. Don't
  call it directly from an async handler.
- **`add_venue` → `add_instrument` → `add_data` order matters.**
  Nautilus enforces it; out-of-order calls raise `InvalidConfiguration`
  or "instrument not found in cache".
- **Nautilus's `Bar` enforces `low <= open,close <= high`** in its
  constructor. `_to_nautilus_bar` validates first and returns None
  for bad rows so one corrupt bar doesn't abort the whole run.

## Authoring strategies

DON'T put strategies in this repo. They live in
`techie-strategies-private`. See its README for the convention
(Strategy + StrategyConfig pair, system fields, naming).

The notebook flow:
```python
# In a techie-trader notebook cell:
Path("../techie-strategies-private/src/techie_strategies_private/strategies/my.py").write_text(
    "...", encoding="utf-8"
)
await reload_strategies()
await run_backtest(strategy="My", params={...}, ...)
```

## Tests

`pytest` runs the smoke tests (module imports, server.py imports
cleanly). No integration tests against a live historical-data
instance yet.
