# CLAUDE.md — techie-backtester

## Status

**Inc 0 shipped 2026-04-29.** Bare cortex scaffold — the service boots
and exposes the default cortex endpoints. No custom actions, no
frontend, no NautilusTrader dependency yet. Inc 1 (next) adds those.

The build plan and rationale live in **`techie-trader/doc/dev/backtester/`**:
- [README.md](../techie-trader/doc/dev/backtester/README.md) — increments
- [DECISIONS.md](../techie-trader/doc/dev/backtester/DECISIONS.md) — why

Read those before adding code. They're the ground truth for what this
service is, what it isn't, and what order to build it in.

## Pattern

This service follows the canonical
[cortex service pattern](../techie-cortex/doc/patterns/service.md).
Read it for project layout, pyproject conventions, workspace
integration. Don't reinvent.

Service-specific notes live in [`doc/README.md`](doc/README.md).

## What this IS for

- Wrapping NautilusTrader's `BacktestEngine` to run strategies against
  historical bars from `techie-historical-data`.
- Producing JSON results (equity curve, trades, stats) that the
  `techie-trader` notebook renders in cells.
- Providing a UI for kicking off runs, viewing run history, and
  inspecting results outside the notebook.

## What this is NOT for

- **Live trading.** Different repo (`techie-bot`, future). Same
  strategies, different runtime.
- **Research / free-form data exploration.** That's the notebook in
  `techie-trader` against `techie-historical-data` directly.
- **Holding strategy code.** Strategies live in
  `techie-strategies-private` (separate, private repo). This service
  imports them.
- **Owning historical data.** This service reads from
  `techie-historical-data` over HTTP. It does not have its own DuckDB.

## Conventions

- **Poetry** for Python deps (NOT uv — same convention as the rest of
  the ecosystem; uv is only used for `techie-cortex/mcp`).
- **npm** for frontend (added in Inc 1).
- **Python 3.13**, type hints on all functions.
- **Functional React components**, named exports.
- **Tailwind** for styling — no CSS modules.
- **No secondary indexes on DuckDB tables** if/when we add a DuckDB
  store later — see `techie-historical-data/CLAUDE.md` "Sharp edges"
  for the lesson learned.
- **Match the cortex service pattern.** When in doubt, look at how
  `techie-historical-data` does the same thing.

## Tech stack

- **Backend**: Python 3.13, FastAPI, uvicorn, Poetry
- **Engine** (Inc 1+): NautilusTrader (LGPL, Rust core + Python)
- **HTTP client**: httpx (for techie-historical-data calls)
- **Frontend** (Inc 1+): React 19, TypeScript strict, Vite, Tailwind 4

## Ports

| What                 | Port |
|----------------------|------|
| Backend              | 8103 |
| Frontend (Vite dev)  | 5177 |

## Related projects

All under `C:\projects\github\`:

| Repo | Purpose | This service touches it? |
|---|---|---|
| `techie-cortex` | Framework all services build on | Depend on it |
| `techie-historical-data` | Local DuckDB for bars + articles | YES — pulls bars + articles via `get_bars` and articles read API |
| `techie-trader` | Workstation / notebook hub | YES — notebook calls our `run_backtest` action and renders results |
| `techie-strategies-private` | **Private** — strategy implementations | YES — `import` strategies from it |
| `techie-live-data` | Droplet WS multiplexer | NO — only `techie-bot` consumes this |
| `techie-symbols` | Symbol metadata service on droplet | NO directly — get symbols via historical-data |
| `techie-bot` | Future droplet live runtime | NO yet — comes after backtester is solid |

## Sharp edges (will accumulate)

None yet — Inc 0 is too small. Anything learned in Inc 1+ that future
sessions need to know goes here.
