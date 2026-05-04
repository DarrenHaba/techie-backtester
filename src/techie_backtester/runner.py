"""Nautilus BacktestEngine wrapper.

Looks up a Strategy class from techie-strategies-private's registry by
name, instantiates it with user-supplied params plus the runtime-injected
instrument_id + bar_type, runs it through Nautilus's BacktestEngine,
and returns a JSON-friendly result.

The strategy code itself lives in techie-strategies-private. This file
is the thin wrapper that turns a (strategy_name, params, bars) request
into a backtest run + a result dict.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.core.nautilus_pyo3 import MaxDrawdown, SharpeRatio
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import (
    AccountType,
    OmsType,
)
from nautilus_trader.model.identifiers import (
    InstrumentId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity

# Strategy registry — single source of truth for available strategies.
from techie_strategies_private.registry import (
    StrategyInfo,
    get_strategy,
    list_strategies,
)

log = logging.getLogger(__name__)


# --- Bar conversion --------------------------------------------------------


def _to_nautilus_bar(
    raw: dict[str, Any],
    bar_type: BarType,
    price_precision: int = 2,
) -> Bar | None:
    """Convert one raw OHLCV dict to a Nautilus Bar.

    Returns None for malformed bars (bad OHLC ordering, zero volume,
    missing fields) — Nautilus enforces low<=open,close<=high in the
    Bar constructor and would raise. Filtering here keeps one bad row
    from killing a whole backtest, mirroring the bulletproofing in
    techie-historical-data's bulk insert.
    """
    try:
        o = float(raw["open"])
        h = float(raw["high"])
        lo = float(raw["low"])
        c = float(raw["close"])
        v = int(raw["volume"])
    except (KeyError, TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if not (lo <= o <= h and lo <= c <= h):
        return None
    ts = dt_to_unix_nanos(pd.Timestamp(raw["datetime_utc"], tz="UTC"))
    return Bar(
        bar_type=bar_type,
        open=Price(o, price_precision),
        high=Price(h, price_precision),
        low=Price(lo, price_precision),
        close=Price(c, price_precision),
        volume=Quantity(v, 0),
        ts_event=ts,
        ts_init=ts,
    )


# --- Equity curve + drawdown (mark-to-market, NOT Nautilus's broken
#     account_report which only emits rows on cash events) ----------------


def _compute_equity_curve(
    bars_raw: list[dict[str, Any]],
    fills_records: list[dict[str, Any]],
    starting_cash: float,
) -> list[dict[str, Any]]:
    """Mark-to-market equity at each bar's close."""
    parsed_fills: list[dict[str, Any]] = []
    for f in fills_records:
        ts_raw = f.get("ts_last") or f.get("ts_init")
        if ts_raw is None:
            continue
        try:
            ts_dt = pd.Timestamp(ts_raw)
            if ts_dt.tz is None:
                ts_dt = ts_dt.tz_localize("UTC")
            else:
                ts_dt = ts_dt.tz_convert("UTC")
        except Exception:
            continue
        side = str(f.get("side", "")).upper()
        try:
            qty = float(f.get("filled_qty") or f.get("quantity") or 0)
            px = float(f.get("avg_px") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or px <= 0:
            continue
        parsed_fills.append({"ts": ts_dt, "side": side, "qty": qty, "px": px})
    parsed_fills.sort(key=lambda x: x["ts"])

    cash = float(starting_cash)
    qty = 0.0
    fill_idx = 0
    curve: list[dict[str, Any]] = []

    for raw in bars_raw:
        try:
            bar_ts = pd.Timestamp(raw["datetime_utc"])
            if bar_ts.tz is None:
                bar_ts = bar_ts.tz_localize("UTC")
            close = float(raw["close"])
        except (KeyError, TypeError, ValueError):
            continue

        while fill_idx < len(parsed_fills) and parsed_fills[fill_idx]["ts"] <= bar_ts:
            f = parsed_fills[fill_idx]
            if f["side"] == "BUY":
                cash -= f["qty"] * f["px"]
                qty += f["qty"]
            elif f["side"] == "SELL":
                cash += f["qty"] * f["px"]
                qty -= f["qty"]
            fill_idx += 1

        equity = cash + qty * close
        curve.append({
            "timestamp": bar_ts.isoformat(),
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "position_qty": qty,
            "position_value": round(qty * close, 2),
            "close": close,
        })

    return curve


def _max_drawdown_pct(curve: list[dict[str, Any]]) -> float | None:
    """Max peak-to-trough drawdown as a positive percent."""
    if len(curve) < 2:
        return None
    peak = curve[0]["equity"]
    max_dd = 0.0
    for p in curve:
        eq = p["equity"]
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return round(max_dd * 100.0, 4)


# --- Helpers ---------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    """Best-effort cast; strips Money strings like '6710.00 USD'."""
    if v is None:
        return None
    if isinstance(v, str):
        cleaned = v.split()[0] if v.split() else v
        try:
            f = float(cleaned)
        except (TypeError, ValueError):
            return None
    else:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
    if f != f:
        return None
    return f


def _df_to_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    out = df.reset_index().to_dict(orient="records")
    for row in out:
        for k, v in list(row.items()):
            if isinstance(v, pd.Timestamp):
                row[k] = v.isoformat()
            elif hasattr(v, "isoformat") and not isinstance(v, str):
                try:
                    row[k] = v.isoformat()
                except Exception:
                    row[k] = str(v)
            elif isinstance(v, Decimal):
                row[k] = float(v)
    return out


# --- Public API ------------------------------------------------------------


def list_available_strategies() -> list[dict[str, Any]]:
    """Names + param schemas for every strategy in the registry."""
    return [s.to_dict() for s in list_strategies()]


def _coerce_param(value: Any, python_type: str) -> Any:
    """Coerce a JSON-supplied param value to the right Python type for
    the strategy's StrategyConfig. msgspec is strict — it won't accept
    a JSON int where Decimal is required."""
    if value is None:
        return None
    pt = python_type.lower()
    try:
        if "decimal" in pt:
            return Decimal(str(value))
        if "int" in pt:
            return int(value)
        if "float" in pt or "number" in pt:
            return float(value)
        if "bool" in pt:
            return bool(value)
    except (TypeError, ValueError):
        pass
    return value


def _build_strategy(
    info: StrategyInfo,
    user_params: dict[str, Any],
    instrument_id: InstrumentId,
    bar_type: BarType,
):
    """Instantiate Strategy + Config from user-supplied params + the
    runtime-injected instrument_id and bar_type."""
    coerced: dict[str, Any] = {}
    for fname, fmeta in info.params_schema.items():
        if fname in user_params:
            coerced[fname] = _coerce_param(
                user_params[fname], fmeta.get("python_type", "")
            )
    config = info.config_class(
        instrument_id=instrument_id,
        bar_type=bar_type,
        **coerced,
    )
    return info.strategy_class(config), config


def _run_engine_sync(
    bars_raw: list[dict[str, Any]],
    symbol: str,
    starting_cash: float,
    strategy_name: str,
    user_params: dict[str, Any],
) -> dict[str, Any]:
    """Synchronous Nautilus run. Wrapped in to_thread by the async caller."""
    if not bars_raw:
        return {
            "ok": False,
            "error": "no bars provided — historical-data returned an empty range",
            "stats": {},
            "equity_curve": [],
            "trades": [],
            "fills": [],
        }

    # Look up the strategy.
    try:
        info = get_strategy(strategy_name)
    except KeyError as e:
        return {"ok": False, "error": str(e), "stats": {}, "equity_curve": [], "trades": [], "fills": []}

    venue = Venue("XNAS")
    instrument_id = InstrumentId(symbol=Symbol(symbol), venue=venue)
    instrument = Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol(symbol),
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        lot_size=Quantity.from_int(1),
        ts_event=0,
        ts_init=0,
    )
    bar_type = BarType.from_str(f"{symbol}.XNAS-1-DAY-LAST-EXTERNAL")

    # Convert + filter bars before touching the engine.
    nautilus_bars: list[Bar] = []
    dropped = 0
    for raw in bars_raw:
        b = _to_nautilus_bar(raw, bar_type)
        if b is None:
            dropped += 1
        else:
            nautilus_bars.append(b)
    if not nautilus_bars:
        return {
            "ok": False,
            "error": (
                f"all {len(bars_raw)} bars rejected by validation "
                "(bad OHLC ordering, missing fields, or zero volume)"
            ),
            "stats": {},
            "equity_curve": [],
            "trades": [],
            "fills": [],
        }

    # Build the strategy from registry + user params.
    try:
        strategy, config = _build_strategy(info, user_params, instrument_id, bar_type)
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"failed to build {strategy_name}({user_params}): {type(e).__name__}: {e}",
            "stats": {}, "equity_curve": [], "trades": [], "fills": [],
        }

    # bypass_logging=True is critical: Nautilus's Rust FFI logger can
    # only initialize once per Python process. Without bypass the second
    # backtest call panics ("logger already initialized") and crashes
    # the worker thread.
    engine_config = BacktestEngineConfig(
        trader_id=TraderId("BT-001"),
        logging=LoggingConfig(bypass_logging=True),
    )
    engine = BacktestEngine(config=engine_config)
    try:
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=USD,
            starting_balances=[Money(Decimal(str(starting_cash)), USD)],
        )
        engine.add_instrument(instrument)
        engine.add_data(nautilus_bars)

        engine.portfolio.analyzer.register_statistic(SharpeRatio())
        engine.portfolio.analyzer.register_statistic(MaxDrawdown())

        engine.add_strategy(strategy)
        engine.run()

        # Reports
        try:
            fills_report = engine.trader.generate_order_fills_report()
        except Exception:
            fills_report = None
        try:
            positions_report = engine.trader.generate_positions_report()
        except Exception:
            positions_report = None

        try:
            stats_pnl = engine.portfolio.analyzer.get_performance_stats_pnls(USD)
        except Exception:
            stats_pnl = {}
        try:
            stats_returns = engine.portfolio.analyzer.get_performance_stats_returns()
        except Exception:
            stats_returns = {}

        positions_records = _df_to_records(positions_report)
        fills_records = _df_to_records(fills_report)

        equity_curve = _compute_equity_curve(
            bars_raw=bars_raw,
            fills_records=fills_records,
            starting_cash=starting_cash,
        )

        realized_pnl = 0.0
        for p in positions_records:
            v = _safe_float(p.get("realized_pnl"))
            if v is not None:
                realized_pnl += v

        starting_eq = equity_curve[0]["equity"] if equity_curve else starting_cash
        ending_eq = equity_curve[-1]["equity"] if equity_curve else starting_cash
        peak_eq = max((p["equity"] for p in equity_curve), default=starting_cash)
        trough_eq = min((p["equity"] for p in equity_curve), default=starting_cash)
        total_return_pct = (
            ((ending_eq - starting_eq) / starting_eq * 100.0)
            if starting_eq > 0
            else None
        )
        max_dd_pct = _max_drawdown_pct(equity_curve)

        stats = {
            "starting_equity": _safe_float(starting_eq),
            "ending_equity": _safe_float(ending_eq),
            "peak_equity": _safe_float(peak_eq),
            "trough_equity": _safe_float(trough_eq),
            "total_return_pct": _safe_float(total_return_pct),
            "realized_pnl": _safe_float(realized_pnl),
            "sharpe_ratio": _safe_float(stats_returns.get("Sharpe Ratio (252 days)")),
            "max_drawdown_pct": max_dd_pct,
            "trade_count": len(positions_records),
            "bar_count": len(nautilus_bars),
            "bars_dropped_invalid": dropped,
        }

        extra_stats: dict[str, Any] = {}
        for source in (stats_pnl, stats_returns):
            for k, v in (source or {}).items():
                fv = _safe_float(v)
                if fv is not None:
                    extra_stats[k] = fv

        # Echo back the resolved params for transparency (msgspec converts
        # them to native Python; jsonable-ize Decimals).
        resolved_params: dict[str, Any] = {}
        for fname in info.params_schema.keys():
            try:
                resolved_params[fname] = _jsonable(getattr(config, fname))
            except AttributeError:
                pass

        return {
            "ok": True,
            "symbol": symbol,
            "strategy": info.name,
            "params": resolved_params,
            "stats": stats,
            "extra_stats": extra_stats,
            "equity_curve": equity_curve,
            "trades": positions_records,
            "fills": fills_records,
        }
    finally:
        try:
            engine.dispose()
        except Exception as e:  # noqa: BLE001
            log.warning("engine.dispose() failed: %s", e)


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


async def run_backtest(
    bars_raw: list[dict[str, Any]],
    symbol: str,
    strategy_name: str = "BuyAndHold",
    params: dict[str, Any] | None = None,
    starting_cash: float = 100_000.0,
) -> dict[str, Any]:
    """Async wrapper around _run_engine_sync. The Nautilus engine is
    CPU-bound and synchronous — push it onto a worker thread so the
    FastAPI event loop doesn't block."""
    return await asyncio.to_thread(
        _run_engine_sync,
        bars_raw,
        symbol.upper(),
        starting_cash,
        strategy_name,
        params or {},
    )
