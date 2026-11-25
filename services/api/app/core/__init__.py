"""The template: everything the app is built from, beside its domain."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from beanie import Document
from fastapi import APIRouter, FastAPI
from starlette.middleware import Middleware

from app.core.auth import Session, User, auth_router, get_provider, get_urls, oauth_state_middleware
from app.core.docs import docs_router
from app.core.errors import exception_handlers, responses
from app.core.frontend import gzip_middleware, static_cache_middleware
from app.core.health import health_router
from app.core.logging import request_boundary
from app.core.security import security_headers_middleware

__all__ = [
    "exception_handlers",
    "middleware",
    "models",
    "responses",
    "router",
]

# Every Document the template stores.
models: tuple[type[Document], ...] = (User, Session)


# Middleware Stack:
# Requests travel down, and responses travel up.
# Exceptions raised anywhere travel up until a layer answers them.
#
# ↓ ServerErrorMiddleware*  ↑   • Last resort: catches all exceptions, returns 500 response.
# ↓ headers middleware      ↑   • Middleware that adds headers to responses, and must not raise.
# ↓ RequestBoundary         ↑   • Each request's ID and its log line; catches all exceptions.
# ↓ other middleware        ↑   • Other middleware which may raise.
# ↓ ExceptionMiddleware*    ↑   • Catches exceptions with a handler, returns handler response.
# ↓ app routes              ↑   • The app's routes, which may raise.

# Outermost first.
middleware: tuple[Middleware, ...] = (
    # Above the boundary: only middleware that cannot raise, adding headers
    # to every response, the 500 included.
    security_headers_middleware,
    request_boundary,
    oauth_state_middleware,
    static_cache_middleware,
    gzip_middleware,
)


@asynccontextmanager
async def startup(_: FastAPI) -> AsyncGenerator[None]:
    """Start each piece the template needs, in order. Any failure fails startup.

    It runs inside the app's own lifespan, once the database is ready.
    """
    # Settings first, so a missing variable fails before any network call.
    get_urls()
    await get_provider().connect()
    yield


# Its lifespan joins the app's when the app includes it.
router = APIRouter(lifespan=startup)
router.include_router(auth_router)
router.include_router(docs_router)
router.include_router(health_router)
