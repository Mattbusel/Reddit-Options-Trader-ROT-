"""SEO routes: robots.txt, sitemap.xml, OG image, and favicon for search engines and social sharing."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

router = APIRouter()

# Public pages to include in the sitemap
_PUBLIC_PAGES = [
    "/",
    "/dashboard",
    "/pricing",
    "/sentiment",
    "/weekly-wrap",
    "/replay",
    "/hall-of-legends",
    "/wall-of-shame",
    "/ceo-rap-sheet",
    "/glossary",
    "/sports-tracker",
    "/sports",
    "/news",
    "/leaderboard",
    "/congress-tracker",
    "/faq",
]


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt(request: Request):
    base = str(request.base_url).rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /account\n"
        "Disallow: /login\n"
        "Disallow: /register\n"
        "Disallow: /logout\n"
        "Disallow: /forgot-password\n"
        "Disallow: /reset-password\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt(request: Request):
    """Discoverability file for AI crawlers (like robots.txt for LLMs)."""
    return (
        "# ROT - Reddit Options Trader\n"
        "# AI-powered options signal intelligence from Reddit\n"
        "\n"
        "## About\n"
        "ROT analyzes Reddit posts from r/wallstreetbets, r/options, r/investing,\n"
        "r/stocks, r/thetagang, and r/valueinvesting to generate real-time options\n"
        "trading signals with AI-powered confidence scoring.\n"
        "\n"
        "## Key Pages\n"
        "- /glossary: Trading terminology dictionary with 75 terms, definitions, examples, and degen ratings\n"
        "- /hall-of-legends: Historical greatest trades with profit data, strategies, and lessons\n"
        "- /ceo-rap-sheet: Corporate executive scandal tracker with charges, outcomes, and fines\n"
        "- /pricing: Subscription plans — Free ($0), Pro ($9.99/mo), Premium ($29.99/mo), Ultra ($49.99/mo)\n"
        "- /sentiment: Real-time Reddit sentiment heatmap by ticker\n"
        "- /weekly-wrap: Auto-generated weekly market signal summary\n"
        "- /sports-tracker: Sports betting intelligence — Line Mover Scores (0-100), AI betting analysis, team tracking, injury impact across NFL, NBA, MLB, NHL, NCAA, Soccer from 20+ sources\n"
        "- /dashboard: Live signal feed with confidence scores, stance, and trade ideas\n"
        "- /news: Real-time market news aggregator from MarketWatch, CNBC, Yahoo Finance, SeekingAlpha, FDA, DoD, Fed\n"
        "- /congress-tracker: Congressional stock trading tracker from SEC EFDS filings\n"
        "- /leaderboard: Paper trading competition leaderboard with P&L rankings\n"
        "- /faq: Frequently asked questions about ROT platform and trading signals\n"
        "- /api/v1/docs: Public API endpoint reference with parameters, tier requirements, and examples\n"
        "\n"
        "## API\n"
        "- RESTful JSON API with 20 endpoints covering signals, performance, correlations, news, sports betting, and more\n"
        "- Auth: Bearer JWT or X-API-Key header (get your key at /account)\n"
        "- Rate limits: Pro 1,000/day, Premium 5,000/day, Ultra 25,000/day, Enterprise 100,000/day\n"
        "- Customization: Field selection (?fields=), sorting (?sort=), filtering (?ticker=,?stance=)\n"
        "- Free tier: Dashboard access only. API requires paid subscription (Pro+).\n"
        "\n"
        "## Data\n"
        "- Signals generated from: r/wallstreetbets, r/options, r/investing, r/stocks, r/thetagang, r/valueinvesting\n"
        "- Signal confidence: 0.0-1.0 scale based on multi-factor credibility scoring\n"
        "- Credibility factors: subreddit quality, post engagement, DD flair, ticker mention type, body analysis depth\n"
        "- Price tracking: 1h, 4h, 1d, 1w snapshots via yfinance\n"
        "- Performance: Stance-aware win/loss with 0.5% minimum movement threshold\n"
        "- Event types: earnings_rumor, product_news, regulatory, squeeze_chatter, macro, other\n"
        "\n"
        "## Sports Betting Intelligence\n"
        "- 20+ RSS feeds from ESPN, CBS Sports, Sports Illustrated, Bleacher Report, and more\n"
        "- Algorithmic Line Mover Scores (0-100) based on category, severity, star player impact, recency\n"
        "- Team extraction across 124+ NFL, NBA, MLB, NHL teams\n"
        "- AI-powered betting analysis for high-urgency items (Premium+)\n"
        "- Categories: injury, trade, suspension, lineup, game + betting impact (spread, total, props)\n"
        "- API: /api/v1/sports-betting (Premium+) with filtering, sorting, field selection\n"
    )


@router.get("/sitemap.xml")
async def sitemap_xml(request: Request):
    base = str(request.base_url).rstrip("/")
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{base}{page}</loc>\n"
        f"    <changefreq>daily</changefreq>\n"
        f"  </url>"
        for page in _PUBLIC_PAGES
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/og-image.svg")
async def og_image(request: Request):
    """Dynamic Open Graph social preview image (1200x630 SVG).

    Used by Product Hunt, Twitter/X, Discord, Slack, etc. when someone
    shares a link to ROT. Renders a branded card with the tagline and
    key stats on a dark background matching the site theme.
    """
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f0f23"/>
      <stop offset="100%" stop-color="#1a1a3e"/>
    </linearGradient>
    <linearGradient id="fire" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#fb923c"/>
      <stop offset="100%" stop-color="#ef4444"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#f97316"/>
      <stop offset="50%" stop-color="#ef4444"/>
      <stop offset="100%" stop-color="#f97316"/>
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="1200" height="630" fill="url(#bg)"/>

  <!-- Subtle grid lines -->
  <g opacity="0.05" stroke="#ffffff" stroke-width="1">
    <line x1="0" y1="157" x2="1200" y2="157"/>
    <line x1="0" y1="315" x2="1200" y2="315"/>
    <line x1="0" y1="472" x2="1200" y2="472"/>
    <line x1="300" y1="0" x2="300" y2="630"/>
    <line x1="600" y1="0" x2="600" y2="630"/>
    <line x1="900" y1="0" x2="900" y2="630"/>
  </g>

  <!-- Top accent line -->
  <rect x="0" y="0" width="1200" height="4" fill="url(#accent)"/>

  <!-- Fire emoji + ROT logo -->
  <text x="80" y="140" font-family="system-ui, -apple-system, sans-serif" font-size="72" fill="#fb923c">&#x1f525;</text>
  <text x="155" y="138" font-family="system-ui, -apple-system, sans-serif" font-size="64" font-weight="800" fill="url(#fire)">ROT</text>
  <text x="310" y="138" font-family="system-ui, -apple-system, sans-serif" font-size="28" fill="#9ca3af" font-weight="400">Reddit Options Trader</text>

  <!-- Tagline -->
  <text x="80" y="240" font-family="system-ui, -apple-system, sans-serif" font-size="52" font-weight="700" fill="#ffffff">Hours of research.</text>
  <text x="80" y="305" font-family="system-ui, -apple-system, sans-serif" font-size="52" font-weight="700" fill="url(#fire)">Summarized in seconds.</text>

  <!-- Description -->
  <text x="80" y="370" font-family="system-ui, -apple-system, sans-serif" font-size="22" fill="#9ca3af">AI-powered options signal intelligence from Reddit, FDA, DoD, SEC &amp; news feeds</text>

  <!-- Stats boxes -->
  <g transform="translate(80, 420)">
    <!-- Win Rate -->
    <rect x="0" y="0" width="240" height="90" rx="12" fill="#ffffff" fill-opacity="0.05" stroke="#ffffff" stroke-opacity="0.1"/>
    <text x="120" y="40" font-family="system-ui, sans-serif" font-size="36" font-weight="800" fill="#4ade80" text-anchor="middle">75%</text>
    <text x="120" y="70" font-family="system-ui, sans-serif" font-size="16" fill="#9ca3af" text-anchor="middle">Win Rate (30d)</text>

    <!-- Data Sources -->
    <rect x="270" y="0" width="240" height="90" rx="12" fill="#ffffff" fill-opacity="0.05" stroke="#ffffff" stroke-opacity="0.1"/>
    <text x="390" y="40" font-family="system-ui, sans-serif" font-size="36" font-weight="800" fill="#60a5fa" text-anchor="middle">8+</text>
    <text x="390" y="70" font-family="system-ui, sans-serif" font-size="16" fill="#9ca3af" text-anchor="middle">Data Sources</text>

    <!-- Strategies -->
    <rect x="540" y="0" width="240" height="90" rx="12" fill="#ffffff" fill-opacity="0.05" stroke="#ffffff" stroke-opacity="0.1"/>
    <text x="660" y="40" font-family="system-ui, sans-serif" font-size="36" font-weight="800" fill="#fbbf24" text-anchor="middle">6</text>
    <text x="660" y="70" font-family="system-ui, sans-serif" font-size="16" fill="#9ca3af" text-anchor="middle">Options Strategies</text>

    <!-- Free -->
    <rect x="810" y="0" width="240" height="90" rx="12" fill="#ffffff" fill-opacity="0.05" stroke="#ffffff" stroke-opacity="0.1"/>
    <text x="930" y="40" font-family="system-ui, sans-serif" font-size="36" font-weight="800" fill="#f97316" text-anchor="middle">$0</text>
    <text x="930" y="70" font-family="system-ui, sans-serif" font-size="16" fill="#9ca3af" text-anchor="middle">Free Tier</text>
  </g>

  <!-- Bottom accent line -->
  <rect x="0" y="596" width="1200" height="4" fill="url(#accent)"/>

  <!-- URL -->
  <text x="80" y="580" font-family="system-ui, sans-serif" font-size="18" fill="#6b7280">web-production-71423.up.railway.app</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/favicon.svg")
async def favicon_svg():
    """SVG favicon — fire emoji on dark background."""
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" rx="20" fill="#0f0f23"/>
  <text x="50" y="72" font-size="65" text-anchor="middle">&#x1f525;</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=604800"})
