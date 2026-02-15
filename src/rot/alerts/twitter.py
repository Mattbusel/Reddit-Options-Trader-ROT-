"""Automated X/Twitter posting for ROT signal marketing.

Posts the top signal every N hours to the ROT X account.
Uses X API v2 with OAuth 1.0a User Context (manual signing via httpx).

Required environment variables:
  ROT_TWITTER_API_KEY         - Consumer / API key
  ROT_TWITTER_API_SECRET      - Consumer / API secret
  ROT_TWITTER_ACCESS_TOKEN    - User access token (for the ROT account)
  ROT_TWITTER_ACCESS_SECRET   - User access token secret
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
import urllib.parse
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger(__name__)

_X_TWEET_URL = "https://api.x.com/2/tweets"

# Stance emoji mapping
_STANCE_EMOJI = {
    "bullish": "\U0001f7e2",   # green circle
    "bearish": "\U0001f534",   # red circle
    "mixed": "\U0001f7e1",     # yellow circle
    "unknown": "\u26aa",       # white circle
}


# ── OAuth 1.0a signing ──

def _oauth1_sign(
    method: str,
    url: str,
    params: Dict[str, str],
    consumer_secret: str,
    token_secret: str,
) -> str:
    """Compute OAuth 1.0a HMAC-SHA1 signature."""
    # 1. Percent-encode and sort params
    encoded = sorted(
        (urllib.parse.quote(k, safe=""), urllib.parse.quote(v, safe=""))
        for k, v in params.items()
    )
    param_string = "&".join(f"{k}={v}" for k, v in encoded)

    # 2. Signature base string
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_string, safe=""),
    ])

    # 3. Signing key
    signing_key = (
        urllib.parse.quote(consumer_secret, safe="")
        + "&"
        + urllib.parse.quote(token_secret, safe="")
    )

    # 4. HMAC-SHA1 (required by Twitter OAuth 1.0a spec - not for cryptographic security)
    digest = hmac.new(
        signing_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha1,  # nosec B303 - OAuth 1.0a protocol requirement, not password hashing
    ).digest()

    return base64.b64encode(digest).decode("utf-8")


def _build_oauth_header(
    method: str,
    url: str,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_secret: str,
) -> str:
    """Build the OAuth 1.0a Authorization header value."""
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    signature = _oauth1_sign(method, url, oauth_params, api_secret, access_secret)
    oauth_params["oauth_signature"] = signature

    header_parts = ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# ── Tweet formatting ──

def format_tweet(signal: Dict[str, Any], dashboard_url: str = "") -> str:
    """Format a signal dict (from DB row) into a tweet string (<= 280 chars)."""
    ticker = signal.get("ticker", "???")
    stance = signal.get("stance", "unknown")
    confidence = signal.get("confidence", 0)
    strategy = signal.get("strategy", "none")
    event_type = signal.get("event_type", "other")
    time_horizon = signal.get("time_horizon", "unknown")

    emoji = _STANCE_EMOJI.get(stance, _STANCE_EMOJI["unknown"])

    # Format confidence as percentage
    if isinstance(confidence, float) and confidence <= 1:
        conf_pct = f"{confidence * 100:.0f}%"
    else:
        conf_pct = f"{confidence:.0f}%"

    # Clean up display strings
    strategy_display = strategy.replace("_", " ").title() if strategy != "none" else ""
    event_display = event_type.replace("_", " ").title()
    horizon_display = time_horizon if time_horizon not in ("unknown", "") else ""

    # Build tweet lines
    lines = [f"{emoji} ${ticker} Signal: {stance.upper()} ({conf_pct} confidence)", ""]

    if strategy_display:
        lines.append(f"\U0001f4ca Strategy: {strategy_display}")
    lines.append(f"\U0001f4f0 Event: {event_display}")
    if horizon_display:
        lines.append(f"\u23f0 Horizon: {horizon_display}")

    # Link to dashboard
    if dashboard_url:
        lines.append("")
        lines.append(f"Track live \u2192 {dashboard_url}/dashboard?ticker={ticker}")

    lines.append("")
    lines.append(f"#options #trading #{ticker} #stocks")

    tweet = "\n".join(lines)

    # Safety: truncate if somehow over 280 (shouldn't happen with our format)
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    return tweet


# ── XPoster class ──

class XPoster:
    """Posts signals to X/Twitter via API v2."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_secret: str,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_secret = access_secret

    @property
    def is_configured(self) -> bool:
        return bool(
            self.api_key and self.api_secret
            and self.access_token and self.access_secret
        )

    async def post_tweet(self, text: str) -> Optional[str]:
        """Post a tweet. Returns the tweet ID on success, None on failure."""
        if not self.is_configured:
            log.warning("X/Twitter credentials not configured, skipping post")
            return None

        auth_header = _build_oauth_header(
            method="POST",
            url=_X_TWEET_URL,
            api_key=self.api_key,
            api_secret=self.api_secret,
            access_token=self.access_token,
            access_secret=self.access_secret,
        )

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    _X_TWEET_URL,
                    json={"text": text},
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                    },
                    timeout=15.0,
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    tweet_id = data.get("data", {}).get("id", "")
                    log.info("Tweet posted successfully (id=%s)", tweet_id)
                    return tweet_id
                else:
                    log.error(
                        "X API error %d: %s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    return None
        except Exception as e:
            log.error("X post failed: %s", e)
            return None
