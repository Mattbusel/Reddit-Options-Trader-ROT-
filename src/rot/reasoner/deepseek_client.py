from __future__ import annotations

from rot.core.types import Event, ReasoningPacket

class DeepSeekReasoner:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def reason(self, e: Event) -> ReasoningPacket:
        # V1 stub: structured placeholder
        return ReasoningPacket(
            thesis=f"Reddit chatter mentions {', '.join(e.entities)}; treat as unverified.",
            catalyst_window="unknown",
            market_expectation="unclear; watch implied volatility + liquidity",
            invalidations=[
                "No corroboration across sources",
                "Trend decays within hours",
            ],
            recommended_structures=[
                "debit_spread (defined risk)",
                "calendar (if catalyst known)",
            ],
            risk_notes=[
                "Do not trade without market data gates",
            ],
            raw={"stub": True},
        )
