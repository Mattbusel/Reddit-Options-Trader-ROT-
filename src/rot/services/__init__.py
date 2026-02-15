"""Service layer for ROT business logic.

Decouples route handlers from direct database access by providing
domain-focused service classes with clear error types.
"""
from __future__ import annotations

from rot.services.paper_trading_service import PaperTradingService
from rot.services.signal_service import SignalService
from rot.services.user_service import UserService

__all__ = ["PaperTradingService", "SignalService", "UserService"]
