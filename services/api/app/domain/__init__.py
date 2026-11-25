"""The domain: what this app is for, beside the template that serves it.

The template binds it in by these two names alone, so a fork replaces
everything in this folder and keeps them.
"""

from beanie import Document

from app.domain.models import Client, Order
from app.domain.routes import router

__all__ = ["models", "router"]

# Every Document the domain stores.
models: tuple[type[Document], ...] = (Client, Order)
