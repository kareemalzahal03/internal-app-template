"""The example's demo data: a few clients, each with a few orders.

Inserts only, into collections already emptied, so nothing here can delete
data. Built as documents, so created_at can be backdated and the sorted order
list is worth looking at.
"""

import random
from datetime import UTC, datetime, timedelta

from app.domain.models import Client, ClientStatus, Contact, Order, OrderStatus

# Made-up names, on example.com, a domain reserved for examples (RFC 2606 §3).
CLIENTS = [
    (
        "Harbor Fabrication",
        "ops@harbor.example.com",
        ClientStatus.ACTIVE,
        [
            Contact(name="Jo Chen", role="Accounts Payable", phone="555-0100"),
            Contact(name="Sam Reyes", role="Procurement", phone="555-0101"),
        ],
    ),
    (
        "Lakeside Machine Works",
        "billing@lakeside.example.com",
        ClientStatus.ACTIVE,
        [Contact(name="Hana Kim", role="Finance", phone="555-0200")],
    ),
    (
        "Pine Street Builders",
        "accounts@pinestreet.example.com",
        ClientStatus.ACTIVE,
        [
            Contact(name="Ravi Patel", role="Manager", phone="555-0300"),
            Contact(name="Maria Santos", role="Facilities", phone="555-0301"),
        ],
    ),
    (
        "Riverbend Supply",
        "orders@riverbend.example.com",
        ClientStatus.INACTIVE,
        [Contact(name="Lena Novak", role="Purchasing", phone="555-0400")],
    ),
    ("Summit Tooling", "invoices@summit.example.com", ClientStatus.ACTIVE, []),
]

PRODUCTS = [
    ("Steel brackets (box of 50)", 24.0),
    ("Powder coating service", 180.0),
    ("Aluminium sheet 2mm", 42.5),
    ("CNC machining hour", 95.0),
    ("Fastener assortment", 12.75),
]


async def seed() -> None:
    """Inserts the demo data. Expects the models bound and the example's collections empty."""
    rng = random.Random(42)  # deterministic data across runs
    now = datetime.now(UTC)
    order_count = 0
    for name, email, status, contacts in CLIENTS:
        created = now - timedelta(days=rng.randint(60, 400))
        client = await Client(
            name=name,
            email=email,
            status=status,
            contacts=contacts,
            created_at=created,
            updated_at=created,
        ).insert()
        for _ in range(rng.randint(0, 5)):
            description, unit_price = rng.choice(PRODUCTS)
            await Order(
                client_id=client.id,
                description=description,
                quantity=rng.randint(1, 20),
                unit_price=unit_price,
                status=rng.choice(list(OrderStatus)),
                created_at=created + timedelta(days=rng.randint(1, 59)),
            ).insert()
            order_count += 1
    print(f"seeded {len(CLIENTS)} clients and {order_count} orders")
