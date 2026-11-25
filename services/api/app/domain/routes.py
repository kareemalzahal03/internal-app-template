"""HTTP layer: routing, status codes, and the queries behind them.

Each route owns its own logic, with no service or repository layer. The one
rule shared between routes, "this id must exist, or 404", is a dependency,
so it is part of a route's signature rather than a call each handler has to
remember.

Every route sets an explicit operation_id, so the operation names in the
OpenAPI schema stay stable.
"""

from datetime import UTC, datetime
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError

from app.core.auth import AUTHENTICATED
from app.core.errors import FieldErrorModel
from app.domain.models import (
    Client,
    ClientCreate,
    ClientOrderStats,
    ClientOut,
    ClientStatus,
    ClientUpdate,
    Order,
    OrderCreate,
    OrderOut,
    OrderStatus,
    OrderUpdate,
    Page,
)

LimitParam = Annotated[int, Query(ge=1, le=100)]
OffsetParam = Annotated[int, Query(ge=0)]


def now() -> datetime:
    """The current time, to the millisecond. MongoDB stores no finer, so a
    response that returns the time it stamped matches a later read."""
    time = datetime.now(UTC)
    return time.replace(microsecond=time.microsecond // 1000 * 1000)


### CLIENTS

# A 409 can only come from a unique index, and a client's email is the only
# one a route can collide with. So it is declared on this router, not
# app-wide, where routes that cannot produce one would claim it.
clients_router = APIRouter(
    prefix="/clients",
    tags=["clients"],
    dependencies=AUTHENTICATED,
    responses={409: {"model": FieldErrorModel}},
)


@clients_router.get("", operation_id="list_clients")
async def list_clients(
    status: ClientStatus | None = None,
    limit: LimitParam = 20,
    offset: OffsetParam = 0,
) -> Page[ClientOut]:
    query = Client.find({"status": status.value} if status else {})
    total = await query.count()
    # Ties broken by id, so a page holds the same rows every time it is read.
    clients = await query.sort("+name", "+_id").skip(offset).limit(limit).to_list()
    items = [ClientOut.model_validate(c, from_attributes=True) for c in clients]
    return Page(items=items, total=total, limit=limit, offset=offset)


@clients_router.post("", status_code=201, operation_id="create_client")
async def create_client(data: ClientCreate) -> ClientOut:
    created = now()
    client = await Client(**data.model_dump(), created_at=created, updated_at=created).insert()
    return ClientOut.model_validate(client, from_attributes=True)


async def client_dep(client_id: PydanticObjectId) -> Client:
    client = await Client.get(client_id)
    if client is None:
        raise HTTPException(404, f"client {client_id} not found")
    return client


ClientDep = Annotated[Client, Depends(client_dep)]


@clients_router.get("/{client_id}", operation_id="get_client")
async def get_client(client: ClientDep) -> ClientOut:
    return ClientOut.model_validate(client, from_attributes=True)


@clients_router.put("/{client_id}", operation_id="update_client")
async def update_client(client: ClientDep, data: ClientUpdate) -> ClientOut:
    for field, value in data.model_dump().items():
        setattr(client, field, value)
    client.updated_at = now()
    saved = await client.save()
    return ClientOut.model_validate(saved, from_attributes=True)


@clients_router.delete("/{client_id}", status_code=204, operation_id="delete_client")
async def delete_client(client: ClientDep) -> None:
    # Orders reference the client by id; without the client they are
    # orphans, so deletion cascades.
    await Order.find(Order.client_id == client.id).delete()
    await client.delete()


@clients_router.get("/{client_id}/orders", operation_id="list_client_orders")
async def list_client_orders(
    client: ClientDep,
    limit: LimitParam = 20,
    offset: OffsetParam = 0,
) -> Page[OrderOut]:
    query = Order.find(Order.client_id == client.id)
    total = await query.count()
    # Newest first, ties broken by id, so a page holds the same rows every
    # time it is read.
    orders = await query.sort("-created_at", "-_id").skip(offset).limit(limit).to_list()
    items = [OrderOut.model_validate(o, from_attributes=True) for o in orders]
    return Page(items=items, total=total, limit=limit, offset=offset)


### ORDERS

orders_router = APIRouter(prefix="/orders", tags=["orders"], dependencies=AUTHENTICATED)


# Declared before /orders/{order_id}: FastAPI matches routes in order, and
# "stats" would otherwise be parsed (and rejected) as an ObjectId.
@orders_router.get("/stats", operation_id="get_order_stats_by_client")
async def get_order_stats_by_client() -> list[ClientOrderStats]:
    # Total order value and order count per client, biggest spenders
    # first. Draft orders are excluded — they aren't committed revenue.
    pipeline = [
        {"$match": {"status": {"$in": [OrderStatus.SUBMITTED, OrderStatus.FULFILLED]}}},
        {
            "$group": {
                "_id": "$client_id",
                "order_count": {"$sum": 1},
                "total_value": {"$sum": {"$multiply": ["$quantity", "$unit_price"]}},
            }
        },
        {"$sort": {"total_value": -1}},
    ]
    rows = await Order.aggregate(pipeline).to_list()
    return [
        ClientOrderStats(
            client_id=row["_id"],
            order_count=row["order_count"],
            total_value=row["total_value"],
        )
        for row in rows
    ]


@orders_router.post("", status_code=201, operation_id="create_order")
async def create_order(data: OrderCreate) -> OrderOut:
    # The client is named in the body, not the URL, so a missing one is a bad
    # field, not a missing resource: a 404 means the URL's target was not
    # found (RFC 9110 §15.5.5). Raised as validation fails, so it has that shape.
    if await Client.get(data.client_id) is None:
        error = {"type": "missing_client", "loc": ("body", "client_id"), "msg": "no such client"}
        raise RequestValidationError([error])
    order = await Order(**data.model_dump(), created_at=now()).insert()
    return OrderOut.model_validate(order, from_attributes=True)


async def order_dep(order_id: PydanticObjectId) -> Order:
    order = await Order.get(order_id)
    if order is None:
        raise HTTPException(404, f"order {order_id} not found")
    return order


OrderDep = Annotated[Order, Depends(order_dep)]


@orders_router.get("/{order_id}", operation_id="get_order")
async def get_order(order: OrderDep) -> OrderOut:
    return OrderOut.model_validate(order, from_attributes=True)


@orders_router.put("/{order_id}", operation_id="update_order")
async def update_order(order: OrderDep, data: OrderUpdate) -> OrderOut:
    for field, value in data.model_dump().items():
        setattr(order, field, value)
    saved = await order.save()
    return OrderOut.model_validate(saved, from_attributes=True)


@orders_router.delete("/{order_id}", status_code=204, operation_id="delete_order")
async def delete_order(order: OrderDep) -> None:
    await order.delete()


### THE DOMAIN

# Every router above, as the one the app includes. Guarded too, so a router
# added here later is never served without a session.
router = APIRouter(dependencies=AUTHENTICATED)
router.include_router(clients_router)
router.include_router(orders_router)
