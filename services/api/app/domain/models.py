"""Clients and orders: what MongoDB stores, and what the API speaks.

Grouped by entity rather than by layer, so a Document and the payloads that
read and write it are read together.

Documents and DTOs stay separate *classes*. A Document describes storage
(including fields the API never accepts, like timestamps); a DTO describes
one HTTP payload. Reusing one class for both couples the wire format to the
storage format — the first time they need to differ (rename a stored field,
hide one from the API, accept a subset on create) a shared class forces a
breaking change on one side or the other.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, EmailStr, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

### SHARED


class Page[T](BaseModel):
    """Offset pagination envelope shared by every list endpoint."""

    items: list[T]
    total: int
    limit: int
    offset: int


### CLIENTS


class ClientStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Contact(BaseModel):
    """Embedded sub-document: contacts are always loaded with their client,
    never queried on their own, and the list is bounded — the textbook case
    for embedding over a separate collection."""

    name: str
    role: str
    phone: str


# The bound that makes embedding safe: a client's document cannot grow
# without limit, toward MongoDB's 16 MB cap.
Contacts = Annotated[list[Contact], Field(max_length=20)]


class Client(Document):
    name: str
    email: EmailStr
    status: ClientStatus
    contacts: list[Contact]
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "clients"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("email", ASCENDING)], unique=True),
            # Listing clients by status matches status and sorts by name,
            # ties broken by id: equality first, then the sort (ESR rule).
            IndexModel([("status", ASCENDING), ("name", ASCENDING), ("_id", ASCENDING)]),
        ]


class ClientCreate(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    status: ClientStatus = ClientStatus.ACTIVE
    contacts: Contacts = []


class ClientUpdate(BaseModel):
    """PUT replaces the whole client, so every field is required: one left
    out is an error, never a reset to the create default."""

    name: str = Field(min_length=1)
    email: EmailStr
    status: ClientStatus
    contacts: Contacts


class ClientOut(BaseModel):
    # PydanticObjectId serializes to a plain string, in JSON and in the
    # OpenAPI schema.
    id: PydanticObjectId
    name: str
    email: EmailStr
    status: ClientStatus
    contacts: list[Contact]
    created_at: datetime
    updated_at: datetime


### ORDERS


class OrderStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    FULFILLED = "fulfilled"


class Order(Document):
    # A reference rather than an embedded document: orders are unbounded per
    # client and are queried independently (stats, order detail), so they get
    # their own collection with a foreign-key-style field.
    client_id: PydanticObjectId
    description: str
    quantity: int
    unit_price: float
    status: OrderStatus
    created_at: datetime

    class Settings:
        name = "orders"
        indexes: ClassVar[list[IndexModel]] = [
            # ESR rule (Equality, Sort, Range): equality-matched fields first,
            # then sort fields. Listing a client's orders matches client_id
            # and sorts newest first, ties broken by id. This index serves
            # both, so MongoDB never sorts in memory.
            IndexModel([("client_id", ASCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)]),
        ]


class OrderCreate(BaseModel):
    client_id: PydanticObjectId
    description: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    status: OrderStatus = OrderStatus.DRAFT


class OrderUpdate(BaseModel):
    """PUT with everything except client_id — an order never moves between
    clients."""

    description: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    status: OrderStatus


class OrderOut(BaseModel):
    id: PydanticObjectId
    client_id: PydanticObjectId
    description: str
    quantity: int
    unit_price: float
    status: OrderStatus
    created_at: datetime


class ClientOrderStats(BaseModel):
    """One client's order count and total order value."""

    client_id: PydanticObjectId
    order_count: int
    total_value: float
