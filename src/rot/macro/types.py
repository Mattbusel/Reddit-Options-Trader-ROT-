"""Frozen dataclasses for the Macro Events & Economic Calendar engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


# ── Event importance levels ──────────────────────────────────────────
EventImportance = Literal["low", "medium", "high", "critical"]

# ── Event categories ─────────────────────────────────────────────────
EventCategory = Literal[
    "monetary_policy",
    "employment",
    "inflation",
    "gdp",
    "housing",
    "manufacturing",
    "consumer",
    "markets",
    "earnings",
    "insider",
    "congressional",
    "government",
    "other",
]

# ── Insider trade types ──────────────────────────────────────────────
InsiderTradeType = Literal["buy", "sell", "exercise", "gift"]

# ── Event type constants ─────────────────────────────────────────────
# Monetary policy
FOMC_DECISION = "fomc_decision"
FOMC_MINUTES = "fomc_minutes"
FED_SPEECH = "fed_speech"
ECB_DECISION = "ecb_decision"

# Employment
NFP = "nonfarm_payrolls"
INITIAL_CLAIMS = "initial_claims"
JOLTS = "jolts"
ADP_EMPLOYMENT = "adp_employment"
UNEMPLOYMENT_RATE = "unemployment_rate"

# Inflation
CPI = "cpi"
CORE_CPI = "core_cpi"
PPI = "ppi"
PCE = "pce"
CORE_PCE = "core_pce"

# GDP
GDP_ADVANCE = "gdp_advance"
GDP_PRELIMINARY = "gdp_preliminary"
GDP_FINAL = "gdp_final"

# Housing
HOUSING_STARTS = "housing_starts"
EXISTING_HOME_SALES = "existing_home_sales"
NEW_HOME_SALES = "new_home_sales"
CASE_SHILLER = "case_shiller"
BUILDING_PERMITS = "building_permits"

# Manufacturing
ISM_MANUFACTURING = "ism_manufacturing"
ISM_SERVICES = "ism_services"
DURABLE_GOODS = "durable_goods"
INDUSTRIAL_PRODUCTION = "industrial_production"
CAPACITY_UTILIZATION = "capacity_utilization"

# Consumer
RETAIL_SALES = "retail_sales"
CONSUMER_CONFIDENCE = "consumer_confidence"
MICHIGAN_SENTIMENT = "michigan_sentiment"
PERSONAL_INCOME = "personal_income"
PERSONAL_SPENDING = "personal_spending"

# Markets
VIX_EXPIRY = "vix_expiry"
OPEX = "opex"
QUAD_WITCHING = "quad_witching"
EARNINGS_SEASON_START = "earnings_season_start"
EARNINGS_SEASON_END = "earnings_season_end"

# Earnings
EARNINGS_REPORT = "earnings_report"

# Government
TREASURY_AUCTION = "treasury_auction"
DEBT_CEILING = "debt_ceiling"
GOVERNMENT_SHUTDOWN = "government_shutdown"
TRADE_DATA = "trade_data"
BUDGET_STATEMENT = "budget_statement"

# ── All event types set (for validation) ─────────────────────────────
ALL_EVENT_TYPES = {
    FOMC_DECISION, FOMC_MINUTES, FED_SPEECH, ECB_DECISION,
    NFP, INITIAL_CLAIMS, JOLTS, ADP_EMPLOYMENT, UNEMPLOYMENT_RATE,
    CPI, CORE_CPI, PPI, PCE, CORE_PCE,
    GDP_ADVANCE, GDP_PRELIMINARY, GDP_FINAL,
    HOUSING_STARTS, EXISTING_HOME_SALES, NEW_HOME_SALES, CASE_SHILLER,
    BUILDING_PERMITS,
    ISM_MANUFACTURING, ISM_SERVICES, DURABLE_GOODS, INDUSTRIAL_PRODUCTION,
    CAPACITY_UTILIZATION,
    RETAIL_SALES, CONSUMER_CONFIDENCE, MICHIGAN_SENTIMENT, PERSONAL_INCOME,
    PERSONAL_SPENDING,
    VIX_EXPIRY, OPEX, QUAD_WITCHING, EARNINGS_SEASON_START, EARNINGS_SEASON_END,
    EARNINGS_REPORT,
    TREASURY_AUCTION, DEBT_CEILING, GOVERNMENT_SHUTDOWN, TRADE_DATA,
    BUDGET_STATEMENT,
}

# ── Category mapping ─────────────────────────────────────────────────
EVENT_TYPE_CATEGORY: Dict[str, EventCategory] = {
    FOMC_DECISION: "monetary_policy",
    FOMC_MINUTES: "monetary_policy",
    FED_SPEECH: "monetary_policy",
    ECB_DECISION: "monetary_policy",
    NFP: "employment",
    INITIAL_CLAIMS: "employment",
    JOLTS: "employment",
    ADP_EMPLOYMENT: "employment",
    UNEMPLOYMENT_RATE: "employment",
    CPI: "inflation",
    CORE_CPI: "inflation",
    PPI: "inflation",
    PCE: "inflation",
    CORE_PCE: "inflation",
    GDP_ADVANCE: "gdp",
    GDP_PRELIMINARY: "gdp",
    GDP_FINAL: "gdp",
    HOUSING_STARTS: "housing",
    EXISTING_HOME_SALES: "housing",
    NEW_HOME_SALES: "housing",
    CASE_SHILLER: "housing",
    BUILDING_PERMITS: "housing",
    ISM_MANUFACTURING: "manufacturing",
    ISM_SERVICES: "manufacturing",
    DURABLE_GOODS: "manufacturing",
    INDUSTRIAL_PRODUCTION: "manufacturing",
    CAPACITY_UTILIZATION: "manufacturing",
    RETAIL_SALES: "consumer",
    CONSUMER_CONFIDENCE: "consumer",
    MICHIGAN_SENTIMENT: "consumer",
    PERSONAL_INCOME: "consumer",
    PERSONAL_SPENDING: "consumer",
    VIX_EXPIRY: "markets",
    OPEX: "markets",
    QUAD_WITCHING: "markets",
    EARNINGS_SEASON_START: "markets",
    EARNINGS_SEASON_END: "markets",
    EARNINGS_REPORT: "earnings",
    TREASURY_AUCTION: "government",
    DEBT_CEILING: "government",
    GOVERNMENT_SHUTDOWN: "government",
    TRADE_DATA: "government",
    BUDGET_STATEMENT: "government",
}

# ── Importance mapping ───────────────────────────────────────────────
EVENT_TYPE_IMPORTANCE: Dict[str, EventImportance] = {
    FOMC_DECISION: "critical",
    FOMC_MINUTES: "high",
    FED_SPEECH: "medium",
    ECB_DECISION: "high",
    NFP: "critical",
    INITIAL_CLAIMS: "medium",
    JOLTS: "medium",
    ADP_EMPLOYMENT: "high",
    UNEMPLOYMENT_RATE: "high",
    CPI: "critical",
    CORE_CPI: "critical",
    PPI: "high",
    PCE: "critical",
    CORE_PCE: "critical",
    GDP_ADVANCE: "high",
    GDP_PRELIMINARY: "medium",
    GDP_FINAL: "medium",
    HOUSING_STARTS: "medium",
    EXISTING_HOME_SALES: "medium",
    NEW_HOME_SALES: "medium",
    CASE_SHILLER: "low",
    BUILDING_PERMITS: "low",
    ISM_MANUFACTURING: "high",
    ISM_SERVICES: "high",
    DURABLE_GOODS: "medium",
    INDUSTRIAL_PRODUCTION: "medium",
    CAPACITY_UTILIZATION: "low",
    RETAIL_SALES: "high",
    CONSUMER_CONFIDENCE: "medium",
    MICHIGAN_SENTIMENT: "medium",
    PERSONAL_INCOME: "medium",
    PERSONAL_SPENDING: "medium",
    VIX_EXPIRY: "medium",
    OPEX: "high",
    QUAD_WITCHING: "high",
    EARNINGS_SEASON_START: "medium",
    EARNINGS_SEASON_END: "low",
    EARNINGS_REPORT: "high",
    TREASURY_AUCTION: "medium",
    DEBT_CEILING: "critical",
    GOVERNMENT_SHUTDOWN: "high",
    TRADE_DATA: "medium",
    BUDGET_STATEMENT: "low",
}

# ── Sector sensitivity (which sectors react most to each category) ───
CATEGORY_SECTOR_SENSITIVITY: Dict[str, List[str]] = {
    "monetary_policy": ["Financials", "Real Estate", "Utilities", "Technology"],
    "employment": ["Consumer Discretionary", "Financials", "Industrials"],
    "inflation": ["Consumer Staples", "Energy", "Materials", "Financials"],
    "gdp": ["Industrials", "Consumer Discretionary", "Financials"],
    "housing": ["Real Estate", "Financials", "Materials", "Industrials"],
    "manufacturing": ["Industrials", "Materials", "Technology"],
    "consumer": ["Consumer Discretionary", "Consumer Staples", "Retail"],
    "markets": ["Technology", "Financials"],
    "government": ["Industrials", "Defense", "Financials"],
}


# ── Core dataclasses ─────────────────────────────────────────────────


@dataclass(frozen=True)
class MacroEvent:
    """A scheduled or historical economic/macro event."""

    id: str
    event_type: str
    name: str
    scheduled_at: float  # Unix timestamp
    category: str
    importance: str = "medium"
    country: str = "US"
    actual_at: Optional[float] = None
    consensus_value: Optional[float] = None
    actual_value: Optional[float] = None
    previous_value: Optional[float] = None
    surprise_pct: Optional[float] = None
    affected_sectors: List[str] = field(default_factory=list)
    affected_tickers: List[str] = field(default_factory=list)
    source: str = ""
    meta: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalReaction:
    """Historical market reaction to a specific event occurrence."""

    date: float  # Unix timestamp
    spy_move_pct: float
    vix_change: float
    surprise_pct: float = 0.0
    sector_moves: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EventImpact:
    """Aggregated historical impact analysis for an event type."""

    event_type: str
    avg_spy_move_pct: float
    avg_vix_change: float
    max_spy_move_pct: float = 0.0
    min_spy_move_pct: float = 0.0
    historical_reactions: List[HistoricalReaction] = field(default_factory=list)
    most_affected_sectors: List[str] = field(default_factory=list)
    sample_size: int = 0


@dataclass(frozen=True)
class EarningsEvent:
    """An earnings report event for a specific ticker."""

    id: str
    ticker: str
    report_date: float  # Unix timestamp
    fiscal_quarter: str = ""
    eps_estimate: Optional[float] = None
    eps_actual: Optional[float] = None
    revenue_estimate: Optional[float] = None
    revenue_actual: Optional[float] = None
    surprise_pct: Optional[float] = None
    expected_move_pct: Optional[float] = None
    actual_move_pct: Optional[float] = None
    iv_before: Optional[float] = None
    iv_after: Optional[float] = None
    iv_crush_pct: Optional[float] = None
    meta: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class InsiderTrade:
    """An insider or congressional trade filing."""

    id: str
    ticker: str
    insider_name: str
    trade_type: str  # buy/sell/exercise/gift
    filing_date: float  # Unix timestamp
    source: str  # form4 / congress
    title: str = ""
    shares: int = 0
    price: float = 0.0
    value: float = 0.0
    transaction_date: Optional[float] = None
    meta: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class FOMCMeeting:
    """FOMC meeting record with rate decision and analysis."""

    id: str
    meeting_date: float  # Unix timestamp
    rate_decision: str = ""  # "hold", "raise_25", "raise_50", "cut_25", etc.
    rate_before: float = 0.0
    rate_after: float = 0.0
    statement_text: str = ""
    statement_diff: str = ""  # HTML diff vs previous meeting
    hawkish_score: float = 0.0  # 0.0 = very dovish, 1.0 = very hawkish
    dovish_score: float = 0.0
    dot_plot_median: Optional[float] = None
    meta: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class SeasonalPattern:
    """Monthly seasonal pattern for a ticker or sector."""

    ticker_or_sector: str
    month: int  # 1-12
    avg_return_pct: float
    win_rate_pct: float
    sample_years: int
    best_year_return: float = 0.0
    worst_year_return: float = 0.0
    median_return_pct: float = 0.0
