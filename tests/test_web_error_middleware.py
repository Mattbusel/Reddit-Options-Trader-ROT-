"""
Comprehensive tests for error tracking middleware.

Modules tested:
- rot.web.error_middleware

Coverage:
- ErrorTrackingMiddleware (exception handling, HTTP error tracking)
- get_client_ip (X-Forwarded-For, X-Real-IP, direct IP)
- Error response creation (development vs production)
- User context extraction
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from rot.web.error_middleware import ErrorTrackingMiddleware, get_client_ip


class TestErrorTrackingMiddleware:
    @pytest.fixture
    def app(self):
        """Create FastAPI app with error middleware."""
        app = FastAPI()
        app.add_middleware(ErrorTrackingMiddleware)

        @app.get("/success")
        def success_route():
            return {"status": "ok"}

        @app.get("/error")
        def error_route():
            raise ValueError("Test error")

        @app.get("/http_error")
        def http_error_route():
            raise HTTPException(status_code=403, detail="Forbidden")

        @app.get("/server_error")
        def server_error_route():
            raise HTTPException(status_code=500, detail="Server error")

        return app

    def test_success_request_passes_through(self, app):
        """Successful requests pass through middleware unchanged."""
        client = TestClient(app)
        response = client.get("/success")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @patch("rot.web.error_middleware.capture_exception")
    def test_unhandled_exception_captured(self, mock_capture, app):
        """Unhandled exceptions are captured with context."""
        mock_capture.return_value = "error_id_123"

        client = TestClient(app)
        response = client.get("/error")

        assert response.status_code == 500
        assert mock_capture.called
        # Check that exception was captured
        assert mock_capture.call_args[0][0].__class__.__name__ == "ValueError"

    @patch("rot.web.error_middleware.capture_exception")
    @patch.dict("os.environ", {"ROT_ENV": "development"})
    def test_error_response_development_mode(self, mock_capture, app):
        """Development mode includes error details in response."""
        mock_capture.return_value = "error_id_123"

        client = TestClient(app)
        response = client.get("/error")

        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert "Test error" in data["error"]
        assert data["error_type"] == "ValueError"
        assert data["error_id"] == "error_id_123"

    @patch("rot.web.error_middleware.capture_exception")
    @patch.dict("os.environ", {"ROT_ENV": "production"})
    def test_error_response_production_mode(self, mock_capture, app):
        """Production mode hides error details."""
        mock_capture.return_value = "error_id_456"

        client = TestClient(app)
        response = client.get("/error")

        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Internal server error. Our team has been notified."
        assert data["error_code"] == "INTERNAL_ERROR"
        assert data["error_id"] == "error_id_456"
        # Should not include error type or details in production
        assert "error_type" not in data

    @patch("rot.web.error_middleware.capture_message")
    def test_http_500_error_tracked(self, mock_capture_msg, app):
        """HTTP 500 errors are tracked."""
        client = TestClient(app)
        response = client.get("/server_error")

        assert response.status_code == 500
        assert mock_capture_msg.called
        # Check message contains endpoint info
        call_args = mock_capture_msg.call_args
        assert "HTTP 500" in call_args[0][0]
        assert "/server_error" in call_args[0][0]
        assert call_args[1]["level"] == "error"

    @patch("rot.web.error_middleware.capture_message")
    def test_http_403_error_tracked(self, mock_capture_msg, app):
        """HTTP 403 errors are tracked."""
        client = TestClient(app)
        response = client.get("/http_error")

        assert response.status_code == 403
        assert mock_capture_msg.called
        call_args = mock_capture_msg.call_args
        assert "HTTP 403" in call_args[0][0]
        assert call_args[1]["level"] == "warning"

    @patch("rot.web.error_middleware.capture_message")
    def test_http_401_error_tracked(self, mock_capture_msg, app):
        """HTTP 401 errors are tracked."""
        app_with_401 = FastAPI()
        app_with_401.add_middleware(ErrorTrackingMiddleware)

        @app_with_401.get("/unauthorized")
        def unauthorized_route():
            raise HTTPException(status_code=401, detail="Unauthorized")

        client = TestClient(app_with_401)
        response = client.get("/unauthorized")

        assert response.status_code == 401
        assert mock_capture_msg.called

    @patch("rot.web.error_middleware.capture_message")
    def test_http_429_error_tracked(self, mock_capture_msg, app):
        """HTTP 429 errors are tracked."""
        app_with_429 = FastAPI()
        app_with_429.add_middleware(ErrorTrackingMiddleware)

        @app_with_429.get("/rate_limited")
        def rate_limited_route():
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        client = TestClient(app_with_429)
        response = client.get("/rate_limited")

        assert response.status_code == 429
        assert mock_capture_msg.called

    @patch("rot.web.error_middleware.capture_message")
    def test_http_404_not_tracked(self, mock_capture_msg, app):
        """HTTP 404 errors are not tracked (too noisy)."""
        client = TestClient(app)
        response = client.get("/nonexistent")

        assert response.status_code == 404
        assert not mock_capture_msg.called

    @patch("rot.web.error_middleware.capture_exception")
    def test_user_context_captured(self, mock_capture, app):
        """User context is included in error capture."""
        mock_capture.return_value = "error_id_789"

        # Create app with user state
        app_with_user = FastAPI()
        app_with_user.add_middleware(ErrorTrackingMiddleware)

        @app_with_user.get("/error_with_user")
        def error_route(request: Request):
            # Simulate user in request state
            request.state.user = {
                "id": 123,
                "email": "test@example.com",
                "tier": "pro",
            }
            raise ValueError("Test error")

        client = TestClient(app_with_user)
        response = client.get("/error_with_user")

        assert response.status_code == 500
        assert mock_capture.called

        # Check context includes user info
        context = mock_capture.call_args[1]["context"]
        assert context["user_id"] == 123
        assert context["user_email"] == "test@example.com"
        assert context["user_tier"] == "pro"

    @patch("rot.web.error_middleware.capture_exception")
    def test_client_ip_captured(self, mock_capture, app):
        """Client IP is included in error capture."""
        mock_capture.return_value = "error_id_ip"

        client = TestClient(app)
        response = client.get("/error")

        assert mock_capture.called
        context = mock_capture.call_args[1]["context"]
        assert "client_ip" in context

    @patch("rot.web.error_middleware.capture_exception")
    def test_request_headers_captured(self, mock_capture, app):
        """Request headers are included in error capture."""
        mock_capture.return_value = "error_id_headers"

        client = TestClient(app)
        response = client.get("/error", headers={"User-Agent": "TestClient"})

        assert mock_capture.called
        context = mock_capture.call_args[1]["context"]
        assert "headers" in context
        assert "user-agent" in context["headers"]

    @patch("rot.web.error_middleware.capture_message")
    def test_http_error_includes_endpoint_tags(self, mock_capture_msg, app):
        """HTTP error tracking includes endpoint tags."""
        client = TestClient(app)
        response = client.get("/server_error")

        assert mock_capture_msg.called
        tags = mock_capture_msg.call_args[1]["tags"]
        assert tags["endpoint"] == "/server_error"
        assert tags["method"] == "GET"
        assert tags["status_code"] == "500"


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
