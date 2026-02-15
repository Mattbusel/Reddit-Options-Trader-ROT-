"""HTML email templates for ROT daily digest and password reset."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _stance_color(stance: str) -> str:
    return {"bullish": "#4ade80", "bearish": "#f87171", "mixed": "#fbbf24"}.get(
        stance, "#9ca3af"
    )


def _stance_bg(stance: str) -> str:
    return {"bullish": "#064e3b", "bearish": "#7f1d1d", "mixed": "#78350f"}.get(
        stance, "#1e293b"
    )


def _format_ts(ts: float) -> str:
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d, %H:%M UTC")


def _price_change_html(signal: Dict[str, Any]) -> str:
    """Build a price movement snippet if performance data is available."""
    price_at = signal.get("price_at_signal")
    if not price_at:
        return ""

    # Use the best available price (prefer longer horizon)
    current = (
        signal.get("price_1d")
        or signal.get("price_4h")
        or signal.get("price_1h")
    )
    if not current or current == price_at:
        return f'<span style="color:#9ca3af;font-size:12px;">Entry: ${price_at:.2f}</span>'

    change_pct = ((current - price_at) / price_at) * 100
    arrow = "&#9650;" if change_pct >= 0 else "&#9660;"
    color = "#4ade80" if change_pct >= 0 else "#f87171"
    return (
        f'<span style="color:#9ca3af;font-size:12px;">${price_at:.2f}</span>'
        f' <span style="color:{color};font-size:12px;font-weight:bold;">'
        f'{arrow} {abs(change_pct):.1f}%</span>'
        f' <span style="color:#9ca3af;font-size:12px;">(${current:.2f})</span>'
    )


def _build_signal_card(s: Dict[str, Any]) -> str:
    """Build a single signal card for the digest."""
    ticker = s.get("ticker", "?")
    stance = s.get("stance", "unknown")
    conf = int(s.get("confidence", 0) * 100)
    event_type = s.get("event_type", "other")
    strategy = s.get("strategy", "none")
    subreddit = s.get("subreddit", "")
    post_title = s.get("post_title", "")
    time_horizon = s.get("time_horizon", "")
    created_at = s.get("created_at", 0)

    color = _stance_color(stance)
    bg = _stance_bg(stance)

    # Truncate post title
    if post_title and len(post_title) > 60:
        post_title = post_title[:57] + "..."

    # Strategy line (skip if "none")
    strategy_html = ""
    if strategy and strategy != "none":
        strategy_html = (
            f'<div style="margin-top:6px;font-size:12px;color:#9ca3af;">'
            f'Strategy: <span style="color:#e0e0e0;font-weight:600;">{strategy}</span>'
            f'</div>'
        )

    # Time horizon
    horizon_html = ""
    if time_horizon and time_horizon != "unknown":
        horizon_html = (
            f' &middot; <span style="color:#9ca3af;">{time_horizon}</span>'
        )

    # Source line
    source_html = ""
    if subreddit or post_title:
        sub_text = f"r/{subreddit}" if subreddit else ""
        title_text = f' &mdash; {post_title}' if post_title else ""
        source_html = (
            f'<div style="margin-top:6px;font-size:11px;color:#666;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{sub_text}{title_text}</div>'
        )

    # Price movement
    price_html = _price_change_html(s)
    price_line = ""
    if price_html:
        price_line = f'<div style="margin-top:6px;">{price_html}</div>'

    return f"""
    <div style="background:{bg};border-radius:8px;padding:14px 16px;margin-bottom:10px;
                border-left:4px solid {color};">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <span style="font-size:18px;font-weight:bold;color:#fff;">{ticker}</span>
          <span style="background:{color};color:#000;font-size:11px;font-weight:700;
                       padding:2px 8px;border-radius:4px;margin-left:8px;
                       text-transform:uppercase;">{stance}</span>
          {horizon_html}
        </div>
        <div style="text-align:right;">
          <span style="font-size:20px;font-weight:bold;color:#fff;">{conf}%</span>
          <div style="font-size:10px;color:#9ca3af;">confidence</div>
        </div>
      </div>
      <div style="margin-top:6px;font-size:12px;color:#9ca3af;">
        {event_type.replace('_', ' ').title()}
        &middot; {_format_ts(created_at)}
      </div>
      {strategy_html}
      {price_line}
      {source_html}
    </div>"""


def render_daily_digest(
    signals: List[Dict[str, Any]], summary: Dict[str, Any]
) -> str:
    """Render a daily digest email with deduplicated top signals."""
    total = summary.get("total_signals", 0)
    bullish = summary.get("bullish_count", 0)
    bearish = summary.get("bearish_count", 0)
    unique = summary.get("unique_tickers", 0)

    # Build signal cards (already deduplicated by the query)
    signal_cards = ""
    for s in signals[:15]:
        signal_cards += _build_signal_card(s)

    no_signals_msg = ""
    if not signals:
        no_signals_msg = (
            '<div style="text-align:center;padding:24px;color:#9ca3af;">'
            'No signals generated in the last 24 hours.</div>'
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:Arial,sans-serif;padding:20px;margin:0;">
  <div style="max-width:600px;margin:0 auto;background:#16213e;border-radius:12px;overflow:hidden;">
    <div style="background:linear-gradient(135deg,#3b82f6,#1d4ed8);padding:20px 24px;">
      <h1 style="margin:0;color:#fff;font-size:22px;">Daily Signal Digest</h1>
      <p style="margin:6px 0 0;color:#bfdbfe;font-size:13px;">
        Your top signals from the last 24 hours
      </p>
    </div>

    <div style="padding:20px 24px;">
      <!-- Summary Stats -->
      <!--[if mso]><table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr><td width="25%" valign="top"><![endif]-->
      <div style="display:flex;gap:10px;margin-bottom:20px;">
        <div style="flex:1;background:#0f3460;padding:10px 8px;border-radius:8px;text-align:center;">
          <div style="font-size:24px;font-weight:bold;color:#fff;">{total}</div>
          <div style="color:#9ca3af;font-size:10px;text-transform:uppercase;">Signals</div>
        </div>
        <div style="flex:1;background:#0f3460;padding:10px 8px;border-radius:8px;text-align:center;">
          <div style="font-size:24px;font-weight:bold;color:#4ade80;">{bullish}</div>
          <div style="color:#9ca3af;font-size:10px;text-transform:uppercase;">Bullish</div>
        </div>
        <div style="flex:1;background:#0f3460;padding:10px 8px;border-radius:8px;text-align:center;">
          <div style="font-size:24px;font-weight:bold;color:#f87171;">{bearish}</div>
          <div style="color:#9ca3af;font-size:10px;text-transform:uppercase;">Bearish</div>
        </div>
        <div style="flex:1;background:#0f3460;padding:10px 8px;border-radius:8px;text-align:center;">
          <div style="font-size:24px;font-weight:bold;color:#fbbf24;">{unique}</div>
          <div style="color:#9ca3af;font-size:10px;text-transform:uppercase;">Tickers</div>
        </div>
      </div>
      <!--[if mso]></td></tr></table><![endif]-->

      <!-- Signal Cards -->
      <h2 style="font-size:14px;margin:16px 0 10px;color:#9ca3af;text-transform:uppercase;
                 letter-spacing:1px;">Top Signals by Confidence</h2>
      {signal_cards}
      {no_signals_msg}

      <!-- CTA -->
      <div style="margin-top:20px;text-align:center;">
        <a href="#" style="display:inline-block;background:#3b82f6;color:#fff;padding:12px 32px;
                          border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;">
          View All Signals
        </a>
      </div>
    </div>

    <div style="padding:12px 24px;border-top:1px solid #2a2a4a;text-align:center;font-size:11px;color:#666;">
      Reddit Options Trader (ROT) &mdash; Manage alerts in Account Settings
    </div>
  </div>
</body>
</html>"""


