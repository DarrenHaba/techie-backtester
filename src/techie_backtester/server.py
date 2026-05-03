"""Techie Backtester — built on techie-cortex.

Increment 0: bare cortex scaffold. The service boots, exposes the
default cortex endpoints (`/api/health`, `/api/actions`, `/api/logs`,
WebSocket `/ws`), and that's it. No custom actions, no frontend yet.

Inc 1 adds the NautilusTrader dependency, a `health` action that
reports the Nautilus version, and a minimal React frontend.

Plan: see `techie-trader/doc/dev/backtester/` for the full build plan
and decisions doc.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from techie_cortex import create_app

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


async def _on_startup(app: FastAPI) -> None:
    log.info("techie-backtester started")


async def _on_shutdown(app: FastAPI) -> None:
    log.info("techie-backtester stopped")


app = create_app(
    title="Techie Backtester",
    project_root=_PROJECT_ROOT,
    on_startup=_on_startup,
    on_shutdown=_on_shutdown,
)
