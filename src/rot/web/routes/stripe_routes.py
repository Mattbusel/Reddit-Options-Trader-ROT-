from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from rot.web.auth import require_user

log = logging.getLogger(__name__)

try:
    import stripe
    _HAS_STRIPE = True
except ImportError:
    stripe = None
    _HAS_STRIPE = False

router = APIRouter(prefix="/billing")

_TIER_PRICE_MAP = {
    "pro": "pro_price_id",
    "premium": "premium_price_id",
    "ultra": "ultra_price_id",
}

_PRICE_TO_TIER = {}  # populated at runtime from settings


def _ensure_stripe(request: Request):
    """Check that Stripe is configured and available."""
    if not _HAS_STRIPE:
        raise HTTPException(status_code=501, detail="Billing not available (stripe package not installed)")
    secret_key = request.app.state.settings.stripe.secret_key
    if not secret_key:
        raise HTTPException(status_code=501, detail="Billing not configured")
    stripe.api_key = secret_key


def _build_price_to_tier(settings) -> dict:
    """Build reverse mapping from price ID -> tier."""
    mapping = {}
    cfg = settings.stripe
    if cfg.pro_price_id:
        mapping[cfg.pro_price_id] = "pro"
    if cfg.premium_price_id:
        mapping[cfg.premium_price_id] = "premium"
    if cfg.ultra_price_id:
        mapping[cfg.ultra_price_id] = "ultra"
    return mapping


class CheckoutRequest(BaseModel):
    tier: str  # "pro", "premium", or "ultra"


@router.post("/checkout")
async def create_checkout(body: CheckoutRequest, request: Request):
    """Create a Stripe Checkout session for a subscription upgrade."""
    _ensure_stripe(request)
    user = await require_user(request)
    settings = request.app.state.settings

    price_attr = _TIER_PRICE_MAP.get(body.tier)
    if not price_attr:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {body.tier}")

    price_id = getattr(settings.stripe, price_attr, "")
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Price not configured for {body.tier} tier")

    # Check if user already has a Stripe customer
    db = request.app.state.db
    sub = await db.get_subscription(user["id"])
    customer_id = sub.get("stripe_customer_id") if sub else None

    base_url = f"{request.base_url}".rstrip("/")
    checkout_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": base_url + settings.stripe.success_url,
        "cancel_url": base_url + settings.stripe.cancel_url,
        "metadata": {"user_id": user["id"], "tier": body.tier},
    }

    if customer_id:
        checkout_params["customer"] = customer_id
    else:
        checkout_params["customer_email"] = user["email"]

    session = stripe.checkout.Session.create(**checkout_params)
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    _ensure_stripe(request)
    settings = request.app.state.settings
    db = request.app.state.db

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe.webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        log.warning("Webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]
    log.info("Stripe webhook: %s", event_type)

    price_tier_map = _build_price_to_tier(settings)

    if event_type == "checkout.session.completed":
        user_id = data.get("metadata", {}).get("user_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        tier = data.get("metadata", {}).get("tier", "pro")

        if user_id:
            await db.upsert_subscription(user_id, {
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "tier": tier,
                "status": "active",
            })
            await db.update_user_tier(user_id, tier)
            log.info("User %s upgraded to %s", user_id, tier)

    elif event_type == "customer.subscription.updated":
        subscription_id = data.get("id")
        sub = await db.get_subscription_by_stripe_id(subscription_id)
        if sub:
            # Determine new tier from price
            items = data.get("items", {}).get("data", [])
            new_tier = "free"
            for item in items:
                price_id = item.get("price", {}).get("id", "")
                if price_id in price_tier_map:
                    new_tier = price_tier_map[price_id]
                    break

            status = data.get("status", "active")
            period_end = data.get("current_period_end")
            await db.upsert_subscription(sub["user_id"], {
                "tier": new_tier,
                "status": status,
                "current_period_end": period_end,
            })
            if status == "active":
                await db.update_user_tier(sub["user_id"], new_tier)

    elif event_type == "customer.subscription.deleted":
        subscription_id = data.get("id")
        sub = await db.get_subscription_by_stripe_id(subscription_id)
        if sub:
            await db.upsert_subscription(sub["user_id"], {
                "tier": "free",
                "status": "canceled",
            })
            await db.update_user_tier(sub["user_id"], "free")
            log.info("User %s downgraded to free (subscription canceled)", sub["user_id"])

    return JSONResponse(content={"received": True})


@router.get("/portal")
async def billing_portal(request: Request):
    """Redirect to Stripe Customer Portal for subscription management."""
    _ensure_stripe(request)
    user = await require_user(request)
    db = request.app.state.db

    sub = await db.get_subscription(user["id"])
    if not sub or not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No active subscription found")

    base_url = f"{request.base_url}".rstrip("/")
    session = stripe.billing_portal.Session.create(
        customer=sub["stripe_customer_id"],
        return_url=base_url + "/account",
    )
    return RedirectResponse(url=session.url)


@router.get("/status")
async def billing_status(request: Request):
    """Get current subscription status."""
    user = await require_user(request)
    db = request.app.state.db
    sub = await db.get_subscription(user["id"])

    stripe_configured = bool(request.app.state.settings.stripe.secret_key)

    return {
        "tier": user["tier"],
        "stripe_enabled": stripe_configured and _HAS_STRIPE,
        "subscription": {
            "status": sub.get("status"),
            "tier": sub.get("tier"),
            "current_period_end": sub.get("current_period_end"),
        } if sub else None,
    }
