"""Tests for rot.core.logging — JsonlLogger, sanitize_for_log, SanitizingLogFilter, market cache cleanup."""
from __future__ import annotations

import json
import logging
import os
import time

import pytest

from rot.core.logging import (
    JsonlLogger,
    SanitizingLogFilter,
    _to_jsonable,
    cleanup_market_cache,
    sanitize_for_log,
)


# ---------------------------------------------------------------------------
# sanitize_for_log
# ---------------------------------------------------------------------------


class TestSanitizeForLog:
    def test_plain_string(self):
        assert sanitize_for_log("hello world") == "hello world"

    def test_newlines_replaced(self):
        result = sanitize_for_log("line1\nline2\rline3")
        assert "\n" not in result
        assert "\r" not in result
        assert "line1" in result and "line2" in result

    def test_ansi_codes_removed(self):
        result = sanitize_for_log("\x1b[31mRED\x1b[0m")
        assert "\x1b" not in result
        assert "RED" in result

    def test_control_chars_removed(self):
        result = sanitize_for_log("hello\x00world\x01test")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "hello" in result

    def test_truncation_at_500(self):
        long_string = "x" * 1000
        result = sanitize_for_log(long_string)
        assert len(result) <= 500
        assert result.endswith("...")

    def test_under_500_not_truncated(self):
        short = "x" * 200
        assert sanitize_for_log(short) == short

    def test_non_string_converted(self):
        result = sanitize_for_log(12345)
        assert result == "12345"

    @pytest.mark.parametrize("input_val,should_not_contain", [
        ("line1\nline2", "\n"),
        ("line1\rline2", "\r"),
        ("\x1b[31mred\x1b[0m", "\x1b"),
        ("null\x00byte", "\x00"),
    ])
    def test_injection_variants(self, input_val, should_not_contain):
        result = sanitize_for_log(input_val)
        assert should_not_contain not in result

    def test_empty_string(self):
        assert sanitize_for_log("") == ""

    @pytest.mark.parametrize("val", [None, 42, 3.14, True, [], {}])
    def test_non_string_types(self, val):
        result = sanitize_for_log(val)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _to_jsonable
# ---------------------------------------------------------------------------


class TestToJsonable:
    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert _to_jsonable(d) == d

    def test_list_passthrough(self):
        lst = [1, 2, 3]
        assert _to_jsonable(lst) == lst

    def test_nested_dict(self):
        d = {"a": {"b": [1, 2]}}
        assert _to_jsonable(d) == d

    def test_tuple_to_list(self):
        result = _to_jsonable((1, 2, 3))
        assert result == [1, 2, 3]

    def test_primitive_passthrough(self):
        assert _to_jsonable(42) == 42
        assert _to_jsonable("hello") == "hello"
        assert _to_jsonable(3.14) == 3.14

    def test_dataclass_converted(self):
        from dataclasses import dataclass

        @dataclass
        class Foo:
            x: int = 1
            y: str = "bar"

        result = _to_jsonable(Foo())
        assert result == {"x": 1, "y": "bar"}


# ---------------------------------------------------------------------------
# JsonlLogger
# ---------------------------------------------------------------------------


