"""Report generation for backtest results.

Provides CSV export of trade logs and HTML report generation.
"""

from __future__ import annotations

import io
import csv
from typing import Any, Dict, List, Optional


def generate_csv_trades(trades: List[Dict[str, Any]]) -> str:
    """Generate CSV content from a list of trade dicts.

    Args:
        trades: list of trade dicts (from BacktestResult.to_dict()["trades"])

    Returns:
        CSV string with header row + one row per trade.
    """
    if not trades:
        return "signal_id,ticker,stance,strategy,event_type,confidence,entry_price,exit_price,pnl_pct,pnl_dollars,is_win\n"

    output = io.StringIO()
    fieldnames = [
        "signal_id",
        "ticker",
        "stance",
        "strategy",
        "event_type",
        "confidence",
        "entry_price",
        "exit_price",
        "pnl_pct",
        "pnl_dollars",
        "is_win",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for trade in trades:
        writer.writerow({
            "signal_id": trade.get("signal_id", ""),
            "ticker": trade.get("ticker", ""),
            "stance": trade.get("stance", ""),
            "strategy": trade.get("strategy", ""),
            "event_type": trade.get("event_type", ""),
            "confidence": round(trade.get("confidence", 0), 3),
            "entry_price": round(trade.get("entry_price", 0), 2),
            "exit_price": round(trade.get("exit_price", 0), 2),
            "pnl_pct": round(trade.get("pnl_pct", 0), 2),
            "pnl_dollars": round(trade.get("pnl_dollars", 0), 2),
            "is_win": trade.get("is_win", False),
        })

    return output.getvalue()


def generate_html_report(
    result_dict: Dict[str, Any],
    risk_dict: Optional[Dict[str, Any]] = None,
    mc_dict: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a standalone HTML report from backtest results.

    Args:
        result_dict: serialized BacktestResult dict
        risk_dict: optional serialized RiskMetrics dict
        mc_dict: optional serialized MonteCarloResult dict

    Returns:
        Complete HTML string for standalone viewing.
    """
    total_trades = result_dict.get("total_trades", 0)
    win_rate = (result_dict.get("win_rate", 0) or 0) * 100
    total_return = result_dict.get("total_return_pct", 0) or 0
    final_equity = result_dict.get("final_equity", 0) or 0
    max_dd = result_dict.get("max_drawdown_pct", 0) or 0
    sharpe = result_dict.get("sharpe_ratio")
    profit_factor = result_dict.get("profit_factor", 0) or 0

    # Build trades table rows
    trades_html = ""
    for i, t in enumerate(result_dict.get("trades", [])[:100], 1):
        pnl = t.get("pnl_pct", 0) or 0
        pnl_color = "#4ade80" if pnl >= 0 else "#f87171"
        result_badge = "WIN" if t.get("is_win") else "LOSS"
        badge_bg = "#166534" if t.get("is_win") else "#991b1b"
        trades_html += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td><strong>{t.get('ticker', '')}</strong></td>"
            f"<td>{t.get('stance', '')}</td>"
            f"<td>{t.get('strategy', '')}</td>"
            f"<td>{(t.get('confidence', 0) or 0) * 100:.0f}%</td>"
            f"<td>${t.get('entry_price', 0):.2f}</td>"
            f"<td>${t.get('exit_price', 0):.2f}</td>"
            f"<td style='color:{pnl_color};font-weight:bold'>{pnl:+.2f}%</td>"
            f"<td><span style='background:{badge_bg};padding:2px 6px;border-radius:4px;font-size:11px'>{result_badge}</span></td>"
            f"</tr>\n"
        )

    # Risk section
    risk_html = ""
    if risk_dict:
        risk_html = "<h2>Risk Analytics</h2><table>"
        for key, val in risk_dict.items():
            if isinstance(val, (int, float)):
                risk_html += f"<tr><td>{key.replace('_', ' ').title()}</td><td>{val:.2f}</td></tr>"
        risk_html += "</table>"

    # Monte Carlo section
    mc_html = ""
    if mc_dict:
        mc_html = (
            "<h2>Monte Carlo Simulation</h2>"
            f"<p>{mc_dict.get('n_simulations', 0)} simulations, "
            f"{mc_dict.get('n_trades', 0)} trades</p>"
            "<table>"
            f"<tr><td>Prob. Profit</td><td>{(mc_dict.get('prob_profit', 0) or 0) * 100:.0f}%</td></tr>"
            f"<tr><td>Prob. Ruin</td><td>{(mc_dict.get('prob_ruin', 0) or 0) * 100:.1f}%</td></tr>"
            f"<tr><td>Median Final Equity</td><td>${mc_dict.get('final_equity_p50', 0):,.0f}</td></tr>"
            f"<tr><td>5th Pct Equity</td><td>${mc_dict.get('final_equity_p5', 0):,.0f}</td></tr>"
            f"<tr><td>95th Pct Equity</td><td>${mc_dict.get('final_equity_p95', 0):,.0f}</td></tr>"
            "</table>"
        )

    sharpe_display = f"{sharpe:.3f}" if sharpe is not None else "N/A"
    return_color = "#4ade80" if total_return >= 0 else "#f87171"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ROT Backtest Report</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; background: #111827; color: #e5e7eb; margin: 0; padding: 20px; }}
h1 {{ color: #fff; font-size: 24px; }}
h2 {{ color: #fff; font-size: 18px; margin-top: 30px; border-bottom: 1px solid #374151; padding-bottom: 8px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin: 20px 0; }}
.kpi {{ background: rgba(31,41,55,0.8); border: 1px solid #374151; border-radius: 8px; padding: 14px; }}
.kpi .label {{ font-size: 11px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.kpi .value {{ font-size: 22px; font-weight: bold; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; color: #9ca3af; border-bottom: 1px solid #374151; padding: 8px; font-weight: 600; }}
td {{ padding: 8px; border-bottom: 1px solid #1f2937; }}
tr:hover {{ background: rgba(31,41,55,0.5); }}
.footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #374151; font-size: 12px; color: #6b7280; }}
</style>
</head>
<body>
<h1>ROT Backtest Report</h1>
<p style="color:#9ca3af;font-size:14px">Generated by ROT Backtesting Engine</p>

<div class="kpi-grid">
<div class="kpi"><div class="label">Total Trades</div><div class="value" style="color:#fff">{total_trades}</div></div>
<div class="kpi"><div class="label">Win Rate</div><div class="value" style="color:{'#4ade80' if win_rate >= 50 else '#f87171'}">{win_rate:.1f}%</div></div>
<div class="kpi"><div class="label">Total Return</div><div class="value" style="color:{return_color}">{total_return:+.1f}%</div></div>
<div class="kpi"><div class="label">Final Equity</div><div class="value" style="color:#fff">${final_equity:,.0f}</div></div>
<div class="kpi"><div class="label">Max Drawdown</div><div class="value" style="color:#f87171">{max_dd:.1f}%</div></div>
<div class="kpi"><div class="label">Sharpe Ratio</div><div class="value" style="color:#fff">{sharpe_display}</div></div>
<div class="kpi"><div class="label">Profit Factor</div><div class="value" style="color:{'#4ade80' if profit_factor > 1 else '#f87171'}">{profit_factor:.2f}</div></div>
</div>

{risk_html}
{mc_html}

<h2>Trade Log</h2>
<table>
<thead>
<tr><th>#</th><th>Ticker</th><th>Stance</th><th>Strategy</th><th>Conf</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Result</th></tr>
</thead>
<tbody>
{trades_html}
</tbody>
</table>

<div class="footer">
Report generated by ROT (Reddit Options Trader) Backtesting Engine.
</div>
</body>
</html>"""

    return html
