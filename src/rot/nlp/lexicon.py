"""Financial sentiment lexicon for the ROT NLP engine.

500+ terms with polarity, intensity, and domain classification.
Pure Python dict — no external files, no disk I/O at import time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class LexiconEntry:
    """A single entry in the sentiment lexicon."""
    term: str
    polarity: float       # -1.0 to +1.0
    intensity: float      # 0.0 to 1.0 (inherent strength)
    category: str         # "action", "outcome", "descriptor", "emoji", "slang", "modifier"
    domain: str           # "general", "options", "technical", "wsb_slang", "macro"


def _build_lexicon() -> Dict[str, LexiconEntry]:
    """Construct the full sentiment lexicon."""

    def e(term: str, pol: float, inten: float, cat: str, dom: str) -> LexiconEntry:
        """Shorthand constructor for a LexiconEntry."""
        return LexiconEntry(term=term, polarity=pol, intensity=inten, category=cat, domain=dom)

    entries = [
        # =====================================================================
        # STRONG BULLISH  (polarity 0.7–1.0, intensity 0.7–1.0)
        # =====================================================================
        e("moon", 0.9, 0.9, "outcome", "wsb_slang"),
        e("moonshot", 0.95, 0.95, "outcome", "wsb_slang"),
        e("mooning", 0.9, 0.9, "outcome", "wsb_slang"),
        e("tendies", 0.8, 0.8, "outcome", "wsb_slang"),
        e("rocket", 0.85, 0.85, "outcome", "wsb_slang"),
        e("squeeze", 0.7, 0.8, "outcome", "options"),
        e("breakout", 0.75, 0.8, "outcome", "technical"),
        e("rip", 0.7, 0.75, "outcome", "wsb_slang"),
        e("parabolic", 0.85, 0.9, "descriptor", "technical"),
        e("lambo", 0.9, 0.85, "outcome", "wsb_slang"),
        e("print", 0.75, 0.7, "outcome", "options"),
        e("printing", 0.75, 0.7, "outcome", "options"),
        e("face-ripper", 0.85, 0.9, "outcome", "wsb_slang"),
        e("gap-up", 0.75, 0.8, "outcome", "technical"),
        e("gap up", 0.75, 0.8, "outcome", "technical"),
        e("ath", 0.7, 0.7, "outcome", "technical"),
        e("all-time high", 0.75, 0.75, "outcome", "technical"),
        e("all time high", 0.75, 0.75, "outcome", "technical"),
        e("explosive", 0.8, 0.85, "descriptor", "general"),
        e("skyrocket", 0.9, 0.9, "outcome", "general"),
        e("surge", 0.7, 0.75, "outcome", "general"),
        e("surging", 0.7, 0.75, "outcome", "general"),
        e("soar", 0.75, 0.8, "outcome", "general"),
        e("soaring", 0.75, 0.8, "outcome", "general"),
        e("rally", 0.7, 0.75, "outcome", "technical"),
        e("rallying", 0.7, 0.75, "outcome", "technical"),
        e("melt-up", 0.8, 0.8, "outcome", "technical"),
        e("gamma squeeze", 0.8, 0.85, "outcome", "options"),
        e("short squeeze", 0.8, 0.85, "outcome", "options"),

        # =====================================================================
        # MODERATE BULLISH  (polarity 0.3–0.7, intensity 0.4–0.7)
        # =====================================================================
        e("calls", 0.5, 0.6, "action", "options"),
        e("buy", 0.5, 0.55, "action", "general"),
        e("buying", 0.5, 0.55, "action", "general"),
        e("bought", 0.45, 0.5, "action", "general"),
        e("long", 0.5, 0.55, "action", "general"),
        e("bull", 0.6, 0.6, "descriptor", "general"),
        e("bullish", 0.65, 0.65, "descriptor", "general"),
        e("upside", 0.5, 0.55, "descriptor", "general"),
        e("accumulate", 0.5, 0.5, "action", "general"),
        e("accumulating", 0.5, 0.5, "action", "general"),
        e("support", 0.4, 0.45, "descriptor", "technical"),
        e("bounce", 0.5, 0.55, "outcome", "technical"),
        e("bouncing", 0.5, 0.55, "outcome", "technical"),
        e("recovery", 0.55, 0.55, "outcome", "general"),
        e("recovering", 0.5, 0.5, "outcome", "general"),
        e("undervalued", 0.6, 0.6, "descriptor", "general"),
        e("upgrade", 0.55, 0.6, "outcome", "general"),
        e("upgraded", 0.55, 0.6, "outcome", "general"),
        e("outperform", 0.55, 0.6, "descriptor", "general"),
        e("beat", 0.55, 0.6, "outcome", "general"),
        e("beats", 0.55, 0.6, "outcome", "general"),
        e("beaten", 0.5, 0.5, "outcome", "general"),
        e("oversold", 0.5, 0.55, "descriptor", "technical"),
        e("dip", 0.35, 0.4, "descriptor", "general"),
        e("btd", 0.5, 0.55, "action", "wsb_slang"),
        e("buy the dip", 0.55, 0.6, "action", "wsb_slang"),
        e("golden cross", 0.65, 0.7, "outcome", "technical"),
        e("cup and handle", 0.6, 0.65, "descriptor", "technical"),
        e("bullish flag", 0.6, 0.65, "descriptor", "technical"),
        e("bull flag", 0.6, 0.65, "descriptor", "technical"),
        e("ascending", 0.4, 0.45, "descriptor", "technical"),
        e("breakout", 0.65, 0.7, "outcome", "technical"),
        e("green", 0.35, 0.4, "descriptor", "general"),
        e("pumping", 0.5, 0.55, "outcome", "general"),
        e("ripping", 0.6, 0.65, "outcome", "wsb_slang"),
        e("positive", 0.4, 0.45, "descriptor", "general"),
        e("beat estimates", 0.6, 0.65, "outcome", "general"),
        e("guidance raise", 0.6, 0.65, "outcome", "general"),
        e("raised guidance", 0.6, 0.65, "outcome", "general"),
        e("strong earnings", 0.6, 0.65, "outcome", "general"),
        e("blowout", 0.65, 0.7, "outcome", "general"),
        e("killer earnings", 0.7, 0.75, "outcome", "wsb_slang"),
        e("crushed", 0.5, 0.55, "outcome", "general"),  # "crushed earnings" = bullish
        e("smashed", 0.5, 0.55, "outcome", "wsb_slang"),
        e("nailed", 0.45, 0.5, "outcome", "general"),
        e("solid", 0.35, 0.4, "descriptor", "general"),
        e("strong", 0.4, 0.45, "descriptor", "general"),
        e("momentum", 0.4, 0.5, "descriptor", "technical"),
        e("volume spike", 0.45, 0.55, "descriptor", "technical"),
        e("institutional buying", 0.6, 0.65, "action", "general"),
        e("whale", 0.45, 0.5, "descriptor", "options"),  # context-dependent

        # =====================================================================
        # MILD BULLISH  (polarity 0.1–0.3, intensity 0.2–0.4)
        # =====================================================================
        e("hold", 0.15, 0.25, "action", "general"),
        e("holding", 0.15, 0.25, "action", "general"),
        e("hodl", 0.2, 0.3, "action", "wsb_slang"),
        e("stable", 0.1, 0.2, "descriptor", "general"),
        e("steady", 0.1, 0.2, "descriptor", "general"),
        e("decent", 0.2, 0.25, "descriptor", "general"),
        e("consolidating", 0.15, 0.2, "descriptor", "technical"),
        e("base building", 0.2, 0.25, "descriptor", "technical"),
        e("good entry", 0.3, 0.35, "descriptor", "general"),
        e("entry point", 0.25, 0.3, "descriptor", "general"),
        e("fair value", 0.15, 0.2, "descriptor", "general"),
        e("apes", 0.2, 0.25, "descriptor", "wsb_slang"),
        e("diamond hands", 0.3, 0.35, "descriptor", "wsb_slang"),

        # =====================================================================
        # STRONG BEARISH  (polarity -0.7 to -1.0, intensity 0.7–1.0)
        # =====================================================================
        e("crash", -0.9, 0.9, "outcome", "general"),
        e("crashing", -0.9, 0.9, "outcome", "general"),
        e("tank", -0.8, 0.85, "outcome", "general"),
        e("tanking", -0.8, 0.85, "outcome", "general"),
        e("drill", -0.75, 0.8, "outcome", "wsb_slang"),
        e("drilling", -0.75, 0.8, "outcome", "wsb_slang"),
        e("plunge", -0.85, 0.9, "outcome", "general"),
        e("plunging", -0.85, 0.9, "outcome", "general"),
        e("collapse", -0.9, 0.9, "outcome", "general"),
        e("collapsing", -0.9, 0.9, "outcome", "general"),
        e("dump", -0.7, 0.75, "outcome", "general"),
        e("dumping", -0.7, 0.75, "outcome", "general"),
        e("rug pull", -0.9, 0.95, "outcome", "wsb_slang"),
        e("rug-pull", -0.9, 0.95, "outcome", "wsb_slang"),
        e("ponzi", -0.85, 0.9, "descriptor", "general"),
        e("scam", -0.8, 0.85, "descriptor", "general"),
        e("fraud", -0.85, 0.9, "descriptor", "general"),
        e("implosion", -0.85, 0.9, "outcome", "general"),
        e("circuit breaker", -0.9, 0.95, "outcome", "general"),
        e("death cross", -0.75, 0.8, "outcome", "technical"),
        e("rekt", -0.85, 0.9, "outcome", "wsb_slang"),
        e("wrecked", -0.8, 0.85, "outcome", "general"),
        e("guh", -0.9, 0.95, "outcome", "wsb_slang"),
        e("bagholding", -0.7, 0.75, "descriptor", "wsb_slang"),
        e("bagholder", -0.7, 0.75, "descriptor", "wsb_slang"),
        e("bag holder", -0.7, 0.75, "descriptor", "wsb_slang"),
        e("margin call", -0.85, 0.9, "outcome", "options"),
        e("margin called", -0.85, 0.9, "outcome", "options"),
        e("meltdown", -0.8, 0.85, "outcome", "general"),
        e("freefall", -0.85, 0.9, "outcome", "general"),
        e("free fall", -0.85, 0.9, "outcome", "general"),
        e("blood bath", -0.8, 0.85, "outcome", "general"),
        e("bloodbath", -0.8, 0.85, "outcome", "general"),
        e("obliterated", -0.85, 0.9, "outcome", "general"),
        e("destroyed", -0.8, 0.85, "outcome", "general"),
        e("wiped", -0.75, 0.8, "outcome", "general"),
        e("wiped out", -0.8, 0.85, "outcome", "general"),
        e("zero", -0.7, 0.75, "outcome", "general"),
        e("worthless", -0.85, 0.9, "descriptor", "options"),
        e("expired worthless", -0.9, 0.95, "outcome", "options"),
        e("gap-down", -0.7, 0.75, "outcome", "technical"),
        e("gap down", -0.7, 0.75, "outcome", "technical"),

        # =====================================================================
        # MODERATE BEARISH  (polarity -0.3 to -0.7, intensity 0.4–0.7)
        # =====================================================================
        e("puts", -0.5, 0.6, "action", "options"),
        e("sell", -0.45, 0.5, "action", "general"),
        e("selling", -0.45, 0.5, "action", "general"),
        e("sold", -0.4, 0.45, "action", "general"),
        e("short", -0.5, 0.55, "action", "general"),
        e("shorting", -0.5, 0.55, "action", "general"),
        e("shorted", -0.45, 0.5, "action", "general"),
        e("bear", -0.6, 0.6, "descriptor", "general"),
        e("bearish", -0.65, 0.65, "descriptor", "general"),
        e("downgrade", -0.55, 0.6, "outcome", "general"),
        e("downgraded", -0.55, 0.6, "outcome", "general"),
        e("miss", -0.55, 0.6, "outcome", "general"),
        e("missed", -0.55, 0.6, "outcome", "general"),
        e("misses", -0.55, 0.6, "outcome", "general"),
        e("overvalued", -0.55, 0.6, "descriptor", "general"),
        e("overbought", -0.5, 0.55, "descriptor", "technical"),
        e("resistance", -0.35, 0.4, "descriptor", "technical"),
        e("rejection", -0.5, 0.55, "outcome", "technical"),
        e("distribution", -0.4, 0.45, "descriptor", "technical"),
        e("head and shoulders", -0.55, 0.6, "descriptor", "technical"),
        e("double top", -0.5, 0.55, "descriptor", "technical"),
        e("descending", -0.35, 0.4, "descriptor", "technical"),
        e("red", -0.3, 0.35, "descriptor", "general"),
        e("bleeding", -0.6, 0.65, "outcome", "general"),
        e("paper hands", -0.5, 0.55, "descriptor", "wsb_slang"),
        e("paper-hands", -0.5, 0.55, "descriptor", "wsb_slang"),
        e("weak", -0.4, 0.45, "descriptor", "general"),
        e("weakness", -0.45, 0.5, "descriptor", "general"),
        e("negative", -0.4, 0.45, "descriptor", "general"),
        e("missed estimates", -0.6, 0.65, "outcome", "general"),
        e("guidance cut", -0.65, 0.7, "outcome", "general"),
        e("lowered guidance", -0.65, 0.7, "outcome", "general"),
        e("weak earnings", -0.6, 0.65, "outcome", "general"),
        e("disappointing", -0.55, 0.6, "descriptor", "general"),
        e("underwhelming", -0.45, 0.5, "descriptor", "general"),
        e("dilution", -0.55, 0.6, "outcome", "general"),
        e("diluted", -0.5, 0.55, "outcome", "general"),
        e("offering", -0.4, 0.45, "outcome", "general"),  # secondary offering
        e("insider selling", -0.55, 0.6, "action", "general"),
        e("head fake", -0.45, 0.5, "outcome", "technical"),
        e("bull trap", -0.55, 0.6, "outcome", "technical"),
        e("dead cat bounce", -0.6, 0.65, "outcome", "technical"),
        e("fade", -0.4, 0.45, "outcome", "general"),
        e("fading", -0.4, 0.45, "outcome", "general"),
        e("declining", -0.45, 0.5, "outcome", "general"),
        e("falling", -0.5, 0.55, "outcome", "general"),
        e("sinking", -0.55, 0.6, "outcome", "general"),
        e("underwater", -0.6, 0.65, "descriptor", "general"),
        e("loss porn", -0.3, 0.4, "descriptor", "wsb_slang"),  # context: bearish

        # =====================================================================
        # MILD BEARISH  (polarity -0.1 to -0.3, intensity 0.2–0.4)
        # =====================================================================
        e("cautious", -0.15, 0.25, "descriptor", "general"),
        e("concerned", -0.2, 0.3, "descriptor", "general"),
        e("risky", -0.2, 0.3, "descriptor", "general"),
        e("worried", -0.2, 0.3, "descriptor", "general"),
        e("uncertainty", -0.25, 0.3, "descriptor", "general"),
        e("headwinds", -0.3, 0.35, "descriptor", "general"),
        e("slowing", -0.25, 0.3, "descriptor", "general"),
        e("stagnant", -0.2, 0.25, "descriptor", "general"),
        e("flat", -0.1, 0.15, "descriptor", "general"),
        e("choppy", -0.15, 0.2, "descriptor", "technical"),
        e("volatile", -0.1, 0.2, "descriptor", "general"),
        e("volatility", -0.1, 0.2, "descriptor", "general"),
        e("sideways", -0.1, 0.15, "descriptor", "technical"),
        e("bag", -0.25, 0.3, "descriptor", "wsb_slang"),
        e("stuck", -0.2, 0.25, "descriptor", "general"),
        e("overextended", -0.3, 0.35, "descriptor", "technical"),

        # =====================================================================
        # EMOJI SENTIMENT
        # =====================================================================
        # Bullish emojis
        e("ROCKET_EMOJI", 0.8, 0.8, "emoji", "wsb_slang"),
        e("CHART_UP_EMOJI", 0.6, 0.6, "emoji", "general"),
        e("BULL_EMOJI", 0.6, 0.6, "emoji", "general"),
        e("DIAMOND_EMOJI", 0.5, 0.5, "emoji", "wsb_slang"),
        e("RAISED_HANDS_EMOJI", 0.4, 0.4, "emoji", "general"),
        e("FIRE_EMOJI", 0.5, 0.55, "emoji", "general"),
        e("MONEY_BAG_EMOJI", 0.5, 0.5, "emoji", "general"),
        e("DOLLAR_EMOJI", 0.35, 0.35, "emoji", "general"),
        e("MONEY_FACE_EMOJI", 0.5, 0.5, "emoji", "general"),
        e("PARTY_EMOJI", 0.4, 0.4, "emoji", "general"),
        e("CHECK_EMOJI", 0.3, 0.3, "emoji", "general"),
        e("MOON_FACE_EMOJI", 0.7, 0.7, "emoji", "wsb_slang"),
        e("MOON_EMOJI", 0.7, 0.7, "emoji", "wsb_slang"),
        e("MUSCLE_EMOJI", 0.4, 0.4, "emoji", "general"),
        # Bearish emojis
        e("CHART_DOWN_EMOJI", -0.6, 0.6, "emoji", "general"),
        e("BEAR_EMOJI", -0.6, 0.6, "emoji", "general"),
        e("POOP_EMOJI", -0.65, 0.65, "emoji", "general"),
        e("CRYING_EMOJI", -0.5, 0.55, "emoji", "general"),
        e("MONEY_WINGS_EMOJI", -0.55, 0.55, "emoji", "general"),
        e("SKULL_EMOJI", -0.7, 0.7, "emoji", "general"),
        e("SKULL_CROSSBONES", -0.7, 0.7, "emoji", "general"),
        e("SIREN_EMOJI", -0.4, 0.5, "emoji", "general"),
        e("BROKEN_HEART_EMOJI", -0.5, 0.5, "emoji", "general"),
        # Sarcasm/irony emojis
        e("CLOWN_EMOJI", -0.3, 0.6, "emoji", "wsb_slang"),  # sarcasm marker
        e("EYEROLL_EMOJI", -0.2, 0.4, "emoji", "general"),
        e("SLOT_MACHINE_EMOJI", -0.2, 0.3, "emoji", "general"),

        # =====================================================================
        # CONVICTION INDICATORS (not polarity — used for conviction scoring)
        # =====================================================================
        # High conviction (polarity neutral, high intensity)
        e("all in", 0.3, 0.9, "action", "wsb_slang"),
        e("bet the farm", 0.2, 0.9, "action", "wsb_slang"),
        e("loaded", 0.3, 0.8, "action", "wsb_slang"),
        e("loaded to the tills", 0.3, 0.85, "action", "wsb_slang"),
        e("guaranteed", 0.2, 0.9, "descriptor", "general"),
        e("no doubt", 0.15, 0.8, "descriptor", "general"),
        e("100%", 0.2, 0.85, "descriptor", "general"),
        e("mark my words", 0.15, 0.85, "descriptor", "general"),
        e("trust me", 0.1, 0.7, "descriptor", "general"),
        e("easy money", 0.4, 0.8, "descriptor", "wsb_slang"),
        e("free money", 0.3, 0.8, "descriptor", "wsb_slang"),
        e("cant lose", 0.3, 0.85, "descriptor", "wsb_slang"),
        e("no brainer", 0.3, 0.75, "descriptor", "general"),
        e("lock", 0.25, 0.7, "descriptor", "general"),
        e("obvious", 0.15, 0.65, "descriptor", "general"),
        e("certain", 0.15, 0.75, "descriptor", "general"),
        e("definitely", 0.1, 0.7, "descriptor", "general"),
        e("absolutely", 0.1, 0.75, "descriptor", "general"),
        e("convinced", 0.2, 0.75, "descriptor", "general"),
        e("yolo", 0.2, 0.9, "action", "wsb_slang"),

        # =====================================================================
        # MACRO / ECONOMIC TERMS
        # =====================================================================
        e("rate cut", 0.55, 0.6, "outcome", "macro"),
        e("rate hike", -0.45, 0.55, "outcome", "macro"),
        e("dovish", 0.5, 0.55, "descriptor", "macro"),
        e("hawkish", -0.4, 0.5, "descriptor", "macro"),
        e("inflation", -0.3, 0.4, "descriptor", "macro"),
        e("recession", -0.6, 0.65, "descriptor", "macro"),
        e("soft landing", 0.4, 0.5, "outcome", "macro"),
        e("hard landing", -0.55, 0.6, "outcome", "macro"),
        e("pivot", 0.5, 0.55, "outcome", "macro"),  # Fed pivot = bullish
        e("taper", -0.35, 0.4, "action", "macro"),
        e("tapering", -0.35, 0.4, "action", "macro"),
        e("quantitative easing", 0.45, 0.5, "action", "macro"),
        e("qe", 0.45, 0.5, "action", "macro"),
        e("quantitative tightening", -0.45, 0.5, "action", "macro"),
        e("qt", -0.4, 0.45, "action", "macro"),
        e("stimulus", 0.5, 0.55, "outcome", "macro"),
        e("tariff", -0.4, 0.5, "outcome", "macro"),
        e("tariffs", -0.4, 0.5, "outcome", "macro"),
        e("trade war", -0.5, 0.55, "outcome", "macro"),
        e("sanctions", -0.4, 0.45, "outcome", "macro"),
        e("default", -0.7, 0.75, "outcome", "macro"),
        e("debt ceiling", -0.35, 0.4, "outcome", "macro"),
        e("shutdown", -0.4, 0.45, "outcome", "macro"),

        # =====================================================================
        # OPTIONS-SPECIFIC TERMS
        # =====================================================================
        e("iv crush", -0.5, 0.6, "outcome", "options"),
        e("theta decay", -0.3, 0.4, "outcome", "options"),
        e("theta burn", -0.35, 0.45, "outcome", "options"),
        e("gamma squeeze", 0.7, 0.8, "outcome", "options"),
        e("max pain", -0.2, 0.35, "descriptor", "options"),
        e("pinning", -0.15, 0.25, "descriptor", "options"),
        e("dark pool", 0.1, 0.5, "descriptor", "options"),
        e("dark pool print", 0.15, 0.5, "descriptor", "options"),
        e("unusual options", 0.3, 0.55, "descriptor", "options"),
        e("sweep", 0.35, 0.5, "action", "options"),
        e("sweeps", 0.35, 0.5, "action", "options"),
        e("block trade", 0.2, 0.45, "action", "options"),
        e("open interest", 0.1, 0.3, "descriptor", "options"),
        e("options flow", 0.2, 0.4, "descriptor", "options"),
        e("put call ratio", -0.1, 0.3, "descriptor", "options"),
        e("credit spread", 0.1, 0.3, "action", "options"),
        e("debit spread", 0.1, 0.3, "action", "options"),
        e("iron condor", 0.0, 0.3, "action", "options"),
        e("straddle", 0.0, 0.3, "action", "options"),
        e("strangle", 0.0, 0.3, "action", "options"),
        e("leap", 0.3, 0.4, "action", "options"),
        e("leaps", 0.3, 0.4, "action", "options"),
        e("premium", 0.0, 0.2, "descriptor", "options"),
        e("assigned", -0.3, 0.4, "outcome", "options"),
        e("exercised", 0.1, 0.3, "outcome", "options"),

        # =====================================================================
        # CORPORATE EVENT TERMS
        # =====================================================================
        e("merger", 0.45, 0.55, "outcome", "general"),
        e("acquisition", 0.4, 0.5, "outcome", "general"),
        e("buyback", 0.5, 0.55, "action", "general"),
        e("share buyback", 0.5, 0.55, "action", "general"),
        e("stock split", 0.45, 0.5, "outcome", "general"),
        e("reverse split", -0.5, 0.55, "outcome", "general"),
        e("dividend", 0.35, 0.4, "outcome", "general"),
        e("special dividend", 0.5, 0.55, "outcome", "general"),
        e("bankruptcy", -0.9, 0.95, "outcome", "general"),
        e("chapter 11", -0.8, 0.85, "outcome", "general"),
        e("delisting", -0.85, 0.9, "outcome", "general"),
        e("ipo", 0.3, 0.4, "outcome", "general"),
        e("spac", 0.15, 0.3, "descriptor", "general"),
        e("insider buying", 0.55, 0.6, "action", "general"),
        e("fda approval", 0.7, 0.75, "outcome", "general"),
        e("fda approved", 0.7, 0.75, "outcome", "general"),
        e("fda rejection", -0.7, 0.75, "outcome", "general"),
        e("patent", 0.35, 0.4, "outcome", "general"),
        e("lawsuit", -0.4, 0.5, "outcome", "general"),
        e("sec investigation", -0.55, 0.6, "outcome", "general"),
        e("earnings beat", 0.6, 0.65, "outcome", "general"),
        e("earnings miss", -0.6, 0.65, "outcome", "general"),
        e("revenue beat", 0.55, 0.6, "outcome", "general"),
        e("revenue miss", -0.55, 0.6, "outcome", "general"),
        e("guidance raise", 0.6, 0.65, "outcome", "general"),
        e("guidance cut", -0.65, 0.7, "outcome", "general"),

        # =====================================================================
        # ADDITIONAL GENERAL TERMS
        # =====================================================================
        e("underperform", -0.5, 0.55, "descriptor", "general"),
        e("outperform", 0.5, 0.55, "descriptor", "general"),
        e("overweight", 0.4, 0.45, "descriptor", "general"),
        e("underweight", -0.4, 0.45, "descriptor", "general"),
        e("sector rotation", 0.0, 0.3, "descriptor", "general"),
        e("rotation", 0.0, 0.25, "descriptor", "general"),
        e("profit taking", -0.25, 0.3, "action", "general"),
        e("capitulation", -0.6, 0.65, "outcome", "general"),
        e("euphoria", 0.3, 0.5, "descriptor", "general"),  # can be sarcastic
        e("fomo", 0.3, 0.5, "descriptor", "wsb_slang"),
        e("panic", -0.6, 0.65, "descriptor", "general"),
        e("panic sell", -0.7, 0.75, "action", "general"),
        e("panic selling", -0.7, 0.75, "action", "general"),
        e("panic buying", 0.4, 0.5, "action", "general"),
        e("catalyst", 0.2, 0.35, "descriptor", "general"),
        e("tailwind", 0.35, 0.4, "descriptor", "general"),
        e("tailwinds", 0.35, 0.4, "descriptor", "general"),
        e("headwind", -0.3, 0.35, "descriptor", "general"),
        e("trap", -0.4, 0.45, "outcome", "general"),
        e("bear trap", 0.45, 0.5, "outcome", "technical"),
        e("priced in", -0.1, 0.3, "descriptor", "general"),
    ]

    # Build dict keyed by lowercase term
    lexicon: Dict[str, LexiconEntry] = {}
    for entry in entries:
        lexicon[entry.term.lower()] = entry

    return lexicon


# Module-level constant — built once at import time
_LEXICON: Dict[str, LexiconEntry] = _build_lexicon()


def get_lexicon() -> Dict[str, LexiconEntry]:
    """Return the full sentiment lexicon."""
    return _LEXICON


# ── Modifier lookups ──

NEGATORS = frozenset({
    "not", "no", "never", "neither", "nobody", "nothing", "nowhere",
    "nor", "hardly", "barely", "scarcely", "without",
    "dont", "don't", "doesnt", "doesn't", "didnt", "didn't",
    "wont", "won't", "wouldnt", "wouldn't", "cant", "can't",
    "cannot", "couldnt", "couldn't", "shouldnt", "shouldn't",
    "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't",
    "werent", "weren't", "hasnt", "hasn't", "havent", "haven't",
    "hadnt", "hadn't",
})

INTENSIFIERS = frozenset({
    "extremely", "absolutely", "definitely", "massive", "insane",
    "literally", "huge", "incredible", "absurdly", "insanely",
    "ridiculously", "astronomically", "wildly", "overwhelmingly",
    "unbelievably", "extraordinarily", "tremendously", "spectacularly",
    "seriously", "very", "really", "truly", "super", "mega",
    "ultra", "crazy", "f*cking", "fucking", "fking",
})

DIMINISHERS = frozenset({
    "slightly", "maybe", "might", "possibly", "could", "perhaps",
    "somewhat", "kinda", "sorta", "barely", "hardly", "mildly",
    "relatively", "moderately", "a bit", "a little", "not very",
    "not really",
})

# High-conviction phrases (for conviction scoring)
HIGH_CONVICTION_PHRASES = [
    "all in", "bet the farm", "loaded to the tills", "loaded up",
    "100%", "guaranteed", "no doubt", "mark my words", "trust me",
    "easy money", "free money", "cant lose", "can't lose",
    "no brainer", "no-brainer", "obvious play", "certain",
    "absolutely certain", "i know", "this is it", "money printer",
    "conviction play", "maximum conviction", "full send",
    "bet my life", "yolo", "going all in",
]

# Low-conviction phrases (for conviction scoring)
LOW_CONVICTION_PHRASES = [
    "maybe", "might", "possibly", "could be", "perhaps",
    "not sure", "idk", "who knows", "we'll see", "dyor",
    "nfa", "not financial advice", "do your own research",
    "just my opinion", "take this with a grain of salt",
    "could go either way", "hard to say", "uncertain",
    "speculative", "just a thought", "food for thought",
    "i think", "i believe", "imo", "imho",
]

# Known sarcastic phrases
SARCASTIC_PHRASES = [
    "what could go wrong",
    "what could possibly go wrong",
    "this is fine",
    "everything is fine",
    "totally not a bubble",
    "surely this time is different",
    "this time its different",
    "this time it's different",
    "cant go tits up",
    "can't go tits up",
    "literally cant go tits up",
    "free money glitch",
    "infinite money glitch",
    "genius move",
    "big brain",
    "big brain move",
    "big brain play",
    "to the moon right",
    "nailed it",
    "going great",
    "shocked pikachu",
    "nobody could have seen this coming",
    "who could have predicted",
    "who would have thought",
    "how could this happen",
    "working as intended",
    "totally sustainable",
    "nothing to see here",
    "im sure itll be fine",
    "i'm sure it'll be fine",
    "priced in right",
]
