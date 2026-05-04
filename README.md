# techie-backtester

**Status:** working — strict event-driven backtester with strategy
hot-reload. Three strategies registered out-of-the-box (BuyAndHold,
SmaCrossover, MomentumBreakout). Notebook-driven workflow proven
end-to-end (write a strategy in a cell → reload → backtest → results
in the cell, no service restart).

Local cortex service that wraps
[NautilusTrader](https://github.com/nautechsystems/nautilus_trader) as
the engine. Strategies live in
[`techie-strategies-private`](https://github.com/DarrenHaba/techie-strategies-private)
and are auto-discovered by the registry — drop a `.py` file in there,
hot-reload, and the strategy is callable.

## What this IS for

- Running strategies against historical bars from
  `techie-historical-data` (HTTP) with strict no-lookahead.
- Returning equity curves, trades, fills, and stats as JSON for
  downstream rendering (the `techie-trader` notebook is the primary
  consumer).
- Hot-reloading strategy code without restarting the service —
  notebook-driven dev loop.

## What this is NOT for

- Live trading. That's `techie-bot` (future, on the droplet) — same
  `Strategy` classes from `techie-strategies-private`, different
  engine (Nautilus's `TradingNode` vs `BacktestEngine`).
- Holding strategy code. Strategies live in `techie-strategies-private`.
- Owning historical data. This service reads from
  `techie-historical-data` over HTTP.
- Research / vectorized data exploration. That's the notebook in
  `techie-trader`.

## Architecture

```
techie-historical-data  (8101) ─── HTTP get_bars ──┐
                                                    │
techie-strategies-private  (private pkg) ─ import ─┤
                                                    ▼
                                  techie-backtester  (8103)
                                  - registry → list_strategies
                                  - run_backtest(strategy, params)
                                  - reload_strategies (hot-reload)
                                  - own React UI on 5177
                                                    │
                                                    ▼
                                  techie-trader  (8766 / 5175)
                                  notebook helpers wrap the API
```

## Actions

| Action | Args | Returns |
|---|---|---|
| `health` | — | service + nautilus + cortex versions, registered_strategies count |
| `list_strategies` | — | per-strategy `{name, module, config_class, params_schema, docstring}` |
| `reload_strategies` | — | `{ok, reloaded, newly_imported, strategies, errors}` |
| `run_backtest` | `symbol`, `start`, `end`, `strategy`, `params`, `starting_cash`, `timeframe` | `{ok, stats, equity_curve, trades, fills, request, params}` |

Try them at `http://127.0.0.1:8103/docs` (FastAPI Swagger UI).

## Result shape

`run_backtest` returns:
```python
{
  "ok": True,
  "symbol": "AAPL",
  "strategy": "BuyAndHold",
  "params": {"trade_size": "100"},
  "stats": {
    "starting_equity": 100000.0,
    "ending_equity":   106710.0,
    "peak_equity":     107388.0,
    "trough_equity":    97978.0,
    "total_return_pct":  6.71,
    "realized_pnl":   6710.0,
    "sharpe_ratio":   0.833,
    "max_drawdown_pct": 2.94,    # already in percent units (5.0 = 5%)
    "trade_count":      1,
    "bar_count":      251,
    "bars_dropped_invalid": 0,
  },
  "equity_curve": [             # one row per bar, mark-to-market
    {"timestamp": "2024-01-02T05:00:00+00:00", "equity": 100000.0,
     "cash": 81627.0, "position_qty": 100.0, "position_value": 18373.0,
     "close": 183.73},
    ...
  ],
  "trades": [...],              # Nautilus positions report
  "fills":  [...],              # Nautilus order fills report
  "request": {...},             # echo of what was asked
}
```

The equity curve is computed by walking bars chronologically and
marking the position to market at each close — NOT pulled from
Nautilus's `account_report` (which only emits a row per cash event
and produces a useless 3-point sawtooth for buy-and-hold).

## Authoring a new strategy

The fast path — from a `techie-trader` notebook cell:

```python
from pathlib import Path
Path("../techie-strategies-private/src/techie_strategies_private/strategies/my_strategy.py").write_text(
    """
    # Strategy + StrategyConfig pair following the convention
    """,
    encoding="utf-8",   # important on Windows
)
await reload_strategies()
result = await run_backtest(symbol="AAPL", start="2024-01-01", end="2024-12-31",
                            strategy="MyStrategy", params={...})
```

Or write the file directly in the strategies repo and call
`reload_strategies` (or restart the backtester).

See [`techie-strategies-private`](https://github.com/DarrenHaba/techie-strategies-private)
for the convention (Strategy + StrategyConfig pair, naming, system
fields).

## Tech stack

- **Python 3.13**, **Poetry**
- **NautilusTrader** 1.226 — Rust core, Python bindings, LGPL-3.0
- **FastAPI** + **techie-cortex** for the service
- **httpx** for HTTP calls to `techie-historical-data`
- **React 19**, **Vite 8**, **Tailwind 4** for the standalone UI

## Running

First-time setup:

```
poetry install
cd frontend && npm install && cd ..
```

Then:

```
start.bat
# Backend: http://127.0.0.1:8103
# Frontend: http://127.0.0.1:5177
# Health:  http://127.0.0.1:8103/api/health
# Docs:    http://127.0.0.1:8103/docs
```

The standalone frontend (5177) is a single-strategy form for
one-off runs. The primary interface is the `techie-trader` notebook
on http://127.0.0.1:5175/, which uses the same actions to drive
parameter sweeps and ad-hoc analysis.

## Ports

| Service                 | Port |
|-------------------------|------|
| techie-backtester (be)  | 8103 |
| techie-backtester (fe)  | 5177 |

(Reserved against the existing ecosystem: live-data 8100,
historical-data 8101 / 5176, symbols 8102, trader 8766 / 5175.)

## Sharp edges

- **Nautilus's Rust FFI logger can only initialize once per Python
  process.** Without `LoggingConfig(bypass_logging=True)` the second
  `BacktestEngine()` call panics ("attempted to set a logger after the
  logging system was already initialized") and crashes the worker.
  Bypass is on by default.
- **Money is rendered as strings.** Nautilus's positions report has
  `realized_pnl="6710.00 USD"`. `_safe_float` strips the currency
  suffix.
- **Equity curve is OURS, not Nautilus's.** Nautilus's `account_report`
  only emits rows on cash events (initial deposit + per fill). For a
  buy-and-hold over 251 bars that's 3 points. We compute equity per
  bar by marking the position to market.
- **Daily timeframe only for v0.** Minute support is a one-line
  `BarType` change in `runner.py` once we want to test it.
- **strategies-private is editable path-dep.** Edits to that repo
  show up here without `poetry install`. Hot-reload picks up new
  files via `importlib.invalidate_caches() + reload`.
- **Windows strategy file writes need `encoding="utf-8"`.** Default
  cp1252 encodes em-dashes as 0x97 which Python's source loader
  rejects. The notebook cell that writes a strategy passes
  `encoding="utf-8"` explicitly.

## Plan + history

The original build plan is in
[`techie-trader/doc/dev/backtester/README.md`](https://github.com/DarrenHaba/techie-trader/blob/refactor/use-cortex-package/doc/dev/backtester/README.md).
We hit Inc 0 → Inc 7 essentially in compressed form, then went past
the plan to add the strategy registry + hot-reload + per-bar equity
curve. Detailed rationale lives in
[DECISIONS.md](https://github.com/DarrenHaba/techie-trader/blob/refactor/use-cortex-package/doc/dev/backtester/DECISIONS.md).
