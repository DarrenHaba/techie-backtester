"""Nautilus BacktestEngine wrapper.

One function: `run_buy_and_hold(bars, symbol)`. Takes raw bar dicts,
runs them through Nautilus's event-driven engine with a toy
buy-and-hold Strategy, returns a JSON-friendly result dict.

This is the v0 of the runner. Strategies will move into
techie-strategies-private once we have something worth promoting; for
now BuyAndHold is inlined here as the smoke-test case that proves the
engine wiring works end-to-end.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.config import BacktestEngineConfig, StrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.core.nautilus_pyo3 import MaxDrawdown, SharpeRatio
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import (
    AccountType,
    OmsType,
    OrderSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import (
    InstrumentId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.trading.strategy import Strategy

log = logging.getLogger(__name__)


# --- Strategy --------------------------------------------------------------


class BuyAndHoldConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg,misc]
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal


class BuyAndHold(Strategy):
    """Buy on the first bar, hold to the last, force-close at the end so
    the position appears in the positions report with realized PnL."""

    def __init__(self, config: BuyAndHoldConfig) -> None:
        super().__init__(config)
        self.entered = False

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"instrument {self.config.instrument_id} not found")
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self.entered:
            return
        order: MarketOrder = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(self.config.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self.entered = True

    def on_stop(self) -> None:
        # Realize the PnL so it shows in the positions report.
        self.close_all_positions(self.config.instrument_id)


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
        # Nautilus Quantity rejects 0 volume in some venue configs; skip.
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


# --- Result extraction -----------------------------------------------------


def _safe_float(v: Any) -> float | None:
    """Best-effort cast. None / NaN / non-numeric become None for JSON.

    Also strips Nautilus Money formatting like "6710.00 USD" — the
    positions report renders realized_pnl as a Money string, not a
    number.
    """
    if v is None:
        return None
    if isinstance(v, str):
        # Money objects render like "6710.00 USD" — strip the currency.
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
    if f != f:  # NaN
        return None
    return f


def _compute_equity_curve(
    bars_raw: list[dict[str, Any]],
    fills_records: list[dict[str, Any]],
    starting_cash: float,
) -> list[dict[str, Any]]:
    """Mark-to-market equity at each bar's close.

    Walks bars in chronological order, applying fills as they happen,
    and reports `equity = cash + position_qty * bar.close` per bar. This
    is the proper portfolio-value time series. We don't use Nautilus's
    `account_report` because it only emits a row per cash event (one on
    initial deposit, one per fill), which gives you a 3-point sawtooth
    for a buy-and-hold instead of a smooth curve, and produces nonsense
    drawdowns.
    """
    # Normalize fill timestamps + sort.
    parsed_fills: list[dict[str, Any]] = []
    for f in fills_records:
        # ts_last / ts_init come back as ISO strings from _df_to_records.
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

        # Apply any fills whose timestamp is <= this bar's timestamp.
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
    """Return max peak-to-trough drawdown as a positive percent.

    e.g. an equity that fell from 100k to 95k somewhere along the way
    returns 5.0 (i.e. 5.0%). Returns None for curves with < 2 points.
    """
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


def _df_to_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Convert a (maybe-None, maybe-empty) DataFrame to JSON-safe records."""
    if df is None or df.empty:
        return []
    out = df.reset_index().to_dict(orient="records")
    # Convert pandas Timestamps to ISO strings so json.dumps doesn't choke.
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


# --- Public entry point ----------------------------------------------------


def _run_engine_sync(
    bars_raw: list[dict[str, Any]],
    symbol: str,
    starting_cash: float,
    trade_size: float,
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

    venue = Venue("XNAS")
    instrument_id = InstrumentId(symbol=Symbol(symbol), venue=venue)
    instrument = Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol(symbol),
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        lot_size=Quantity.from_int(1),  # allow arbitrary share counts
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

    # bypass_logging=True is critical: Nautilus's Rust FFI logger can only
    # be initialized once per Python process. Without bypass, the second
    # backtest call would panic ("attempted to set a logger after the
    # logging system was already initialized") and crash the worker
    # thread. Bypassing also makes runs much quieter — Nautilus's normal
    # output is hundreds of lines per backtest.
    config = BacktestEngineConfig(
        trader_id=TraderId("BT-001"),
        logging=LoggingConfig(bypass_logging=True),
    )
    engine = BacktestEngine(config=config)
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

        engine.add_strategy(
            BuyAndHold(
                BuyAndHoldConfig(
                    instrument_id=instrument_id,
                    bar_type=bar_type,
                    trade_size=Decimal(str(trade_size)),
                )
            )
        )

        engine.run()

        # Reports ----------------------------------------------------------
        try:
            account_report = engine.trader.generate_account_report(venue)
        except Exception:
            account_report = None
        try:
            fills_report = engine.trader.generate_order_fills_report()
        except Exception:
            fills_report = None
        try:
            positions_report = engine.trader.generate_positions_report()
        except Exception:
            positions_report = None

        # Stats ------------------------------------------------------------
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

        # Build a proper mark-to-market equity curve from bars + fills.
        # Nautilus's account_report is useless for this — see
        # _compute_equity_curve docstring.
        equity_curve = _compute_equity_curve(
            bars_raw=bars_raw,
            fills_records=fills_records,
            starting_cash=starting_cash,
        )

        # Sum realized pnl from positions (engine.portfolio numbers can be None
        # when the position closed exactly at the last bar; this is a fallback).
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
            # Nautilus's Sharpe is computed from its own (broken-for-our-case)
            # returns series; surface it but with the caveat that it's only
            # meaningful once we compute returns from our own equity curve.
            "sharpe_ratio": _safe_float(stats_returns.get("Sharpe Ratio (252 days)")),
            "max_drawdown_pct": max_dd_pct,
            "trade_count": len(positions_records),
            "bar_count": len(nautilus_bars),
            "bars_dropped_invalid": dropped,
        }
        # Surface any other stat strings Nautilus computed, for transparency.
        extra_stats: dict[str, Any] = {}
        for source in (stats_pnl, stats_returns):
            for k, v in (source or {}).items():
                fv = _safe_float(v)
                if fv is not None:
                    extra_stats[k] = fv

        return {
            "ok": True,
            "symbol": symbol,
            "stats": stats,
            "extra_stats": extra_stats,
            "equity_curve": equity_curve,
            "trades": positions_records,
            "fills": _df_to_records(fills_report),
        }
    finally:
        try:
            engine.dispose()
        except Exception as e:  # noqa: BLE001
            log.warning("engine.dispose() failed: %s", e)


async def run_buy_and_hold(
    bars_raw: list[dict[str, Any]],
    symbol: str,
    starting_cash: float = 100_000.0,
    trade_size: float = 100.0,
) -> dict[str, Any]:
    """Async wrapper. Pushes the CPU-bound run onto a worker thread so the
    FastAPI event loop doesn't block."""
    return await asyncio.to_thread(
        _run_engine_sync, bars_raw, symbol.upper(), starting_cash, trade_size
    )
