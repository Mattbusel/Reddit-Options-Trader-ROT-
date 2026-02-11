"""Glossary of Degens — The definitive WSB trading dictionary."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()


# ── WSB/Trading slang dictionary ──
# Categories: strategy, emotion, culture, instrument, insult
# Degen rating: 1 (mainstream) to 5 (peak degen)

GLOSSARY_DATA = [
    {"term": "Ape", "definition": "A retail investor who buys and holds a stock regardless of fundamentals, often out of spite toward short sellers.", "example": "Just aping into GME again, don't even care about the earnings report", "category": "culture", "degen_rating": 3},
    {"term": "ATH", "definition": "All-Time High. When a stock or portfolio reaches its highest price ever.", "example": "NVDA just hit ATH and I'm still not selling", "category": "instrument", "degen_rating": 1},
    {"term": "ATM", "definition": "At The Money. An option with a strike price equal to the current stock price.", "example": "Bought ATM calls expiring Friday, let's ride", "category": "instrument", "degen_rating": 2},
    {"term": "Bagholder", "definition": "Someone left holding shares of a stock that has plummeted in value. They bought the top and are now 'holding the bag.'", "example": "I'm a proud WISH bagholder at $14, current price $0.50", "category": "insult", "degen_rating": 3},
    {"term": "Bear", "definition": "Someone who believes a stock or the market will go down. Bears buy puts or short stocks.", "example": "I've been a bear on TSLA since $200 and I've been wrong every single time", "category": "emotion", "degen_rating": 1},
    {"term": "BTFD", "definition": "Buy The F***ing Dip. A rallying cry to buy when prices drop, assuming they'll recover.", "example": "SPY down 2%? BTFD this is a gift", "category": "strategy", "degen_rating": 3},
    {"term": "Bull", "definition": "Someone who believes a stock or the market will go up. Bulls buy calls or shares.", "example": "Perma-bull since birth, bears are always wrong eventually", "category": "emotion", "degen_rating": 1},
    {"term": "Calls", "definition": "Call options. Give you the right to BUY a stock at a specific price. You buy calls when you think a stock will go UP.", "example": "AAPL 200c 3/21 let's gooooo", "category": "instrument", "degen_rating": 2},
    {"term": "Crayon Eater", "definition": "Someone who does technical analysis (drawing lines on charts). Self-deprecating term implying TA is as sophisticated as eating crayons.", "example": "As a crayon eater, I can confirm the head and shoulders pattern on this chart", "category": "insult", "degen_rating": 3},
    {"term": "DD", "definition": "Due Diligence. An in-depth analysis or research post about a stock. The holy grail of WSB content.", "example": "Just spent 47 hours writing DD on why PLTR is going to $100. TLDR: buy calls", "category": "strategy", "degen_rating": 2},
    {"term": "Degen", "definition": "Degenerate. A trader who makes reckless, high-risk bets. Worn as a badge of honor on WSB.", "example": "Full degen mode activated: just put my entire savings into 0DTE SPY calls", "category": "culture", "degen_rating": 4},
    {"term": "Diamond Hands", "definition": "Holding a position through extreme volatility without selling. The ultimate compliment on WSB.", "example": "Down 80% and still holding. Diamond hands baby, these shares are going to the grave with me", "category": "emotion", "degen_rating": 4},
    {"term": "FD", "definition": "A deeply out-of-the-money option expiring very soon (usually same week). Originally stood for something NSFW. The riskiest play possible.", "example": "Bought SPY 500c 0DTE for $0.03, this is either Lambos or Wendys", "category": "instrument", "degen_rating": 5},
    {"term": "FOMO", "definition": "Fear Of Missing Out. The anxiety that drives you to buy a stock after it's already pumped 200%.", "example": "I know I shouldn't chase but FOMO is too strong, buying the top again", "category": "emotion", "degen_rating": 3},
    {"term": "FUD", "definition": "Fear, Uncertainty, and Doubt. Negative sentiment or information spread about a stock, often accused of being deliberate manipulation.", "example": "Don't listen to the FUD, the shorts are desperate", "category": "emotion", "degen_rating": 2},
    {"term": "Gain Porn", "definition": "Screenshots of massive unrealized or realized profits. The content that makes WSB jealous.", "example": "Check out this gain porn: turned $500 into $50,000 on TSLA weeklies", "category": "culture", "degen_rating": 4},
    {"term": "Gamma Ramp", "definition": "When market makers who sold call options have to buy the underlying stock to hedge, creating a self-reinforcing upward price spiral.", "example": "The gamma ramp is set up perfectly for a squeeze, we just need volume", "category": "strategy", "degen_rating": 3},
    {"term": "GUH", "definition": "The sound of watching your entire portfolio evaporate. Origin: a WSB member who live-streamed his account going to zero.", "example": "Just opened my portfolio... GUH", "category": "culture", "degen_rating": 5},
    {"term": "HODL", "definition": "Hold On for Dear Life. Originally a typo in a Bitcoin forum post that became a meme. Means holding no matter what.", "example": "HODL gang checking in, I'll sell when I'm dead", "category": "strategy", "degen_rating": 3},
    {"term": "Hopium", "definition": "The drug of irrational optimism. When you hold a losing position based on hope rather than any logical thesis.", "example": "My BBBY calls are down 95% but I'm high on hopium, this is fine", "category": "emotion", "degen_rating": 4},
    {"term": "IV Crush", "definition": "Implied Volatility Crush. When IV drops sharply after an event (like earnings), destroying the value of options even if you got the direction right.", "example": "Stock went up 5% after earnings but my calls lost money because of IV crush. I hate this game.", "category": "instrument", "degen_rating": 2},
    {"term": "LMAO Gottem", "definition": "The feeling when your ridiculous YOLO trade actually works out and you can laugh at everyone who doubted you.", "example": "They called me crazy for buying 0DTE puts. LMAO GOTTEM", "category": "culture", "degen_rating": 4},
    {"term": "Loss Porn", "definition": "Screenshots of massive losses. WSB's favorite content. The worse the loss, the more upvotes.", "example": "Here's my loss porn: -$97,000 on WISH. My wife's boyfriend is not happy.", "category": "culture", "degen_rating": 5},
    {"term": "Moon", "definition": "When a stock price skyrockets. 'To the moon' is the ultimate bull thesis.", "example": "GME is going to the moon, pack your bags apes", "category": "emotion", "degen_rating": 3},
    {"term": "OTM", "definition": "Out of The Money. An option that has no intrinsic value. Calls with strikes above current price, puts with strikes below.", "example": "Bought some deep OTM calls because I like lottery tickets", "category": "instrument", "degen_rating": 2},
    {"term": "Paper Hands", "definition": "Selling a position at the first sign of a dip. The opposite of diamond hands. The worst insult on WSB.", "example": "If you sold GME at $150 you have paper hands and deserve to be poor", "category": "insult", "degen_rating": 3},
    {"term": "Puts", "definition": "Put options. Give you the right to SELL a stock at a specific price. You buy puts when you think a stock will go DOWN.", "example": "TSLA 100p 4/20 because Elon tweeted something dumb again", "category": "instrument", "degen_rating": 2},
    {"term": "Regard", "definition": "The WSB-safe version of a word that rhymes with it. A term of endearment among degens.", "example": "You beautiful regards actually did it, we squeezed the shorts", "category": "insult", "degen_rating": 4},
    {"term": "Smooth Brain", "definition": "Someone who makes decisions without thinking. A compliment in WSB culture. The fewer wrinkles, the more degen.", "example": "I'm too smooth-brained to understand the 10-K, I just buy what the DD says", "category": "insult", "degen_rating": 3},
    {"term": "Stonks", "definition": "The intentionally misspelled version of 'stocks.' Used ironically when making terrible financial decisions.", "example": "Stonks only go up, everyone knows this", "category": "culture", "degen_rating": 3},
    {"term": "Tendies", "definition": "Profits. Chicken tenders. The reward for a successful trade. Originally from Good Boy Points meme culture.", "example": "If this trade works out I'm getting tendies for a month", "category": "culture", "degen_rating": 4},
    {"term": "The Wheel", "definition": "An options strategy: sell cash-secured puts, get assigned, then sell covered calls. Repeat. Theta gang's bread and butter.", "example": "Running the wheel on AAPL, collecting $500/week in premium. Boring but profitable.", "category": "strategy", "degen_rating": 1},
    {"term": "Theta Gang", "definition": "Options sellers who profit from time decay (theta). They sell options to degens and collect premium while time erodes option value.", "example": "Theta gang always wins. Let the degens buy FDs, I'll sell them.", "category": "strategy", "degen_rating": 2},
    {"term": "To the Moon", "definition": "A stock is about to or should go to extremely high prices. The universal WSB bullish thesis.", "example": "This is it boys, AMC to the moon, apes together strong", "category": "emotion", "degen_rating": 3},
    {"term": "Wendy's", "definition": "Where you'll be working after your YOLO fails. The default fallback career for broke traders.", "example": "My 0DTE puts expired worthless, see you at the Wendy's dumpster", "category": "culture", "degen_rating": 4},
    {"term": "Wife's Boyfriend", "definition": "A running joke that WSB members are such losers that their wives have boyfriends. Used self-deprecatingly.", "example": "My wife's boyfriend said I could use his computer to check my portfolio today", "category": "culture", "degen_rating": 5},
    {"term": "Wrinkle Brain", "definition": "Someone who is actually smart and does real research. The opposite of smooth brain. Used with genuine respect.", "example": "This DD is incredible, OP is a true wrinkle brain", "category": "culture", "degen_rating": 2},
    {"term": "YOLO", "definition": "You Only Live Once. Going all-in on a single trade with your entire account. The purest expression of degen trading.", "example": "YOLO'd my entire 401k into TSLA 300c weeklies. Either I retire or I restart. No in-between.", "category": "strategy", "degen_rating": 5},
    {"term": "0DTE", "definition": "Zero Days To Expiration. Options that expire TODAY. Maximum risk, maximum reward, maximum degen.", "example": "0DTE SPY puts at open, let's see if Powell tanks the market today", "category": "instrument", "degen_rating": 5},
    {"term": "Bag", "definition": "A losing position you're still holding. 'Holding bags' means you're stuck with worthless shares.", "example": "Still holding these CLOV bags from last summer, down 85%", "category": "instrument", "degen_rating": 2},
    {"term": "Chad", "definition": "A trader who makes bold, confident moves that work out. The ideal degen.", "example": "That guy who put $100K into GME at $4 is a total Chad", "category": "culture", "degen_rating": 3},
    {"term": "Copium", "definition": "The copium you inhale to convince yourself your losing trade will turn around. The opposite of hopium - you know you're coping.", "example": "It's not a loss until you sell, right? *inhales copium*", "category": "emotion", "degen_rating": 4},
    {"term": "DFV", "definition": "DeepF***ingValue. The legendary WSB member (Keith Gill) who turned $53K into $46M on GameStop. A living legend.", "example": "If DFV is still in, I'm still in", "category": "culture", "degen_rating": 4},
    {"term": "Earnings Roulette", "definition": "Buying options before an earnings report hoping for a big move. Pure gambling with extra steps.", "example": "Playing earnings roulette on AMZN tonight, straddle or bust", "category": "strategy", "degen_rating": 4},
    {"term": "Exit Liquidity", "definition": "The person who buys your bags at the top. If you don't know who the exit liquidity is, it's you.", "example": "Thanks for being my exit liquidity at $400, regards", "category": "insult", "degen_rating": 4},
    {"term": "Green Dildo", "definition": "A large green candlestick on a stock chart, indicating a sharp price increase.", "example": "Wake up to a massive green dildo on the 5-min chart, we eating today", "category": "instrument", "degen_rating": 4},
    {"term": "Infinite Money Glitch", "definition": "A trade setup that theoretically can't lose. Spoiler: it can and will lose.", "example": "Found an infinite money glitch: sell puts, use premium to buy calls. Can't go tits up.", "category": "strategy", "degen_rating": 5},
    {"term": "ITM", "definition": "In The Money. An option that has intrinsic value. Calls below current price, puts above.", "example": "My ITM calls are finally printing, patience pays off", "category": "instrument", "degen_rating": 1},
    {"term": "Lambo", "definition": "Lamborghini. The dream purchase after a YOLO pays off. The ultimate degen milestone.", "example": "When this trade hits I'm getting a lambo. When it doesn't I'm getting a bus pass.", "category": "culture", "degen_rating": 4},
    {"term": "Let It Ride", "definition": "Not taking profits and letting a winning trade continue running. Usually ends in tears.", "example": "Up 400% but I'm going to let it ride because I'm greedy and stupid", "category": "strategy", "degen_rating": 4},
    {"term": "NGMI", "definition": "Not Gonna Make It. Used to describe someone making terrible financial decisions (which is everyone on WSB).", "example": "Sold your GME at $40? NGMI", "category": "insult", "degen_rating": 3},
    {"term": "Power Hour", "definition": "The last hour of trading (3-4 PM ET). When volume surges and degens make their most impulsive decisions.", "example": "Waiting for power hour to YOLO into SPY calls", "category": "instrument", "degen_rating": 2},
    {"term": "Printer Go Brrr", "definition": "The Federal Reserve printing money (quantitative easing), which inflates asset prices. The ultimate bull thesis.", "example": "Why would I buy puts? Money printer go brrr, stonks only go up", "category": "strategy", "degen_rating": 3},
    {"term": "Red Dildo", "definition": "A large red candlestick on a chart, indicating a sharp price drop.", "example": "Three red dildos in a row, my calls are toast", "category": "instrument", "degen_rating": 4},
    {"term": "Short Ladder Attack", "definition": "An alleged manipulation tactic by short sellers. Whether it's real or conspiracy theory depends on who you ask.", "example": "They're doing a short ladder attack on GME again! Hold the line!", "category": "strategy", "degen_rating": 3},
    {"term": "Short Squeeze", "definition": "When a heavily shorted stock rises, forcing short sellers to buy shares to cover, driving the price even higher. The holy grail of WSB.", "example": "Short interest is 140%, this is the mother of all short squeezes", "category": "strategy", "degen_rating": 3},
    {"term": "Tits Up", "definition": "When a trade goes catastrophically wrong. Usually preceded by 'literally cannot go.'", "example": "He said it literally can't go tits up. It went tits up.", "category": "culture", "degen_rating": 5},
    {"term": "WAGMI", "definition": "We're All Gonna Make It. The opposite of NGMI. Used to express collective optimism.", "example": "Apes together strong. WAGMI", "category": "emotion", "degen_rating": 3},
]


def _degen_skulls(rating: int) -> str:
    """Return skull emojis for degen rating."""
    return "\U0001F480" * rating


def _category_color(cat: str) -> str:
    return {
        "strategy": "bg-blue-600/30 text-blue-400 border-blue-500/40",
        "emotion": "bg-purple-600/30 text-purple-400 border-purple-500/40",
        "culture": "bg-orange-600/30 text-orange-400 border-orange-500/40",
        "instrument": "bg-green-600/30 text-green-400 border-green-500/40",
        "insult": "bg-red-600/30 text-red-400 border-red-500/40",
    }.get(cat, "bg-gray-600/30 text-gray-400 border-gray-500/40")


def _category_emoji(cat: str) -> str:
    return {
        "strategy": "\U0001F9E0",  # brain
        "emotion": "\U0001F525",   # fire
        "culture": "\U0001F3AD",   # performing arts
        "instrument": "\U0001F4CA", # bar chart
        "insult": "\U0001F921",    # clown
    }.get(cat, "\U0001F4F0")


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


@router.get("/glossary", response_class=HTMLResponse)
async def glossary(request: Request, category: str = "all", letter: str = "all"):
    """Glossary of Degens — The definitive WSB trading dictionary."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)

    # Sort alphabetically
    sorted_terms = sorted(GLOSSARY_DATA, key=lambda t: t["term"].upper())

    # Apply filters
    if category != "all":
        sorted_terms = [t for t in sorted_terms if t["category"] == category]
    if letter != "all":
        sorted_terms = [t for t in sorted_terms if t["term"][0].upper() == letter.upper()]

    # Get all unique first letters
    all_letters = sorted(set(t["term"][0].upper() for t in GLOSSARY_DATA))
    all_categories = ["strategy", "emotion", "culture", "instrument", "insult"]

    # Category counts
    category_counts = {}
    for t in GLOSSARY_DATA:
        category_counts[t["category"]] = category_counts.get(t["category"], 0) + 1

    # Stats
    avg_degen = sum(t["degen_rating"] for t in GLOSSARY_DATA) / len(GLOSSARY_DATA) if GLOSSARY_DATA else 0
    max_degen = [t for t in GLOSSARY_DATA if t["degen_rating"] == 5]

    # Build FAQPage JSON-LD schema from glossary data
    faq_items = []
    for t in GLOSSARY_DATA:
        faq_items.append({
            "@type": "Question",
            "name": f"What does {t['term']} mean in trading?",
            "acceptedAnswer": {
                "@type": "Answer",
                "text": t["definition"],
            },
        })
    faq_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": faq_items,
    })

    # Share URL
    base = str(request.base_url).rstrip("/")

    ctx.update({
        "terms": sorted_terms,
        "total_terms": len(GLOSSARY_DATA),
        "all_letters": all_letters,
        "all_categories": all_categories,
        "selected_category": category,
        "selected_letter": letter,
        "category_counts": category_counts,
        "avg_degen": avg_degen,
        "max_degen_count": len(max_degen),
        "degen_skulls": _degen_skulls,
        "category_color": _category_color,
        "category_emoji": _category_emoji,
        "faq_schema": faq_schema,
        "share_url": f"{base}/glossary",
        "share_text": f"WSB Trading Dictionary — {len(GLOSSARY_DATA)} degen terms explained",
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("glossary.html", ctx)
