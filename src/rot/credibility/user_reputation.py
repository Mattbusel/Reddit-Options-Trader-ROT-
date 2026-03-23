"""User Reputation System for Reddit Options Trader.

Builds a per-user reputation score from Reddit karma, account age,
historical post accuracy, and manipulation detection flags.  Scores are
persisted via a lightweight SQLAlchemy-style dataclass so they can be
stored to the existing SQLite layer without adding a hard SQLAlchemy
runtime dependency.

Typical usage::

    scorer = UserReputationScorer()
    rep = scorer.score(
        username="retard_chad",
        karma=45_000,
        account_age_days=730,
        manipulation_flags=0,
        accuracy_ratio=0.62,
    )
    # Multiply signal credibility by rep.weight
    adjusted_confidence = raw_confidence * rep.weight
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional


# ── Constants ─────────────────────────────────────────────

# Log-normalisation ceiling: karma >= this gets the maximum karma bonus
_KARMA_LOG_CEIL = math.log1p(1_000_000)

# Account age thresholds (days)
_AGE_NEW = 30
_AGE_ESTABLISHED = 365
_AGE_VETERAN = 730

# How much each component contributes to the final weight (must sum to 1.0)
_WEIGHT_KARMA = 0.30
_WEIGHT_AGE = 0.20
_WEIGHT_ACCURACY = 0.35
_WEIGHT_MANIPULATION = 0.15


# ── Data Classes ──────────────────────────────────────────


@dataclass(frozen=True)
class UserReputation:
    """Scored reputation for a single Reddit user.

    Attributes:
        username: Reddit username (without u/ prefix).
        karma_score: Log-normalised karma contribution, 0.0–1.0.
        post_history_score: Accuracy of past option call posts, 0.0–1.0.
        accuracy_score: Alias for post_history_score (backward-compat).
        pump_dump_flag: ``True`` when the manipulation detector has flagged
            this author as part of a pump-and-dump or coordinated-posting
            campaign within the last scoring window.
        weight: Composite reputation weight in (0.05, 1.0].  Multiply raw
            signal credibility by this value before acting on the signal.
        scored_at: Unix timestamp when this score was computed.
    """

    username: str
    karma_score: float
    post_history_score: float
    accuracy_score: float
    pump_dump_flag: bool
    weight: float
    scored_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "username": self.username,
            "karma_score": round(self.karma_score, 4),
            "post_history_score": round(self.post_history_score, 4),
            "accuracy_score": round(self.accuracy_score, 4),
            "pump_dump_flag": self.pump_dump_flag,
            "weight": round(self.weight, 4),
            "scored_at": self.scored_at,
        }


@dataclass
class ReputationStore:
    """In-process persistence store for ``UserReputation`` records.

    Backed by a plain dict keyed on username.  In a production deployment
    this would delegate to a database mixin; here it provides the same
    interface without requiring a live DB connection, making it fully
    testable with zero I/O.

    Schema mirrors what a SQL table would look like::

        CREATE TABLE user_reputation (
            username TEXT PRIMARY KEY,
            karma_score REAL,
            post_history_score REAL,
            accuracy_score REAL,
            pump_dump_flag INTEGER,
            weight REAL,
            scored_at REAL
        );
    """

    _records: dict[str, UserReputation] = field(default_factory=dict)

    def upsert(self, rep: UserReputation) -> None:
        """Insert or replace a reputation record."""
        self._records[rep.username] = rep

    def get(self, username: str) -> Optional[UserReputation]:
        """Return the stored reputation for *username*, or ``None``."""
        return self._records.get(username)

    def all(self) -> list[UserReputation]:
        """Return all stored records sorted by weight descending."""
        return sorted(self._records.values(), key=lambda r: -r.weight)

    def __len__(self) -> int:
        return len(self._records)


# ── Scorer ────────────────────────────────────────────────


class UserReputationScorer:
    """Builds a ``UserReputation`` from observable Reddit metadata.

    Scoring components
    ------------------
    **Karma (30%)** — log-normalised.  ``log1p(karma) / log1p(1_000_000)``
    so a user with 1 M karma gets 1.0, 10 k karma ≈ 0.58, 100 karma ≈ 0.28.

    **Account age (20%)** — three tiers:
      - < 30 days  → 0.10 (new account, unproven)
      - 30–364 days → linear interpolation 0.10–0.60
      - 365–729 days → 0.60 (established)
      - >= 730 days → 1.00 (veteran)

    **Post accuracy (35%)** — pass the historical win-rate of option calls
    attributed to this user as a float in [0, 1].  Defaults to a neutral
    0.50 when no history is available.

    **Manipulation penalty (15%)** — a pump-dump / coordinated-posting flag
    from ``ManipulationDetector`` zeroes out this component.  Clean users
    receive full 1.0.

    The four weighted components are combined and then clamped to [0.05, 1.0]
    so even badly-flagged users retain a minimal non-zero weight (rather than
    silently dropping their signals entirely — consumers can decide whether
    to act on a weight of 0.05).
    """

    def __init__(self, store: Optional[ReputationStore] = None) -> None:
        self._store = store or ReputationStore()

    @property
    def store(self) -> ReputationStore:
        """The backing reputation store."""
        return self._store

    # ── Public API ──────────────────────────────────────

    def score(
        self,
        username: str,
        karma: int = 0,
        account_age_days: int = 0,
        accuracy_ratio: float = 0.50,
        manipulation_flags: int = 0,
        *,
        persist: bool = True,
    ) -> UserReputation:
        """Compute (and optionally persist) a reputation score.

        Parameters
        ----------
        username:
            Reddit username to score.
        karma:
            Total combined karma (post + comment).  Negative values are
            treated as 0.
        account_age_days:
            Age of the account in days at scoring time.
        accuracy_ratio:
            Historical win-rate for option call posts in [0.0, 1.0].
            Pass ``0.50`` when no history is available (neutral assumption).
        manipulation_flags:
            Number of active manipulation detection flags from
            ``ManipulationDetector`` associated with this author.
            0 = clean; >= 1 = penalised.
        persist:
            When ``True`` (default) the result is saved to ``self.store``.

        Returns
        -------
        UserReputation
            Scored reputation record.
        """
        karma_s = self._karma_score(max(0, karma))
        age_s = self._age_score(max(0, account_age_days))
        acc_s = float(max(0.0, min(1.0, accuracy_ratio)))
        manip_s = 0.0 if manipulation_flags > 0 else 1.0
        pump_flag = manipulation_flags > 0

        raw_weight = (
            karma_s * _WEIGHT_KARMA
            + age_s * _WEIGHT_AGE
            + acc_s * _WEIGHT_ACCURACY
            + manip_s * _WEIGHT_MANIPULATION
        )
        weight = max(0.05, min(1.0, raw_weight))

        rep = UserReputation(
            username=username,
            karma_score=round(karma_s, 4),
            post_history_score=round(acc_s, 4),
            accuracy_score=round(acc_s, 4),
            pump_dump_flag=pump_flag,
            weight=round(weight, 4),
        )

        if persist:
            self._store.upsert(rep)

        return rep

    def apply_to_confidence(
        self,
        confidence: float,
        username: str,
    ) -> float:
        """Multiply a signal confidence by the stored reputation weight.

        If no reputation record exists for *username*, the signal confidence
        is returned unchanged (neutral; no penalty for unknown users).

        Parameters
        ----------
        confidence:
            Raw signal credibility score in [0.0, 1.0].
        username:
            Reddit author of the signal.

        Returns
        -------
        float
            Adjusted confidence in [0.0, 1.0].
        """
        rep = self._store.get(username)
        if rep is None:
            return confidence
        return max(0.0, min(1.0, confidence * rep.weight))

    # ── Private helpers ──────────────────────────────────

    @staticmethod
    def _karma_score(karma: int) -> float:
        """Log-normalised karma contribution, 0.0–1.0."""
        if karma <= 0:
            return 0.0
        return min(1.0, math.log1p(karma) / _KARMA_LOG_CEIL)

    @staticmethod
    def _age_score(age_days: int) -> float:
        """Account-age contribution, 0.0–1.0."""
        if age_days < _AGE_NEW:
            return 0.10
        if age_days < _AGE_ESTABLISHED:
            # Linear interpolation from 0.10 to 0.60 over [30, 365)
            frac = (age_days - _AGE_NEW) / (_AGE_ESTABLISHED - _AGE_NEW)
            return 0.10 + frac * 0.50
        if age_days < _AGE_VETERAN:
            return 0.60
        return 1.0
