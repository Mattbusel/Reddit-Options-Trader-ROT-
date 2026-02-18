"""Contact — Investors & Support."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()

CONTACT_EMAIL = "mattbusel@gmail.com"


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


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    """Contact page — investors and support."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)

    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "ContactPage",
        "name": "Contact ROT",
        "description": "Contact Reddit Options Trader for investor inquiries or support.",
        "url": str(request.base_url).rstrip("/") + "/contact",
    })

    base = str(request.base_url).rstrip("/")

    ctx.update({
        "contact_email": CONTACT_EMAIL,
        "contact_schema": schema,
        "share_url": f"{base}/contact",
        "share_text": "Contact Reddit Options Trader",
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("contact.html", ctx)
