"""Broker integration package for ROT signal execution.

Provides an abstract :class:`BrokerClient` interface plus concrete
implementations:

* :class:`AlpacaBroker` -- Alpaca Markets paper/live trading via REST API v2.
* :class:`MockBroker`   -- In-memory simulator for unit tests and local dev.

Usage::

    from rot.brokers import AlpacaBroker, MockBroker
    from rot.brokers.base import OptionOrder

    # Paper trading (safe default)
    broker = AlpacaBroker(api_key="...", secret_key="...", paper=True)

    # Local testing
    broker = MockBroker(initial_buying_power=Decimal("50000"))
"""
from rot.brokers.base import AccountInfo, BrokerClient, OptionOrder, OrderResult
from rot.brokers.alpaca import AlpacaBroker, AlpacaError
from rot.brokers.mock import MockBroker

__all__ = [
    "BrokerClient",
    "OptionOrder",
    "OrderResult",
    "AccountInfo",
    "AlpacaBroker",
    "AlpacaError",
    "MockBroker",
]
