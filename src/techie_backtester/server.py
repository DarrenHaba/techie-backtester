"""Techie Backtester — built on techie-cortex.

Compressed Inc 2 + 3: real backtest end-to-end.

`run_backtest` action:
  1. Pulls daily bars from techie-historical-data via HTTP.
  2. Feeds them into a NautilusTrader BacktestEngine.
  3. Runs a built-in `BuyAndHold` toy strategy.
  4. Returns equity curve + trades + stats as JSON.

The UI has a form for symbol / start / end / starting cash / trade
size, runs it, and renders the results inline. Strategies will move
to techie-strategies-private later; BuyAndHold lives in `runner.py`
for now as the smoke-test case.

Plan: techie-trader/doc/dev/backtester/.
"""

from __future__ import annotations

import logging
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from techie_cortex import create_app
from techie_cortex.actions import action_registry

from . import __version__
from .historical_client import HistoricalDataError, get_bars
from .runner import run_buy_and_hold

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

load_dotenv(_PROJECT_ROOT / ".env")


# --- Actions ---------------------------------------------------------------


def _safe_version(pkg: str) -> str | None:
    try:
        return version(pkg)
    except PackageNotFoundError:
        return None


async def _health() -> dict:
    """Service health + dependency versions.

    Confirms NautilusTrader is importable. The MCP and the UI both
    poll this; if `nautilus_trader_version` is None the install is
    broken.
    """
    return {
        "ok": True,
        "service": "techie-backtester",
        "service_version": __version__,
        "python_version": platform.python_version(),
        "nautilus_trader_version": _safe_version("nautilus_trader"),
        "techie_cortex_version": _safe_version("techie-cortex"),
        "httpx_version": _safe_version("httpx"),
    }


async def _run_backtest(
    symbol: str = "AAPL",
    start: str = "2024-01-01",
    end: str = "2024-12-31",
    timeframe: str = "1d",
    starting_cash: float = 100_000.0,
    trade_size: float = 100.0,
) -> dict[str, Any]:
    """Run a buy-and-hold backtest end-to-end.

    Pulls bars from techie-historical-data over HTTP, feeds them into
    a Nautilus BacktestEngine with the built-in BuyAndHold strategy,
    and returns equity curve + trades + stats as JSON ready to render.

    Daily timeframe only for v0. Minute support comes when the BarType
    string is parameterised on timeframe (one-line change in runner.py
    once we want to test it).
    """
    sym = symbol.upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol is required"}
    if timeframe != "1d":
        return {
            "ok": False,
            "error": (
                f"timeframe {timeframe!r} not supported yet — only '1d' for now. "
                "Minute support comes when runner.py learns to parameterise BarType."
            ),
        }

    log.info(
        "run_backtest %s %s..%s tf=%s cash=$%s size=%s",
        sym,
        start,
        end,
        timeframe,
        starting_cash,
        trade_size,
    )

    # 1. Pull bars.
    try:
        bars = await get_bars(symbol=sym, start=start, end=end, timeframe=timeframe)
    except HistoricalDataError as e:
        return {
            "ok": False,
            "error": str(e),
            "hint": (
                "Is techie-historical-data running on http://127.0.0.1:8101? "
                "Set TECHIE_HISTORICAL_URL env var to override."
            ),
        }

    if not bars:
        return {
            "ok": False,
            "error": (
                f"no bars returned for {sym} {start}..{end} on timeframe {timeframe}. "
                "Check coverage in the historical-data UI."
            ),
        }

    # 2. Run engine.
    try:
        result = await run_buy_and_hold(
            bars_raw=bars,
            symbol=sym,
            starting_cash=starting_cash,
            trade_size=trade_size,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("backtest engine raised")
        return {
            "ok": False,
            "error": f"engine failed: {type(e).__name__}: {e}",
        }

    # Stamp the run with what was requested so the UI can echo it back.
    result["request"] = {
        "symbol": sym,
        "start": start,
        "end": end,
        "timeframe": timeframe,
        "starting_cash": starting_cash,
        "trade_size": trade_size,
        "strategy": "BuyAndHold",
    }
    return result


def _register_actions() -> None:
    action_registry.register("health", _health)
    action_registry.register("run_backtest", _run_backtest)


# --- App -------------------------------------------------------------------


async def _on_startup(app: FastAPI) -> None:
    nautilus_v = _safe_version("nautilus_trader")
    if nautilus_v is None:
        log.warning(
            "techie-backtester started — nautilus_trader is NOT installed. "
            "Run `poetry install` to fix."
        )
    else:
        log.info(
            "techie-backtester started — nautilus_trader=%s python=%s",
            nautilus_v,
            platform.python_version(),
        )


async def _on_shutdown(app: FastAPI) -> None:
    log.info("techie-backtester stopped")


app = create_app(
    title="Techie Backtester",
    project_root=_PROJECT_ROOT,
    register_actions=_register_actions,
    on_startup=_on_startup,
    on_shutdown=_on_shutdown,
)
