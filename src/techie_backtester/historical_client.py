"""HTTP client for techie-historical-data.

Tiny shim around the `get_bars` action. Returns plain Python dicts
(no pandas, no Nautilus types) so this module stays usable from
notebooks or other tools that don't want the engine pulled in.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = os.environ.get("TECHIE_HISTORICAL_URL", "http://127.0.0.1:8101")


class HistoricalDataError(RuntimeError):
    """The historical-data service rejected the request or is unreachable."""


async def get_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1d",
    base_url: str | None = None,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """Pull bars for one symbol over one window.

    Returns the raw list of bar dicts:
        [{"datetime_utc": "...", "open": ..., "high": ..., "low": ...,
          "close": ..., "volume": ...}, ...]

    Raises `HistoricalDataError` if the service is down or returns an
    error payload.
    """
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/api/actions/get_bars"
    payload = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "start": start,
        "end": end,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        raise HistoricalDataError(
            f"techie-historical-data unreachable at {url}: {e}"
        ) from e
    if resp.status_code != 200:
        raise HistoricalDataError(
            f"get_bars HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    # Cortex sometimes wraps action results in {"result": ...}; accept both.
    if isinstance(body, dict) and "bars" in body:
        bars = body["bars"]
    elif isinstance(body, dict) and "result" in body and isinstance(body["result"], dict):
        bars = body["result"].get("bars", [])
    else:
        bars = []
    if not isinstance(bars, list):
        raise HistoricalDataError(f"unexpected get_bars response: {body!r}")
    return bars
