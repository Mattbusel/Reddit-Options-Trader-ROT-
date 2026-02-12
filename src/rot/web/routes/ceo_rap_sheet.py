"""CEO Rap Sheet — Corporate leader scandal and controversy tracker."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()


# ── CEO / Executive Controversies ──
# Sources: DOJ, SEC, court records, public reporting
#
# Fields:
#   name           – executive name
#   company        – company at time of scandal
#   ticker         – stock ticker (or "" if private/defunct)
#   year           – primary year of scandal
#   category       – fraud / insider_trading / sec_violation / workplace / environmental / crypto
#   description    – brief summary
#   outcome        – convicted / settled / acquitted / ongoing / no_charges / fled
#   fine_amount    – personal fine or restitution in USD (0 if none)
#   shame_score    – 1-10 scale of severity
#   still_active   – whether they're still a CEO/executive

CEO_DATA = [
    {
        "name": "Jeffrey Skilling",
        "company": "Enron",
        "ticker": "ENE",
        "year": 2001,
        "category": "fraud",
        "description": "Orchestrated one of the largest corporate frauds in history. Enron's fake accounting hid billions in debt. 20,000 employees lost jobs and pensions. Skilling sentenced to 24 years.",
        "outcome": "convicted",
        "fine_amount": 45_000_000,
        "shame_score": 10,
        "still_active": False,
    },
    {
        "name": "Bernie Ebbers",
        "company": "WorldCom",
        "ticker": "WCOM",
        "year": 2002,
        "category": "fraud",
        "description": "Directed an $11B accounting fraud at WorldCom, the largest in history at the time. Sentenced to 25 years. Died in prison in 2020 after compassionate release.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 10,
        "still_active": False,
    },
    {
        "name": "Sam Bankman-Fried",
        "company": "FTX",
        "ticker": "",
        "year": 2022,
        "category": "crypto",
        "description": "Stole $10B+ in customer deposits from FTX crypto exchange to fund Alameda Research. Convicted on 7 fraud and conspiracy counts. Sentenced to 25 years. The crypto Bernie Madoff.",
        "outcome": "convicted",
        "fine_amount": 11_000_000_000,
        "shame_score": 10,
        "still_active": False,
    },
    {
        "name": "Elizabeth Holmes",
        "company": "Theranos",
        "ticker": "",
        "year": 2018,
        "category": "fraud",
        "description": "Claimed Theranos could run hundreds of blood tests from a single drop. It couldn't. Defrauded investors of $700M+ and endangered patients with fake test results. Sentenced to 11 years.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "Dennis Kozlowski",
        "company": "Tyco International",
        "ticker": "TYC",
        "year": 2002,
        "category": "fraud",
        "description": "Looted $600M from Tyco. Infamous $6,000 shower curtain and $2M birthday party on the company dime. Sentenced to 8-25 years. Released in 2014.",
        "outcome": "convicted",
        "fine_amount": 70_000_000,
        "shame_score": 8,
        "still_active": False,
    },
    {
        "name": "Richard Fuld",
        "company": "Lehman Brothers",
        "ticker": "LEH",
        "year": 2008,
        "category": "fraud",
        "description": "CEO during Lehman's $691B collapse that triggered the global financial crisis. Used Repo 105 accounting tricks to hide $50B in debt. Never criminally charged despite congressional grilling.",
        "outcome": "no_charges",
        "fine_amount": 0,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "Angelo Mozilo",
        "company": "Countrywide Financial",
        "ticker": "CFC",
        "year": 2008,
        "category": "sec_violation",
        "description": "CEO of the largest subprime mortgage lender. Made $140M selling stock while knowing loans were toxic. Settled with SEC for $67.5M. Never criminally charged. Ground zero of the housing crisis.",
        "outcome": "settled",
        "fine_amount": 67_500_000,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "John Stumpf",
        "company": "Wells Fargo",
        "ticker": "WFC",
        "year": 2016,
        "category": "fraud",
        "description": "Oversaw creation of 16 million fake customer accounts to hit sales targets. Employees opened accounts without permission, charged fees on them. Fined $17.5M personally, clawed back $41M. Banned from banking.",
        "outcome": "settled",
        "fine_amount": 17_500_000,
        "shame_score": 8,
        "still_active": False,
    },
    {
        "name": "Martin Shkreli",
        "company": "Turing Pharmaceuticals",
        "ticker": "",
        "year": 2015,
        "category": "fraud",
        "description": "Raised the price of Daraprim (a life-saving AIDS drug) by 5,000% overnight from $13.50 to $750. Later convicted of securities fraud at his hedge fund. Sentenced to 7 years. Dubbed 'Pharma Bro.'",
        "outcome": "convicted",
        "fine_amount": 64_600_000,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "Elon Musk",
        "company": "Tesla",
        "ticker": "TSLA",
        "year": 2018,
        "category": "sec_violation",
        "description": "Tweeted 'Am considering taking Tesla private at $420. Funding secured.' The funding was not secured. SEC sued, settled for $20M fine each (Musk + Tesla), forced to step down as chairman.",
        "outcome": "settled",
        "fine_amount": 20_000_000,
        "shame_score": 5,
        "still_active": True,
    },
    {
        "name": "Adam Neumann",
        "company": "WeWork",
        "ticker": "WE",
        "year": 2019,
        "category": "fraud",
        "description": "Burned through $16B trying to IPO a real estate company as a tech startup. Self-dealing: charged WeWork $5.9M for his own 'We' trademark. Ousted before IPO. Got $1.7B exit package.",
        "outcome": "no_charges",
        "fine_amount": 0,
        "shame_score": 7,
        "still_active": True,
    },
    {
        "name": "Travis Kalanick",
        "company": "Uber",
        "ticker": "UBER",
        "year": 2017,
        "category": "workplace",
        "description": "Fostered a toxic culture including harassment, discrimination, and surveillance of competitors. Uber used 'Greyball' tool to evade regulators. Forced to resign as CEO. Still a billionaire.",
        "outcome": "no_charges",
        "fine_amount": 0,
        "shame_score": 6,
        "still_active": False,
    },
    {
        "name": "Do Kwon",
        "company": "Terraform Labs",
        "ticker": "",
        "year": 2022,
        "category": "crypto",
        "description": "Designed the Luna/UST stablecoin that collapsed in May 2022, wiping out $40B and destroying life savings. Fled to Montenegro, was arrested, extradited. SEC won a $4.5B judgment.",
        "outcome": "convicted",
        "fine_amount": 4_500_000_000,
        "shame_score": 10,
        "still_active": False,
    },
    {
        "name": "Changpeng Zhao (CZ)",
        "company": "Binance",
        "ticker": "",
        "year": 2023,
        "category": "crypto",
        "description": "CEO of the world's largest crypto exchange. Pled guilty to AML violations for allowing money laundering and sanctions evasion. Binance fined $4.3B. CZ sentenced to 4 months in prison.",
        "outcome": "convicted",
        "fine_amount": 50_000_000,
        "shame_score": 7,
        "still_active": False,
    },
    {
        "name": "Markus Braun",
        "company": "Wirecard",
        "ticker": "WDI",
        "year": 2020,
        "category": "fraud",
        "description": "CEO of German fintech whose $2.1B in reported cash 'didn't exist.' Europe's Enron. Braun arrested, COO Jan Marsalek fled and is still missing. Company collapsed overnight.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "Michael Milken",
        "company": "Drexel Burnham Lambert",
        "ticker": "",
        "year": 1989,
        "category": "insider_trading",
        "description": "The 'Junk Bond King' who revolutionized high-yield debt. Indicted on 98 counts of racketeering and fraud. Pled guilty to 6 felonies, paid $600M in fines. Banned from securities. Later pardoned by Trump.",
        "outcome": "convicted",
        "fine_amount": 600_000_000,
        "shame_score": 8,
        "still_active": False,
    },
    {
        "name": "Ivan Boesky",
        "company": "Boesky Corp",
        "ticker": "",
        "year": 1986,
        "category": "insider_trading",
        "description": "The original Wall Street insider trader. His cooperation brought down Michael Milken and Drexel. Fined $100M, sentenced to 3.5 years. Inspired Gordon Gekko's 'Greed is good' speech.",
        "outcome": "convicted",
        "fine_amount": 100_000_000,
        "shame_score": 8,
        "still_active": False,
    },
    {
        "name": "Raj Rajaratnam",
        "company": "Galleon Group",
        "ticker": "",
        "year": 2011,
        "category": "insider_trading",
        "description": "Ran the largest hedge fund insider trading ring in history. FBI wiretaps caught him receiving tips from Goldman Sachs board members. Sentenced to 11 years. Forfeited $53.8M.",
        "outcome": "convicted",
        "fine_amount": 53_800_000,
        "shame_score": 8,
        "still_active": False,
    },
    {
        "name": "Steve Cohen",
        "company": "SAC Capital",
        "ticker": "",
        "year": 2013,
        "category": "insider_trading",
        "description": "SAC Capital pled guilty to insider trading, paid $1.8B. Cohen personally was never charged despite 8 employees being convicted. Banned from managing outside money for 2 years. Now runs Point72.",
        "outcome": "no_charges",
        "fine_amount": 0,
        "shame_score": 6,
        "still_active": True,
    },
    {
        "name": "Jamie Dimon",
        "company": "JPMorgan Chase",
        "ticker": "JPM",
        "year": 2020,
        "category": "sec_violation",
        "description": "Under his leadership, JPM accumulated $34.2B in fines — the most of any bank CEO in history. Includes mortgage fraud, precious metals manipulation, and the London Whale disaster. Still CEO.",
        "outcome": "no_charges",
        "fine_amount": 0,
        "shame_score": 6,
        "still_active": True,
    },
    {
        "name": "Lloyd Blankfein",
        "company": "Goldman Sachs",
        "ticker": "GS",
        "year": 2010,
        "category": "sec_violation",
        "description": "Goldman sold toxic mortgage CDOs to clients while secretly betting against them. Famous 'Fabulous Fab' emails. Testified to Congress that Goldman was 'doing God's work.' $550M SEC settlement.",
        "outcome": "settled",
        "fine_amount": 0,
        "shame_score": 7,
        "still_active": False,
    },
    {
        "name": "Ken Lay",
        "company": "Enron",
        "ticker": "ENE",
        "year": 2001,
        "category": "fraud",
        "description": "Enron founder who built the fraud factory. Encouraged employees to buy stock while secretly selling his own. Convicted on 10 counts. Died of a heart attack before sentencing, vacating the conviction.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 10,
        "still_active": False,
    },
    {
        "name": "Andrew Fastow",
        "company": "Enron",
        "ticker": "ENE",
        "year": 2001,
        "category": "fraud",
        "description": "Enron's CFO who created the off-balance-sheet entities that hid billions in debt. Made $45M from the schemes. Cooperated with prosecutors, sentenced to 6 years. The architect of the fraud.",
        "outcome": "convicted",
        "fine_amount": 23_800_000,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "Bernie Madoff",
        "company": "BMIS",
        "ticker": "",
        "year": 2008,
        "category": "fraud",
        "description": "Ran the largest Ponzi scheme in history for at least 17 years. $64.8B in stated client assets vanished. Thousands of victims including charities. Sentenced to 150 years. Died in prison.",
        "outcome": "convicted",
        "fine_amount": 170_000_000_000,
        "shame_score": 10,
        "still_active": False,
    },
    {
        "name": "Allen Stanford",
        "company": "Stanford Financial",
        "ticker": "",
        "year": 2009,
        "category": "fraud",
        "description": "Ran a $7B Ponzi scheme through fake certificates of deposit in Antigua. FBI raided his offices. Convicted on 13 felony counts. Sentenced to 110 years in federal prison.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 9,
        "still_active": False,
    },
    {
        "name": "Carlos Ghosn",
        "company": "Nissan / Renault",
        "ticker": "NSANY",
        "year": 2018,
        "category": "fraud",
        "description": "Auto industry titan arrested in Tokyo for hiding $80M+ in compensation. Escaped Japan while out on bail by hiding in a musical equipment box on a private jet. Now a fugitive in Lebanon.",
        "outcome": "fled",
        "fine_amount": 0,
        "shame_score": 7,
        "still_active": False,
    },
    {
        "name": "John McAfee",
        "company": "McAfee / Various",
        "ticker": "",
        "year": 2020,
        "category": "crypto",
        "description": "Antivirus pioneer turned crypto pump-and-dumper. Charged with tax evasion and crypto fraud. Made millions promoting ICOs without disclosing payments. Found dead in Spanish prison cell before extradition.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 7,
        "still_active": False,
    },
    {
        "name": "Jack Dorsey",
        "company": "Block (Square)",
        "ticker": "SQ",
        "year": 2023,
        "category": "sec_violation",
        "description": "DOJ and SEC investigations into Cash App for inadequate anti-money laundering controls. Block settled with multiple regulators. Cash App reportedly processed transactions for terrorists and sanctioned entities.",
        "outcome": "settled",
        "fine_amount": 80_000_000,
        "shame_score": 4,
        "still_active": False,
    },
    {
        "name": "Trevor Milton",
        "company": "Nikola",
        "ticker": "NKLA",
        "year": 2020,
        "category": "fraud",
        "description": "Claimed Nikola had a working hydrogen semi-truck. The demo video was a truck rolling downhill with no engine. Convicted of 3 fraud counts for lying to investors. Sentenced to 4 years.",
        "outcome": "convicted",
        "fine_amount": 0,
        "shame_score": 8,
        "still_active": False,
    },
    {
        "name": "Mark Zuckerberg",
        "company": "Meta (Facebook)",
        "ticker": "META",
        "year": 2019,
        "category": "sec_violation",
        "description": "Cambridge Analytica scandal: 87M users' data harvested without consent. FTC fined Facebook $5B — largest FTC fine in history. Accused of knowing and ignoring the data misuse for years.",
        "outcome": "settled",
        "fine_amount": 5_000_000_000,
        "shame_score": 6,
        "still_active": True,
    },
]


def _format_usd(amount: int) -> str:
    if amount >= 1_000_000_000_000:
        return f"${amount / 1_000_000_000_000:.1f}T"
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.0f}M"
    if amount > 0:
        return f"${amount:,.0f}"
    return "N/A"


def _category_emoji(cat: str) -> str:
    return {
        "fraud": "\U0001F3AD",          # performing arts
        "insider_trading": "\U0001F4B8", # money with wings
        "sec_violation": "\U0001F4C4",   # document
        "workplace": "\U0001F6A8",       # police light
        "environmental": "\U0001F30D",   # globe
        "crypto": "\U0001FA99",          # coin
    }.get(cat, "\U0001F4B0")


def _category_color(cat: str) -> str:
    return {
        "fraud": "bg-red-600/30 text-red-400 border-red-500/40",
        "insider_trading": "bg-purple-600/30 text-purple-400 border-purple-500/40",
        "sec_violation": "bg-yellow-600/30 text-yellow-400 border-yellow-500/40",
        "workplace": "bg-orange-600/30 text-orange-400 border-orange-500/40",
        "environmental": "bg-green-600/30 text-green-400 border-green-500/40",
        "crypto": "bg-cyan-600/30 text-cyan-400 border-cyan-500/40",
    }.get(cat, "bg-gray-600/30 text-gray-400 border-gray-500/40")


def _outcome_color(outcome: str) -> str:
    return {
        "convicted": "bg-red-900/40 text-red-400 border-red-700/50",
        "settled": "bg-yellow-900/40 text-yellow-400 border-yellow-700/50",
        "acquitted": "bg-green-900/40 text-green-400 border-green-700/50",
        "ongoing": "bg-blue-900/40 text-blue-400 border-blue-700/50",
        "no_charges": "bg-gray-800 text-gray-400 border-gray-700/50",
        "fled": "bg-purple-900/40 text-purple-400 border-purple-700/50",
    }.get(outcome, "bg-gray-800 text-gray-400 border-gray-700/50")


def _outcome_emoji(outcome: str) -> str:
    return {
        "convicted": "\u2696\uFE0F",    # scales
        "settled": "\U0001F4B0",         # money bag
        "acquitted": "\u2705",           # green check
        "ongoing": "\u23F3",             # hourglass
        "no_charges": "\U0001F937",      # shrug
        "fled": "\U0001F3C3",            # runner
    }.get(outcome, "")


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


@router.get("/ceo-rap-sheet", response_class=HTMLResponse)
async def ceo_rap_sheet(request: Request, category: str = "all"):
    """CEO Rap Sheet — Corporate leader scandal tracker."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)

    # Filter by category
    filtered = CEO_DATA if category == "all" else [c for c in CEO_DATA if c["category"] == category]

    # Sort by shame score (descending)
    sorted_ceos = sorted(filtered, key=lambda c: c["shame_score"], reverse=True)

    # Stats
    total_fines = sum(c["fine_amount"] for c in CEO_DATA)
    convicted = sum(1 for c in CEO_DATA if c["outcome"] == "convicted")
    no_charges = sum(1 for c in CEO_DATA if c["outcome"] == "no_charges")
    still_active = sum(1 for c in CEO_DATA if c["still_active"])

    # Category counts
    all_categories = sorted(set(c["category"] for c in CEO_DATA))
    category_counts = {}
    for c in CEO_DATA:
        category_counts[c["category"]] = category_counts.get(c["category"], 0) + 1

    base = str(request.base_url).rstrip("/")
    ctx.update({
        "ceos": sorted_ceos,
        "total_ceos": len(CEO_DATA),
        "total_fines": total_fines,
        "convicted": convicted,
        "no_charges": no_charges,
        "still_active": still_active,
        "all_categories": all_categories,
        "selected_category": category,
        "category_counts": category_counts,
        "format_usd": _format_usd,
        "category_emoji": _category_emoji,
        "category_color": _category_color,
        "outcome_color": _outcome_color,
        "outcome_emoji": _outcome_emoji,
        "share_url": f"{base}/ceo-rap-sheet",
        "share_text": f"CEO scandals they hope you forgot — {len(CEO_DATA)} executives tracked",
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("ceo_rap_sheet.html", ctx)
