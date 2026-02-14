"""Strategy Marketplace — publish, subscribe, rate, and discover strategies.

Users can publish their strategies to the marketplace so others can subscribe,
copy, and rate them.  The marketplace maintains in-memory state for entries,
subscriptions, and ratings; persistence is handled by the storage layer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from uuid import uuid4

from rot.strategy.types import MarketplaceEntry, Strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sort key helpers
# ---------------------------------------------------------------------------

_SORT_KEYS: dict[str, callable] = {
    "rating": lambda e: (e.rating, e.subscriber_count),
    "subscribers": lambda e: (e.subscriber_count, e.rating),
    "newest": lambda e: e.created_at,
    "win_rate": lambda e: e.performance.get("win_rate", 0.0),
    "sharpe": lambda e: e.performance.get("sharpe", 0.0),
}


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------


class Marketplace:
    """In-memory marketplace for publishing, subscribing, and rating strategies.

    All mutations (publish, subscribe, rate, etc.) are synchronous and
    thread-safe only under the GIL.  For async callers the storage layer
    wraps these in ``run_in_executor``.

    Attributes
    ----------
    _entries : dict[str, MarketplaceEntry]
        Map of entry_id to marketplace entry.
    _subscriptions : dict[str, set[str]]
        Map of user_id to the set of entry_ids the user is subscribed to.
    _ratings : dict[str, list[tuple[str, float]]]
        Map of entry_id to list of ``(user_id, rating)`` pairs.
    """

    def __init__(self) -> None:
        self._entries: dict[str, MarketplaceEntry] = {}
        self._subscriptions: dict[str, set[str]] = {}
        self._ratings: dict[str, list[tuple[str, float]]] = {}

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(
        self,
        strategy: Strategy,
        author_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> MarketplaceEntry:
        """Publish a strategy to the marketplace.

        Parameters
        ----------
        strategy:
            The strategy to publish.
        author_id:
            User ID of the publisher.
        name:
            Display name.  Falls back to ``strategy.name``.
        description:
            Marketing description.  Falls back to ``strategy.description``.

        Returns
        -------
        MarketplaceEntry
            The newly created marketplace entry.
        """

        entry_id = str(uuid4())
        display_name = name if name else strategy.name
        display_desc = description if description is not None else strategy.description

        entry = MarketplaceEntry(
            id=entry_id,
            strategy_id=strategy.id,
            author_id=author_id,
            name=display_name,
            description=display_desc,
            performance=dict(strategy.performance),
            subscriber_count=0,
            rating=0.0,
            created_at=time.time(),
        )

        self._entries[entry_id] = entry
        self._ratings[entry_id] = []
        logger.info(
            "Published strategy %s as marketplace entry %s by author %s",
            strategy.id,
            entry_id,
            author_id,
        )
        return entry

    def unpublish(self, entry_id: str, author_id: str) -> bool:
        """Remove a marketplace entry if the requesting user is the author.

        Parameters
        ----------
        entry_id:
            Marketplace entry to remove.
        author_id:
            User requesting the removal (must match the entry author).

        Returns
        -------
        bool
            ``True`` if the entry was removed, ``False`` if not found or the
            caller is not the author.
        """

        entry = self._entries.get(entry_id)
        if entry is None:
            logger.debug("unpublish: entry %s not found", entry_id)
            return False
        if entry.author_id != author_id:
            logger.warning(
                "unpublish: author mismatch for entry %s (expected %s, got %s)",
                entry_id,
                entry.author_id,
                author_id,
            )
            return False

        # Remove the entry itself.
        del self._entries[entry_id]
        self._ratings.pop(entry_id, None)

        # Remove all subscriptions pointing to this entry.
        for uid, subs in self._subscriptions.items():
            subs.discard(entry_id)

        logger.info("Unpublished marketplace entry %s", entry_id)
        return True

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, user_id: str, entry_id: str) -> bool:
        """Subscribe a user to a marketplace entry.

        Parameters
        ----------
        user_id:
            The subscribing user.
        entry_id:
            The marketplace entry to subscribe to.

        Returns
        -------
        bool
            ``True`` if newly subscribed, ``False`` if already subscribed or
            the entry does not exist.
        """

        entry = self._entries.get(entry_id)
        if entry is None:
            logger.debug("subscribe: entry %s not found", entry_id)
            return False

        user_subs = self._subscriptions.setdefault(user_id, set())
        if entry_id in user_subs:
            return False

        user_subs.add(entry_id)

        # Increment subscriber count (frozen dataclass -> replace).
        self._entries[entry_id] = replace(
            entry, subscriber_count=entry.subscriber_count + 1
        )
        logger.info("User %s subscribed to entry %s", user_id, entry_id)
        return True

    def unsubscribe(self, user_id: str, entry_id: str) -> bool:
        """Unsubscribe a user from a marketplace entry.

        Parameters
        ----------
        user_id:
            The user unsubscribing.
        entry_id:
            The marketplace entry to unsubscribe from.

        Returns
        -------
        bool
            ``True`` if the subscription was removed, ``False`` if the user
            was not subscribed or the entry does not exist.
        """

        user_subs = self._subscriptions.get(user_id)
        if user_subs is None or entry_id not in user_subs:
            return False

        entry = self._entries.get(entry_id)
        if entry is None:
            # Entry was deleted but subscription lingered -- clean up.
            user_subs.discard(entry_id)
            return False

        user_subs.discard(entry_id)

        new_count = max(0, entry.subscriber_count - 1)
        self._entries[entry_id] = replace(entry, subscriber_count=new_count)
        logger.info("User %s unsubscribed from entry %s", user_id, entry_id)
        return True

    # ------------------------------------------------------------------
    # Ratings
    # ------------------------------------------------------------------

    def rate(self, user_id: str, entry_id: str, rating: float) -> float:
        """Add or update a user's rating for a marketplace entry.

        Parameters
        ----------
        user_id:
            The rating user.
        entry_id:
            The entry being rated.
        rating:
            Numeric rating in the range ``[1.0, 5.0]``.

        Returns
        -------
        float
            The new average rating for the entry.

        Raises
        ------
        ValueError
            If *rating* is outside the valid range.
        KeyError
            If *entry_id* does not exist.
        """

        if not (1.0 <= rating <= 5.0):
            raise ValueError(f"rating must be between 1.0 and 5.0, got {rating}")

        entry = self._entries.get(entry_id)
        if entry is None:
            raise KeyError(f"Marketplace entry {entry_id} not found")

        # Upsert: replace existing rating from this user, or append.
        ratings_list = self._ratings.setdefault(entry_id, [])
        updated = False
        for idx, (uid, _old_rating) in enumerate(ratings_list):
            if uid == user_id:
                ratings_list[idx] = (user_id, rating)
                updated = True
                break
        if not updated:
            ratings_list.append((user_id, rating))

        # Compute new average.
        avg = sum(r for _, r in ratings_list) / len(ratings_list)
        avg = round(avg, 2)

        self._entries[entry_id] = replace(entry, rating=avg)
        logger.info(
            "User %s rated entry %s -> %.1f (new avg %.2f)",
            user_id,
            entry_id,
            rating,
            avg,
        )
        return avg

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_entry(self, entry_id: str) -> MarketplaceEntry | None:
        """Return a single marketplace entry or ``None``."""

        return self._entries.get(entry_id)

    def list_entries(
        self,
        sort_by: str = "rating",
        limit: int = 20,
        offset: int = 0,
    ) -> list[MarketplaceEntry]:
        """Return a paginated, sorted list of marketplace entries.

        Parameters
        ----------
        sort_by:
            Sort criterion.  One of ``"rating"``, ``"subscribers"``,
            ``"newest"``, ``"win_rate"``, ``"sharpe"``.
        limit:
            Maximum entries to return.
        offset:
            Number of entries to skip (for pagination).

        Returns
        -------
        list[MarketplaceEntry]
            Sorted slice of entries.
        """

        key_fn = _SORT_KEYS.get(sort_by, _SORT_KEYS["rating"])
        entries = sorted(self._entries.values(), key=key_fn, reverse=True)
        return entries[offset : offset + limit]

    def get_user_subscriptions(self, user_id: str) -> list[MarketplaceEntry]:
        """Return all entries a user is currently subscribed to.

        Parameters
        ----------
        user_id:
            The subscriber.

        Returns
        -------
        list[MarketplaceEntry]
            Entries the user is subscribed to, sorted by rating descending.
        """

        entry_ids = self._subscriptions.get(user_id, set())
        entries = [
            self._entries[eid] for eid in entry_ids if eid in self._entries
        ]
        entries.sort(key=lambda e: e.rating, reverse=True)
        return entries

    def get_author_entries(self, author_id: str) -> list[MarketplaceEntry]:
        """Return all entries published by a given author.

        Parameters
        ----------
        author_id:
            The publisher.

        Returns
        -------
        list[MarketplaceEntry]
            Entries authored by *author_id*, sorted newest first.
        """

        entries = [
            e for e in self._entries.values() if e.author_id == author_id
        ]
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def search(self, query: str) -> list[MarketplaceEntry]:
        """Simple case-insensitive text search over entry names and descriptions.

        Parameters
        ----------
        query:
            Search string.

        Returns
        -------
        list[MarketplaceEntry]
            Matching entries sorted by rating descending.
        """

        if not query or not query.strip():
            return []

        q_lower = query.strip().lower()
        matches: list[MarketplaceEntry] = []

        for entry in self._entries.values():
            name_lower = entry.name.lower()
            desc_lower = entry.description.lower()
            if q_lower in name_lower or q_lower in desc_lower:
                matches.append(entry)

        matches.sort(key=lambda e: e.rating, reverse=True)
        return matches

    def get_top_performers(
        self,
        days: int = 30,
        limit: int = 10,
    ) -> list[MarketplaceEntry]:
        """Return entries with the best performance metrics.

        Entries are sorted by Sharpe ratio extracted from the ``performance``
        dict.  The *days* parameter is reserved for future use (e.g. filtering
        by performance window) but currently all entries are considered.

        Parameters
        ----------
        days:
            Performance look-back window in days (currently informational).
        limit:
            Maximum entries to return.

        Returns
        -------
        list[MarketplaceEntry]
            Top-performing entries sorted by Sharpe descending.
        """

        entries = list(self._entries.values())

        # Sort by Sharpe (primary) then win_rate (secondary), descending.
        entries.sort(
            key=lambda e: (
                e.performance.get("sharpe", 0.0),
                e.performance.get("win_rate", 0.0),
            ),
            reverse=True,
        )
        return entries[:limit]

    # ------------------------------------------------------------------
    # Internals / helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of published entries."""

        return len(self._entries)

    def __contains__(self, entry_id: str) -> bool:
        """Check if an entry exists."""

        return entry_id in self._entries
