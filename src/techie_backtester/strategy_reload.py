"""Hot-reload strategies from techie-strategies-private without
restarting the backtester service.

The notebook flow we want to support:
  1. User writes a new strategy file from a notebook cell.
  2. Cell calls reload_strategies (this module's entry point).
  3. Cell calls run_backtest with the new strategy name.

Python's import system caches modules. To pick up a NEW file, we have
to:
  - Invalidate the import cache (importlib.invalidate_caches)
  - Reload the strategies *package* itself (so iter_modules sees new
    files)
  - Reload each existing module (so EDITS to existing strategies take
    effect)
  - Reset the registry's discovery cache so the next list_strategies
    call rediscovers from scratch.

This is best-effort. Renamed/deleted classes can leave stale entries
in sys.modules — the registry filters by `obj.__module__ == module
name` so stale top-level names don't pollute the registry, but if a
file imports another at module level and that other file goes away,
you'll see a clear ImportError.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from typing import Any

log = logging.getLogger(__name__)


def reload_strategies() -> dict[str, Any]:
    """Hot-reload everything under techie_strategies_private.strategies.
    Returns a summary dict for logging / API responses."""
    out: dict[str, Any] = {
        "ok": True,
        "reloaded": [],
        "newly_imported": [],
        "errors": [],
    }

    importlib.invalidate_caches()

    # Reload the strategies subpackage so iter_modules sees newly-added
    # files. If the package isn't imported yet, importing it counts.
    try:
        import techie_strategies_private.strategies as strategies_pkg
        strategies_pkg = importlib.reload(strategies_pkg)
    except Exception as e:  # noqa: BLE001
        msg = f"failed to reload strategies package: {type(e).__name__}: {e}"
        log.warning(msg)
        out["ok"] = False
        out["errors"].append(msg)
        return out

    # Walk the (now-fresh) package and reload each submodule.
    for _finder, modname, _ispkg in pkgutil.iter_modules(strategies_pkg.__path__):
        full = f"{strategies_pkg.__name__}.{modname}"
        if full in sys.modules:
            try:
                importlib.reload(sys.modules[full])
                out["reloaded"].append(full)
            except Exception as e:  # noqa: BLE001
                msg = f"reload {full}: {type(e).__name__}: {e}"
                log.warning(msg)
                out["errors"].append(msg)
        else:
            try:
                importlib.import_module(full)
                out["newly_imported"].append(full)
            except Exception as e:  # noqa: BLE001
                msg = f"import {full}: {type(e).__name__}: {e}"
                log.warning(msg)
                out["errors"].append(msg)

    # Force the registry to rediscover on next call.
    try:
        from techie_strategies_private.registry import (
            list_strategies,
            reset_registry,
        )
        reset_registry()
        names = [s.name for s in list_strategies()]
        out["strategies"] = names
    except Exception as e:  # noqa: BLE001
        msg = f"registry refresh failed: {type(e).__name__}: {e}"
        log.warning(msg)
        out["ok"] = False
        out["errors"].append(msg)

    if out["errors"]:
        out["ok"] = False
    return out
