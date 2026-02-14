"""Wall Street Raid Tracker — Leaderboard of raided financial institutions since 1980."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional

router = APIRouter()


# ── Historical dataset: financial institution raids, seizures & enforcement ──
# Sources: DOJ, SEC, FBI, FDIC, SIGTARP, Better Markets, Violation Tracker
#
# Each entry represents a major government enforcement action ("raid") against
# a financial institution.  Fields:
#   institution  – company name at time of action
#   ticker       – stock ticker (or "" if private/defunct)
#   year         – year the action/settlement occurred
#   agency       – primary enforcing agency
#   action_type  – raid / settlement / indictment / seizure / guilty plea
#   amount       – total penalty/settlement in USD (0 if no monetary penalty)
#   description  – brief summary
#   executives_charged – number of executives charged/convicted
#   still_operating    – whether the institution still exists today

RAID_DATA = [
    # ── 1980s: S&L Crisis + Insider Trading ──
    {
        "institution": "Lincoln Savings & Loan",
        "ticker": "",
        "year": 1989,
        "agency": "DOJ / OTS",
        "action_type": "seizure / indictment",
        "amount": 3_400_000_000,
        "description": "Charles Keating's S&L collapsed costing taxpayers $3.4B. Keating convicted of fraud.",
        "executives_charged": 1,
        "still_operating": False,
    },
    {
        "institution": "Drexel Burnham Lambert",
        "ticker": "",
        "year": 1989,
        "agency": "SEC / DOJ",
        "action_type": "indictment / guilty plea",
        "amount": 650_000_000,
        "description": "Junk bond king Michael Milken indicted for securities fraud. Drexel pled guilty, paid $650M, went bankrupt.",
        "executives_charged": 2,
        "still_operating": False,
    },
    {
        "institution": "Ivan Boesky (multiple firms)",
        "ticker": "",
        "year": 1986,
        "agency": "SEC / DOJ",
        "action_type": "indictment",
        "amount": 100_000_000,
        "description": "Insider trading ring. Boesky fined $100M, sentenced to 3.5 years, banned from securities industry.",
        "executives_charged": 1,
        "still_operating": False,
    },
    {
        "institution": "BCCI (Bank of Credit and Commerce International)",
        "ticker": "",
        "year": 1991,
        "agency": "DOJ / FBI / Fed",
        "action_type": "raid / seizure",
        "amount": 15_000_000_000,
        "description": "FBI raided offices worldwide. Largest bank fraud in history at the time. $15B in losses. Described as 'Bank of Crooks and Criminals.'",
        "executives_charged": 5,
        "still_operating": False,
    },
    # ── 2000s: Corporate Fraud Era ──
    {
        "institution": "Enron",
        "ticker": "ENE",
        "year": 2001,
        "agency": "DOJ / SEC / FBI",
        "action_type": "raid / indictment",
        "amount": 63_400_000_000,
        "description": "FBI raided offices. $63.4B bankruptcy — largest on record at the time. CEO Skilling got 24 years. CFO Fastow cooperated.",
        "executives_charged": 16,
        "still_operating": False,
    },
    {
        "institution": "WorldCom",
        "ticker": "WCOM",
        "year": 2002,
        "agency": "DOJ / SEC",
        "action_type": "indictment",
        "amount": 11_000_000_000,
        "description": "$11B accounting fraud. CEO Bernie Ebbers sentenced to 25 years. Led to Sarbanes-Oxley Act.",
        "executives_charged": 6,
        "still_operating": False,
    },
    {
        "institution": "Arthur Andersen",
        "ticker": "",
        "year": 2002,
        "agency": "DOJ",
        "action_type": "indictment",
        "amount": 0,
        "description": "Enron's auditor indicted for obstruction of justice (shredding documents). Conviction destroyed the firm — 85,000 jobs lost.",
        "executives_charged": 0,
        "still_operating": False,
    },
    {
        "institution": "Tyco International",
        "ticker": "TYC",
        "year": 2002,
        "agency": "SEC / DOJ",
        "action_type": "indictment",
        "amount": 600_000_000,
        "description": "CEO Dennis Kozlowski and CFO looted $600M from the company. Both sentenced to 8-25 years.",
        "executives_charged": 3,
        "still_operating": False,
    },
    # ── 2008 Financial Crisis ──
    {
        "institution": "Bear Stearns",
        "ticker": "BSC",
        "year": 2008,
        "agency": "Fed / SEC",
        "action_type": "seizure",
        "amount": 0,
        "description": "Collapsed in 72 hours. Fed forced emergency sale to JPMorgan at $2/share (was $170). Two hedge fund managers indicted.",
        "executives_charged": 2,
        "still_operating": False,
    },
    {
        "institution": "Lehman Brothers",
        "ticker": "LEH",
        "year": 2008,
        "agency": "FBI / DOJ / SEC",
        "action_type": "raid / seizure",
        "amount": 691_000_000_000,
        "description": "FBI raided offices. $691B bankruptcy — largest in US history. Triggered global financial crisis. CEO Fuld never charged.",
        "executives_charged": 0,
        "still_operating": False,
    },
    {
        "institution": "Bernie Madoff (BMIS)",
        "ticker": "",
        "year": 2008,
        "agency": "FBI / DOJ / SEC",
        "action_type": "raid / indictment",
        "amount": 64_800_000_000,
        "description": "FBI arrested Madoff at his apartment. Largest Ponzi scheme in history — $64.8B fraud. Sentenced to 150 years. Died in prison.",
        "executives_charged": 6,
        "still_operating": False,
    },
    {
        "institution": "Bank of America",
        "ticker": "BAC",
        "year": 2014,
        "agency": "DOJ / SEC / CFPB",
        "action_type": "settlement",
        "amount": 82_700_000_000,
        "description": "Largest cumulative penalties of any bank: $82.7B across 214 enforcement actions. Single largest: $16.65B DOJ settlement for toxic mortgage fraud.",
        "executives_charged": 0,
        "still_operating": True,
    },
    {
        "institution": "JPMorgan Chase",
        "ticker": "JPM",
        "year": 2013,
        "agency": "DOJ / SEC / CFTC",
        "action_type": "settlement",
        "amount": 34_200_000_000,
        "description": "$34.2B in cumulative fines. Includes $13B DOJ settlement for mortgage fraud, $920M for market manipulation (metals & Treasuries).",
        "executives_charged": 3,
        "still_operating": True,
    },
    {
        "institution": "Citigroup",
        "ticker": "C",
        "year": 2014,
        "agency": "DOJ / SEC",
        "action_type": "settlement",
        "amount": 19_700_000_000,
        "description": "$7B DOJ settlement for toxic mortgage securities. $19.7B total across multiple enforcement actions. Enabling Enron schemes added $255M.",
        "executives_charged": 0,
        "still_operating": True,
    },
    {
        "institution": "Wells Fargo",
        "ticker": "WFC",
        "year": 2020,
        "agency": "DOJ / CFPB / OCC",
        "action_type": "settlement",
        "amount": 20_300_000_000,
        "description": "Fake accounts scandal: 16M unauthorized accounts opened. $3B DOJ settlement, $3.7B CFPB fine. $20.3B cumulative penalties.",
        "executives_charged": 8,
        "still_operating": True,
    },
    {
        "institution": "Goldman Sachs",
        "ticker": "GS",
        "year": 2020,
        "agency": "DOJ / SEC / MAS",
        "action_type": "settlement / guilty plea",
        "amount": 7_700_000_000,
        "description": "1MDB scandal: facilitated $4.5B theft from Malaysian state fund. $2.9B DOJ settlement, $3.9B Malaysia settlement. Subsidiary pled guilty.",
        "executives_charged": 4,
        "still_operating": True,
    },
    {
        "institution": "Deutsche Bank",
        "ticker": "DB",
        "year": 2017,
        "agency": "DOJ / SEC / FCA",
        "action_type": "settlement",
        "amount": 16_600_000_000,
        "description": "$7.2B DOJ settlement for toxic mortgage securities. LIBOR manipulation fines. Russian mirror trading $630M. Epstein ties.",
        "executives_charged": 3,
        "still_operating": True,
    },
    {
        "institution": "BNP Paribas",
        "ticker": "BNP",
        "year": 2014,
        "agency": "DOJ",
        "action_type": "guilty plea",
        "amount": 8_970_000_000,
        "description": "Pled guilty to violating US sanctions — processing $30B in transactions through US system for Sudan, Iran, Cuba.",
        "executives_charged": 0,
        "still_operating": True,
    },
    {
        "institution": "Credit Suisse",
        "ticker": "CS",
        "year": 2017,
        "agency": "DOJ / SEC",
        "action_type": "settlement",
        "amount": 8_600_000_000,
        "description": "$5.3B DOJ settlement for toxic mortgage securities. Tax evasion guilty plea ($2.6B). Collapsed and acquired by UBS in 2023.",
        "executives_charged": 2,
        "still_operating": False,
    },
    {
        "institution": "MF Global",
        "ticker": "MF",
        "year": 2011,
        "agency": "CFTC / SEC / DOJ",
        "action_type": "seizure",
        "amount": 1_600_000_000,
        "description": "$1.6B in customer funds vanished. CEO Jon Corzine (ex-NJ Governor) never criminally charged. CFTC fined him $5M personally.",
        "executives_charged": 1,
        "still_operating": False,
    },
    {
        "institution": "Washington Mutual (WaMu)",
        "ticker": "WM",
        "year": 2008,
        "agency": "FDIC / OTS",
        "action_type": "seizure",
        "amount": 307_000_000_000,
        "description": "Largest bank failure in US history. $307B in assets seized by FDIC. Sold to JPMorgan for $1.9B. CEO Kerry Killinger never charged.",
        "executives_charged": 0,
        "still_operating": False,
    },
    {
        "institution": "IndyMac Bancorp",
        "ticker": "IMB",
        "year": 2008,
        "agency": "FDIC / FBI",
        "action_type": "seizure / indictment",
        "amount": 32_000_000_000,
        "description": "FBI investigated. FDIC seized the bank. $32B in assets. CEO Michael Perry charged with fraud in 2011.",
        "executives_charged": 1,
        "still_operating": False,
    },
    {
        "institution": "Countrywide Financial",
        "ticker": "CFC",
        "year": 2008,
        "agency": "SEC / DOJ / FBI",
        "action_type": "settlement / indictment",
        "amount": 624_000_000,
        "description": "Largest mortgage lender — ground zero of subprime crisis. CEO Angelo Mozilo fined $67.5M by SEC. Acquired by Bank of America.",
        "executives_charged": 3,
        "still_operating": False,
    },
    # ── 2010s: Ongoing Enforcement ──
    {
        "institution": "HSBC",
        "ticker": "HSBC",
        "year": 2012,
        "agency": "DOJ / FinCEN",
        "action_type": "settlement",
        "amount": 1_920_000_000,
        "description": "Laundered $881M for Mexican drug cartels. Processed transactions for sanctioned countries. $1.92B settlement. No executives jailed.",
        "executives_charged": 0,
        "still_operating": True,
    },
    {
        "institution": "Standard Chartered",
        "ticker": "STAN",
        "year": 2012,
        "agency": "DOJ / NYDFS",
        "action_type": "settlement",
        "amount": 1_100_000_000,
        "description": "Violated US sanctions by hiding $250B in transactions with Iran. $667M initial settlement, repeated violations led to $1.1B total.",
        "executives_charged": 0,
        "still_operating": True,
    },
    {
        "institution": "SAC Capital Advisors",
        "ticker": "",
        "year": 2013,
        "agency": "FBI / DOJ / SEC",
        "action_type": "raid / guilty plea",
        "amount": 1_800_000_000,
        "description": "FBI raided offices in 2010. Pled guilty to insider trading. $1.8B penalty — largest ever for insider trading. Renamed Point72.",
        "executives_charged": 8,
        "still_operating": True,
    },
    {
        "institution": "Morgan Stanley",
        "ticker": "MS",
        "year": 2016,
        "agency": "DOJ / SEC",
        "action_type": "settlement",
        "amount": 3_200_000_000,
        "description": "$3.2B DOJ settlement for misleading investors about mortgage securities quality pre-crisis.",
        "executives_charged": 0,
        "still_operating": True,
    },
    {
        "institution": "Binance",
        "ticker": "",
        "year": 2023,
        "agency": "DOJ / FinCEN / OFAC",
        "action_type": "guilty plea",
        "amount": 4_300_000_000,
        "description": "Largest crypto enforcement ever. CEO CZ pled guilty to AML violations. $4.3B settlement. CZ sentenced to 4 months.",
        "executives_charged": 1,
        "still_operating": True,
    },
    {
        "institution": "FTX",
        "ticker": "",
        "year": 2022,
        "agency": "FBI / DOJ / SEC / CFTC",
        "action_type": "raid / indictment",
        "amount": 10_000_000_000,
        "description": "FBI raided Bahamas offices. $10B in customer deposits misappropriated. SBF convicted on 7 counts, sentenced to 25 years.",
        "executives_charged": 5,
        "still_operating": False,
    },
    {
        "institution": "Terraform Labs",
        "ticker": "",
        "year": 2024,
        "agency": "SEC",
        "action_type": "settlement",
        "amount": 4_500_000_000,
        "description": "Luna/UST collapse wiped $40B. SEC won $4.5B judgment — largest in SEC history. Do Kwon extradited.",
        "executives_charged": 1,
        "still_operating": False,
    },
    {
        "institution": "Silicon Valley Bank",
        "ticker": "SIVB",
        "year": 2023,
        "agency": "FDIC / DOJ / SEC",
        "action_type": "seizure",
        "amount": 209_000_000_000,
        "description": "2nd-largest bank failure in US history. $209B in assets. Bank run triggered by unrealized losses. FDIC sued 6 officers + 11 directors.",
        "executives_charged": 0,
        "still_operating": False,
    },
    {
        "institution": "Signature Bank",
        "ticker": "SBNY",
        "year": 2023,
        "agency": "FDIC / NYDFS",
        "action_type": "seizure",
        "amount": 110_000_000_000,
        "description": "3rd-largest bank failure in US history. $110B in assets. Closed by NYDFS amid contagion fears from SVB collapse.",
        "executives_charged": 0,
        "still_operating": False,
    },
    {
        "institution": "First Republic Bank",
        "ticker": "FRC",
        "year": 2023,
        "agency": "FDIC",
        "action_type": "seizure",
        "amount": 229_000_000_000,
        "description": "4th-largest bank failure ever. $229B in assets seized. Sold to JPMorgan. FDIC estimated $13B cost to deposit insurance fund.",
        "executives_charged": 0,
        "still_operating": False,
    },
    {
        "institution": "Wirecard",
        "ticker": "WDI",
        "year": 2020,
        "agency": "German BaFin / DOJ",
        "action_type": "raid / indictment",
        "amount": 2_100_000_000,
        "description": "German police raided HQ. $2.1B in cash that 'didn't exist.' CEO Braun arrested. COO Marsalek fled, still missing. Europe's Enron.",
        "executives_charged": 3,
        "still_operating": False,
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


def _action_emoji(action_type: str) -> str:
    """Get emoji for action type."""
    if "raid" in action_type:
        return "\U0001F6A8"  # police light
    if "seizure" in action_type:
        return "\U0001F6AB"  # no entry
    if "guilty" in action_type:
        return "\u2696\uFE0F"  # scales of justice
    if "indictment" in action_type:
        return "\U0001F46E"  # police officer
    return "\U0001F4B0"  # money bag (settlement)


def _action_color(action_type: str) -> str:
    """Tailwind color class for action type badge."""
    if "raid" in action_type:
        return "bg-red-600/30 text-red-400 border-red-500/40"
    if "seizure" in action_type:
        return "bg-orange-600/30 text-orange-400 border-orange-500/40"
    if "guilty" in action_type:
        return "bg-purple-600/30 text-purple-400 border-purple-500/40"
    if "indictment" in action_type:
        return "bg-yellow-600/30 text-yellow-400 border-yellow-500/40"
    return "bg-blue-600/30 text-blue-400 border-blue-500/40"


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


@router.get("/wall-of-shame", response_class=HTMLResponse)
async def wall_of_shame(request: Request):
    """The Wall of Shame — Financial Institution Raid Leaderboard."""
    user = await get_current_user_optional(request)
    ctx = _base_context(request, user)

    # Sort by penalty amount (descending) for the main leaderboard
    sorted_by_amount = sorted(RAID_DATA, key=lambda r: r["amount"], reverse=True)

    # Calculate aggregate stats
    total_penalties = sum(r["amount"] for r in RAID_DATA)
    total_raids = len(RAID_DATA)
    total_executives = sum(r["executives_charged"] for r in RAID_DATA)
    still_operating = sum(1 for r in RAID_DATA if r["still_operating"])
    destroyed = total_raids - still_operating

    # Decade breakdown
    decades = {}
    for r in RAID_DATA:
        decade = f"{(r['year'] // 10) * 10}s"
        if decade not in decades:
            decades[decade] = {"count": 0, "amount": 0}
        decades[decade]["count"] += 1
        decades[decade]["amount"] += r["amount"]

    # By agency (primary)
    agency_counts = {}
    for r in RAID_DATA:
        primary = r["agency"].split("/")[0].strip()
        agency_counts[primary] = agency_counts.get(primary, 0) + 1

    ctx.update({
        "raids": sorted_by_amount,
        "total_penalties": total_penalties,
        "total_raids": total_raids,
        "total_executives": total_executives,
        "still_operating": still_operating,
        "destroyed": destroyed,
        "decades": dict(sorted(decades.items())),
        "agency_counts": dict(sorted(agency_counts.items(), key=lambda x: x[1], reverse=True)),
        "format_usd": _format_usd,
        "action_emoji": _action_emoji,
        "action_color": _action_color,
    })

    templates = request.app.state.templates
    return templates.TemplateResponse("wall_of_shame.html", ctx)
