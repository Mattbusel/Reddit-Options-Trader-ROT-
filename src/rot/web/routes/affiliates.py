"""Affiliate / referral program routes.

Provides:
  - /affiliates — public affiliate program page
  - /api/v1/affiliates/register — sign up as affiliate
  - /api/v1/affiliates/stats — view commissions + stats
  - /api/v1/affiliates/request-payout — request payout
  - /api/v1/affiliates/widget — embeddable widget code
  - /ref/{code} — referral landing redirect
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from rot.web.auth import get_current_user_optional, require_user
from rot.affiliates import AffiliateEngine

log = logging.getLogger(__name__)

router = APIRouter()

# Commission rate: 20% recurring
COMMISSION_RATE = 0.20
REFERRAL_REWARD_DAYS = 7  # 7 days free Pro for both sides


# ── Models ──

class AffiliateRegisterRequest(BaseModel):
    payment_email: str = ""  # PayPal/Stripe email for payouts


class PayoutRequest(BaseModel):
    payment_method: str = "paypal"  # paypal, stripe, bank_transfer


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
    engine = AffiliateEngine(db)

    try:
        # Check if already registered
        existing = await db.get_affiliate_by_user(user["id"])
        if existing:
            return {
                "ok": True,
                "already_registered": True,
                "affiliate": existing,
            }

        # Register new affiliate
        affiliate = await engine.register_affiliate(
            user_id=user["id"],
            payment_email=body.payment_email or user.get("email", ""),
        )

        return {"ok": True, "affiliate": affiliate.to_dict()}

    except Exception as e:
        log.error("Error registering affiliate: %s", e)
        # Don't expose internal error details to users (CWE-209)
        raise HTTPException(status_code=500, detail="Failed to register affiliate")


# ── Affiliate stats ──

@router.get("/api/v1/affiliates/stats")
async def affiliate_stats(request: Request, days: int = 30):
    """Get affiliate stats and commission data."""
    user = await require_user(request)
    db = request.app.state.db
    engine = AffiliateEngine(db)

    # Get affiliate record
    affiliate = await db.get_affiliate_by_user(user["id"])
    if not affiliate:
        raise HTTPException(status_code=400, detail="Not registered as affiliate. Register first.")

    try:
        # Get statistics
        stats = await engine.get_referral_stats(affiliate["id"], days=days)

        # Get payout report
        payout_report = await engine.generate_payout_report(affiliate["id"])

        return {
            "ok": True,
            "affiliate": affiliate,
            "referral_link": f"{request.base_url}ref/{affiliate['referral_code']}",
            "stats": stats.to_dict(),
            "payout_report": payout_report,
            "commission_rate": COMMISSION_RATE,
        }

    except Exception as e:
        log.error("Error fetching affiliate stats: %s", e)
        # Don't expose internal error details to users (CWE-209)
        raise HTTPException(status_code=500, detail="Failed to fetch affiliate stats")


# ── Request payout ──

@router.post("/api/v1/affiliates/request-payout")
async def request_payout(body: PayoutRequest, request: Request):
    """Request a payout for accumulated commissions."""
    user = await require_user(request)
    db = request.app.state.db
    engine = AffiliateEngine(db)

    # Get affiliate record
    affiliate = await db.get_affiliate_by_user(user["id"])
    if not affiliate:
        raise HTTPException(status_code=400, detail="Not registered as affiliate.")

    try:
        # Request payout
        payout = await engine.request_payout(
            affiliate_id=affiliate["id"],
            payment_method=body.payment_method,
        )

        return {
            "ok": True,
            "payout": payout.to_dict(),
            "message": f"Payout request submitted for ${payout.amount_usd:.2f}",
        }

    except ValueError as e:
        # ValueError is expected for validation errors, safe to expose
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("Error requesting payout: %s", e)
        # Don't expose internal error details to users (CWE-209)
        raise HTTPException(status_code=500, detail="Failed to process payout request")


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
async def referral_redirect(ref_code: str, request: Request, source: str = ""):
    """Track referral click and redirect to signup/dashboard."""
    db = request.app.state.db
    engine = AffiliateEngine(db)

    # Record the referral click
    ip_address = request.client.host if request.client else ""
    await engine.track_click(
        referral_code=ref_code,
        source=source,
        ip_address=ip_address,
    )

    # Sanitize ref_code to alphanumeric + dash/underscore only (CWE-601)
    safe_ref = re.sub(r"[^a-zA-Z0-9_-]", "", ref_code)
    # Redirect to dashboard with sanitized ref code (hardcoded path, not user-controlled)
    return RedirectResponse(
        url="/dashboard?ref=" + safe_ref,
        status_code=302,
    )
