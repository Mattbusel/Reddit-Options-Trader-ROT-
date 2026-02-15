"""
Comprehensive tests for SeenStore module.

Modules tested:
- rot.ingest.seen_store

Coverage:
- SeenRecord dataclass
- SeenStore initialization
- Load from JSON file
- Save to JSON file
- Get seen record
- Update seen record
- is_changed detection
- Old entry eviction
- Size capping (MAX_SIZE)
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from rot.ingest.seen_store import SeenRecord, SeenStore


class TestSeenRecord:
    def test_seen_record_creation(self):
        """SeenRecord dataclass can be created."""
        record = SeenRecord(score=100, num_comments=50, last_seen_ts=1234567890)
        assert record.score == 100
        assert record.num_comments == 50
        assert record.last_seen_ts == 1234567890


class TestSeenStoreInit:
    def test_seen_store_creation(self):
        """SeenStore can be created with default path."""
        store = SeenStore()
        assert store.path == Path("storage/seen_posts.json")
        assert store.max_age_s == 2 * 24 * 3600
        assert store._loaded is False

    def test_seen_store_custom_path(self):
        """SeenStore can be created with custom path."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            path = f.name
        try:
            store = SeenStore(path=path)
            assert store.path == Path(path)
        finally:
            Path(path).unlink(missing_ok=True)


class TestSeenStoreLoadSave:
    def test_load_nonexistent_file(self):
        """Loading nonexistent file does not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.json"
            store = SeenStore(path=str(path))
            store.load()
            assert store._loaded is True
            assert len(store._data) == 0

    def test_load_valid_file(self):
        """Loading valid JSON file populates data."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            data = {
                "post1": {"score": 100, "num_comments": 50, "last_seen_ts": 1234567890},
                "post2": {"score": 200, "num_comments": 75, "last_seen_ts": 1234567900},
            }
            json.dump(data, f)
            path = f.name
        try:
            store = SeenStore(path=path)
            store.load()
            assert len(store._data) == 2
            assert store._data["post1"].score == 100
            assert store._data["post2"].num_comments == 75
        finally:
            Path(path).unlink()

    def test_save_creates_directory(self):
        """Save creates parent directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "seen.json"
            store = SeenStore(path=str(path))
            store.update("post1", 100, 50, int(time.time()))
            store.save()
            assert path.exists()
            assert path.parent.exists()


class TestSeenStoreGetUpdate:
    def test_get_nonexistent_post(self):
        """Getting nonexistent post returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"))
            result = store.get("nonexistent")
            assert result is None

    def test_update_new_post(self):
        """Updating new post creates record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"))
            ts = int(time.time())
            store.update("post1", 100, 50, ts)
            assert "post1" in store._data
            assert store._data["post1"].score == 100


class TestSeenStoreIsChanged:
    def test_is_changed_new_post(self):
        """New posts are considered changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"))
            assert store.is_changed("new_post", 100, 50) is True

    def test_is_changed_same_values(self):
        """Posts with same values are not changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"))
            ts = int(time.time())
            store.update("post1", 100, 50, ts)
            assert store.is_changed("post1", 100, 50) is False

    def test_is_changed_score_changed(self):
        """Posts with different score are changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"))
            ts = int(time.time())
            store.update("post1", 100, 50, ts)
            assert store.is_changed("post1", 200, 50) is True


class TestSeenStoreEviction:
    def test_evict_old_entries(self):
        """Old entries are evicted based on max_age."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"), max_age_s=100)
            now = int(time.time())
            store.update("old_post", 100, 50, now - 200)
            store.update("recent_post", 200, 75, now)
            store.save()
            assert "old_post" not in store._data
            assert "recent_post" in store._data

    def test_size_capping(self):
        """Entries are capped at MAX_SIZE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SeenStore(path=str(Path(tmpdir) / "seen.json"))
            now = int(time.time())
            for i in range(SeenStore.MAX_SIZE + 100):
                store.update(f"post{i}", 100, 50, now + i)
            store.save()
            assert len(store._data) == SeenStore.MAX_SIZE
