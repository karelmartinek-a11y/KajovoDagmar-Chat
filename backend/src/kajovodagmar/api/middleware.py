from __future__ import annotations

import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from kajovodagmar.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS
from kajovodagmar.observability.tracing import traced


class CorrelationAndSecurityMiddleware(BaseHTTPMiddleware):
    @traced("http.server.request")
    async def dispatch(self, request: Request, call_next):
        correlation = request.headers.get("X-Correlation-ID") or uuid4().hex
        request.state.correlation_id = correlation
        started = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        route_name = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(
            method=request.method, route=route_name, status_class=f"{response.status_code // 100}xx"
        ).inc()
        HTTP_LATENCY.labels(method=request.method, route=route_name).observe(elapsed)
        response.headers["X-Correlation-ID"] = correlation
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "font-src 'self'; img-src 'self' data:; connect-src 'self' wss:; "
            "media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "public, max-age=300"
        )
        return response
