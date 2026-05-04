"""Techie Backtester — built on techie-cortex.

Strategies live in techie-strategies-private (separate, private repo)
and are auto-discovered by the registry. This service:
  - lists available strategies (`list_strategies` action)
  - runs any registered strategy against historical bars
    (`run_backtest` action)
  - reports health + Nautilus version (`health` action)

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
from .runner import list_available_strategies, run_backtest

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
    """Service health + dependency versions + strategy count."""
    try:
        strat_count = len(list_available_strategies())
    except Exception as e:  # noqa: BLE001
        strat_count = -1
        log.warning("list_strategies failed in health: %s", e)
    return {
        "ok": True,
        "service": "techie-backtester",
        "service_version": __version__,
        "python_version": platform.python_version(),
        "nautilus_trader_version": _safe_version("nautilus_trader"),
        "techie_cortex_version": _safe_version("techie-cortex"),
        "techie_strategies_private_version": _safe_version("techie-strategies-private"),
        "httpx_version": _safe_version("httpx"),
        "registered_strategies": strat_count,
    }


async def _list_strategies() -> list[dict[str, Any]]:
    """Names + per-strategy param schemas. Driven by the registry in
    techie-strategies-private — drop a new .py file there, restart this
    service, and it shows up here."""
    return list_available_strategies()


async def _run_backtest(
    symbol: str = "AAPL",
    start: str = "2024-01-01",
    end: str = "2024-12-31",
    timeframe: str = "1d",
    starting_cash: float = 100_000.0,
    strategy: str = "BuyAndHold",
    params: dict[str, Any] | None = None,
    # Backwards-compat: previous version had `trade_size` as a top-level
    # param (always BuyAndHold). Keep accepting it; if `params` is empty
    # AND trade_size was supplied, fold it into params for BuyAndHold.
    trade_size: float | None = None,
) -> dict[str, Any]:
    """Run a backtest end-to-end.

    Looks up `strategy` in techie-strategies-private's registry, builds
    the strategy with `params` merged with the runtime instrument_id +
    bar_type, runs Nautilus, returns equity curve + trades + stats.

    Daily timeframe only for v0. Minute support is one BarType change
    in runner.py.
    """
    sym = symbol.upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol is required"}
    if timeframe != "1d":
        return {
            "ok": False,
            "error": (
                f"timeframe {timeframe!r} not supported yet — only '1d' for now."
            ),
        }

    # Backwards compat: old callers passed trade_size as a top-level arg.
    merged_params: dict[str, Any] = dict(params or {})
    if trade_size is not None and "trade_size" not in merged_params:
        merged_params["trade_size"] = trade_size

    log.info(
        "run_backtest %s %s..%s tf=%s strategy=%s params=%s cash=$%s",
        sym, start, end, timeframe, strategy, merged_params, starting_cash,
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
        result = await run_backtest(
            bars_raw=bars,
            symbol=sym,
            strategy_name=strategy,
            params=merged_params,
            starting_cash=starting_cash,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("backtest engine raised")
        return {
            "ok": False,
            "error": f"engine failed: {type(e).__name__}: {e}",
        }

    # Stamp the run with what was requested.
    result["request"] = {
        "symbol": sym,
        "start": start,
        "end": end,
        "timeframe": timeframe,
        "starting_cash": starting_cash,
        "strategy": strategy,
        "params": merged_params,
    }
    return result


def _register_actions() -> None:
    action_registry.register("health", _health)
    action_registry.register("list_strategies", _list_strategies)
    action_registry.register("run_backtest", _run_backtest)


# --- App -------------------------------------------------------------------


async def _on_startup(app: FastAPI) -> None:
    nautilus_v = _safe_version("nautilus_trader")
    try:
        strats = list_available_strategies()
        names = [s["name"] for s in strats]
        log.info(
            "techie-backtester started — nautilus=%s python=%s strategies=%s",
            nautilus_v, platform.python_version(), names or "(none)",
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "techie-backtester started — nautilus=%s python=%s "
            "BUT registry failed: %s",
            nautilus_v, platform.python_version(), e,
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
