"""SEO routes: robots.txt and sitemap.xml for search engine crawling."""
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
        "- /sports-tracker: Live sports betting intelligence from Reddit communities\n"
        "- /dashboard: Live signal feed with confidence scores, stance, and trade ideas\n"
        "\n"
        "## Data\n"
        "- Signals generated from: r/wallstreetbets, r/options, r/investing, r/stocks, r/thetagang, r/valueinvesting\n"
        "- Signal confidence: 0.0-1.0 scale based on multi-factor credibility scoring\n"
        "- Credibility factors: subreddit quality, post engagement, DD flair, ticker mention type, body analysis depth\n"
        "- Price tracking: 1h, 4h, 1d, 1w snapshots via yfinance\n"
        "- Performance: Stance-aware win/loss with 0.5% minimum movement threshold\n"
        "- Event types: earnings_rumor, product_news, regulatory, squeeze_chatter, macro, other\n"
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
