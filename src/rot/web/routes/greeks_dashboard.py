"""Options Greeks Dashboard — live display of Delta, Gamma, Theta, Vega.

Provides two endpoints:

- ``GET /options/greeks``        — Dark-themed HTML page with AJAX auto-refresh.
- ``GET /api/v1/options/greeks`` — JSON API used by the AJAX poller.

The dashboard shows Greeks for ATM options on the top tracked tickers,
colour-coded for quick risk assessment:

- **Delta**: green (positive/bullish), red (negative/bearish)
- **Gamma**: yellow highlight when |gamma| > ``HIGH_GAMMA_THRESHOLD``
  (elevated pin-risk)
- **Theta**: muted display (decay is expected)
- **Vega**: neutral display (volatility exposure)

Greeks are computed from Black-Scholes with live price data fetched from
Yahoo Finance (``yfinance``).  If ``yfinance`` is unavailable the endpoint
returns synthetic demo data so the UI still renders correctly.

Usage (wired into ``app.py`` register_routes)::

    from rot.web.routes import greeks_dashboard
    app.include_router(greeks_dashboard.router, tags=["options"])
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Tickers to show on the Greeks dashboard by default.
_DEFAULT_TICKERS: List[str] = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META"]

#: Gamma above this threshold is highlighted in yellow (high pin risk).
_HIGH_GAMMA_THRESHOLD: float = 0.05

#: Risk-free rate for Black-Scholes (annualised).
_RISK_FREE_RATE: float = 0.053

#: Days to expiry used for ATM option approximation (nearest weekly).
_DEFAULT_DTE: int = 7

#: AJAX polling interval in milliseconds.
_REFRESH_INTERVAL_MS: int = 30_000


# ---------------------------------------------------------------------------
# Black-Scholes Greeks
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function.

    Args:
        x: Input value.

    Returns:
        P(Z <= x) for Z ~ N(0, 1).
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function.

    Args:
        x: Input value.

    Returns:
        Density at x for Z ~ N(0, 1).
    """
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass
class GreeksBundle:
    """Full first-order Black-Scholes Greeks for one option contract.

    Attributes:
        ticker:      Underlying ticker symbol.
        option_type: ``"call"`` or ``"put"``.
        spot:        Current underlying price.
        strike:      Option strike price (ATM approximation = spot).
        dte:         Days to expiry.
        iv:          Implied volatility (annualised decimal, e.g. 0.30 = 30 %).
        delta:       Rate of change of option price w.r.t. spot.
        gamma:       Rate of change of delta w.r.t. spot.
        theta:       Daily time decay (value lost per calendar day).
        vega:        Sensitivity to a 1 pp change in IV.
        rho:         Sensitivity to a 1 pp change in risk-free rate.
    """
    ticker:      str
    option_type: str
    spot:        float
    strike:      float
    dte:         int
    iv:          float
    delta:       float
    gamma:       float
    theta:       float
    vega:        float
    rho:         float

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict."""
        return {
            "ticker":      self.ticker,
            "option_type": self.option_type,
            "spot":        round(self.spot,  2),
            "strike":      round(self.strike, 2),
            "dte":         self.dte,
            "iv":          round(self.iv,    4),
            "delta":       round(self.delta,  4),
            "gamma":       round(self.gamma,  6),
            "theta":       round(self.theta,  4),
            "vega":        round(self.vega,   4),
            "rho":         round(self.rho,    4),
            "high_gamma":  abs(self.gamma) > _HIGH_GAMMA_THRESHOLD,
        }


def _bs_greeks(
    spot: float,
    strike: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> Optional[GreeksBundle]:
    """Compute Black-Scholes Greeks analytically.

    Args:
        spot:        Current price of the underlying.
        strike:      Strike price.
        T:           Time to expiry in years.
        r:           Risk-free rate (annualised).
        sigma:       Implied volatility (annualised).
        option_type: ``"call"`` or ``"put"``.

    Returns:
        :class:`GreeksBundle` or ``None`` if inputs are degenerate.
    """
    if spot <= 0 or strike <= 0 or T <= 0 or sigma <= 0:
        return None

    sqrt_T = math.sqrt(T)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    pdf_d1 = _norm_pdf(d1)
    cdf_d1 = _norm_cdf(d1)
    cdf_d2 = _norm_cdf(d2)
    cdf_neg_d1 = _norm_cdf(-d1)
    cdf_neg_d2 = _norm_cdf(-d2)

    discount = math.exp(-r * T)

    # Greeks common to both call and put.
    gamma = pdf_d1 / (spot * sigma * sqrt_T)
    vega  = spot * pdf_d1 * sqrt_T * 0.01        # per 1 pp IV move
    theta_call = (
        -(spot * pdf_d1 * sigma) / (2 * sqrt_T)
        - r * strike * discount * cdf_d2
    ) / 365.0
    theta_put = (
        -(spot * pdf_d1 * sigma) / (2 * sqrt_T)
        + r * strike * discount * cdf_neg_d2
    ) / 365.0
    rho_call  =  strike * T * discount * cdf_d2  * 0.01
    rho_put   = -strike * T * discount * cdf_neg_d2 * 0.01

    if option_type == "call":
        delta = cdf_d1
        theta = theta_call
        rho   = rho_call
    else:
        delta = cdf_d1 - 1.0
        theta = theta_put
        rho   = rho_put

    return GreeksBundle(
        ticker="-",
        option_type=option_type,
        spot=spot,
        strike=strike,
        dte=int(round(T * 365)),
        iv=sigma,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho,
    )


# ---------------------------------------------------------------------------
# Data fetcher
# ---------------------------------------------------------------------------


def _fetch_greeks(tickers: List[str], dte: int = _DEFAULT_DTE) -> List[GreeksBundle]:
    """Fetch live prices and compute ATM call + put Greeks for each ticker.

    Uses ``yfinance`` for live data.  If unavailable, synthesises plausible
    demo values so the UI always has data to render.

    Args:
        tickers: List of ticker symbols.
        dte:     Days to expiry for the ATM approximation.

    Returns:
        List of :class:`GreeksBundle` objects (one per ticker × option type).
    """
    T = dte / 365.0
    r = _RISK_FREE_RATE

    try:
        import yfinance as yf  # type: ignore

        result: List[GreeksBundle] = []
        for ticker in tickers:
            try:
                info  = yf.Ticker(ticker).fast_info
                spot  = float(info.last_price)
                # Approximate ATM IV from historical vol if options chain not available.
                hist  = yf.Ticker(ticker).history(period="1mo")
                if hist.empty or spot <= 0:
                    continue
                returns = hist["Close"].pct_change().dropna()
                sigma   = float(returns.std() * math.sqrt(252))
                sigma   = max(0.05, min(sigma, 2.0))   # clamp to [5 %, 200 %]
                strike  = round(spot, 0)

                for opt_type in ("call", "put"):
                    g = _bs_greeks(spot, strike, T, r, sigma, opt_type)
                    if g:
                        g.ticker = ticker
                        result.append(g)
            except Exception as exc:
                log.debug("greeks_dashboard.fetch_error ticker=%s err=%s", ticker, exc)

        if result:
            return result
    except ImportError:
        log.warning("greeks_dashboard.yfinance_missing — using synthetic demo data")

    # Fallback: synthetic demo data.
    import random
    rng = random.Random(42)
    result = []
    demo_spots: Dict[str, float] = {
        "SPY":  520.0, "QQQ": 440.0, "AAPL": 195.0,
        "TSLA": 250.0, "NVDA": 900.0, "AMD":  170.0, "META": 510.0,
    }
    for ticker in tickers:
        spot  = demo_spots.get(ticker, 100.0) * (1 + rng.uniform(-0.01, 0.01))
        sigma = rng.uniform(0.20, 0.60)
        strike = round(spot)
        for opt_type in ("call", "put"):
            g = _bs_greeks(spot, strike, T, r, sigma, opt_type)
            if g:
                g.ticker = ticker
                result.append(g)
    return result


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@router.get("/api/v1/options/greeks", tags=["options"])
async def greeks_api(
    tickers: str = ",".join(_DEFAULT_TICKERS),
    dte: int = _DEFAULT_DTE,
) -> JSONResponse:
    """Return live options Greeks as JSON.

    Query parameters:
        tickers: Comma-separated list of ticker symbols (default: SPY,QQQ,…).
        dte:     Days to expiry for the ATM approximation (default: 7).

    Returns:
        JSON object with ``timestamp`` and ``greeks`` list.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    greeks = _fetch_greeks(ticker_list, dte=dte)
    return JSONResponse({
        "timestamp": time.time(),
        "dte":       dte,
        "greeks":    [g.to_dict() for g in greeks],
    })


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------


