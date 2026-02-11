"""SEO routes: robots.txt and sitemap.xml for search engine crawling."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

router = APIRouter()

# Public pages to include in the sitemap
_PUBLIC_PAGES = [
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
