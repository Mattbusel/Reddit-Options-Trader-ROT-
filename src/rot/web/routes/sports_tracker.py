"""Sports Betting Intelligence — Line Mover Scores, AI analysis, team tracking.

The sleeper feature. Nobody in the trading tools space offers this.
Free news attracts bettors → Line Mover Scores, AI analysis, and API are paywalled.

Replaces: Action Network ($35/mo), Sharp ($50/mo), premium DFS tools.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_sports_betting_access

log = logging.getLogger(__name__)

router = APIRouter()

# ── Sports RSS Feeds ──
# 22+ feeds covering all major leagues with betting-focused sources.

SPORTS_FEEDS = [
    # ── NFL ──
    {"url": "https://www.espn.com/espn/rss/nfl/news", "label": "ESPN NFL", "league": "NFL", "icon": "\U0001F3C8"},
    {"url": "https://www.cbssports.com/rss/headlines/nfl/", "label": "CBS NFL", "league": "NFL", "icon": "\U0001F3C8"},
    {"url": "https://profootballtalk.nbcsports.com/feed/", "label": "Pro Football Talk", "league": "NFL", "icon": "\U0001F3C8"},
    # ── NBA ──
    {"url": "https://www.espn.com/espn/rss/nba/news", "label": "ESPN NBA", "league": "NBA", "icon": "\U0001F3C0"},
    {"url": "https://www.cbssports.com/rss/headlines/nba/", "label": "CBS NBA", "league": "NBA", "icon": "\U0001F3C0"},
    # ── MLB ──
    {"url": "https://www.espn.com/espn/rss/mlb/news", "label": "ESPN MLB", "league": "MLB", "icon": "\u26BE"},
    {"url": "https://www.cbssports.com/rss/headlines/mlb/", "label": "CBS MLB", "league": "MLB", "icon": "\u26BE"},
    # ── NHL ──
    {"url": "https://www.espn.com/espn/rss/nhl/news", "label": "ESPN NHL", "league": "NHL", "icon": "\U0001F3D2"},
    {"url": "https://www.cbssports.com/rss/headlines/nhl/", "label": "CBS NHL", "league": "NHL", "icon": "\U0001F3D2"},
    # ── Soccer / MLS ──
    {"url": "https://www.espn.com/espn/rss/soccer/news", "label": "ESPN Soccer", "league": "Soccer", "icon": "\u26BD"},
    # ── NCAA ──
    {"url": "https://www.espn.com/espn/rss/ncf/news", "label": "ESPN College Football", "league": "NCAA", "icon": "\U0001F393"},
    {"url": "https://www.espn.com/espn/rss/ncb/news", "label": "ESPN College Basketball", "league": "NCAA", "icon": "\U0001F393"},
    {"url": "https://www.cbssports.com/rss/headlines/college-football/", "label": "CBS College Football", "league": "NCAA", "icon": "\U0001F393"},
    {"url": "https://www.cbssports.com/rss/headlines/college-basketball/", "label": "CBS College Basketball", "league": "NCAA", "icon": "\U0001F393"},
    # ── Multi-sport / General ──
    {"url": "https://www.cbssports.com/rss/headlines/", "label": "CBS Sports Headlines", "league": "Multi", "icon": "\U0001F3C6"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml", "label": "NY Times Sports", "league": "Multi", "icon": "\U0001F4F0"},
    # ── Betting-Focused Sources ──
    {"url": "https://bleacherreport.com/articles/feed", "label": "Bleacher Report", "league": "Multi", "icon": "\U0001F4F0"},
    {"url": "https://www.si.com/.rss/full/", "label": "Sports Illustrated", "league": "Multi", "icon": "\U0001F3C6"},
    {"url": "https://www.sbnation.com/rss/current", "label": "SB Nation", "league": "Multi", "icon": "\U0001F4F0"},
    {"url": "https://www.sportingnews.com/us/rss", "label": "Sporting News", "league": "Multi", "icon": "\U0001F3C6"},
]


# ═══════════════════════════════════════════════════════════════════════
# TEAM EXTRACTION — ~124 teams across NFL, NBA, MLB, NHL
# Pure keyword matching against headlines. Key: lowercase alias → canonical.
# ═══════════════════════════════════════════════════════════════════════

_NFL_TEAMS: Dict[str, str] = {
    # AFC West
    "chiefs": "KC Chiefs", "kansas city chiefs": "KC Chiefs",
    "broncos": "DEN Broncos", "denver broncos": "DEN Broncos",
    "raiders": "LV Raiders", "las vegas raiders": "LV Raiders",
    "chargers": "LA Chargers", "los angeles chargers": "LA Chargers",
    # AFC East
    "bills": "BUF Bills", "buffalo bills": "BUF Bills",
    "dolphins": "MIA Dolphins", "miami dolphins": "MIA Dolphins",
    "patriots": "NE Patriots", "new england patriots": "NE Patriots",
    "jets": "NY Jets", "new york jets": "NY Jets",
    # AFC North
    "ravens": "BAL Ravens", "baltimore ravens": "BAL Ravens",
    "bengals": "CIN Bengals", "cincinnati bengals": "CIN Bengals",
    "browns": "CLE Browns", "cleveland browns": "CLE Browns",
    "steelers": "PIT Steelers", "pittsburgh steelers": "PIT Steelers",
    # AFC South
    "texans": "HOU Texans", "houston texans": "HOU Texans",
    "colts": "IND Colts", "indianapolis colts": "IND Colts",
    "jaguars": "JAX Jaguars", "jacksonville jaguars": "JAX Jaguars",
    "titans": "TEN Titans", "tennessee titans": "TEN Titans",
    # NFC West
    "49ers": "SF 49ers", "san francisco 49ers": "SF 49ers", "niners": "SF 49ers",
    "seahawks": "SEA Seahawks", "seattle seahawks": "SEA Seahawks",
    "rams": "LA Rams", "los angeles rams": "LA Rams",
    "cardinals": "ARI Cardinals", "arizona cardinals": "ARI Cardinals",
    # NFC East
    "cowboys": "DAL Cowboys", "dallas cowboys": "DAL Cowboys",
    "eagles": "PHI Eagles", "philadelphia eagles": "PHI Eagles",
    "commanders": "WAS Commanders", "washington commanders": "WAS Commanders",
    "giants": "NY Giants", "new york giants": "NY Giants",
    # NFC North
    "packers": "GB Packers", "green bay packers": "GB Packers",
    "bears": "CHI Bears", "chicago bears": "CHI Bears",
    "lions": "DET Lions", "detroit lions": "DET Lions",
    "vikings": "MIN Vikings", "minnesota vikings": "MIN Vikings",
    # NFC South
    "buccaneers": "TB Buccaneers", "tampa bay buccaneers": "TB Buccaneers", "bucs": "TB Buccaneers",
    "saints": "NO Saints", "new orleans saints": "NO Saints",
    "falcons": "ATL Falcons", "atlanta falcons": "ATL Falcons",
    "panthers": "CAR Panthers", "carolina panthers": "CAR Panthers",
}

_NBA_TEAMS: Dict[str, str] = {
    "celtics": "BOS Celtics", "boston celtics": "BOS Celtics",
    "nets": "BKN Nets", "brooklyn nets": "BKN Nets",
    "knicks": "NY Knicks", "new york knicks": "NY Knicks",
    "76ers": "PHI 76ers", "philadelphia 76ers": "PHI 76ers", "sixers": "PHI 76ers",
    "raptors": "TOR Raptors", "toronto raptors": "TOR Raptors",
    "bulls": "CHI Bulls", "chicago bulls": "CHI Bulls",
    "cavaliers": "CLE Cavaliers", "cleveland cavaliers": "CLE Cavaliers", "cavs": "CLE Cavaliers",
    "pistons": "DET Pistons", "detroit pistons": "DET Pistons",
    "pacers": "IND Pacers", "indiana pacers": "IND Pacers",
    "bucks": "MIL Bucks", "milwaukee bucks": "MIL Bucks",
    "hawks": "ATL Hawks", "atlanta hawks": "ATL Hawks",
    "hornets": "CHA Hornets", "charlotte hornets": "CHA Hornets",
    "heat": "MIA Heat", "miami heat": "MIA Heat",
    "magic": "ORL Magic", "orlando magic": "ORL Magic",
    "wizards": "WAS Wizards", "washington wizards": "WAS Wizards",
    "nuggets": "DEN Nuggets", "denver nuggets": "DEN Nuggets",
    "timberwolves": "MIN Timberwolves", "minnesota timberwolves": "MIN Timberwolves", "wolves": "MIN Timberwolves",
    "thunder": "OKC Thunder", "oklahoma city thunder": "OKC Thunder",
    "trail blazers": "POR Trail Blazers", "portland trail blazers": "POR Trail Blazers", "blazers": "POR Trail Blazers",
    "jazz": "UTA Jazz", "utah jazz": "UTA Jazz",
    "warriors": "GS Warriors", "golden state warriors": "GS Warriors",
    "clippers": "LA Clippers", "los angeles clippers": "LA Clippers",
    "lakers": "LA Lakers", "los angeles lakers": "LA Lakers",
    "suns": "PHX Suns", "phoenix suns": "PHX Suns",
    "kings": "SAC Kings", "sacramento kings": "SAC Kings",
    "mavericks": "DAL Mavericks", "dallas mavericks": "DAL Mavericks", "mavs": "DAL Mavericks",
    "rockets": "HOU Rockets", "houston rockets": "HOU Rockets",
    "grizzlies": "MEM Grizzlies", "memphis grizzlies": "MEM Grizzlies",
    "pelicans": "NO Pelicans", "new orleans pelicans": "NO Pelicans",
    "spurs": "SA Spurs", "san antonio spurs": "SA Spurs",
}

_MLB_TEAMS: Dict[str, str] = {
    "yankees": "NY Yankees", "new york yankees": "NY Yankees",
    "red sox": "BOS Red Sox", "boston red sox": "BOS Red Sox",
    "blue jays": "TOR Blue Jays", "toronto blue jays": "TOR Blue Jays",
    "orioles": "BAL Orioles", "baltimore orioles": "BAL Orioles",
    "rays": "TB Rays", "tampa bay rays": "TB Rays",
    "white sox": "CHI White Sox", "chicago white sox": "CHI White Sox",
    "guardians": "CLE Guardians", "cleveland guardians": "CLE Guardians",
    "tigers": "DET Tigers", "detroit tigers": "DET Tigers",
    "royals": "KC Royals", "kansas city royals": "KC Royals",
    "twins": "MIN Twins", "minnesota twins": "MIN Twins",
    "astros": "HOU Astros", "houston astros": "HOU Astros",
    "angels": "LA Angels", "los angeles angels": "LA Angels",
    "athletics": "OAK Athletics", "oakland athletics": "OAK Athletics",
    "mariners": "SEA Mariners", "seattle mariners": "SEA Mariners",
    "rangers": "TEX Rangers", "texas rangers": "TEX Rangers",
    "braves": "ATL Braves", "atlanta braves": "ATL Braves",
    "marlins": "MIA Marlins", "miami marlins": "MIA Marlins",
    "mets": "NY Mets", "new york mets": "NY Mets",
    "phillies": "PHI Phillies", "philadelphia phillies": "PHI Phillies",
    "nationals": "WAS Nationals", "washington nationals": "WAS Nationals",
    "cubs": "CHI Cubs", "chicago cubs": "CHI Cubs",
    "reds": "CIN Reds", "cincinnati reds": "CIN Reds",
    "brewers": "MIL Brewers", "milwaukee brewers": "MIL Brewers",
    "pirates": "PIT Pirates", "pittsburgh pirates": "PIT Pirates",
    "cardinals": "STL Cardinals", "st. louis cardinals": "STL Cardinals",
    "diamondbacks": "ARI Diamondbacks", "arizona diamondbacks": "ARI Diamondbacks", "d-backs": "ARI Diamondbacks",
    "rockies": "COL Rockies", "colorado rockies": "COL Rockies",
    "dodgers": "LA Dodgers", "los angeles dodgers": "LA Dodgers",
    "padres": "SD Padres", "san diego padres": "SD Padres",
    "giants": "SF Giants", "san francisco giants": "SF Giants",
}

_NHL_TEAMS: Dict[str, str] = {
    "bruins": "BOS Bruins", "boston bruins": "BOS Bruins",
    "sabres": "BUF Sabres", "buffalo sabres": "BUF Sabres",
    "red wings": "DET Red Wings", "detroit red wings": "DET Red Wings",
    "panthers": "FLA Panthers", "florida panthers": "FLA Panthers",
    "canadiens": "MTL Canadiens", "montreal canadiens": "MTL Canadiens", "habs": "MTL Canadiens",
    "senators": "OTT Senators", "ottawa senators": "OTT Senators",
    "lightning": "TB Lightning", "tampa bay lightning": "TB Lightning",
    "maple leafs": "TOR Maple Leafs", "toronto maple leafs": "TOR Maple Leafs", "leafs": "TOR Maple Leafs",
    "hurricanes": "CAR Hurricanes", "carolina hurricanes": "CAR Hurricanes",
    "blue jackets": "CBJ Blue Jackets", "columbus blue jackets": "CBJ Blue Jackets",
    "devils": "NJ Devils", "new jersey devils": "NJ Devils",
    "islanders": "NY Islanders", "new york islanders": "NY Islanders",
    "flyers": "PHI Flyers", "philadelphia flyers": "PHI Flyers",
    "penguins": "PIT Penguins", "pittsburgh penguins": "PIT Penguins",
    "capitals": "WAS Capitals", "washington capitals": "WAS Capitals", "caps": "WAS Capitals",
    "blackhawks": "CHI Blackhawks", "chicago blackhawks": "CHI Blackhawks",
    "avalanche": "COL Avalanche", "colorado avalanche": "COL Avalanche",
    "stars": "DAL Stars", "dallas stars": "DAL Stars",
    "predators": "NSH Predators", "nashville predators": "NSH Predators", "preds": "NSH Predators",
    "blues": "STL Blues", "st. louis blues": "STL Blues",
    "wild": "MIN Wild", "minnesota wild": "MIN Wild",
    "jets": "WPG Jets", "winnipeg jets": "WPG Jets",
    "flames": "CGY Flames", "calgary flames": "CGY Flames",
    "oilers": "EDM Oilers", "edmonton oilers": "EDM Oilers",
    "canucks": "VAN Canucks", "vancouver canucks": "VAN Canucks",
    "kraken": "SEA Kraken", "seattle kraken": "SEA Kraken",
    "golden knights": "VGK Golden Knights", "vegas golden knights": "VGK Golden Knights",
    "coyotes": "UTA Hockey Club", "utah hockey club": "UTA Hockey Club",
    "ducks": "ANA Ducks", "anaheim ducks": "ANA Ducks",
    "kings": "LA Kings", "los angeles kings": "LA Kings",
    "sharks": "SJ Sharks", "san jose sharks": "SJ Sharks",
}

# Build unified lookup (longest keys first to match "new york giants" before "giants")
_ALL_TEAMS: Dict[str, str] = {}
for _league_teams in (_NFL_TEAMS, _NBA_TEAMS, _MLB_TEAMS, _NHL_TEAMS):
    _ALL_TEAMS.update(_league_teams)
# Sort by key length descending so longer phrases match first
_TEAM_KEYS_SORTED = sorted(_ALL_TEAMS.keys(), key=len, reverse=True)


def _extract_teams(text: str) -> List[str]:
    """Extract team names from headline+summary. Returns list of canonical names."""
    text_lower = text.lower()
    found: Set[str] = set()
    for keyword in _TEAM_KEYS_SORTED:
        if keyword in text_lower:
            found.add(_ALL_TEAMS[keyword])
    return sorted(found)


# ═══════════════════════════════════════════════════════════════════════
# NEWS CLASSIFICATION — Injury, trade, suspension, lineup, game + BETTING
# ═══════════════════════════════════════════════════════════════════════

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
    "transfer portal", "portal", "transfer", "NIL", "commit",
    "decommit", "recruiting", "recruit", "flip",
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

# ── Betting Impact Keywords (monetized classification) ──
_SPREAD_IMPACT_KEYWORDS = [
    "spread", "point spread", "ATS", "against the spread", "cover",
    "favorite", "underdog", "handicap", "line", "line move",
]

_TOTAL_IMPACT_KEYWORDS = [
    "over/under", "total", "O/U", "points total", "scoring",
    "pace", "tempo", "weather", "wind", "rain", "snow", "dome",
    "high-scoring", "low-scoring", "defensive",
]

_PROP_IMPACT_KEYWORDS = [
    "prop", "player prop", "yards", "touchdowns", "rebounds",
    "assists", "strikeouts", "saves", "goals", "hat trick",
    "double-double", "triple-double", "home run", "RBI",
]


def _classify_news(title: str, summary: str = "") -> dict:
    """Classify a sports news item by type, urgency, and betting impact."""
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

    # Betting impact categories (paid feature)
    betting_categories = []
    if any(kw in text for kw in _SPREAD_IMPACT_KEYWORDS):
        betting_categories.append("spread_impact")
    if any(kw in text for kw in _TOTAL_IMPACT_KEYWORDS):
        betting_categories.append("total_impact")
    if any(kw in text for kw in _PROP_IMPACT_KEYWORDS):
        betting_categories.append("prop_impact")

    # Urgency scoring
    if "injury" in categories or "suspension" in categories:
        urgency = "high"
    elif "trade" in categories or "lineup" in categories:
        urgency = "medium"
    else:
        urgency = "low"

    return {"categories": categories, "urgency": urgency, "betting_categories": betting_categories}


# ═══════════════════════════════════════════════════════════════════════
# LINE MOVER SCORE — 0-100 algorithmic scoring (MONETIZED)
# ═══════════════════════════════════════════════════════════════════════

_HIGH_IMPACT_INJURY = [
    "ruled out", "torn", "ACL", "out for season", "surgery",
    "IR", "injured reserve", "out indefinitely", "broken",
    "fractured", "done for the year", "career-threatening",
]

_MEDIUM_IMPACT_INJURY = [
    "doubtful", "questionable", "concussion", "sprain",
    "hamstring", "limited practice", "game-time decision",
]

# Star players — names that move lines when mentioned in injury/trade context
_STAR_PLAYERS = {
    # NFL
    "mahomes", "kelce", "allen", "burrow", "hurts", "lamar jackson",
    "mccaffrey", "hill", "chase", "henry", "jefferson",
    "ceedee lamb", "travis kelce", "cj stroud", "caleb williams",
    # NBA
    "lebron", "curry", "giannis", "jokic", "doncic", "tatum",
    "sga", "gilgeous-alexander", "embiid", "durant", "morant",
    "anthony edwards", "wembanyama", "brunson",
    # MLB
    "ohtani", "judge", "trout", "soto", "acuna", "tatis",
    "betts", "devers", "vlad guerrero", "gunnar henderson",
    # NHL
    "mcdavid", "draisaitl", "crosby", "mackinnon", "kucherov",
    "ovechkin", "matthews", "bedard",
}


def _compute_line_mover_score(item: "NewsItem") -> int:
    """Compute 0-100 line mover score. Higher = more likely to move betting lines."""
    score = 0
    text = f"{item.title} {item.summary}".lower()

    # Base category score
    cat_scores = {"injury": 40, "suspension": 35, "lineup": 25, "trade": 20, "game": 10, "news": 5}
    for cat in item.categories:
        score = max(score, cat_scores.get(cat, 5))

    # Severity boost
    if any(kw in text for kw in _HIGH_IMPACT_INJURY):
        score += 20
    elif any(kw in text for kw in _MEDIUM_IMPACT_INJURY):
        score += 10

    # Star player boost
    if any(player in text for player in _STAR_PLAYERS):
        score += 15

    # Multiple teams = matchup context = more actionable
    if len(item.teams) >= 2:
        score += 5

    # Recency boost
    age_hours = (time.time() - item.published) / 3600
    if age_hours < 1:
        score += 15
    elif age_hours < 3:
        score += 10
    elif age_hours < 6:
        score += 5

    # Source credibility
    if "ESPN" in item.source or "CBS" in item.source:
        score += 5

    # Betting keyword boost
    if item.betting_categories:
        score += 5

    return min(100, max(0, score))


# ═══════════════════════════════════════════════════════════════════════
# AI BETTING ANALYSIS (Premium+ feature)
# ═══════════════════════════════════════════════════════════════════════

_SPORTS_AI_SYSTEM = """You are a concise sports betting analyst. Given a sports news item, write a 1-2 sentence betting impact summary. Include: which teams/lines are affected, direction of impact (spread/total/props), and urgency level. Be direct and actionable. No disclaimers."""

_SPORTS_AI_TEMPLATE = """News: {title}
League: {league} | Teams: {teams}
Category: {categories} | Urgency: {urgency}
Line Mover Score: {score}/100
Summary: {summary}"""


def _build_heuristic_sports_summary(item: "NewsItem") -> str:
    """Fast rule-based betting summary when no LLM is available. Zero cost."""
    teams_str = ", ".join(item.teams) if item.teams else item.league
    cat = item.categories[0] if item.categories else "news"

    if cat == "injury":
        is_star = any(p in item.title.lower() for p in _STAR_PLAYERS)
        severity = "major" if item.line_mover_score >= 60 else "moderate" if item.line_mover_score >= 40 else "minor"
        player_type = "star player" if is_star else "player"
        return (
            f"{severity.capitalize()} {cat} impact for {teams_str}. "
            f"{'Star' if is_star else 'Key'} {player_type} news — monitor spread and player props before game time. "
            f"Line Mover Score: {item.line_mover_score}/100."
        )
    elif cat == "suspension":
        return (
            f"Suspension news for {teams_str}. "
            f"May affect spread and team totals. Score: {item.line_mover_score}/100."
        )
    elif cat == "trade":
        return (
            f"Trade/transaction for {teams_str}. "
            f"Roster change may shift futures and game lines. Score: {item.line_mover_score}/100."
        )
    elif cat == "lineup":
        return (
            f"Lineup change for {teams_str}. "
            f"Check starter status — may impact spread and props. Score: {item.line_mover_score}/100."
        )
    elif cat == "game":
        return (
            f"Game intel for {teams_str}. "
            f"Odds/preview context — cross-reference with injury report. Score: {item.line_mover_score}/100."
        )
    return f"Sports news for {teams_str}. Score: {item.line_mover_score}/100."


async def _generate_sports_ai_summary(item: "NewsItem") -> str:
    """Generate AI betting analysis. Uses platform key or falls back to heuristic."""
    platform_key = os.environ.get("ROT_PLATFORM_LLM_KEY", "")
    if not platform_key or len(platform_key) < 20:
        return _build_heuristic_sports_summary(item)

    teams_str = ", ".join(item.teams) if item.teams else "Unknown"
    user_prompt = _SPORTS_AI_TEMPLATE.format(
        title=item.title[:200],
        league=item.league,
        teams=teams_str,
        categories=", ".join(item.categories),
        urgency=item.urgency,
        score=item.line_mover_score,
        summary=item.summary[:300],
    )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=platform_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SPORTS_AI_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=100,
            temperature=0.3,
        )
        summary = resp.choices[0].message.content.strip()
        return summary[:500]
    except ImportError:
        log.debug("openai package not installed — using heuristic sports summary")
        return _build_heuristic_sports_summary(item)
    except Exception as e:
        log.warning("Sports AI summary failed: %s", e)
        return _build_heuristic_sports_summary(item)


# ═══════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════

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
        "NCAA": "bg-indigo-800/40 text-indigo-300 border-indigo-600/40",
        "Multi": "bg-gray-700/40 text-gray-300 border-gray-600/40",
    }.get(league, "bg-gray-700/40 text-gray-300 border-gray-600/40")


def _line_mover_color(score: int) -> str:
    """CSS class for line mover score badge."""
    if score >= 70:
        return "bg-red-600/30 text-red-400 border-red-500/50"
    elif score >= 40:
        return "bg-yellow-600/30 text-yellow-400 border-yellow-500/50"
    return "bg-green-600/30 text-green-400 border-green-500/50"


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


# ═══════════════════════════════════════════════════════════════════════
# IN-MEMORY CACHE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    published: float          # unix timestamp
    source: str               # feed label
    league: str
    icon: str
    categories: List[str] = field(default_factory=list)
    urgency: str = "low"
    item_id: str = ""
    # ── Betting intelligence (new) ──
    teams: List[str] = field(default_factory=list)
    line_mover_score: int = 0
    betting_categories: List[str] = field(default_factory=list)
    ai_summary: str = ""


class SportsNewsCache:
    """In-memory cache of sports news items, refreshed from RSS feeds."""

    def __init__(self, ttl_s: int = 300):
        self.items: List[NewsItem] = []
        self.last_fetch: float = 0
        self.ttl_s = ttl_s
        self._lock = asyncio.Lock()
        self._ai_generated: set = set()  # item_ids that already have AI summaries

    async def get_items(self, league: str = "all", category: str = "all", team: str = "all") -> List[NewsItem]:
        """Get cached news items, refreshing if stale."""
        if time.time() - self.last_fetch > self.ttl_s:
            await self._refresh()

        items = self.items
        if league != "all":
            items = [i for i in items if i.league == league]
        if category != "all":
            items = [i for i in items if category in i.categories]
        if team != "all":
            team_lower = team.lower()
            items = [i for i in items if any(team_lower in t.lower() for t in i.teams)]

        return items

    async def generate_ai_for_top_items(self, count: int = 10):
        """Generate AI summaries for top line-mover items that don't have one yet."""
        eligible = [
            i for i in self.items
            if i.line_mover_score >= 50 and i.item_id not in self._ai_generated
        ]
        eligible.sort(key=lambda x: x.line_mover_score, reverse=True)

        for item in eligible[:count]:
            try:
                item.ai_summary = await _generate_sports_ai_summary(item)
                self._ai_generated.add(item.item_id)
            except Exception as e:
                log.warning("Sports AI summary failed for %s: %s", item.item_id, e)

    async def _refresh(self):
        """Fetch all sports RSS feeds concurrently."""
        async with self._lock:
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

            # Dedup
            seen_ids: set = set()
            deduped = []
            for item in new_items:
                if item.item_id not in seen_ids:
                    seen_ids.add(item.item_id)
                    deduped.append(item)

            if deduped:
                # Compute line mover scores and extract teams
                for item in deduped:
                    item.teams = _extract_teams(f"{item.title} {item.summary}")
                    item.line_mover_score = _compute_line_mover_score(item)

                deduped.sort(key=lambda x: x.published, reverse=True)
                self.items = deduped[:500]  # Larger cache for paid tier lookback
                log.info("Sports tracker: cached %d items (top score: %d)",
                         len(self.items),
                         max((i.line_mover_score for i in self.items), default=0))
            else:
                log.warning("Sports tracker: all feeds failed, keeping %d stale items", len(self.items))

            self.last_fetch = time.time()

        # Generate AI summaries for top items (non-blocking, after lock release)
        try:
            await self.generate_ai_for_top_items(count=10)
        except Exception as e:
            log.warning("Sports AI batch failed: %s", e)

    async def _fetch_feed(self, feed: dict) -> List[NewsItem]:
        """Fetch and parse a single RSS feed."""
        import feedparser

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    feed["url"],
                    headers={"User-Agent": "ROT-Sports-Betting-Intel/2.0"},
                )
                resp.raise_for_status()
                raw = resp.text
        except Exception as e:
            log.warning("Sports feed %s failed: %s", feed["label"], e)
            return []

        parsed = feedparser.parse(raw)
        items = []

        for entry in parsed.entries[:25]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            link = entry.get("link", "")
            summary = entry.get("summary", entry.get("description", ""))
            if summary:
                import re
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]

            # Parse published time
            published = 0.0
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = float(calendar.timegm(entry.published_parsed))
                except Exception:
                    published = time.time()
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                try:
                    published = float(calendar.timegm(entry.updated_parsed))
                except Exception:
                    published = time.time()
            else:
                published = time.time()

            item_id = hashlib.md5(f"{title}:{link}".encode(), usedforsecurity=False).hexdigest()[:12]
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
                betting_categories=classification["betting_categories"],
            ))

        return items


