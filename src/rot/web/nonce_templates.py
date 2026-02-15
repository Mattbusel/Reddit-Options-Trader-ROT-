"""Jinja2Templates subclass that auto-injects CSP nonce into every template context.

This avoids modifying every route file — the nonce is pulled from request.state
(set by SecurityHeadersMiddleware) and injected into the template context
automatically on every TemplateResponse call.
"""
from __future__ import annotations

from typing import Any

from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.responses import Response


class NonceTemplates(Jinja2Templates):
    """Templates that automatically inject ``csp_nonce`` from ``request.state``."""

    def TemplateResponse(
        self,
        name: str,
        context: dict[str, Any],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> Response:
        request = context.get("request")
        if request and hasattr(getattr(request, "state", None), "csp_nonce"):
            context.setdefault("csp_nonce", request.state.csp_nonce)
        return super().TemplateResponse(
            name,
            context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )
