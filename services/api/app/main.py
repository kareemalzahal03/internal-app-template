"""The app: the template's core and the domain. All API routes prefixed with /api."""

from pathlib import Path

from fastapi import FastAPI

from app import core, db, domain

app = FastAPI(
    title="Internal App",
    description="A template for internal web apps.",
    lifespan=db.lifespan,
    openapi_url="/api/openapi.json",
    docs_url=None,
    redoc_url=None,
    responses=core.responses,
    middleware=core.middleware,
    exception_handlers=core.exception_handlers,
)

# Routes
app.include_router(core.router, prefix="/api")
app.include_router(domain.router, prefix="/api")

# Frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.frontend("/", directory=FRONTEND_DIR, fallback="index.html", check_dir=True)