# Global cache instance
_news_cache = SportsNewsCache(ttl_s=300)


# ═══════════════════════════════════════════════════════════════════════
# ROUTE: HTML PAGE — /sports-tracker (renamed: Betting Edge)
# ═══════════════════════════════════════════════════════════════════════

def _base_context(request: Request, user: dict | None) -> dict:
    tier = (user or {}).get("tier", "free")
    badge_map = {
        "free": "bg-gray-700 text-gray-300",
        "pro": "bg-blue-700/60 text-blue-200",
        "premium": "bg-purple-700/60 text-purple-200",
        "ultra": "bg-orange-700/60 text-orange-200",
        "admin": "bg-red-700/60 text-red-200",
    }
    return {
        "request": request,
        "user": user,
        "tier": tier,
        "tier_badge_class": badge_map.get(tier, badge_map["free"]),
        "stripe_enabled": bool(request.app.state.settings.stripe.secret_key),
    }


@router.get("/sports-tracker", response_class=HTMLResponse)
@router.get("/sports", response_class=HTMLResponse)
async def sports_tracker(
    request: Request,
    league: str = "all",
    category: str = "all",
    team: str = "all",
    sort_by: str = "time",
):
    """Sports Betting Intelligence — Line mover scores, AI analysis, team tracking."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)
    tier = ctx["tier"]

    gate = gate_sports_betting_access(tier)
    items = await _news_cache.get_items(league=league, category=category, team=team if gate["has_team_filter"] else "all")

    # Tier-based time cap
    max_age_s = gate["max_days"] * 86400
    cutoff = time.time() - max_age_s
    items = [i for i in items if i.published >= cutoff]

    # Sort
    if sort_by == "score" and gate["has_score_sort"]:
        items.sort(key=lambda x: x.line_mover_score, reverse=True)

    # Calculate stats (before truncation)
    total_items = len(items)
    injury_count = sum(1 for i in items if "injury" in i.categories)
    trade_count = sum(1 for i in items if "trade" in i.categories)
    high_urgency = sum(1 for i in items if i.urgency == "high")
    avg_score = int(sum(i.line_mover_score for i in items) / max(len(items), 1))
    top_score = max((i.line_mover_score for i in items), default=0)

    # League breakdown
    league_counts = {}
    for item in items:
        league_counts[item.league] = league_counts.get(item.league, 0) + 1

    # Enforce max_items from gate
    items = items[:gate["max_items"]]

    # Strip line mover scores for free users
    if not gate["has_line_mover_scores"]:
        for item in items:
            item.line_mover_score = -1  # sentinel = locked

    # Strip AI summaries for non-premium
    if not gate["has_ai_summaries"]:
        for item in items:
            item.ai_summary = ""

    # Strip betting categories for free users
    if not gate["has_betting_categories"]:
        for item in items:
            item.betting_categories = []

    all_leagues = sorted(set(f["league"] for f in SPORTS_FEEDS))
    all_categories = ["injury", "trade", "suspension", "lineup", "game", "news"]

    # Build available teams list from current items (for team filter dropdown)
    all_teams_in_feed: Set[str] = set()
    for item in _news_cache.items:
        all_teams_in_feed.update(item.teams)

    ctx.update({
        "items": items,
        "total_items": total_items,
        "max_days": gate["max_days"],
        "max_items_limit": gate["max_items"],
        "injury_count": injury_count,
        "trade_count": trade_count,
        "high_urgency": high_urgency,
        "avg_score": avg_score,
        "top_score": top_score,
        "league_counts": league_counts,
        "all_leagues": all_leagues,
        "all_categories": all_categories,
        "all_teams": sorted(all_teams_in_feed),
        "selected_league": league,
        "selected_category": category,
        "selected_team": team,
        "selected_sort": sort_by,
        "gate": gate,
        "category_emoji": _category_emoji,
        "category_color": _category_color,
        "urgency_color": _urgency_color,
        "league_color": _league_color,
        "line_mover_color": _line_mover_color,
        "time_ago": _time_ago,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("sports_tracker.html", ctx)


# ═══════════════════════════════════════════════════════════════════════
# ROUTE: JSON API — /api/v1/sports-betting (Premium+ only)
# ═══════════════════════════════════════════════════════════════════════

_SPORTS_API_FIELDS = {
    "item_id", "title", "link", "summary", "published", "source", "league",
    "categories", "urgency", "teams", "line_mover_score", "betting_categories",
    "ai_summary",
}


@router.get("/api/v1/sports-betting", tags=["sports-betting"])
async def sports_betting_api(
    request: Request,
    league: str = "all",
    category: str = "all",
    team: str = "all",
    urgency: str = "all",
    min_score: int = 0,
    sort: str = "time",
    limit: int = 50,
    offset: int = 0,
    fields: str = "",
):
    """Sports Betting Intelligence API. Requires paid subscription (Premium+)."""
    from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers

    user = await get_current_user_optional(request)
    await require_api_auth(request, user)
    await check_rate_limit(request, user)

    tier = (user or {}).get("tier", "free")
    gate = gate_sports_betting_access(tier)

    if not gate["has_api"]:
        headers = rate_limit_headers(user)
        return JSONResponse(
            content={"error": "Sports Betting API requires Premium+ subscription. Upgrade at /pricing."},
            status_code=403,
            headers=headers,
        )

    items = await _news_cache.get_items(
        league=league, category=category,
        team=team if gate["has_team_filter"] else "all",
    )

    # Time cap
    max_age_s = gate["max_days"] * 86400
    cutoff = time.time() - max_age_s
    items = [i for i in items if i.published >= cutoff]

    # Urgency filter
    if urgency != "all":
        items = [i for i in items if i.urgency == urgency]

    # Min score filter
    if min_score > 0:
        items = [i for i in items if i.line_mover_score >= min_score]

    # Sort
    if sort == "score":
        items.sort(key=lambda x: x.line_mover_score, reverse=True)

    total = len(items)

    # Pagination
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    items = items[offset:offset + limit]

    # Serialize
    results = []
    for item in items:
        row: Dict[str, Any] = {
            "item_id": item.item_id,
            "title": item.title,
            "link": item.link,
            "summary": item.summary,
            "published": item.published,
            "source": item.source,
            "league": item.league,
            "categories": item.categories,
            "urgency": item.urgency,
            "teams": item.teams,
            "line_mover_score": item.line_mover_score,
            "betting_categories": item.betting_categories,
        }
        if gate["has_ai_summaries"] and item.ai_summary:
            row["ai_summary"] = item.ai_summary
        results.append(row)

    # Field selection
    if fields:
        requested = {f.strip() for f in fields.split(",") if f.strip()}
        valid = requested & _SPORTS_API_FIELDS
        if valid:
            results = [{k: v for k, v in r.items() if k in valid} for r in results]

    headers = rate_limit_headers(user)
    return JSONResponse(
        content={
            "total": total,
            "offset": offset,
            "limit": limit,
            "tier": tier,
            "items": results,
        },
        headers=headers,
    )
