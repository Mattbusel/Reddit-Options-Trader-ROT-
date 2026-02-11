"""Hall of Legends — The greatest trades in market history."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()


# ── Historical dataset: legendary trades that changed the game ──
# Sources: public financial history, Bloomberg, WSJ, books, SEC filings
#
# Fields:
#   trader         – person or fund name
#   trade_name     – short name for the trade
#   year           – year the trade hit
#   profit         – estimated profit in USD
#   strategy_type  – macro / short / options / long / arbitrage
#   instrument     – what they traded
#   description    – brief story
#   rating         – legend rating 1-5 stars
#   still_active   – whether the trader is still in the game

LEGENDS_DATA = [
    {
        "trader": "John Paulson",
        "trade_name": "The Greatest Trade Ever",
        "year": 2007,
        "profit": 15_000_000_000,
        "strategy_type": "short",
        "instrument": "CDS on subprime MBS",
        "description": "Bet against the entire subprime mortgage market using credit default swaps. His fund made $15B in a single year while the financial system collapsed around him.",
        "rating": 5,
        "still_active": True,
    },
    {
        "trader": "George Soros",
        "trade_name": "Breaking the Bank of England",
        "year": 1992,
        "profit": 1_000_000_000,
        "strategy_type": "macro",
        "instrument": "GBP short",
        "description": "Shorted $10B worth of British pounds, forcing the UK out of the European Exchange Rate Mechanism on 'Black Wednesday.' Earned the title 'The Man Who Broke the Bank of England.'",
        "rating": 5,
        "still_active": False,
    },
    {
        "trader": "Michael Burry",
        "trade_name": "The Big Short",
        "year": 2007,
        "profit": 800_000_000,
        "strategy_type": "short",
        "instrument": "CDS on subprime MBS",
        "description": "A former neurologist-turned-hedge-fund manager who saw the housing crisis coming years early. Endured massive client pressure and margin calls before being proven spectacularly right.",
        "rating": 5,
        "still_active": True,
    },
    {
        "trader": "Jesse Livermore",
        "trade_name": "The 1929 Crash Short",
        "year": 1929,
        "profit": 100_000_000,
        "strategy_type": "short",
        "instrument": "US equities",
        "description": "Shorted the entire stock market before the 1929 crash. Made $100M ($1.5B adjusted) in a single day. Called 'The Boy Plunger.' Later lost it all and tragically took his own life.",
        "rating": 5,
        "still_active": False,
    },
    {
        "trader": "Jim Simons",
        "trade_name": "The Medallion Fund",
        "year": 1988,
        "profit": 100_000_000_000,
        "strategy_type": "arbitrage",
        "instrument": "Multi-asset quant",
        "description": "Renaissance Technologies' Medallion Fund averaged 66% annual returns before fees from 1988-2018. The greatest sustained trading performance in history. Simons was a former NSA codebreaker.",
        "rating": 5,
        "still_active": False,
    },
    {
        "trader": "Stanley Druckenmiller",
        "trade_name": "Soros's Right Hand",
        "year": 1992,
        "profit": 1_000_000_000,
        "strategy_type": "macro",
        "instrument": "GBP short + German bonds",
        "description": "Actually conceived the British pound trade that Soros gets credit for. Druckenmiller pitched it, Soros told him to make it bigger. Never had a losing year in 30 years of managing money.",
        "rating": 5,
        "still_active": True,
    },
    {
        "trader": "Paul Tudor Jones",
        "trade_name": "Black Monday Prediction",
        "year": 1987,
        "profit": 100_000_000,
        "strategy_type": "short",
        "instrument": "S&P 500 futures",
        "description": "Predicted and profited from the 1987 crash (Black Monday, -22.6% in one day). His fund returned 125.9% that year while the market imploded. Famous documentary 'Trader' captured it.",
        "rating": 5,
        "still_active": True,
    },
    {
        "trader": "Bill Ackman",
        "trade_name": "The COVID Hedge",
        "year": 2020,
        "profit": 2_600_000_000,
        "strategy_type": "options",
        "instrument": "CDS / credit protection",
        "description": "Spent $27M on credit protection in February 2020 as COVID fears mounted. Within 3 weeks, those positions were worth $2.6B. Went on CNBC crying about the apocalypse while his hedge printed.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Keith Gill (DeepF***ingValue)",
        "trade_name": "GameStop Squeeze",
        "year": 2021,
        "profit": 46_000_000,
        "strategy_type": "long",
        "instrument": "GME calls + shares",
        "description": "A Massachusetts financial advisor who posted his $53K GME YOLO on Reddit for over a year. His conviction held through massive drawdowns. Turned it into $46M and became the face of the retail revolution.",
        "rating": 5,
        "still_active": True,
    },
    {
        "trader": "Warren Buffett",
        "trade_name": "Bank of America Bailout",
        "year": 2011,
        "profit": 12_000_000_000,
        "strategy_type": "long",
        "instrument": "BAC preferred shares + warrants",
        "description": "Invested $5B in Bank of America preferred shares with warrants during the 2011 panic. By 2017, the position was worth $17B. Classic Buffett: be greedy when others are fearful.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Warren Buffett",
        "trade_name": "Goldman Sachs Rescue",
        "year": 2008,
        "profit": 3_700_000_000,
        "strategy_type": "long",
        "instrument": "GS preferred shares + warrants",
        "description": "Invested $5B in Goldman Sachs at the peak of the 2008 crisis. Got 10% dividend plus warrants to buy shares at $115. Goldman paid him back with a $500M premium. Total profit: $3.7B.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Andrew Hall",
        "trade_name": "The $100 Oil Bet",
        "year": 2008,
        "profit": 250_000_000,
        "strategy_type": "long",
        "instrument": "Oil futures",
        "description": "In 2003, when oil was at $30, Hall loaded up on long-dated oil futures betting it would hit $100. By 2008 oil hit $147. Citigroup paid him $100M in a single bonus. Earned the nickname 'God.'",
        "rating": 4,
        "still_active": False,
    },
    {
        "trader": "David Tepper",
        "trade_name": "The Bank Recovery Bet",
        "year": 2009,
        "profit": 7_000_000_000,
        "strategy_type": "long",
        "instrument": "Bank stocks & distressed debt",
        "description": "Bought massive positions in beaten-down bank stocks and distressed financial debt in early 2009. His fund returned 132% that year. Made $4B personally — one of the best single-year performances ever.",
        "rating": 5,
        "still_active": True,
    },
    {
        "trader": "John Arnold",
        "trade_name": "Natural Gas Domination",
        "year": 2006,
        "profit": 2_000_000_000,
        "strategy_type": "macro",
        "instrument": "Natural gas futures",
        "description": "Former Enron trader who started Centaurus Energy. Made billions trading natural gas futures, including massive profits during the Amaranth collapse. Retired at 38 to become a philanthropist.",
        "rating": 4,
        "still_active": False,
    },
    {
        "trader": "Nassim Taleb",
        "trade_name": "Black Swan Profits",
        "year": 2008,
        "profit": 500_000_000,
        "strategy_type": "options",
        "instrument": "Deep OTM puts",
        "description": "The philosopher-trader who literally wrote the book on Black Swans. His Universa fund bought cheap far-out-of-the-money puts that exploded during the 2008 crash. Returned 115% in October 2008 alone.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Mark Baum (Steve Eisman)",
        "trade_name": "FrontPoint Subprime Short",
        "year": 2007,
        "profit": 1_000_000_000,
        "strategy_type": "short",
        "instrument": "CDS on subprime MBS",
        "description": "Immortalized as Mark Baum in The Big Short (played by Steve Carell). Eisman's FrontPoint Partners shorted subprime mortgage bonds and made over $1B. Famous for his rage at Wall Street corruption.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Chris Sacca",
        "trade_name": "Early Twitter & Uber Investments",
        "year": 2011,
        "profit": 5_000_000_000,
        "strategy_type": "long",
        "instrument": "TWTR + UBER pre-IPO equity",
        "description": "Former Google employee who became one of the most successful angel investors ever. Early bets on Twitter and Uber turned a few million into an estimated $5B+ fortune.",
        "rating": 4,
        "still_active": False,
    },
    {
        "trader": "Peter Thiel",
        "trade_name": "The Facebook Bet",
        "year": 2004,
        "profit": 1_000_000_000,
        "strategy_type": "long",
        "instrument": "META (Facebook) pre-IPO equity",
        "description": "Invested $500K as the first outside investor in Facebook in 2004 for a 10.2% stake. By the IPO in 2012, his shares were worth over $1B. Held some shares even longer.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Ray Dalio",
        "trade_name": "2008 Crisis Navigation",
        "year": 2008,
        "profit": 14_000_000_000,
        "strategy_type": "macro",
        "instrument": "Bonds, gold, TIPS",
        "description": "Bridgewater's Pure Alpha fund returned 9.4% in 2008 while the S&P dropped 37%. Dalio had positioned into Treasuries and gold. His 'Beautiful Deleveraging' thesis proved exactly right.",
        "rating": 4,
        "still_active": False,
    },
    {
        "trader": "George Soros",
        "trade_name": "The 1987 Japan Short",
        "year": 1987,
        "profit": 300_000_000,
        "strategy_type": "short",
        "instrument": "Japanese equities",
        "description": "Soros shorted Japanese stocks ahead of the 1987 crash but got caught on the wrong side initially. He then doubled down and made $300M. He said this trade taught him more than any winner.",
        "rating": 3,
        "still_active": False,
    },
    {
        "trader": "Kyle Bass",
        "trade_name": "Subprime Mortgage CDS",
        "year": 2007,
        "profit": 500_000_000,
        "strategy_type": "short",
        "instrument": "CDS on subprime MBS",
        "description": "Another Big Short hero. Bass turned $30M into $500M+ by buying credit default swaps on subprime mortgage bonds. His Hayman Capital became famous for macro bets.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Carl Icahn",
        "trade_name": "TWA Corporate Raid",
        "year": 1985,
        "profit": 469_000_000,
        "strategy_type": "long",
        "instrument": "TWA equity",
        "description": "Took over Trans World Airlines in a hostile takeover, sold off its assets, and walked away with $469M while the airline eventually went bankrupt. Defined the era of corporate raiders.",
        "rating": 3,
        "still_active": True,
    },
    {
        "trader": "T. Boone Pickens",
        "trade_name": "Gulf Oil Takeover Bid",
        "year": 1984,
        "profit": 760_000_000,
        "strategy_type": "long",
        "instrument": "Gulf Oil equity",
        "description": "Launched a hostile bid for Gulf Oil, which was 10x the size of his own company. Even though the bid failed, he forced a sale to Chevron and walked away with $760M in greenmail profits.",
        "rating": 4,
        "still_active": False,
    },
    {
        "trader": "Izzy Englander",
        "trade_name": "Millennium Management's Machine",
        "year": 2022,
        "profit": 8_000_000_000,
        "strategy_type": "arbitrage",
        "instrument": "Multi-strategy",
        "description": "Millennium made $8B in 2022 while most funds lost money. Englander's pod-based multi-strategy model has become the template for modern hedge funds. Virtually no down years since founding.",
        "rating": 4,
        "still_active": True,
    },
    {
        "trader": "Ken Griffin",
        "trade_name": "Citadel's 2022 Record Year",
        "year": 2022,
        "profit": 16_000_000_000,
        "strategy_type": "arbitrage",
        "instrument": "Multi-strategy",
        "description": "Citadel made $16B in net gains in 2022 — the most profitable year by any hedge fund ever. Griffin started trading from his Harvard dorm room with a satellite dish on the roof.",
        "rating": 4,
        "still_active": True,
    },
]


def _format_usd(amount: int) -> str:
    """Format dollar amount for display."""
    if amount >= 1_000_000_000_000:
        return f"${amount / 1_000_000_000_000:.1f}T"
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.0f}M"
    if amount > 0:
        return f"${amount:,.0f}"
    return "N/A"


def _strategy_emoji(strategy_type: str) -> str:
    return {
        "short": "\U0001F4C9",       # chart decreasing
        "long": "\U0001F4C8",        # chart increasing
        "macro": "\U0001F30D",       # globe
        "options": "\U0001F3B0",     # slot machine
        "arbitrage": "\u2696\uFE0F", # scales
    }.get(strategy_type, "\U0001F4B0")


def _strategy_color(strategy_type: str) -> str:
    return {
        "short": "bg-red-600/30 text-red-400 border-red-500/40",
        "long": "bg-green-600/30 text-green-400 border-green-500/40",
        "macro": "bg-blue-600/30 text-blue-400 border-blue-500/40",
        "options": "bg-purple-600/30 text-purple-400 border-purple-500/40",
        "arbitrage": "bg-cyan-600/30 text-cyan-400 border-cyan-500/40",
    }.get(strategy_type, "bg-gray-600/30 text-gray-400 border-gray-500/40")


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


@router.get("/hall-of-legends", response_class=HTMLResponse)
async def hall_of_legends(request: Request):
    """Hall of Legends — The Greatest Trades in Market History."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)

    # Sort by profit (descending)
    sorted_by_profit = sorted(LEGENDS_DATA, key=lambda r: r["profit"], reverse=True)

    # Aggregate stats
    total_profit = sum(r["profit"] for r in LEGENDS_DATA)
    total_traders = len(set(r["trader"] for r in LEGENDS_DATA))
    greatest_trade = max(LEGENDS_DATA, key=lambda r: r["profit"])
    still_active = sum(1 for r in LEGENDS_DATA if r["still_active"])
    five_star = sum(1 for r in LEGENDS_DATA if r["rating"] == 5)

    # Decade breakdown
    decades = {}
    for r in LEGENDS_DATA:
        decade = f"{(r['year'] // 10) * 10}s"
        if decade not in decades:
            decades[decade] = {"count": 0, "profit": 0}
        decades[decade]["count"] += 1
        decades[decade]["profit"] += r["profit"]

    # Strategy breakdown
    strategy_counts = {}
    for r in LEGENDS_DATA:
        st = r["strategy_type"]
        strategy_counts[st] = strategy_counts.get(st, 0) + 1

    ctx.update({
        "legends": sorted_by_profit,
        "total_profit": total_profit,
        "total_traders": total_traders,
        "greatest_trade": greatest_trade,
        "still_active": still_active,
        "five_star": five_star,
        "decades": dict(sorted(decades.items())),
        "strategy_counts": dict(sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True)),
        "format_usd": _format_usd,
        "strategy_emoji": _strategy_emoji,
        "strategy_color": _strategy_color,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("hall_of_legends.html", ctx)
