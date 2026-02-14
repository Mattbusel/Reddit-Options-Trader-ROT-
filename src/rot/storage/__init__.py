"""
ROT Storage Layer - Database abstraction for SQLite persistence.

Main exports:
- Database: Async SQLite database class composed of domain mixins
"""

from .database import Database

__all__ = ["Database"]
