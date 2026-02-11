"""Affiliate / referral program routes.

Provides:
  - /affiliates — public affiliate program page
  - /api/v1/affiliates/register — sign up as affiliate
  - /api/v1/affiliates/dashboard — view commissions + stats
  - /api/v1/affiliates/widget — embeddable widget code
  - /ref/{code} — referral landing redirect
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from rot.web.auth import get_current_user_optional, require_user

log = logging.getLogger(__name__)

router = APIRouter()

# Commission rate: 20% recurring
COMMISSION_RATE = 0.20
REFERRAL_REWARD_DAYS = 7  # 7 days free Pro for both sides


# ── Models ──

class AffiliateRegisterRequest(BaseModel):
    payment_email: str = ""  # PayPal/Stripe email for payouts


# ── Public affiliate page ──

@router.get("/affiliates", response_class=HTMLResponse)
async def affiliates_page(request: Request):
    """Render the affiliate program landing page."""
    user = await get_current_user_optional(request)
    templates = request.app.state.templates

    # Check if user is already an affiliate
    affiliate_info = None
    if user:
        settings = user.get("settings", {})
        if isinstance(settings, dict):
            affiliate_info = settings.get("affiliate")

    return templates.TemplateResponse("affiliates.html", {
        "request": request,
        "user": user,
        "affiliate_info": affiliate_info,
        "commission_rate": int(COMMISSION_RATE * 100),
        "reward_days": REFERRAL_REWARD_DAYS,
        "dashboard_url": str(request.base_url).rstrip("/"),
    })


# ── Register as affiliate ──

@router.post("/api/v1/affiliates/register")
async def register_affiliate(body: AffiliateRegisterRequest, request: Request):
    """Register current user as an affiliate. Generates a unique referral code."""
    user = await require_user(request)

    db = request.app.state.db
    current_settings = user.get("settings", {})
    if not isinstance(current_settings, dict):
        current_settings = {}

    # Check if already registered
    if current_settings.get("affiliate"):
        return {
            "ok": True,
            "already_registered": True,
            "affiliate": current_settings["affiliate"],
        }

    # Generate unique referral code
    ref_code = _generate_ref_code(user.get("email", ""))

    affiliate_data = {
        "ref_code": ref_code,
        "payment_email": body.payment_email or user.get("email", ""),
        "registered_at": time.time(),
        "total_referrals": 0,
        "total_conversions": 0,
        "total_earned": 0.0,
        "pending_payout": 0.0,
    }

    current_settings["affiliate"] = affiliate_data
    await db.update_user_settings(user["id"], current_settings)

    log.info("New affiliate registered: user=%s code=%s", user["id"], ref_code)

    return {"ok": True, "affiliate": affiliate_data}


# ── Affiliate dashboard ──

@router.get("/api/v1/affiliates/dashboard")
async def affiliate_dashboard(request: Request):
    """Get affiliate stats and commission data."""
    user = await require_user(request)

    settings = user.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}

    affiliate = settings.get("affiliate")
    if not affiliate:
        raise HTTPException(status_code=400, detail="Not registered as affiliate. Register first.")

    # Get referral stats from DB
    db = request.app.state.db
    ref_code = affiliate.get("ref_code", "")
    referral_count = await db.count_referrals(ref_code)
    conversion_count = await db.count_referral_conversions(ref_code)

    return {
        "ok": True,
        "ref_code": ref_code,
        "referral_link": f"{request.base_url}ref/{ref_code}",
        "total_clicks": referral_count,
        "total_conversions": conversion_count,
        "commission_rate": COMMISSION_RATE,
        "total_earned": affiliate.get("total_earned", 0),
        "pending_payout": affiliate.get("pending_payout", 0),
        "recent_referrals": await db.get_recent_referrals(ref_code, limit=20),
    }


# ── Embeddable widget code ──

@router.get("/api/v1/affiliates/widget")
async def affiliate_widget(request: Request):
    """Return embeddable HTML/JS widget code for the affiliate."""
    user = await require_user(request)

    settings = user.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}

    affiliate = settings.get("affiliate")
    if not affiliate:
        raise HTTPException(status_code=400, detail="Not registered as affiliate")

    ref_code = affiliate.get("ref_code", "")
    base_url = str(request.base_url).rstrip("/")

    # Generate embeddable widget code
    widget_html = f"""<!-- ROT Signal Widget - Affiliate: {ref_code} -->
<div id="rot-widget" style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:400px;border:1px solid #333;border-radius:12px;background:#1a1a2e;color:#e0e0e0;padding:16px;"></div>
<script>
(function() {{
  var w = document.getElementById('rot-widget');
  fetch('{base_url}/api/v1/tradingview/signals?limit=5')
    .then(r => r.json())
    .then(d => {{
      var h = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">'
            + '<strong style="font-size:16px;">ROT Signals</strong>'
            + '<span style="font-size:11px;color:#888;">Live</span></div>';
      (d.signals || []).forEach(function(s) {{
        var color = s.stance === 'bullish' ? '#4ade80' : s.stance === 'bearish' ? '#f87171' : '#facc15';
        h += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #333;">'
           + '<span style="font-weight:600;">$' + s.s + '</span>'
           + '<span style="color:' + color + ';text-transform:uppercase;font-size:13px;">' + s.stance + '</span>'
           + '<span style="color:#888;font-size:13px;">' + Math.round(s.c * 100) + '%</span></div>';
      }});
      h += '<div style="margin-top:10px;text-align:center;"><a href="{base_url}/ref/{ref_code}" '
         + 'style="color:#818cf8;text-decoration:none;font-size:13px;" target="_blank">'
         + 'Powered by ROT &rarr;</a></div>';
      w.innerHTML = h;
    }})
    .catch(function() {{ w.innerHTML = '<p style="color:#888;">Unable to load signals</p>'; }});
}})();
</script>"""

    iframe_code = f'<iframe src="{base_url}/embed/signals?ref={ref_code}" width="400" height="300" frameborder="0" style="border-radius:12px;"></iframe>'

    return {
        "ok": True,
        "widget_html": widget_html,
        "iframe_code": iframe_code,
        "ref_code": ref_code,
        "ref_link": f"{base_url}/ref/{ref_code}",
    }


# ── Referral redirect ──

@router.get("/ref/{ref_code}")
async def referral_redirect(ref_code: str, request: Request):
    """Track referral click and redirect to signup/dashboard."""
    db = request.app.state.db

    # Record the referral click
    await db.record_referral_click(ref_code, request.client.host if request.client else "")

    # Redirect to signup page with ref code in query
    base_url = str(request.base_url).rstrip("/")
    return RedirectResponse(
        url=f"{base_url}/dashboard?ref={ref_code}",
        status_code=302,
    )


# ── Helpers ──

def _generate_ref_code(email: str) -> str:
    """Generate a short, memorable referral code."""
    # Take first part of email + random suffix
    prefix = email.split("@")[0][:6].lower() if email else "rot"
    suffix = secrets.token_hex(3)  # 6 hex chars
    return f"{prefix}_{suffix}"