class TestJsonlLogger:
    def test_write_creates_file(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        logger.write("test_stream", {"key": "value"})
        path = tmp_path / "test_stream.jsonl"
        assert path.exists()

    def test_write_valid_json(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        logger.write("test_stream", {"foo": "bar"})
        path = tmp_path / "test_stream.jsonl"
        line = path.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["foo"] == "bar"

    def test_write_adds_ts(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        logger.write("test_stream", {"x": 1})
        path = tmp_path / "test_stream.jsonl"
        data = json.loads(path.read_text(encoding="utf-8").strip())
        assert "ts" in data
        assert isinstance(data["ts"], int)

    def test_write_preserves_existing_ts(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        logger.write("test_stream", {"x": 1, "ts": 999})
        path = tmp_path / "test_stream.jsonl"
        data = json.loads(path.read_text(encoding="utf-8").strip())
        assert data["ts"] == 999

    def test_write_multiple_records(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        for i in range(5):
            logger.write("multi", {"i": i})
        path = tmp_path / "multi.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5
        for idx, line in enumerate(lines):
            assert json.loads(line)["i"] == idx

    def test_different_streams(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        logger.write("stream_a", {"a": 1})
        logger.write("stream_b", {"b": 2})
        assert (tmp_path / "stream_a.jsonl").exists()
        assert (tmp_path / "stream_b.jsonl").exists()

    def test_rotate_if_needed_no_rotation(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        path = str(tmp_path / "small.jsonl")
        # Create small file
        with open(path, "w") as f:
            f.write('{"ts":1}\n')
        logger._rotate_if_needed(path)
        assert os.path.exists(path)
        assert not os.path.exists(f"{path}.1")

    def test_rotate_if_needed_rotates_large_file(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        logger.MAX_FILE_BYTES = 100  # Small threshold
        path = str(tmp_path / "big.jsonl")
        with open(path, "w") as f:
            f.write("x" * 200 + "\n")
        logger._rotate_if_needed(path)
        assert os.path.exists(f"{path}.1")

    def test_rotate_method(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        now = int(time.time())
        old_ts = now - 10 * 86400  # 10 days old
        # Write old and new records
        path = tmp_path / "rot.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": old_ts, "old": True}) + "\n")
            f.write(json.dumps({"ts": now, "new": True}) + "\n")
        results = logger.rotate(max_age_days=3)
        # Old should be removed
        assert results.get("rot.jsonl", 0) >= 1
        kept = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(kept) == 1
        assert json.loads(kept[0])["new"] is True

    def test_rotate_empty_file(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        results = logger.rotate(max_age_days=3)
        assert "empty.jsonl" in results

    def test_rotate_malformed_json(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        path = tmp_path / "bad.jsonl"
        path.write_text("not json\n")
        results = logger.rotate(max_age_days=3)
        assert results.get("bad.jsonl", 0) >= 1

    @pytest.mark.parametrize("max_age", [1, 3, 7, 30])
    def test_rotate_with_various_ages(self, tmp_path, max_age):
        logger = JsonlLogger(root=str(tmp_path))
        now = int(time.time())
        path = tmp_path / "age.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": now - (max_age + 1) * 86400}) + "\n")
            f.write(json.dumps({"ts": now}) + "\n")
        logger.rotate(max_age_days=max_age)
        kept = path.read_text().strip().split("\n")
        assert len(kept) == 1

    def test_rotate_deletes_backup_files(self, tmp_path):
        logger = JsonlLogger(root=str(tmp_path))
        # Create backup file
        backup = tmp_path / "test.jsonl.1"
        backup.write_text("old backup")
        logger.rotate(max_age_days=3)
        assert not backup.exists()


# ---------------------------------------------------------------------------
# cleanup_market_cache
# ---------------------------------------------------------------------------


class TestCleanupMarketCache:
    def test_no_cache_file(self, tmp_path):
        result = cleanup_market_cache(str(tmp_path))
        assert result == 0

    def test_empty_cache(self, tmp_path):
        cache_path = tmp_path / "market_cache.json"
        cache_path.write_text("{}")
        result = cleanup_market_cache(str(tmp_path))
        assert result == 0

    def test_evicts_stale_entries(self, tmp_path):
        now = time.time()
        cache = {
            "TSLA": {"ts": now, "price": 250},
            "OLD": {"ts": now - 30 * 86400, "price": 100},
        }
        cache_path = tmp_path / "market_cache.json"
        cache_path.write_text(json.dumps(cache))
        result = cleanup_market_cache(str(tmp_path), max_age_days=7)
        assert result == 1
        remaining = json.loads(cache_path.read_text())
        assert "TSLA" in remaining
        assert "OLD" not in remaining

    def test_keeps_fresh_entries(self, tmp_path):
        now = time.time()
        cache = {"TSLA": {"ts": now, "price": 250}}
        cache_path = tmp_path / "market_cache.json"
        cache_path.write_text(json.dumps(cache))
        result = cleanup_market_cache(str(tmp_path), max_age_days=7)
        assert result == 0

    def test_invalid_json(self, tmp_path):
        cache_path = tmp_path / "market_cache.json"
        cache_path.write_text("not json")
        result = cleanup_market_cache(str(tmp_path))
        assert result == 0

    def test_non_dict_json(self, tmp_path):
        cache_path = tmp_path / "market_cache.json"
        cache_path.write_text("[1,2,3]")
        result = cleanup_market_cache(str(tmp_path))
        assert result == 0

    @pytest.mark.parametrize("max_age", [1, 7, 30])
    def test_various_max_ages(self, tmp_path, max_age):
        now = time.time()
        cache = {
            "FRESH": {"ts": now, "price": 100},
            "STALE": {"ts": now - (max_age + 1) * 86400, "price": 50},
        }
        cache_path = tmp_path / "market_cache.json"
        cache_path.write_text(json.dumps(cache))
        result = cleanup_market_cache(str(tmp_path), max_age_days=max_age)
        assert result == 1


# ---------------------------------------------------------------------------
# SanitizingLogFilter
# ---------------------------------------------------------------------------


class TestSanitizingLogFilter:
    def test_filter_returns_true(self):
        filt = SanitizingLogFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert filt.filter(record) is True

    def test_sanitizes_msg(self):
        filt = SanitizingLogFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "line1\nline2", (), None)
        filt.filter(record)
        assert "\n" not in record.msg

    def test_sanitizes_string_args(self):
        filt = SanitizingLogFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg: %s", ("bad\ninput",), None)
        filt.filter(record)
        if isinstance(record.args, tuple):
            for arg in record.args:
                if isinstance(arg, str):
                    assert "\n" not in arg

    def test_non_string_args_preserved(self):
        filt = SanitizingLogFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "count: %d", (42,), None)
        filt.filter(record)
        assert record.args == (42,)

    def test_empty_args(self):
        filt = SanitizingLogFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "no args", None, None)
        filt.filter(record)
        assert record.msg == "no args"

    @pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR])
    def test_works_all_levels(self, level):
        filt = SanitizingLogFilter()
        record = logging.LogRecord("test", level, "", 0, "test\nmsg", (), None)
        assert filt.filter(record) is True
        assert "\n" not in record.msg