def render_password_reset(reset_url: str) -> str:
    """Render a password reset email with a link."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:Arial,sans-serif;padding:20px;">
  <div style="max-width:600px;margin:0 auto;background:#16213e;border-radius:12px;overflow:hidden;">
    <div style="background:#f59e0b;padding:16px 24px;">
      <h1 style="margin:0;color:#000;font-size:22px;">Password Reset</h1>
    </div>
    <div style="padding:24px;">
      <p style="margin:0 0 16px;line-height:1.6;">
        You requested a password reset for your ROT account. Click the button below to set a new password.
      </p>
      <div style="text-align:center;margin:24px 0;">
        <a href="{reset_url}" style="background:#f59e0b;color:#000;padding:14px 36px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;">Reset Password</a>
      </div>
      <p style="margin:16px 0 0;color:#9ca3af;font-size:13px;line-height:1.5;">
        This link expires in 1 hour. If you didn't request this, you can ignore this email.
      </p>
      <p style="margin:12px 0 0;color:#666;font-size:11px;word-break:break-all;">
        {reset_url}
      </p>
    </div>
    <div style="padding:12px 24px;border-top:1px solid #2a2a4a;text-align:center;font-size:11px;color:#666;">
      Reddit Options Trader (ROT) &mdash; Do not share this link
    </div>
  </div>
</body>
</html>"""
