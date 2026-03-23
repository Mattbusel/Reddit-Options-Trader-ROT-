"""Reddit data fetching abstraction with mock support and ticker extraction.

Provides:
- ``RedditPost`` — dataclass for a single Reddit submission.
- ``TickerMention`` — aggregated mention stats for a ticker.
- ``RedditClient`` — abstract base for Reddit API clients.
- ``MockRedditClient`` — deterministic fake client for testing.
- ``TickerExtractor`` — regex-based ticker extraction and aggregation.
- ``WallStreetBetsAnalyzer`` — high-level WSB trending ticker analysis.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Common words and subreddit names to exclude from ticker detection
# ---------------------------------------------------------------------------

_COMMON_EXCLUSIONS: frozenset[str] = frozenset(
    [
        "THE", "FOR", "ARE", "AND", "NOT", "BUT", "THIS", "THAT", "WITH",
        "FROM", "HAVE", "BEEN", "WILL", "YOUR", "THEY", "MORE", "WHEN",
        "WHAT", "SOME", "THAN", "INTO", "DOES", "JUST", "BEEN", "ALSO",
        "ITS", "ALL", "NEW", "ONE", "CAN", "HAS", "WAS", "GET", "YOU",
        "ANY", "HOW", "OUR", "OUT", "WHO", "WHY", "HIM", "HER", "WAS",
        "NOW", "DID", "WAY", "EACH", "MAKE", "MAY", "OWN", "USE",
        # Common subreddit names that look like tickers
        "WSB", "ATH", "DD", "YOLO", "CEO", "CFO", "IPO", "ETF", "OTC",
        "SEC", "FED", "GDP", "CPI", "AI", "EV", "PE", "PB", "ROI",
        "TLDR", "IMO", "IMH", "IIRC", "AFAIK", "TBH", "NGL", "FYI",
        # Common financial acronyms that aren't tickers
        "BUY", "SELL", "HOLD", "CALL", "PUT", "SHORT", "LONG",
        "USD", "EUR", "GBP", "JPY",
    ]
)

_TICKER_PATTERN: re.Pattern = re.compile(
    r"(?:^|[\s\(\[\{])(\$[A-Z]{1,5}|[A-Z]{2,5})(?:[\s\)\]\}\.,!?]|$)"
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RedditPost:
    """A single Reddit submission."""

    id: str
    title: str
    body: str
    score: int
    upvote_ratio: float
    num_comments: int
    created_utc: datetime
    subreddit: str
    author: str
    flair: Optional[str] = None
    awards: int = 0


@dataclass
class TickerMention:
    """Aggregated mention data for a single ticker."""

    ticker: str
    mention_count: int
    avg_sentiment: float
    posts: list[RedditPost] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract client
# ---------------------------------------------------------------------------


class RedditClient(ABC):
    """Abstract base class for Reddit API clients."""

    @abstractmethod
    def fetch_posts(
        self,
        subreddit: str,
        limit: int = 100,
        time_filter: str = "day",
    ) -> list[RedditPost]:
        """Fetch top posts from a subreddit.

        Args:
            subreddit: Name of the subreddit (without r/).
            limit: Maximum number of posts to return.
            time_filter: One of "hour", "day", "week", "month", "year", "all".

        Returns:
            List of ``RedditPost`` objects.
        """

    @abstractmethod
    def search_ticker(
        self,
        ticker: str,
        subreddits: list[str],
        limit: int = 50,
    ) -> list[RedditPost]:
        """Search for posts mentioning a specific ticker.

        Args:
            ticker: Ticker symbol to search for.
            subreddits: List of subreddit names to search.
            limit: Maximum number of posts to return.

        Returns:
            List of matching ``RedditPost`` objects.
        """


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


class MockRedditClient(RedditClient):
    """Deterministic fake Reddit client for testing.

    Generates posts based on a fixed seed derived from the subreddit name so
    results are stable across calls.
    """

    _FAKE_TICKERS = ["AAPL", "TSLA", "GME", "AMC", "NVDA", "PLTR", "SPY", "QQQ"]
    _FAKE_AUTHORS = ["diamond_hands_dan", "moon_boy_99", "theta_gang_chad", "wsb_veteran"]
    _FAKE_FLAIRS = ["DD", "YOLO", "Discussion", "Gain", "Loss", None]

    def fetch_posts(
        self,
        subreddit: str,
        limit: int = 100,
        time_filter: str = "day",
    ) -> list[RedditPost]:
        posts: list[RedditPost] = []
        seed = sum(ord(c) for c in subreddit)
        for i in range(min(limit, 20)):
            ticker_idx = (seed + i) % len(self._FAKE_TICKERS)
            ticker = self._FAKE_TICKERS[ticker_idx]
            author_idx = (seed + i * 3) % len(self._FAKE_AUTHORS)
            flair_idx = (seed + i * 7) % len(self._FAKE_FLAIRS)
            posts.append(
                RedditPost(
                    id=f"{subreddit}_{i:04d}",
                    title=f"${ticker} to the moon! {time_filter} play #{i}",
                    body=f"I am buying {ticker} calls. {ticker} is going up. Not financial advice.",
                    score=100 + (seed * i) % 5000,
                    upvote_ratio=0.7 + (i % 3) * 0.1,
                    num_comments=10 + i * 5,
                    created_utc=datetime.now(tz=timezone.utc),
                    subreddit=subreddit,
                    author=self._FAKE_AUTHORS[author_idx],
                    flair=self._FAKE_FLAIRS[flair_idx],
                    awards=i % 5,
                )
            )
        return posts

    def search_ticker(
        self,
        ticker: str,
        subreddits: list[str],
        limit: int = 50,
    ) -> list[RedditPost]:
        posts: list[RedditPost] = []
        for i, subreddit in enumerate(subreddits):
            posts.append(
                RedditPost(
                    id=f"search_{ticker}_{i}",
                    title=f"{ticker} analysis for {subreddit}",
                    body=f"${ticker} looks bullish. Technical analysis shows {ticker} breaking out.",
                    score=200 + i * 50,
                    upvote_ratio=0.85,
                    num_comments=25 + i * 10,
                    created_utc=datetime.now(tz=timezone.utc),
                    subreddit=subreddit,
                    author="mock_analyst",
                    flair="DD",
                    awards=2,
                )
            )
            if len(posts) >= limit:
                break
        return posts


# ---------------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------------


class TickerExtractor:
    """Extracts and aggregates stock ticker mentions from text.

    Uses a regex to find patterns matching uppercase letter sequences preceded
    by ``$`` or appearing as standalone words, then filters against a blocklist
    of common English words and financial acronyms.
    """

    def __init__(self, exclusions: Optional[frozenset[str]] = None) -> None:
        self._exclusions = exclusions if exclusions is not None else _COMMON_EXCLUSIONS

    def extract_tickers(self, text: str) -> list[str]:
        """Extract ticker symbols from a block of text.

        Args:
            text: Raw text (title + body of a post).

        Returns:
            Deduplicated list of ticker symbols found in the text.
        """
        tickers: list[str] = []
        seen: set[str] = set()

        # Find $TICKER patterns (strong signal)
        dollar_pattern = re.findall(r"\$([A-Z]{1,5})\b", text)
        for ticker in dollar_pattern:
            if ticker not in seen and ticker not in self._exclusions:
                tickers.append(ticker)
                seen.add(ticker)

        # Find standalone uppercase words (weaker signal, length 2–5)
        standalone = re.findall(r"\b([A-Z]{2,5})\b", text)
        for ticker in standalone:
            if ticker not in seen and ticker not in self._exclusions:
                tickers.append(ticker)
                seen.add(ticker)

        return tickers

    def aggregate_mentions(
        self,
        posts: list[RedditPost],
        min_mentions: int = 2,
    ) -> list[TickerMention]:
        """Count ticker mentions across a list of posts.

        A simple positive/negative sentiment proxy is derived from the
        post's upvote ratio: > 0.6 → positive, else → negative.

        Args:
            posts: List of Reddit posts to analyze.
            min_mentions: Minimum mention count to include in output.

        Returns:
            List of ``TickerMention`` objects sorted by mention count descending.
        """
        mention_counts: dict[str, int] = defaultdict(int)
        sentiment_sums: dict[str, float] = defaultdict(float)
        ticker_posts: dict[str, list[RedditPost]] = defaultdict(list)

        for post in posts:
            combined_text = f"{post.title} {post.body}".upper()
            tickers = self.extract_tickers(combined_text)
            sentiment = 1.0 if post.upvote_ratio >= 0.6 else -1.0

            for ticker in tickers:
                mention_counts[ticker] += 1
                sentiment_sums[ticker] += sentiment
                ticker_posts[ticker].append(post)

        results: list[TickerMention] = []
        for ticker, count in mention_counts.items():
            if count >= min_mentions:
                avg_sentiment = sentiment_sums[ticker] / count
                results.append(
                    TickerMention(
                        ticker=ticker,
                        mention_count=count,
                        avg_sentiment=avg_sentiment,
                        posts=ticker_posts[ticker],
                    )
                )

        results.sort(key=lambda m: m.mention_count, reverse=True)
        return results


# ---------------------------------------------------------------------------
# WallStreetBets Analyzer
# ---------------------------------------------------------------------------


class WallStreetBetsAnalyzer:
    """High-level analyzer for r/wallstreetbets trends.

    Wraps a ``RedditClient`` to provide trending ticker detection and
    per-ticker sentiment summaries.
    """

    WSB_SUBREDDITS = [
        "wallstreetbets",
        "stocks",
        "investing",
        "options",
        "stockmarket",
    ]

    def __init__(self, client: RedditClient) -> None:
        self._client = client
        self._extractor = TickerExtractor()

    def trending_tickers(
        self,
        limit: int = 50,
        time_filter: str = "day",
    ) -> list[TickerMention]:
        """Return trending tickers from WSB ordered by mention count.

        Args:
            limit: Number of posts to fetch per subreddit.
            time_filter: Reddit time filter ("hour", "day", "week", etc.).

        Returns:
            List of ``TickerMention`` sorted by mention count descending.
        """
        all_posts: list[RedditPost] = self._client.fetch_posts(
            "wallstreetbets", limit=limit, time_filter=time_filter
        )
        return self._extractor.aggregate_mentions(all_posts, min_mentions=1)

    def sentiment_summary(self, ticker: str) -> dict:
        """Compute a sentiment summary for a specific ticker.

        Args:
            ticker: Ticker symbol to analyze (e.g. "AAPL").

        Returns:
            Dict with keys:
            - ``mention_count`` (int)
            - ``avg_sentiment`` (float, in [-1, 1])
            - ``bull_bear_ratio`` (float; > 1.0 → bullish, < 1.0 → bearish)
        """
        posts = self._client.search_ticker(
            ticker, self.WSB_SUBREDDITS, limit=50
        )
        if not posts:
            return {"mention_count": 0, "avg_sentiment": 0.0, "bull_bear_ratio": 1.0}

        bull_count = sum(1 for p in posts if p.upvote_ratio >= 0.6)
        bear_count = len(posts) - bull_count
        avg_sentiment = (bull_count - bear_count) / len(posts)
        bull_bear_ratio = bull_count / max(bear_count, 1)

        return {
            "mention_count": len(posts),
            "avg_sentiment": avg_sentiment,
            "bull_bear_ratio": bull_bear_ratio,
        }
