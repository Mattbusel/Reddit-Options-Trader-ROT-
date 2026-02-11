"""HTML email templates for ROT signal alerts and digests."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _stance_color(stance: str) -> str:
    return {"bullish": "#4ade80", "bearish": "#f87171", "mixed": "#fbbf24"}.get(
        stance, "#9ca3af"
    )


def _format_ts(ts: float) -> str:
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_signal_alert(signal: Dict[str, Any]) -> str:
    """Render a single-signal alert email."""
    ticker = signal.get("ticker", "UNKNOWN")
    stance = signal.get("stance", "unknown")
    confidence = signal.get("confidence", 0)
    event_type = signal.get("event_type", "other")
    strategy = signal.get("strategy", "none")
    reasoning = signal.get("reasoning", {}) or {}
    thesis = reasoning.get("thesis", "") if isinstance(reasoning, dict) else ""
    color = _stance_color(stance)
    conf_pct = int(confidence * 100)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:Arial,sans-serif;padding:20px;">
  <div style="max-width:600px;margin:0 auto;background:#16213e;border-radius:12px;overflow:hidden;">
    <div style="background:{color};padding:16px 24px;">
      <h1 style="margin:0;color:#000;font-size:24px;">{ticker} &mdash; {stance.upper()}</h1>
    </div>
    <div style="padding:24px;">
      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
        <tr>
          <td style="padding:8px;color:#9ca3af;">Confidence</td>
          <td style="padding:8px;font-weight:bold;">{conf_pct}%</td>
          <td style="padding:8px;color:#9ca3af;">Event</td>
          <td style="padding:8px;font-weight:bold;">{event_type}</td>
        </tr>
        <tr>
          <td style="padding:8px;color:#9ca3af;">Strategy</td>
          <td style="padding:8px;font-weight:bold;">{strategy}</td>
          <td style="padding:8px;color:#9ca3af;">Time</td>
          <td style="padding:8px;font-weight:bold;">{_format_ts(signal.get('created_at', 0))}</td>
        </tr>
      </table>
      {"<div style='background:#0f3460;padding:16px;border-radius:8px;margin-top:12px;'><p style='color:#9ca3af;margin:0 0 4px;font-size:12px;'>THESIS</p><p style='margin:0;'>" + thesis + "</p></div>" if thesis else ""}
      <div style="margin-top:24px;text-align:center;">
        <a href="#" style="background:{color};color:#000;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;">View on Dashboard</a>
      </div>
    </div>
    <div style="padding:12px 24px;border-top:1px solid #2a2a4a;text-align:center;font-size:11px;color:#666;">
      Reddit Options Trader (ROT) &mdash; Manage alerts in Account Settings
    </div>
  </div>
</body>
</html>"""


def render_daily_digest(
    signals: List[Dict[str, Any]], summary: Dict[str, Any]
) -> str:
    """Render a daily digest email with top signals."""
    total = summary.get("total_signals", 0)
    bullish = summary.get("bullish_count", 0)
    bearish = summary.get("bearish_count", 0)

    signal_rows = ""
    for s in signals[:10]:
        ticker = s.get("ticker", "?")
        stance = s.get("stance", "unknown")
        conf = int(s.get("confidence", 0) * 100)
        color = _stance_color(stance)
        signal_rows += f"""
        <tr style="border-bottom:1px solid #2a2a4a;">
          <td style="padding:10px;font-weight:bold;">{ticker}</td>
          <td style="padding:10px;"><span style="color:{color};font-weight:bold;">{stance.upper()}</span></td>
          <td style="padding:10px;">{conf}%</td>
          <td style="padding:10px;">{s.get('event_type', 'other')}</td>
          <td style="padding:10px;">{s.get('strategy', 'none')}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:Arial,sans-serif;padding:20px;">
  <div style="max-width:600px;margin:0 auto;background:#16213e;border-radius:12px;overflow:hidden;">
    <div style="background:#3b82f6;padding:16px 24px;">
      <h1 style="margin:0;color:#fff;font-size:22px;">Daily Signal Digest</h1>
    </div>
    <div style="padding:24px;">
      <div style="display:flex;gap:16px;margin-bottom:20px;">
        <div style="flex:1;background:#0f3460;padding:12px;border-radius:8px;text-align:center;">
          <div style="font-size:28px;font-weight:bold;">{total}</div>
          <div style="color:#9ca3af;font-size:12px;">Total Signals</div>
        </div>
        <div style="flex:1;background:#0f3460;padding:12px;border-radius:8px;text-align:center;">
          <div style="font-size:28px;font-weight:bold;color:#4ade80;">{bullish}</div>
          <div style="color:#9ca3af;font-size:12px;">Bullish</div>
        </div>
        <div style="flex:1;background:#0f3460;padding:12px;border-radius:8px;text-align:center;">
          <div style="font-size:28px;font-weight:bold;color:#f87171;">{bearish}</div>
          <div style="color:#9ca3af;font-size:12px;">Bearish</div>
        </div>
      </div>

      <h2 style="font-size:16px;margin:20px 0 12px;">Top Signals</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr style="color:#9ca3af;border-bottom:1px solid #2a2a4a;">
          <th style="padding:8px;text-align:left;">Ticker</th>
          <th style="padding:8px;text-align:left;">Stance</th>
          <th style="padding:8px;text-align:left;">Conf</th>
          <th style="padding:8px;text-align:left;">Event</th>
          <th style="padding:8px;text-align:left;">Strategy</th>
        </tr>
        {signal_rows}
      </table>

      <div style="margin-top:24px;text-align:center;">
        <a href="#" style="background:#3b82f6;color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;">View All Signals</a>
      </div>
    </div>
    <div style="padding:12px 24px;border-top:1px solid #2a2a4a;text-align:center;font-size:11px;color:#666;">
      Reddit Options Trader (ROT) &mdash; Manage alerts in Account Settings
    </div>
  </div>
</body>
</html>"""
