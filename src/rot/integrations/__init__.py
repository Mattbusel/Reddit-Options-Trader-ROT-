"""TradingView integration module.

Provides Pine Script generation for ROT signals, enabling users to:
- Overlay signals on TradingView charts
- Create confidence heatmaps
- Build multi-ticker watchlist panels
- Generate strategy backtests with entry/exit logic
- Set up alert conditions based on signal criteria

Note: Pine Script v5 doesn't support dynamic data fetching. Users must
periodically regenerate scripts to include latest signals.
"""

from .tradingview import PineScriptGenerator
from .types import PineScriptConfig, ScriptType, TVSignalOverlay

__all__ = [
    "PineScriptGenerator",
    "PineScriptConfig",
    "ScriptType",
    "TVSignalOverlay",
]
