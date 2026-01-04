from __future__ import annotations

from rot.core.types import Event

class CredibilityScorer:
    def score(self, e: Event) -> Event:
        # V1: passthrough. Add heuristics later.
        return e