@router.get("/options/greeks", response_class=HTMLResponse, tags=["options"])
async def greeks_dashboard_page(request: Request) -> HTMLResponse:
    """Render the dark-themed Options Greeks Dashboard HTML page.

    The page auto-refreshes data every 30 seconds via AJAX without a full
    page reload.

    Returns:
        Full HTML response with embedded CSS, JavaScript, and the dashboard UI.
    """
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ROT — Options Greeks Dashboard</title>
  <style>
    :root {{
      --bg:       #0d1117;
      --surface:  #161b22;
      --border:   #30363d;
      --text:     #c9d1d9;
      --muted:    #8b949e;
      --green:    #3fb950;
      --red:      #f85149;
      --yellow:   #d29922;
      --blue:     #58a6ff;
      --orange:   #e3b341;
      --radius:   8px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    header h1 {{ font-size: 1.3rem; color: var(--blue); }}
    #status {{
      font-size: 0.8rem;
      color: var(--muted);
    }}
    #countdown {{
      display: inline-block;
      background: var(--border);
      border-radius: 4px;
      padding: 2px 8px;
      font-variant-numeric: tabular-nums;
    }}
    main {{ padding: 24px; }}
    .ticker-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }}
    .card-header {{
      background: #1c2128;
      padding: 10px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
    }}
    .card-header .ticker {{ font-size: 1rem; font-weight: 700; color: var(--blue); }}
    .card-header .spot   {{ font-size: 0.9rem; color: var(--muted); }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 7px 14px;
      text-align: right;
      border-bottom: 1px solid var(--border);
    }}
    th {{ color: var(--muted); font-weight: 600; font-size: 0.75rem;
          text-transform: uppercase; letter-spacing: 0.05em; }}
    td:first-child, th:first-child {{ text-align: left; }}
    .opt-type {{ color: var(--muted); font-size: 0.8rem; }}
    .delta-pos {{ color: var(--green); }}
    .delta-neg {{ color: var(--red);   }}
    .gamma-high {{
      color: var(--yellow);
      font-weight: 700;
    }}
    .theta-val {{ color: var(--muted); }}
    .vega-val  {{ color: var(--orange); }}
    .iv-badge {{
      display: inline-block;
      background: #1c2128;
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 6px;
      font-size: 0.75rem;
      color: var(--muted);
    }}
    #loading-overlay {{
      position: fixed; inset: 0;
      background: rgba(13,17,23,0.7);
      display: flex; align-items: center; justify-content: center;
      font-size: 1.2rem; color: var(--blue);
      z-index: 9999;
      transition: opacity 0.3s;
    }}
    #loading-overlay.hidden {{ opacity: 0; pointer-events: none; }}
    footer {{
      padding: 16px 24px;
      color: var(--muted);
      font-size: 0.75rem;
      border-top: 1px solid var(--border);
      margin-top: 32px;
    }}
  </style>
