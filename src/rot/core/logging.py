from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


class JsonlLogger:
    MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file
    MAX_BACKUPS = 2  # keep .1 and .2 rotated copies

    def __init__(self, root: str = "storage") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _rotate_if_needed(self, path: str) -> None:
        try:
            if not os.path.exists(path) or os.path.getsize(path) < self.MAX_FILE_BYTES:
                return
        except OSError:
            return
        # Rotate: .2 is deleted, .1 -> .2, current -> .1
        for i in range(self.MAX_BACKUPS, 0, -1):
            src = f"{path}.{i}" if i > 1 else path
            dst = f"{path}.{i}"
            if i == self.MAX_BACKUPS:
                # delete oldest backup
                try:
                    os.remove(f"{path}.{i}")
                except OSError:
                    pass
            if i > 1:
                prev = f"{path}.{i - 1}"
                try:
                    os.replace(prev, dst)
                except OSError:
                    pass
        try:
            os.replace(path, f"{path}.1")
        except OSError:
            pass

    def write(self, stream: str, record: Dict[str, Any]) -> None:
        path = os.path.join(self.root, f"{stream}.jsonl")
        self._rotate_if_needed(path)
        record = dict(record)
        record.setdefault("ts", int(time.time()))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_to_jsonable(record), ensure_ascii=False) + "\n")
