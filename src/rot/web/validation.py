"""Pydantic validation models for API route inputs.

Centralised request schemas enforce type checking and constraint validation
before route handlers run.  Each model maps to one or more POST/PUT endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


# ── Strategy Builder ──

class CreateStrategyRequest(BaseModel):
    """Request body for creating a new rule-based strategy."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    rules: List[Dict[str, Any]] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)


class DiscoverStrategiesRequest(BaseModel):
    """Request body for the automated strategy discovery endpoint."""

    days: int = Field(90, ge=1, le=365)
    max_signals: int = Field(1000, ge=10, le=10000)
    max_rules: int = Field(3, ge=1, le=10)
    max_candidates: int = Field(500, ge=10, le=5000)
    min_trades: int = Field(10, ge=1)
    min_win_rate: float = Field(0.5, ge=0.0, le=1.0)
    min_sharpe: float = Field(0.0, ge=-5.0, le=10.0)
    search_mode: str = Field("random")
    walk_forward: bool = False


class MLOptimizeRequest(BaseModel):
    """Request body for the ML-based strategy optimisation endpoint."""

    days: int = Field(90, ge=1, le=365)
    max_signals: int = Field(1000, ge=10, le=10000)
    min_signals: int = Field(200, ge=10, le=5000)


class GeneticEvolveRequest(BaseModel):
    """Request body for the genetic-algorithm strategy evolution endpoint."""

    days: int = Field(90, ge=1, le=365)
    max_signals: int = Field(1000, ge=10, le=10000)
    population_size: int = Field(50, ge=10, le=100)
    generations: int = Field(30, ge=1, le=50)
    max_rules: int = Field(5, ge=1, le=10)


class PublishToMarketplaceRequest(BaseModel):
    """Request body for publishing a strategy to the marketplace."""

    strategy_id: str = Field(..., min_length=1)
    name: str = Field("", max_length=100)
    description: str = Field("", max_length=1000)
    price: float = Field(0.0, ge=0.0)
    tags: List[str] = Field(default_factory=list)


# ── Backtest ──

class BacktestCompareRequest(BaseModel):
    """Request body for comparing two to five backtest runs side-by-side."""

    run_ids: List[str] = Field(..., min_length=2, max_length=5)


# ── Export ──

class ExportScheduleCreateRequest(BaseModel):
    """Request body for creating a new scheduled enterprise data export."""

    format: str = Field("csv")
    frequency: str = Field("daily")
    filters: Dict[str, Any] = Field(default_factory=dict)
