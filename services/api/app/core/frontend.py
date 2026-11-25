"""The cache and compression headers on the built SPA this process serves.

FastAPI serves the files with ETag and Last-Modified, so a conditional
request gets a 304, but with no Cache-Control and no compression. The two
middlewares here add those.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware


async def static_cache_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Set Cache-Control on the SPA's files: forever on hashed assets, never on HTML."""
    response = await call_next(request)
    if request.url.path.startswith("/assets/") and response.status_code < 400:
        # Vite puts a content hash in every filename under /assets, so a
        # changed file is a new URL and the old one can be cached for good.
        # Never a 404: mid-deploy, a new page can ask an old copy for a file
        # it does not have yet, and that answer must not be kept.
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
    elif response.headers.get("content-type", "").startswith("text/html"):
        # index.html is the one entry point and carries no hash, so it must
        # be revalidated every time or a deploy goes unseen — by browsers, and
        # by the CDN in front, which would otherwise keep a stale copy.
        response.headers["cache-control"] = "no-cache"
    # Unhashed files at the root, such as icons, get neither: browser
    # heuristics and the CDN's default TTL apply, which is fine for them.
    return response


# Middleware instance for the FastAPI app: Cache-Control on the served SPA.
static_cache_middleware = Middleware(BaseHTTPMiddleware, dispatch=static_cache_headers)


# Compresses anything over 1000 bytes that the client accepts gzip for: the
# JavaScript bundle to about a third of its size, and API JSON with it.
# Starlette cannot serve pre-compressed files, so this is the only
# compression there is when nothing sits in front of the API.
gzip_middleware = Middleware(GZipMiddleware, minimum_size=1000)
