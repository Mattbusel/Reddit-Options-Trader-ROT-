"""Type definitions for TradingView integration.

Defines configuration objects and data structures for Pine Script generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ScriptType = Literal[
    "signal_overlay",
    "confidence_heatmap",
    "watchlist_indicator",
    "strategy_backtest",
    "alert_conditions",
]


@dataclass(frozen=True)
class TVSignalOverlay:
    """Single signal overlay for TradingView chart.

    Represents one ROT signal that will be plotted on a chart.
    All fields are immutable to ensure data integrity during script generation.
    """

    # Core signal data
    timestamp: int  # Unix timestamp in seconds
    ticker: str
    stance: str  # bullish, bearish, mixed, unknown
    confidence: float  # 0.0 to 1.0

    # Optional enrichment
    event_type: str = "other"
    strategy: str = "none"
    time_horizon: str = "unknown"
    trend_score: float = 0.0
    signal_id: str = ""

    # Display metadata
    label: Optional[str] = None  # Optional text label to show on chart
    color: Optional[str] = None  # Optional custom color override

    def to_pine_arrays(self) -> dict:
        """Convert signal to Pine Script array indices.

        Returns dict with keys:
        - ts: timestamp for time[i] comparison
        - stance_code: 1=bullish, -1=bearish, 0=mixed/unknown
        - conf: confidence value
        - label: text to display (defaults to ticker + confidence)
        """
        stance_code = 1 if self.stance == "bullish" else -1 if self.stance == "bearish" else 0

        label_text = self.label or f"{self.ticker} ({self.confidence:.2f})"

        return {
            "ts": self.timestamp,
            "stance_code": stance_code,
            "conf": self.confidence,
            "label": label_text,
            "ticker": self.ticker,
        }


@dataclass
class PineScriptConfig:
    """Configuration for Pine Script generation.

    Controls how signals are filtered and formatted in the generated script.
    Mutable to allow runtime adjustments.
    """

    # Filtering
    ticker: Optional[str] = None  # Filter to single ticker, or None for all
    min_confidence: float = 0.0  # Minimum confidence threshold (0.0-1.0)
    days: int = 30  # Number of days of historical signals to include
    max_signals: int = 100  # Maximum number of signals (Pine Script performance limit)

    # Display options
    show_labels: bool = True  # Show text labels on chart
    show_lines: bool = False  # Draw vertical lines at signal times
    show_confidence_color: bool = True  # Color by confidence gradient

    # Script metadata
    script_name: str = "ROT Signals"
    script_description: str = "Reddit Options Trader signal overlays"

    # Strategy options (for strategy_backtest type)
    strategy_capital: float = 10000.0  # Initial capital
    strategy_commission: float = 0.0  # Commission per trade (0.0-1.0 as percentage)
    strategy_slippage: int = 0  # Slippage in ticks

    # Alert options (for alert_conditions type)
    alert_on_bullish: bool = True
    alert_on_bearish: bool = True
    alert_min_confidence: float = 0.7  # Minimum confidence to trigger alert

    def validate(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If any configuration value is invalid
        """
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be 0.0-1.0, got {self.min_confidence}")

        if self.days < 1:
            raise ValueError(f"days must be >= 1, got {self.days}")

        if self.max_signals < 1:
            raise ValueError(f"max_signals must be >= 1, got {self.max_signals}")

        if not 0.0 <= self.strategy_commission <= 1.0:
            raise ValueError(f"strategy_commission must be 0.0-1.0, got {self.strategy_commission}")

        if self.strategy_slippage < 0:
            raise ValueError(f"strategy_slippage must be >= 0, got {self.strategy_slippage}")

        if not 0.0 <= self.alert_min_confidence <= 1.0:
            raise ValueError(f"alert_min_confidence must be 0.0-1.0, got {self.alert_min_confidence}")
