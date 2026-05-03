"""Inc 0 smoke test — module imports cleanly."""

from __future__ import annotations


def test_module_imports() -> None:
    import techie_backtester

    assert techie_backtester.__version__ == "0.1.0a0"


def test_server_module_imports() -> None:
    """server.py imports without raising — confirms the cortex
    create_app call is wired correctly even before any custom actions
    are added."""
    from techie_backtester import server

    assert server.app is not None
