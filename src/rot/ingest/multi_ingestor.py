from __future__ import annotations

import logging
from typing import Any, List, Protocol, runtime_checkable

from rot.core.types import ThreadSnapshot

log = logging.getLogger(__name__)


@runtime_checkable
class Ingestor(Protocol):
    """Duck-type protocol for any ingestor with a .poll() method."""

    def poll(self) -> List[ThreadSnapshot]: ...


class MultiSourceIngestor:
    """Combines multiple ingestors into a single .poll() call.

    Each sub-ingestor is polled in sequence. Failures in one do not
    block others — they are logged and skipped.
    """

    def __init__(self, ingestors: List[Any]) -> None:
        self._ingestors = ingestors

    def poll(self) -> List[ThreadSnapshot]:
        all_snaps: List[ThreadSnapshot] = []
        for ing in self._ingestors:
            try:
                snaps = ing.poll()
                all_snaps.extend(snaps)
            except Exception as e:
                name = type(ing).__name__
                log.error("Ingestor %s failed: %s", name, e)
                continue
        return all_snaps
