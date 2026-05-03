# techie-backtester

**Status:** Inc 0 — bare cortex scaffold. Service boots; no custom
actions or frontend yet.

Local cortex service that wraps
[NautilusTrader](https://github.com/nautechsystems/nautilus_trader) to
provide a **strict, event-driven backtester** for the Techie trading
ecosystem. Strategies are loaded from the separate
`techie-strategies-private` package; market data comes from
`techie-historical-data` via HTTP.

This service exists to backtest strategies without lookahead bias.
Research / vectorized exploration happens in the `techie-trader`
notebook against the same historical data; this service is the strict
event-driven path that produces results you can trust before going
live.

## The full plan

The build plan, increments, decisions, and rationale all live in
`techie-trader/doc/dev/backtester/`:

- [README.md](https://github.com/DarrenHaba/techie-trader/blob/refactor/use-cortex-package/doc/dev/backtester/README.md)
  — what to build, increment by increment
- [DECISIONS.md](https://github.com/DarrenHaba/techie-trader/blob/refactor/use-cortex-package/doc/dev/backtester/DECISIONS.md)
  — why NautilusTrader, why a separate service, etc.

## Pattern

This service follows the canonical
[cortex service pattern](https://github.com/DarrenHaba/techie-cortex/blob/main/doc/patterns/service.md).
For project layout, pyproject conventions, and workspace integration,
read the pattern doc — don't reinvent. Service-specific notes live in
[`doc/README.md`](doc/README.md).

## Tech stack

- **Python 3.13**, **Poetry** for deps
- **FastAPI** + **techie-cortex** for the service
- **NautilusTrader** for the engine (added in Inc 1)
- **React 19** + **Vite** + **Tailwind 4** for the frontend (added in
  Inc 1)
- **httpx** for HTTP calls to `techie-historical-data`

## Running

First-time setup:

```
poetry install
```

Then:

```
start.bat
# Backend: http://127.0.0.1:8103
# Health:  http://127.0.0.1:8103/api/health
# Docs:    http://127.0.0.1:8103/docs
```

## Ports

| Service                 | Port |
|-------------------------|------|
| techie-backtester (be)  | 8103 |
| techie-backtester (fe)  | 5177 |

(Reserved against the existing ecosystem: live-data 8100,
historical-data 8101 / 5176, symbols 8102, trader 8766 / 5175.)

## What this is NOT for

- **Live trading.** That's `techie-bot` (future, on the droplet) — it
  will use the same `Strategy` classes from `techie-strategies-private`
  but run them via Nautilus's `TradingNode` against live data.
- **Research / free-form exploration.** That's the notebook in
  `techie-trader`, which can read directly from `techie-historical-data`
  and use vectorized DuckDB / Polars without going through this
  service.
- **Strategy storage.** Strategies live in `techie-strategies-private`,
  not in this repo. This repo is the engine + adapters only.
