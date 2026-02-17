"""MCP landing page — marketing page for the ROT MCP server.

Showcases the world's first financial intelligence MCP server with
connection instructions, tool documentation, and example prompts.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()

EXAMPLE_PROMPTS = [
    "What stocks are trending on Reddit right now?",
    "Show me bearish signals for TSLA",
    "What's the sentiment on NVDA?",
    "Are there any unusual options activity alerts?",
    "Search for signals about FDA approvals",
    "Give me a full market overview for the last 30 days",
    "What NFL injuries might move betting lines today?",
    "Show me the top 5 tickers by signal volume this week",
    "What's the bull/bear ratio on AMD?",
    "Find signals mentioning earnings beat",
]


def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
        "admin": "bg-red-700/60 text-red-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


@router.get("/mcp-server", response_class=HTMLResponse)
async def mcp_landing_page(request: Request):
    """MCP Server landing page — the first financial intelligence MCP server."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    ctx["example_prompts"] = EXAMPLE_PROMPTS
    templates = request.app.state.templates
    return templates.TemplateResponse("mcp.html", ctx)
