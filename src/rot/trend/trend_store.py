from __future__ import annotations

from typing import Dict, Optional

from rot.core.types import ThreadSnapshot


class TrendStore:
    def __init__(self) -> None:
        self._last: Dict[str, ThreadSnapshot] = {}

    def update(self, key: str, snap: ThreadSnapshot) -> Optional[ThreadSnapshot]:
        prev = self._last.get(key)
        self._last[key] = snap
        return prev