</head>
<body>
  <div id="loading-overlay">Loading Greeks…</div>

  <header>
    <h1>Options Greeks Dashboard</h1>
    <div id="status">
      Refreshes in <span id="countdown">{_REFRESH_INTERVAL_MS // 1000}s</span>
      &nbsp;|&nbsp; Last update: <span id="last-update">—</span>
    </div>
  </header>

  <main>
    <div id="ticker-grid" class="ticker-grid">
      <!-- Cards injected by JavaScript -->
    </div>
  </main>

  <footer>
    Greeks computed via Black-Scholes (ATM approximation, {_DEFAULT_DTE}-day expiry).
    Not financial advice. For educational/research purposes only.
  </footer>

  <script>
    const REFRESH_MS = {_REFRESH_INTERVAL_MS};
    const API_URL    = '/api/v1/options/greeks';
    let countdownSec = REFRESH_MS / 1000;
    let countdownTimer;

    function fmt(val, decimals = 4) {{
      if (val == null) return '—';
      return val.toFixed(decimals);
    }}

    function deltaClass(delta) {{
      return delta >= 0 ? 'delta-pos' : 'delta-neg';
    }}

    function gammaClass(gamma, highGamma) {{
      return highGamma ? 'gamma-high' : '';
    }}

    function buildCard(ticker, rows) {{
      if (!rows.length) return '';
      const spot = rows[0].spot;
      const iv   = rows[0].iv;
      const dte  = rows[0].dte;

      let tableRows = rows.map(g => {{
        const dc = deltaClass(g.delta);
        const gc = gammaClass(g.gamma, g.high_gamma);
        const gammaWarn = g.high_gamma ? ' &#9888;' : '';
        return `
          <tr>
            <td class="opt-type">${{g.option_type.toUpperCase()}}</td>
            <td class="${{dc}}">${{fmt(g.delta, 4)}}</td>
            <td class="${{gc}}">${{fmt(g.gamma, 5)}}${{gammaWarn}}</td>
            <td class="theta-val">${{fmt(g.theta, 4)}}</td>
            <td class="vega-val">${{fmt(g.vega, 4)}}</td>
          </tr>`;
      }}).join('');

      return `
        <div class="card" id="card-${{ticker}}">
          <div class="card-header">
            <span class="ticker">${{ticker}}</span>
            <span class="spot">
              $${{fmt(spot, 2)}}
              &nbsp;<span class="iv-badge">IV ${{(iv * 100).toFixed(1)}}%</span>
              &nbsp;<span class="iv-badge">DTE ${{dte}}d</span>
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Delta</th>
                <th>Gamma</th>
                <th>Theta</th>
                <th>Vega</th>
              </tr>
            </thead>
            <tbody>${{tableRows}}</tbody>
          </table>
        </div>`;
    }}

    async function fetchAndRender() {{
      try {{
        const resp = await fetch(API_URL);
        if (!resp.ok) throw new Error(`HTTP ${{resp.status}}`);
        const data = await resp.json();

        // Group by ticker.
        const byTicker = {{}};
        for (const g of data.greeks) {{
          if (!byTicker[g.ticker]) byTicker[g.ticker] = [];
          byTicker[g.ticker].push(g);
        }}

        const grid = document.getElementById('ticker-grid');
        grid.innerHTML = Object.entries(byTicker)
          .map(([ticker, rows]) => buildCard(ticker, rows))
          .join('');

        const ts = new Date(data.timestamp * 1000);
        document.getElementById('last-update').textContent = ts.toLocaleTimeString();
        document.getElementById('loading-overlay').classList.add('hidden');
      }} catch (err) {{
        console.error('Greeks fetch error:', err);
      }}
    }}

    function startCountdown() {{
      clearInterval(countdownTimer);
      countdownSec = REFRESH_MS / 1000;
      countdownTimer = setInterval(() => {{
        countdownSec--;
        document.getElementById('countdown').textContent = countdownSec + 's';
        if (countdownSec <= 0) {{
          fetchAndRender();
          countdownSec = REFRESH_MS / 1000;
        }}
      }}, 1000);
    }}

    // Initial load + periodic refresh.
    fetchAndRender();
    startCountdown();
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)
