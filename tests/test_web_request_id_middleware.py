"""
Comprehensive tests for request ID middleware.

Modules tested:
- rot.web.request_id_middleware

Coverage:
- RequestIDMiddleware (request ID generation, propagation, response headers)
- Request ID header handling (accepts client-provided IDs)
- Correlation ID tracking for distributed tracing
- User ID extraction from request state
- Request timing tracking
- Context cleanup after request
- get_client_ip helper function
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from rot.web.request_id_middleware import RequestIDMiddleware, get_client_ip


class TestRequestIDMiddleware:
    @pytest.fixture
    def app(self):
        """Create FastAPI app with RequestID middleware."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        def test_route():
            return {"status": "ok"}

        @app.get("/with_user")
        def user_route(request: Request):
            # Simulate user in request state
            request.state.user = {"id": 123, "email": "test@example.com"}
            return {"status": "ok"}

        return app

    def test_generates_request_id_if_not_provided(self, app):
        """Middleware generates request ID if not provided by client."""
        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Check format: req_<uuid>
        request_id = response.headers["X-Request-ID"]
        assert request_id.startswith("req_")
        assert len(request_id) > 10

    def test_accepts_client_provided_request_id(self, app):
        """Middleware accepts and propagates client-provided request ID."""
        client = TestClient(app)
        client_request_id = "client_provided_id_123"
        response = client.get("/test", headers={"X-Request-ID": client_request_id})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == client_request_id

    def test_accepts_correlation_id(self, app):
        """Middleware accepts and propagates correlation ID for distributed tracing."""
        client = TestClient(app)
        correlation_id = "correlation_abc_456"
        response = client.get(
            "/test", headers={"X-Correlation-ID": correlation_id}
        )

        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == correlation_id

    def test_adds_response_time_header(self, app):
        """Middleware adds X-Response-Time header."""
        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Response-Time" in response.headers
        # Format: "123ms"
        response_time = response.headers["X-Response-Time"]
        assert response_time.endswith("ms")
        # Check it's a number
        assert int(response_time[:-2]) >= 0

    @patch("rot.web.request_id_middleware.set_request_id")
    def test_sets_request_context(self, mock_set_request_id, app):
        """Middleware sets request context variables."""
        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert mock_set_request_id.called
        # Check request ID was set
        request_id = mock_set_request_id.call_args[0][0]
        assert request_id.startswith("req_")

    @patch("rot.web.request_id_middleware.set_correlation_id")
    def test_sets_correlation_context(self, mock_set_correlation, app):
        """Middleware sets correlation context when header present."""
        client = TestClient(app)
        correlation_id = "trace_xyz_789"
        response = client.get(
            "/test", headers={"X-Correlation-ID": correlation_id}
        )

        assert response.status_code == 200
        assert mock_set_correlation.called
        assert mock_set_correlation.call_args[0][0] == correlation_id

    @patch("rot.web.request_id_middleware.set_correlation_id")
    def test_does_not_set_correlation_without_header(
        self, mock_set_correlation, app
    ):
        """Middleware does not set correlation context without header."""
        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert not mock_set_correlation.called

    @patch("rot.web.request_id_middleware.clear_context")
    def test_clears_context_after_request(self, mock_clear_context, app):
        """Middleware clears context after request completes."""
        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert mock_clear_context.called

    @patch("rot.web.request_id_middleware.clear_context")
    def test_clears_context_even_on_error(self, mock_clear_context):
        """Middleware clears context even if request fails."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/error")
        def error_route():
            raise ValueError("Test error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/error")

        assert response.status_code == 500
        assert mock_clear_context.called

    def test_all_headers_present_simultaneously(self, app):
        """All headers can be present simultaneously."""
        client = TestClient(app)
        response = client.get(
            "/test",
            headers={
                "X-Request-ID": "custom_req_id",
                "X-Correlation-ID": "custom_corr_id",
            },
        )

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "custom_req_id"
        assert response.headers["X-Correlation-ID"] == "custom_corr_id"
        assert "X-Response-Time" in response.headers

    def test_request_id_unique_per_request(self, app):
        """Each request gets a unique request ID."""
        client = TestClient(app)
        response1 = client.get("/test")
        response2 = client.get("/test")

        assert response1.status_code == 200
        assert response2.status_code == 200
        # Different request IDs
        assert response1.headers["X-Request-ID"] != response2.headers["X-Request-ID"]

    def test_response_time_is_reasonable(self, app):
        """Response time is reasonable (< 5 seconds for simple endpoint)."""
        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        response_time_ms = int(response.headers["X-Response-Time"][:-2])
        # Should be fast for simple endpoint
        assert response_time_ms < 5000


class TestGetClientIp:
    def test_get_client_ip_from_x_forwarded_for(self):
        """get_client_ip extracts IP from X-Forwarded-For header."""
        request = Mock(spec=Request)
        request.headers.get.side_effect = lambda key: {
            "X-Forwarded-For": "203.0.113.1, 198.51.100.1, 192.0.2.1"
        }.get(key)
        request.client = None

        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_get_client_ip_from_x_forwarded_for_single(self):
        """get_client_ip handles single IP in X-Forwarded-For."""
        request = Mock(spec=Request)
        request.headers.get.side_effect = lambda key: {
            "X-Forwarded-For": "203.0.113.1"
        }.get(key)
        request.client = None

        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_get_client_ip_from_x_real_ip(self):
        """get_client_ip extracts IP from X-Real-IP header."""
        request = Mock(spec=Request)
        request.headers.get.side_effect = lambda key: {
            "X-Real-IP": "198.51.100.1"
        }.get(key)
        request.client = None

        ip = get_client_ip(request)
        assert ip == "198.51.100.1"

    def test_get_client_ip_from_direct_connection(self):
        """get_client_ip falls back to direct connection IP."""
        request = Mock(spec=Request)
        request.headers.get.return_value = None
        request.client = Mock()
        request.client.host = "192.0.2.1"

        ip = get_client_ip(request)
        assert ip == "192.0.2.1"

    def test_get_client_ip_no_client(self):
        """get_client_ip returns 'unknown' when no IP available."""
        request = Mock(spec=Request)
        request.headers.get.return_value = None
        request.client = None

        ip = get_client_ip(request)
        assert ip == "unknown"

    def test_get_client_ip_x_forwarded_for_priority(self):
        """get_client_ip prioritizes X-Forwarded-For over X-Real-IP."""
        request = Mock(spec=Request)
        request.headers.get.side_effect = lambda key: {
            "X-Forwarded-For": "203.0.113.1",
            "X-Real-IP": "198.51.100.1",
        }.get(key)
        request.client = Mock()
        request.client.host = "192.0.2.1"

        ip = get_client_ip(request)
        assert ip == "203.0.113.1"

    def test_get_client_ip_x_real_ip_priority_over_direct(self):
        """get_client_ip prioritizes X-Real-IP over direct IP."""
        request = Mock(spec=Request)
        request.headers.get.side_effect = lambda key: {
            "X-Real-IP": "198.51.100.1"
        }.get(key)
        request.client = Mock()
        request.client.host = "192.0.2.1"

        ip = get_client_ip(request)
        assert ip == "198.51.100.1"

    def test_get_client_ip_x_forwarded_for_strips_whitespace(self):
        """get_client_ip strips whitespace from X-Forwarded-For IP."""
        request = Mock(spec=Request)
        request.headers.get.side_effect = lambda key: {
            "X-Forwarded-For": " 203.0.113.1 , 198.51.100.1 "
        }.get(key)
        request.client = None

        ip = get_client_ip(request)
        assert ip == "203.0.113.1"
