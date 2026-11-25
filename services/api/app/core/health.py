"""The health check a load balancer polls."""

from fastapi import APIRouter
from pydantic import BaseModel

health_router = APIRouter()


class HealthCheck(BaseModel):
    status: str = "ok"


@health_router.get("/health", tags=["health"], operation_id="health_check")
async def health_check() -> HealthCheck:
    """Whether this process is up and serving."""
    return HealthCheck()
