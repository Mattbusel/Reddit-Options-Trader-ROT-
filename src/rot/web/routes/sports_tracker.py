"""Sports Betting News Tracker — Injuries, trades, suspensions & lineup news for bettors."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

log = logging.getLogger(__name__)

router = APIRouter()

# ── Sports RSS Feeds ──
# Focused on injury reports, transactions, and breaking news that move lines.

SPORTS_FEEDS = [
    # ── NFL ──
    {
        "url": "https://www.espn.com/espn/rss/nfl/news",
        "label": "ESPN NFL",
        "league": "NFL",
        "icon": "\U0001F3C8",  # football
    },
    {
        "url": "https://www.cbssports.com/rss/headlines/nfl/",
        "label": "CBS NFL",
        "league": "NFL",
        "icon": "\U0001F3C8",
    },
    # ── NBA ──
    {
        "url": "https://www.espn.com/espn/rss/nba/news",
        "label": "ESPN NBA",
        "league": "NBA",
        "icon": "\U0001F3C0",  # basketball
    },
    {
        "url": "https://www.cbssports.com/rss/headlines/nba/",
        "label": "CBS NBA",
        "league": "NBA",
        "icon": "\U0001F3C0",
    },
    # ── MLB ──
    {
        "url": "https://www.espn.com/espn/rss/mlb/news",
        "label": "ESPN MLB",
        "league": "MLB",
        "icon": "\u26BE",  # baseball
    },
    {
        "url": "https://www.cbssports.com/rss/headlines/mlb/",
        "label": "CBS MLB",
        "league": "MLB",
        "icon": "\u26BE",
    },
    # ── NHL ──
    {
        "url": "https://www.espn.com/espn/rss/nhl/news",
        "label": "ESPN NHL",
        "league": "NHL",
        "icon": "\U0001F3D2",  # ice hockey
    },
    {
        "url": "https://www.cbssports.com/rss/headlines/nhl/",
        "label": "CBS NHL",
        "league": "NHL",
        "icon": "\U0001F3D2",
    },
    # ── Soccer / MLS ──
    {
        "url": "https://www.espn.com/espn/rss/soccer/news",
        "label": "ESPN Soccer",
        "league": "Soccer",
        "icon": "\u26BD",  # soccer ball
    },
    # ── Multi-sport / General ──
    {
        "url": "https://www.cbssports.com/rss/headlines/",
        "label": "CBS Sports Headlines",
        "league": "Multi",
        "icon": "\U0001F3C6",  # trophy
    },
    {
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",
        "label": "NY Times Sports",
        "league": "Multi",
        "icon": "\U0001F4F0",  # newspaper
    },
]


# ── News classification keywords ──
# These detect the TYPE of news that matters to bettors

_INJURY_KEYWORDS = [
    "injur", "out for", "ruled out", "doubtful", "questionable",
    "probable", "day-to-day", "disabled list", "DL", "IL",
    "concussion", "ACL", "MCL", "hamstring", "ankle", "knee",
    "fracture", "sprain", "strain", "torn", "surgery", "rehab",
    "DNP", "limited practice", "sidelined", "miss", "IR",
    "injured reserve", "health", "setback",
]

_TRADE_KEYWORDS = [
    "trade", "traded", "deal", "acquire", "acquired", "swap",
    "sign", "signed", "signing", "free agent", "free agency",
    "waive", "waived", "release", "released", "cut", "claim",
    "draft", "pick", "prospect", "extension", "contract",
    "buyout", "opt out", "option",
]

_SUSPENSION_KEYWORDS = [
    "suspend", "suspension", "banned", "ban", "fine", "fined",
    "violation", "PED", "substance", "conduct", "ejected",
    "discipline", "disciplinary",
]

_LINEUP_KEYWORDS = [
    "start", "starting", "lineup", "bench", "benched", "rotation",
    "depth chart", "starter", "backup", "inactive", "active",
    "roster", "promoted", "demoted", "called up", "sent down",
    "scratched",
]

_GAME_KEYWORDS = [
    "preview", "prediction", "odds", "spread", "over/under",
    "moneyline", "parlay", "prop", "matchup", "rivalry",
    "playoff", "postseason", "championship", "final", "series",
    "schedule", "postponed", "delayed", "cancelled", "weather",
]


def _classify_news(title: str, summary: str = "") -> dict:
    """Classify a sports news item by type and urgency for bettors."""
    text = f"{title} {summary}".lower()

    categories = []
    if any(kw in text for kw in _INJURY_KEYWORDS):
        categories.append("injury")
    if any(kw in text for kw in _TRADE_KEYWORDS):
        categories.append("trade")
    if any(kw in text for kw in _SUSPENSION_KEYWORDS):
        categories.append("suspension")
    if any(kw in text for kw in _LINEUP_KEYWORDS):
        categories.append("lineup")
    if any(kw in text for kw in _GAME_KEYWORDS):
        categories.append("game")

    if not categories:
        categories.append("news")

    # Urgency: high if injury/suspension (line-moving), medium if trade/lineup, low otherwise
    if "injury" in categories or "suspension" in categories:
        urgency = "high"
    elif "trade" in categories or "lineup" in categories:
        urgency = "medium"
    else:
        urgency = "low"

    return {"categories": categories, "urgency": urgency}


def _category_emoji(cat: str) -> str:
    return {
        "injury": "\U0001FA79",     # bandage
        "trade": "\U0001F4B1",      # currency exchange
        "suspension": "\U0001F6AB", # no entry
        "lineup": "\U0001F4CB",     # clipboard
        "game": "\U0001F3AE",       # game / controller
        "news": "\U0001F4F0",       # newspaper
    }.get(cat, "\U0001F4F0")


def _category_color(cat: str) -> str:
    return {
        "injury": "bg-red-600/30 text-red-400 border-red-500/40",
        "trade": "bg-blue-600/30 text-blue-400 border-blue-500/40",
        "suspension": "bg-purple-600/30 text-purple-400 border-purple-500/40",
        "lineup": "bg-yellow-600/30 text-yellow-400 border-yellow-500/40",
        "game": "bg-green-600/30 text-green-400 border-green-500/40",
        "news": "bg-gray-600/30 text-gray-400 border-gray-500/40",
    }.get(cat, "bg-gray-600/30 text-gray-400 border-gray-500/40")


def _urgency_color(urgency: str) -> str:
    return {
        "high": "text-red-400",
        "medium": "text-yellow-400",
        "low": "text-gray-400",
    }.get(urgency, "text-gray-400")


def _league_color(league: str) -> str:
    return {
        "NFL": "bg-green-800/40 text-green-300 border-green-600/40",
        "NBA": "bg-orange-800/40 text-orange-300 border-orange-600/40",
        "MLB": "bg-blue-800/40 text-blue-300 border-blue-600/40",
        "NHL": "bg-cyan-800/40 text-cyan-300 border-cyan-600/40",
        "Soccer": "bg-emerald-800/40 text-emerald-300 border-emerald-600/40",
        "Multi": "bg-gray-700/40 text-gray-300 border-gray-600/40",
    }.get(league, "bg-gray-700/40 text-gray-300 border-gray-600/40")


def _time_ago(ts: float) -> str:
    """Human-readable time ago string."""
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        m = int(diff / 60)
        return f"{m}m ago"
    if diff < 86400:
        h = int(diff / 3600)
        return f"{h}h ago"
    d = int(diff / 86400)
    return f"{d}d ago"


# ── In-memory news cache ──
# Fetched from RSS feeds and refreshed periodically.

@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    published: float  # unix timestamp
    source: str       # feed label
    league: str
    icon: str
    categories: List[str] = field(default_factory=list)
    urgency: str = "low"
    item_id: str = ""


class SportsNewsCache:
    """In-memory cache of sports news items, refreshed from RSS feeds."""

    def __init__(self, ttl_s: int = 300):
        self.items: List[NewsItem] = []
        self.last_fetch: float = 0
        self.ttl_s = ttl_s
        self._lock = asyncio.Lock()

    async def get_items(self, league: str = "all", category: str = "all") -> List[NewsItem]:
        """Get cached news items, refreshing if stale."""
        if time.time() - self.last_fetch > self.ttl_s:
            await self._refresh()

        items = self.items
        if league != "all":
            items = [i for i in items if i.league == league]
        if category != "all":
            items = [i for i in items if category in i.categories]

        return items

    async def _refresh(self):
        """Fetch all sports RSS feeds concurrently."""
        async with self._lock:
            # Double-check after acquiring lock
            if time.time() - self.last_fetch < self.ttl_s:
                return

            log.info("Sports tracker: refreshing %d feeds...", len(SPORTS_FEEDS))
            tasks = [self._fetch_feed(feed) for feed in SPORTS_FEEDS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_items = []
            for result in results:
                if isinstance(result, Exception):
                    log.warning("Sports feed error: %s", result)
                    continue
                new_items.extend(result)

            # Per-refresh dedup: remove duplicate item_ids within this fetch
            seen_ids: set = set()
            deduped = []
            for item in new_items:
                if item.item_id not in seen_ids:
                    seen_ids.add(item.item_id)
                    deduped.append(item)

            # Only replace cache if we got results; keep stale items on total failure
            if deduped:
                deduped.sort(key=lambda x: x.published, reverse=True)
                self.items = deduped[:200]
                log.info("Sports tracker: cached %d items", len(self.items))
            else:
                log.warning("Sports tracker: all feeds failed or empty, keeping %d stale items", len(self.items))

            self.last_fetch = time.time()

    async def _fetch_feed(self, feed: dict) -> List[NewsItem]:
        """Fetch and parse a single RSS feed."""
        import feedparser

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    feed["url"],
                    headers={"User-Agent": "ROT-Sports-Tracker/1.0"},
                )
                resp.raise_for_status()
                raw = resp.text
        except Exception as e:
            log.warning("Sports feed %s failed: %s", feed["label"], e)
            return []

        parsed = feedparser.parse(raw)
        items = []

        for entry in parsed.entries[:25]:  # Max 25 per feed
            title = entry.get("title", "").strip()
            if not title:
                continue

            link = entry.get("link", "")
            summary = entry.get("summary", entry.get("description", ""))
            # Strip HTML from summary
            if summary:
                import re
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]

            # Parse published time
            published = 0.0
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import calendar
                try:
                    published = float(calendar.timegm(entry.published_parsed))
                except Exception:
                    published = time.time()
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                import calendar
                try:
                    published = float(calendar.timegm(entry.updated_parsed))
                except Exception:
                    published = time.time()
            else:
                published = time.time()

            # Generate unique ID for per-refresh dedup
            item_id = hashlib.md5(f"{title}:{link}".encode()).hexdigest()[:12]

            # Classify
            classification = _classify_news(title, summary)

            items.append(NewsItem(
                title=title,
                link=link,
                summary=summary,
                published=published,
                source=feed["label"],
                league=feed["league"],
                icon=feed["icon"],
                categories=classification["categories"],
                urgency=classification["urgency"],
                item_id=item_id,
            ))

        return items


# Global cache instance
_news_cache = SportsNewsCache(ttl_s=300)  # 5-minute cache


def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


@router.get("/sports-tracker", response_class=HTMLResponse)
async def sports_tracker(
    request: Request,
    league: str = "all",
    category: str = "all",
):
    """Sports Betting News Tracker — Injuries, trades, and lineup news."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    tier = ctx["tier"]

    items = await _news_cache.get_items(league=league, category=category)

    # Tier-based time cap: free = 2 days, pro+ = 5 days
    max_age_s = 2 * 86400 if tier == "free" else 5 * 86400
    cutoff = time.time() - max_age_s
    items = [i for i in items if i.published >= cutoff]

    # Calculate stats
    total_items = len(items)
    injury_count = sum(1 for i in items if "injury" in i.categories)
    trade_count = sum(1 for i in items if "trade" in i.categories)
    high_urgency = sum(1 for i in items if i.urgency == "high")

    # League breakdown
    league_counts = {}
    for item in items:
        league_counts[item.league] = league_counts.get(item.league, 0) + 1

    # Available leagues and categories for filters
    all_leagues = sorted(set(f["league"] for f in SPORTS_FEEDS))
    all_categories = ["injury", "trade", "suspension", "lineup", "game", "news"]

    max_days = 2 if tier == "free" else 5
    ctx.update({
        "items": items[:100],  # Show max 100 items
        "total_items": total_items,
        "max_days": max_days,
        "injury_count": injury_count,
        "trade_count": trade_count,
        "high_urgency": high_urgency,
        "league_counts": league_counts,
        "all_leagues": all_leagues,
        "all_categories": all_categories,
        "selected_league": league,
        "selected_category": category,
        "category_emoji": _category_emoji,
        "category_color": _category_color,
        "urgency_color": _urgency_color,
        "league_color": _league_color,
        "time_ago": _time_ago,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("sports_tracker.html", ctx)
