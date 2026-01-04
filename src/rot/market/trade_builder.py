from __future__ import annotations

from typing import List

from rot.core.types import Event, ReasoningPacket, TradeIdea

class TradeBuilder:
    def build(self, packet: ReasoningPacket, e: Event) -> List[TradeIdea]:
        # V1: no market data yet -> emit no-trade idea with reason
        return [
            TradeIdea(
                underlying=e.entities[0] if e.entities else "UNKNOWN",
                strategy="none",
                legs=[],
                max_loss=0.0,
                thesis=packet.thesis,
                time_stop="N/A",
                quality_score=0.0,
                do_not_trade_reasons=["market_data_not_configured"],
            )
        ]
