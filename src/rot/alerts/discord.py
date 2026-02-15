from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

import httpx

log = logging.getLogger(__name__)

# Stance -> Discord embed color (decimal)
_STANCE_COLORS = {
    "bullish": 0x22C55E,   # green
    "bearish": 0xEF4444,   # red
    "mixed": 0xEAB308,     # yellow
    "unknown": 0x6B7280,   # gray
}


def _to_dict(obj: Any) -> Dict[str, Any]:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {}


class DiscordAlerter:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send_signal(self, signal_data: Dict[str, Any], dashboard_url: str = "") -> bool:
        event = _to_dict(signal_data.get("event"))
        reasoning = _to_dict(signal_data.get("reasoning"))
        idea = _to_dict(signal_data.get("trade_idea"))

        entities = event.get("entities", [])
        ticker = entities[0] if entities else "UNKNOWN"
        stance = event.get("stance", "unknown")
        confidence = event.get("confidence", 0)
        event_type = event.get("event_type", "other")
        evidence = event.get("evidence", [{}])
        first_evidence = evidence[0] if evidence else {}

        strategy = idea.get("strategy", "none")
        thesis = reasoning.get("thesis", "")

        color = _STANCE_COLORS.get(stance, _STANCE_COLORS["unknown"])

        # Build embed
        fields = [
            {"name": "Stance", "value": stance.upper(), "inline": True},
            {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
            {"name": "Event Type", "value": event_type, "inline": True},
        ]

        if strategy != "none":
            fields.append({"name": "Strategy", "value": strategy, "inline": True})

            legs = idea.get("legs", [])
            if legs:
                legs_text = "\n".join(
                    f"{'BUY' if l.get('side') == 'buy' else 'SELL'} {l.get('kind','').upper()} ${l.get('strike',0):.0f} exp {l.get('expiry','')}"
                    for l in legs
                )
                fields.append({"name": "Legs", "value": f"```\n{legs_text}\n```", "inline": False})

            max_loss = idea.get("max_loss", 0)
            if max_loss:
                fields.append({"name": "Max Loss", "value": f"${max_loss:.2f}", "inline": True})

        if reasoning.get("catalyst_window"):
            fields.append({"name": "Catalyst Window", "value": reasoning["catalyst_window"], "inline": True})

        # Risk notes
        risks = reasoning.get("risk_notes", [])
        if risks:
            fields.append({
                "name": "Risks",
                "value": "\n".join(f"- {r}" for r in risks[:3]),
                "inline": False,
            })

        embed = {
            "title": f"{'🟢' if stance == 'bullish' else '🔴' if stance == 'bearish' else '🟡'} {ticker} — {event_type.replace('_', ' ').title()}",
            "description": thesis[:500] if thesis else "",
            "color": color,
            "fields": fields,
            "footer": {"text": "ROT - Reddit Options Trader | Not financial advice"},
        }

        # Add Reddit link
        permalink = first_evidence.get("permalink", "")
        if permalink:
            embed["url"] = permalink

        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )
                if resp.status_code in (200, 204):
                    log.info("Discord alert sent for %s", ticker)
                    return True
                else:
                    log.warning("Discord webhook returned %d: %s", resp.status_code, resp.text[:200])
                    return False
        except Exception as e:
            log.error("Discord alert failed: %s", e)
            return False
