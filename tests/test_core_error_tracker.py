from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from rot.core.error_tracker import ErrorTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracker(tmp_path):
    """Create an ErrorTracker that writes to a temp directory."""
    return ErrorTracker(log_dir=tmp_path)


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read_log_lines(tracker: ErrorTracker) -> list[dict]:
    """Read all JSON lines from today's log file."""
    log_file = tracker._get_log_file()
    if not log_file.exists():
        return []
    lines = []
    with open(log_file, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


# ===================================================================
# capture_exception
# ===================================================================

class TestCaptureException:

    @pytest.mark.asyncio
    @patch("rot.core.request_context.get_request_id", return_value="req_test123")
    @patch("rot.core.request_context.get_user_id", return_value=42)
    async def test_returns_error_id(self, mock_uid, mock_rid, tracker):
        error_id = tracker.capture_exception(ValueError("test error"))
        assert error_id.startswith("err_")

    @patch("rot.core.request_context.get_request_id", return_value="req_abc")
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_writes_to_log_file(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(RuntimeError("boom"))
        lines = _read_log_lines(tracker)
        assert len(lines) == 1
        assert lines[0]["type"] == "RuntimeError"
        assert lines[0]["message"] == "boom"
        assert lines[0]["request_id"] == "req_abc"

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=99)
    def test_captures_context(self, mock_uid, mock_rid, tracker):
        ctx = {"endpoint": "/api/test", "method": "GET"}
        tracker.capture_exception(ValueError("ctx test"), context=ctx)
        lines = _read_log_lines(tracker)
        assert lines[0]["context"]["endpoint"] == "/api/test"
        assert lines[0]["user_id"] == 99

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_captures_tags(self, mock_uid, mock_rid, tracker):
        tags = {"module": "ingest", "source": "reddit"}
        tracker.capture_exception(TypeError("tag test"), tags=tags)
        lines = _read_log_lines(tracker)
        assert lines[0]["tags"]["module"] == "ingest"
        assert lines[0]["tags"]["source"] == "reddit"

    @pytest.mark.parametrize("level", ["error", "warning", "critical"])
    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_level_is_recorded(self, mock_uid, mock_rid, tracker, level):
        tracker.capture_exception(ValueError("level test"), level=level)
        lines = _read_log_lines(tracker)
        assert lines[0]["level"] == level

    @pytest.mark.parametrize("exc_class,exc_msg", [
        (ValueError, "bad value"),
        (TypeError, "wrong type"),
        (RuntimeError, "runtime fail"),
        (IOError, "io problem"),
        (ZeroDivisionError, "division by zero"),
        (AttributeError, "no attribute"),
        (IndexError, "list index"),
        (FileNotFoundError, "no such file"),
        (PermissionError, "access denied"),
    ])
    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_various_exception_types(self, mock_uid, mock_rid, tracker,
                                     exc_class, exc_msg):
        error_id = tracker.capture_exception(exc_class(exc_msg))
        assert error_id.startswith("err_")
        lines = _read_log_lines(tracker)
        assert lines[-1]["type"] == exc_class.__name__
        assert lines[-1]["message"] == str(exc_class(exc_msg))

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_key_error_type(self, mock_uid, mock_rid, tracker):
        error_id = tracker.capture_exception(KeyError("missing_key"))
        assert error_id.startswith("err_")
        lines = _read_log_lines(tracker)
        assert lines[-1]["type"] == "KeyError"

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_stack_trace_captured(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("trace test"))
        lines = _read_log_lines(tracker)
        assert "stack_trace" in lines[0]

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_timestamp_is_iso_format(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("ts test"))
        lines = _read_log_lines(tracker)
        # Should parse without error
        datetime.fromisoformat(lines[0]["timestamp"])

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_updates_error_counts(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("one"))
        tracker.capture_exception(ValueError("two"))
        tracker.capture_exception(TypeError("three"))

        rate = tracker.get_error_rate()
        assert rate["ValueError"] == 2
        assert rate["TypeError"] == 1

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_none_context_and_tags(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("none test"), context=None, tags=None)
        lines = _read_log_lines(tracker)
        assert lines[0]["context"] == {}
        assert lines[0]["tags"] == {}

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_multiple_exceptions_appended(self, mock_uid, mock_rid, tracker):
        for i in range(5):
            tracker.capture_exception(ValueError(f"error {i}"))
        lines = _read_log_lines(tracker)
        assert len(lines) == 5


# ===================================================================
# capture_message
# ===================================================================

class TestCaptureMessage:

    @patch("rot.core.request_context.get_request_id", return_value="req_msg")
    @patch("rot.core.request_context.get_user_id", return_value=10)
    def test_returns_event_id(self, mock_uid, mock_rid, tracker):
        event_id = tracker.capture_message("test message")
        assert event_id.startswith("msg_")

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_writes_to_log_file(self, mock_uid, mock_rid, tracker):
        tracker.capture_message("hello world", level="warning")
        lines = _read_log_lines(tracker)
        assert len(lines) == 1
        assert lines[0]["message"] == "hello world"
        assert lines[0]["level"] == "warning"

    @pytest.mark.parametrize("level", ["info", "warning", "error"])
    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_level_recorded(self, mock_uid, mock_rid, tracker, level):
        tracker.capture_message("msg", level=level)
        lines = _read_log_lines(tracker)
        assert lines[0]["level"] == level

    @patch("rot.core.request_context.get_request_id", return_value="req_c")
    @patch("rot.core.request_context.get_user_id", return_value=5)
    def test_captures_context_and_tags(self, mock_uid, mock_rid, tracker):
        ctx = {"action": "test"}
        tags = {"service": "web"}
        tracker.capture_message("ctx msg", context=ctx, tags=tags)
        lines = _read_log_lines(tracker)
        assert lines[0]["context"]["action"] == "test"
        assert lines[0]["tags"]["service"] == "web"
        assert lines[0]["request_id"] == "req_c"
        assert lines[0]["user_id"] == 5


# ===================================================================
# get_error_stats
# ===================================================================

class TestGetErrorStats:

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_returns_stats_structure(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("stat test"))
        stats = tracker.get_error_stats(hours=24)

        assert "total_errors" in stats
        assert "by_type" in stats
        assert "by_level" in stats
        assert "by_endpoint" in stats
        assert "recent_errors" in stats

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_counts_errors(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("one"))
        tracker.capture_exception(TypeError("two"))
        tracker.capture_exception(ValueError("three"))

        stats = tracker.get_error_stats(hours=24)
        assert stats["total_errors"] == 3
        assert stats["by_type"]["ValueError"] == 2
        assert stats["by_type"]["TypeError"] == 1

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_aggregates_by_level(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("e"), level="error")
        tracker.capture_exception(ValueError("w"), level="warning")
        tracker.capture_exception(ValueError("c"), level="critical")

        stats = tracker.get_error_stats(hours=24)
        assert stats["by_level"]["error"] == 1
        assert stats["by_level"]["warning"] == 1
        assert stats["by_level"]["critical"] == 1

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_aggregates_by_endpoint_tag(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(
            ValueError("ep1"),
            tags={"endpoint": "/api/signals"},
        )
        tracker.capture_exception(
            ValueError("ep2"),
            tags={"endpoint": "/api/signals"},
        )

        stats = tracker.get_error_stats(hours=24)
        assert stats["by_endpoint"]["/api/signals"] == 2

    def test_empty_returns_zero_totals(self, tracker):
        stats = tracker.get_error_stats(hours=24)
        assert stats["total_errors"] == 0
        assert stats["by_type"] == {}
        assert stats["recent_errors"] == []

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_recent_errors_capped_at_50(self, mock_uid, mock_rid, tracker):
        for i in range(60):
            tracker.capture_exception(ValueError(f"err {i}"))

        stats = tracker.get_error_stats(hours=24)
        assert len(stats["recent_errors"]) == 50

    @patch("rot.core.request_context.get_request_id", return_value="req_stat")
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_recent_errors_contain_request_id(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("rid test"))

        stats = tracker.get_error_stats(hours=24)
        assert stats["recent_errors"][0]["request_id"] == "req_stat"

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_recent_errors_sorted_newest_first(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("first"))
        tracker.capture_exception(ValueError("second"))

        stats = tracker.get_error_stats(hours=24)
        first_ts = stats["recent_errors"][0]["timestamp"]
        second_ts = stats["recent_errors"][1]["timestamp"]
        assert first_ts >= second_ts


# ===================================================================
# get_error_rate
# ===================================================================

class TestGetErrorRate:

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_tracks_counts_by_type(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("v1"))
        tracker.capture_exception(ValueError("v2"))
        tracker.capture_exception(TypeError("t1"))

        rate = tracker.get_error_rate()
        assert rate["ValueError"] == 2
        assert rate["TypeError"] == 1

    def test_empty_rate(self, tracker):
        rate = tracker.get_error_rate()
        assert rate == {}

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_reset_after_hour(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("before reset"))
        assert tracker.get_error_rate()["ValueError"] == 1

        # Force the last_reset to be over an hour ago
        tracker._last_reset = datetime.utcnow() - timedelta(hours=2)
        rate = tracker.get_error_rate()
        # After reset, counts should be cleared
        assert rate == {}

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_no_reset_within_hour(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError("within hour"))
        # _last_reset should be recent, so no reset
        rate = tracker.get_error_rate()
        assert rate["ValueError"] == 1


# ===================================================================
# cleanup_old_logs
# ===================================================================

class TestCleanupOldLogs:

    def test_deletes_old_log_files(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)

        # Create an old log file (40 days ago)
        old_date = datetime.utcnow() - timedelta(days=40)
        old_file = tmp_path / f"errors_{old_date.strftime('%Y%m%d')}.jsonl"
        old_file.write_text("{}\n")

        deleted = tracker.cleanup_old_logs(days=30)
        assert deleted >= 1
        assert not old_file.exists()

    def test_keeps_recent_log_files(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)

        recent_date = datetime.utcnow() - timedelta(days=5)
        recent_file = tmp_path / f"errors_{recent_date.strftime('%Y%m%d')}.jsonl"
        recent_file.write_text("{}\n")

        deleted = tracker.cleanup_old_logs(days=30)
        assert deleted == 0
        assert recent_file.exists()

    def test_skips_non_matching_filenames(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)

        bad_file = tmp_path / "errors_notadate.jsonl"
        bad_file.write_text("{}\n")

        deleted = tracker.cleanup_old_logs(days=1)
        assert deleted == 0
        assert bad_file.exists()

    def test_no_files(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)
        deleted = tracker.cleanup_old_logs(days=30)
        assert deleted == 0

    @pytest.mark.parametrize("days_old,keep_days,expect_deleted", [
        (5, 30, False),
        (31, 30, True),
        (60, 30, True),
        (1, 7, False),
        (10, 7, True),
    ])
    def test_parametrized_cleanup(self, tmp_path, days_old, keep_days,
                                  expect_deleted):
        tracker = ErrorTracker(log_dir=tmp_path)

        file_date = datetime.utcnow() - timedelta(days=days_old)
        log_file = tmp_path / f"errors_{file_date.strftime('%Y%m%d')}.jsonl"
        log_file.write_text("{}\n")

        deleted = tracker.cleanup_old_logs(days=keep_days)
        if expect_deleted:
            assert deleted >= 1
        else:
            assert deleted == 0


# ===================================================================
# _get_log_file
# ===================================================================

class TestGetLogFile:

    def test_returns_path(self, tracker):
        path = tracker._get_log_file()
        assert isinstance(path, Path)
        assert path.name.startswith("errors_")
        assert path.suffix == ".jsonl"

    def test_path_in_log_dir(self, tracker):
        path = tracker._get_log_file()
        assert path.parent == tracker.log_dir

    def test_date_in_filename(self, tracker):
        path = tracker._get_log_file()
        today = datetime.utcnow().strftime("%Y%m%d")
        assert today in path.name


# ===================================================================
# _get_recent_log_files
# ===================================================================

class TestGetRecentLogFiles:

    def test_returns_existing_files(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)

        today = datetime.utcnow().strftime("%Y%m%d")
        today_file = tmp_path / f"errors_{today}.jsonl"
        today_file.write_text("{}\n")

        files = tracker._get_recent_log_files(hours=24)
        assert len(files) >= 1
        assert today_file in files

    def test_returns_empty_for_no_files(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)
        files = tracker._get_recent_log_files(hours=24)
        assert files == []

    def test_includes_yesterday(self, tmp_path):
        tracker = ErrorTracker(log_dir=tmp_path)

        yesterday = datetime.utcnow() - timedelta(days=1)
        yest_file = tmp_path / f"errors_{yesterday.strftime('%Y%m%d')}.jsonl"
        yest_file.write_text("{}\n")

        files = tracker._get_recent_log_files(hours=48)
        assert yest_file in files


# ===================================================================
# Module-level convenience functions
# ===================================================================

class TestModuleFunctions:

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_capture_exception_convenience(self, mock_uid, mock_rid):
        from rot.core.error_tracker import capture_exception as cap_exc
        error_id = cap_exc(ValueError("conv test"))
        assert error_id.startswith("err_")

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_capture_message_convenience(self, mock_uid, mock_rid):
        from rot.core.error_tracker import capture_message as cap_msg
        event_id = cap_msg("conv message")
        assert event_id.startswith("msg_")

    def test_get_error_tracker_returns_instance(self):
        from rot.core.error_tracker import get_error_tracker
        tracker = get_error_tracker()
        assert isinstance(tracker, ErrorTracker)

    def test_get_error_tracker_is_singleton(self):
        from rot.core.error_tracker import get_error_tracker
        t1 = get_error_tracker()
        t2 = get_error_tracker()
        assert t1 is t2


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_empty_exception_message(self, mock_uid, mock_rid, tracker):
        error_id = tracker.capture_exception(ValueError(""))
        assert error_id.startswith("err_")
        lines = _read_log_lines(tracker)
        assert lines[0]["message"] == ""

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_unicode_exception_message(self, mock_uid, mock_rid, tracker):
        error_id = tracker.capture_exception(ValueError("unicode test"))
        assert error_id.startswith("err_")

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_nested_context(self, mock_uid, mock_rid, tracker):
        ctx = {"outer": {"inner": {"deep": True}}}
        tracker.capture_exception(ValueError("nested"), context=ctx)
        lines = _read_log_lines(tracker)
        assert lines[0]["context"]["outer"]["inner"]["deep"] is True

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_large_context(self, mock_uid, mock_rid, tracker):
        ctx = {f"key_{i}": f"value_{i}" for i in range(100)}
        tracker.capture_exception(ValueError("large"), context=ctx)
        lines = _read_log_lines(tracker)
        assert len(lines[0]["context"]) == 100

    @patch("rot.core.request_context.get_request_id", return_value=None)
    @patch("rot.core.request_context.get_user_id", return_value=None)
    def test_special_chars_in_message(self, mock_uid, mock_rid, tracker):
        tracker.capture_exception(ValueError('msg with "quotes" and \t tabs'))
        lines = _read_log_lines(tracker)
        assert "quotes" in lines[0]["message"]
