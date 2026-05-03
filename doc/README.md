# techie-backtester — service-specific notes

## Pattern

This service follows the canonical
[cortex service pattern](../../techie-cortex/doc/patterns/service.md).
Project layout, pyproject conventions, workspace integration, and
deployment all live there. Read it first.

## What's here

- Wraps NautilusTrader's `BacktestEngine` for strict event-driven
  backtesting (no lookahead bias).
- Pulls bars + articles from `techie-historical-data` via HTTP.
- Loads strategy classes from `techie-strategies-private` (a private
  Python package) by import.
- Returns results as JSON so the `techie-trader` notebook can render
  them in cells.

## What's NOT here

- Strategies (live in `techie-strategies-private`).
- Historical data (lives in `techie-historical-data`).
- Live trading (will live in `techie-bot`, future).
- Notebook UI (lives in `techie-trader`).

## Build plan

Plan + rationale are in the consumer repo, not here:
- [`techie-trader/doc/dev/backtester/README.md`](../../techie-trader/doc/dev/backtester/README.md)
- [`techie-trader/doc/dev/backtester/DECISIONS.md`](../../techie-trader/doc/dev/backtester/DECISIONS.md)

Each increment is shipped, verified, and committed before the next
starts. Same discipline as `techie-historical-data`.

## Status

**Inc 0 (this commit):** bare cortex scaffold. Service boots, default
endpoints work, nothing custom yet.
