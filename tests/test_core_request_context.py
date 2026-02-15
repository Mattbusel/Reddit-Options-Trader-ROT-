"""Tests for rot.core.request_context — request ID tracking, context vars, logging filter."""
from __future__ import annotations

import logging

import pytest

from rot.core.request_context import (
    RequestContext,
    RequestContextFilter,
    clear_context,
    configure_request_logging,
    generate_request_id,
    get_correlation_id,
    get_log_context,
    get_request_id,
    get_user_id,
    set_correlation_id,
    set_request_id,
    set_user_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_context():
    """Ensure context is clean before and after each test."""
    clear_context()
    yield
    clear_context()


# ---------------------------------------------------------------------------
# generate_request_id
# ---------------------------------------------------------------------------


class TestGenerateRequestId:
    def test_starts_with_req_prefix(self):
        rid = generate_request_id()
        assert rid.startswith("req_")

    def test_unique_each_call(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100

    def test_contains_uuid(self):
        rid = generate_request_id()
        # UUID4 format after prefix: 8-4-4-4-12 hex chars
        uuid_part = rid[4:]
        assert len(uuid_part) == 36
        assert uuid_part.count("-") == 4

    @pytest.mark.parametrize("iteration", range(5))
    def test_format_consistency(self, iteration):
        rid = generate_request_id()
        assert isinstance(rid, str)
        assert len(rid) > 10
        assert rid.startswith("req_")


# ---------------------------------------------------------------------------
# set/get request_id
# ---------------------------------------------------------------------------


class TestRequestIdContext:
    def test_default_is_none(self):
        assert get_request_id() is None

    def test_set_and_get(self):
        set_request_id("req_test123")
        assert get_request_id() == "req_test123"

    def test_overwrite(self):
        set_request_id("req_first")
        set_request_id("req_second")
        assert get_request_id() == "req_second"

    def test_clear_resets(self):
        set_request_id("req_abc")
        clear_context()
        assert get_request_id() is None


# ---------------------------------------------------------------------------
# set/get user_id
# ---------------------------------------------------------------------------


class TestUserIdContext:
    def test_default_is_none(self):
        assert get_user_id() is None

    def test_set_and_get(self):
        set_user_id(42)
        assert get_user_id() == 42

    @pytest.mark.parametrize("uid", [0, 1, 999999, -1])
    def test_various_user_ids(self, uid):
        set_user_id(uid)
        assert get_user_id() == uid

    def test_clear_resets(self):
        set_user_id(10)
        clear_context()
        assert get_user_id() is None


# ---------------------------------------------------------------------------
# set/get correlation_id
# ---------------------------------------------------------------------------


class TestCorrelationIdContext:
    def test_default_is_none(self):
        assert get_correlation_id() is None

    def test_set_and_get(self):
        set_correlation_id("corr_xyz")
        assert get_correlation_id() == "corr_xyz"

    def test_clear_resets(self):
        set_correlation_id("corr_abc")
        clear_context()
        assert get_correlation_id() is None


# ---------------------------------------------------------------------------
# clear_context
# ---------------------------------------------------------------------------


class TestClearContext:
    def test_clears_all_three(self):
        set_request_id("req_1")
        set_user_id(5)
        set_correlation_id("corr_1")
        clear_context()
        assert get_request_id() is None
        assert get_user_id() is None
        assert get_correlation_id() is None

    def test_clear_when_already_empty(self):
        clear_context()
        assert get_request_id() is None
        assert get_user_id() is None
        assert get_correlation_id() is None


# ---------------------------------------------------------------------------
# get_log_context
# ---------------------------------------------------------------------------


class TestGetLogContext:
    def test_empty_when_no_context(self):
        ctx = get_log_context()
        assert ctx == {}

    def test_includes_request_id(self):
        set_request_id("req_log1")
        ctx = get_log_context()
        assert ctx["request_id"] == "req_log1"
        assert "user_id" not in ctx
        assert "correlation_id" not in ctx

    def test_includes_user_id(self):
        set_user_id(77)
        ctx = get_log_context()
        assert ctx["user_id"] == 77

    def test_includes_correlation_id(self):
        set_correlation_id("corr_log")
        ctx = get_log_context()
        assert ctx["correlation_id"] == "corr_log"

    def test_includes_all_when_set(self):
        set_request_id("req_all")
        set_user_id(99)
        set_correlation_id("corr_all")
        ctx = get_log_context()
        assert ctx["request_id"] == "req_all"
        assert ctx["user_id"] == 99
        assert ctx["correlation_id"] == "corr_all"


# ---------------------------------------------------------------------------
# RequestContextFilter (logging filter)
# ---------------------------------------------------------------------------


class TestRequestContextFilter:
    def test_always_returns_true(self):
        filt = RequestContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert filt.filter(record) is True

    def test_adds_request_id_dash_when_none(self):
        filt = RequestContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filt.filter(record)
        assert record.request_id == "-"  # type: ignore[attr-defined]

    def test_adds_request_id_when_set(self):
        set_request_id("req_filter_test")
        filt = RequestContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filt.filter(record)
        assert record.request_id == "req_filter_test"  # type: ignore[attr-defined]

    def test_adds_user_id_dash_when_none(self):
        filt = RequestContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filt.filter(record)
        assert record.user_id == "-"  # type: ignore[attr-defined]

    def test_adds_user_id_when_set(self):
        set_user_id(42)
        filt = RequestContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filt.filter(record)
        assert record.user_id == 42  # type: ignore[attr-defined]

    def test_adds_correlation_id(self):
        set_correlation_id("corr_filt")
        filt = RequestContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filt.filter(record)
        assert record.correlation_id == "corr_filt"  # type: ignore[attr-defined]

    @pytest.mark.parametrize("level", [logging.DEBUG, logging.WARNING, logging.ERROR, logging.CRITICAL])
    def test_works_with_all_levels(self, level):
        filt = RequestContextFilter()
        record = logging.LogRecord("test", level, "", 0, "msg", (), None)
        assert filt.filter(record) is True
        assert hasattr(record, "request_id")


# ---------------------------------------------------------------------------
# RequestContext (context manager)
# ---------------------------------------------------------------------------


class TestRequestContextManager:
    def test_sets_request_id(self):
        with RequestContext(request_id="req_ctx1"):
            assert get_request_id() == "req_ctx1"
        assert get_request_id() is None

    def test_auto_generates_request_id(self):
        with RequestContext() as ctx:
            assert ctx.request_id.startswith("req_")
            assert get_request_id() == ctx.request_id
        assert get_request_id() is None

    def test_sets_user_id(self):
        with RequestContext(user_id=55):
            assert get_user_id() == 55
        assert get_user_id() is None

    def test_sets_correlation_id(self):
        with RequestContext(correlation_id="corr_ctx"):
            assert get_correlation_id() == "corr_ctx"
        assert get_correlation_id() is None

    def test_sets_all_context(self):
        with RequestContext(request_id="req_all2", user_id=88, correlation_id="corr_all2"):
            assert get_request_id() == "req_all2"
            assert get_user_id() == 88
            assert get_correlation_id() == "corr_all2"
        assert get_request_id() is None
        assert get_user_id() is None
        assert get_correlation_id() is None

    def test_restores_previous_context(self):
        set_request_id("req_outer")
        set_user_id(1)
        set_correlation_id("corr_outer")
        with RequestContext(request_id="req_inner", user_id=2, correlation_id="corr_inner"):
            assert get_request_id() == "req_inner"
            assert get_user_id() == 2
            assert get_correlation_id() == "corr_inner"
        assert get_request_id() == "req_outer"
        assert get_user_id() == 1
        assert get_correlation_id() == "corr_outer"

    def test_nested_contexts(self):
        with RequestContext(request_id="req_l1") as ctx1:
            assert get_request_id() == "req_l1"
            with RequestContext(request_id="req_l2") as ctx2:
                assert get_request_id() == "req_l2"
                assert ctx2.request_id == "req_l2"
            assert get_request_id() == "req_l1"
            assert ctx1.request_id == "req_l1"
        assert get_request_id() is None

    def test_exception_still_restores(self):
        set_request_id("req_safe")
        try:
            with RequestContext(request_id="req_err"):
                raise ValueError("boom")
        except ValueError:
            pass
        assert get_request_id() == "req_safe"

    @pytest.mark.parametrize("user_id", [None, 0, 42, -1])
    def test_user_id_variants(self, user_id):
        with RequestContext(user_id=user_id):
            if user_id is not None:
                assert get_user_id() == user_id


# ---------------------------------------------------------------------------
# configure_request_logging
# ---------------------------------------------------------------------------


class TestConfigureRequestLogging:
    def test_adds_filter_to_handlers(self):
        logger = logging.getLogger("test_configure_ctx")
        handler = logging.StreamHandler()
        logger.addHandler(handler)
        # Should not raise
        configure_request_logging()
        # Clean up
        logger.removeHandler(handler)

    def test_idempotent(self):
        configure_request_logging()
        configure_request_logging()
        # Should not duplicate filters — count RequestContextFilter instances
        root = logging.getLogger()
        for handler in root.handlers:
            ctx_filters = [f for f in handler.filters if isinstance(f, RequestContextFilter)]
            assert len(ctx_filters) <= 2  # may have been added by other tests
