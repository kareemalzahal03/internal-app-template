"""Security headers on every response.

The policy assumes the built SPA: one script and one stylesheet from this
origin, no inline code, nothing from anywhere else. A response that sets its
own Content-Security-Policy keeps it.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        # Scripts, styles, images, fonts and fetches: this origin only, so
        # injected markup can neither run inline code nor load a script.
        "default-src 'self'; "
        # Plugins stay off even if default-src is ever widened.
        "object-src 'none'; "
        # A <base> tag would re-point every relative URL on the page.
        "base-uri 'none'; "
        # This and the next do not fall back to default-src. Forms submit only here.
        "form-action 'self'; "
        # No page may frame this one, which rules out clickjacking.
        "frame-ancestors 'none'"
    ),
    # A response is only ever the type it declares: JSON is never run as script.
    "X-Content-Type-Options": "nosniff",
    # Full URLs stay on this site; other sites are sent nothing.
    "Referrer-Policy": "same-origin",
    # A window from another site that opens this one, or that this one opens,
    # gets no handle on it, so it cannot navigate it or count its frames.
    "Cross-Origin-Opener-Policy": "same-origin",
}

# After one response carrying this over HTTPS, browsers refuse plain HTTP to
# this host for a year.
HSTS = {"Strict-Transport-Security": "max-age=31536000"}


async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Add each security header the response does not already carry."""
    response: Response = await call_next(request)
    headers = SECURITY_HEADERS
    # RFC 6797 §7.2: never over plain HTTP. Behind a proxy that ends HTTPS,
    # this is true only when the proxy is trusted to say so.
    if request.url.is_secure:
        headers = {**headers, **HSTS}
    for name, value in headers.items():
        response.headers.setdefault(name, value)
    return response


security_headers_middleware = Middleware(BaseHTTPMiddleware, dispatch=add_security_headers)
"""Middleware instance for the FastAPI app: security headers on every response."""
