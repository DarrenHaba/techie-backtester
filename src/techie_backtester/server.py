"""Techie Backtester — built on techie-cortex.

Increment 1: NautilusTrader dependency wired in. The `health` action
reports the Nautilus version so the UI / MCP / curl can confirm the
engine is importable. No data adapter and no actual backtesting yet —
those land in Inc 2 (historical data adapter) and Inc 3 (first
end-to-end backtest with a toy strategy).

Plan: see `techie-trader/doc/dev/backtester/` for the full build plan
and decisions doc.
"""

from __future__ import annotations

import logging
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from techie_cortex import create_app
from techie_cortex.actions import action_registry

from . import __version__

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

load_dotenv(_PROJECT_ROOT / ".env")


# --- Actions ---------------------------------------------------------------


def _safe_version(pkg: str) -> str | None:
    """Return the installed package version, or None if not installed."""
    try:
        return version(pkg)
    except PackageNotFoundError:
        return None


async def _health() -> dict:
    """Service health + dependency versions.

    Confirms the NautilusTrader engine is importable. The MCP and the
    UI both poll this; if `nautilus_trader_version` is None the install
    is broken and Inc 2+ work won't run.
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


def _register_actions() -> None:
    action_registry.register("health", _health)


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
