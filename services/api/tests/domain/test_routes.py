"""The example domain: clients and their orders, through the API.

A fork replaces this file with tests of its own domain. Every test here is
signed in through `browser` and says nothing else about auth; the session, the
CSRF header and the guard on these routes are tested with the template.
"""

from typing import Any

from pytest import mark

from app.core.errors import FieldErrorModel
from app.main import app
from tests.helpers import MISSING_ID, declared_model, read_error
from tests.parties import Browser

pytestmark = mark.asyncio(loop_scope="session")


### Helpers


async def create_client(browser: Browser, **overrides: Any) -> dict[str, Any]:
    """A client created through the API, with `overrides` over a valid body."""
    payload = {
        "name": "Client A",
        "email": "ops@example.com",
        "contacts": [{"name": "Contact A", "role": "AP", "phone": "555-0100"}],
        **overrides,
    }
    response = await browser.post("/api/clients", json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def create_order(browser: Browser, client_id: str, **overrides: Any) -> dict[str, Any]:
    """An order for `client_id` created through the API, with `overrides`
    over a valid body."""
    payload = {
        "client_id": client_id,
        "description": "Widgets",
        "quantity": 10,
        "unit_price": 4.5,
        "status": "submitted",
        **overrides,
    }
    response = await browser.post("/api/orders", json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


### Clients


async def test_a_created_client_can_be_read_back(browser: Browser) -> None:
    created = await create_client(browser)
    response = await browser.get(f"/api/clients/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Client A"
    assert body["contacts"][0]["phone"] == "555-0100"


async def test_a_write_returns_the_times_a_read_returns(browser: Browser) -> None:
    """MongoDB keeps times to the millisecond; a response must not claim finer."""
    client = await create_client(browser)
    assert (await browser.get(f"/api/clients/{client['id']}")).json() == client

    updated = (await browser.put(f"/api/clients/{client['id']}", json=client)).json()
    assert (await browser.get(f"/api/clients/{client['id']}")).json() == updated

    order = await create_order(browser, client["id"])
    assert (await browser.get(f"/api/orders/{order['id']}")).json() == order


async def test_clients_can_be_listed_by_status(browser: Browser) -> None:
    await create_client(browser, name="Active Co", email="a@example.com")
    await create_client(browser, name="Idle Co", email="b@example.com", status="inactive")
    response = await browser.get("/api/clients", params={"status": "inactive"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Idle Co"


async def test_an_update_replaces_the_client_and_moves_its_timestamp(browser: Browser) -> None:
    created = await create_client(browser)
    response = await browser.put(
        f"/api/clients/{created['id']}",
        json={
            "name": "Client A Renamed",
            "email": "ops@example.com",
            "status": "inactive",
            "contacts": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Client A Renamed"
    assert body["status"] == "inactive"
    assert body["updated_at"] > created["updated_at"]


async def test_an_update_that_leaves_a_field_out_is_rejected(browser: Browser) -> None:
    """Left out, a field would fall back to its create default: an inactive
    client would quietly become active again."""
    created = await create_client(browser, status="inactive")
    response = await browser.put(
        f"/api/clients/{created['id']}",
        json={"name": "Client A Renamed", "email": "ops@example.com"},
    )
    assert response.status_code == 422

    assert {"status", "contacts"} <= read_error(FieldErrorModel, response).fields.keys()
    assert (await browser.get(f"/api/clients/{created['id']}")).json()["status"] == "inactive"


async def test_an_invalid_client_names_every_field_that_failed(browser: Browser) -> None:
    response = await browser.post("/api/clients", json={"name": "", "email": "nope"})
    assert response.status_code == 422

    body = read_error(FieldErrorModel, response)
    assert {"name", "email"} <= body.fields.keys()


async def test_a_client_has_at_most_20_contacts(browser: Browser) -> None:
    contact = {"name": "Contact A", "role": "AP", "phone": "555-0100"}
    await create_client(browser, contacts=[contact] * 20)
    response = await browser.post(
        "/api/clients",
        json={"name": "Other", "email": "other@example.com", "contacts": [contact] * 21},
    )
    assert response.status_code == 422

    assert "contacts" in read_error(FieldErrorModel, response).fields


async def test_a_second_client_with_the_same_email_is_a_409(browser: Browser) -> None:
    """The client email is the one unique index a caller can collide with."""
    await create_client(browser)
    response = await browser.post(
        "/api/clients", json={"name": "Other", "email": "ops@example.com"}
    )
    assert response.status_code == 409

    body = read_error(FieldErrorModel, response)
    assert body.fields == {"email": "already exists"}
    assert body.detail == "a record with email='ops@example.com' already exists"


async def test_only_the_clients_router_declares_a_409() -> None:
    """A status's shape is declared at the narrowest scope where it is true.
    Declared app-wide, every route would promise a 409 it cannot return."""
    assert declared_model("/api/clients", "post", "409") == "FieldErrorModel"
    assert "409" not in app.openapi()["paths"]["/api/orders"]["post"]["responses"]


async def test_a_missing_client_is_a_404(browser: Browser) -> None:
    response = await browser.get(f"/api/clients/{MISSING_ID}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


async def test_deleting_a_client_deletes_its_orders(browser: Browser) -> None:
    client = await create_client(browser)
    order = await create_order(browser, client["id"])
    response = await browser.delete(f"/api/clients/{client['id']}")

    assert response.status_code == 204
    assert (await browser.get(f"/api/orders/{order['id']}")).status_code == 404


### Orders


async def test_a_clients_orders_are_listed_newest_first(browser: Browser) -> None:
    client = await create_client(browser)
    await create_order(browser, client["id"], description="first")
    await create_order(browser, client["id"], description="second")
    response = await browser.get(f"/api/clients/{client['id']}/orders")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [o["description"] for o in body["items"]] == ["second", "first"]


async def test_an_order_for_a_missing_client_is_a_422_on_its_client(browser: Browser) -> None:
    """The order's URL exists; what is wrong is a field of its body."""
    response = await browser.post(
        "/api/orders",
        json={"client_id": MISSING_ID, "description": "Widgets", "quantity": 1, "unit_price": 1},
    )
    assert response.status_code == 422

    body = read_error(FieldErrorModel, response)
    assert body.fields == {"client_id": "no such client"}


async def test_an_order_can_be_updated_then_deleted(browser: Browser) -> None:
    client = await create_client(browser)
    order = await create_order(browser, client["id"])
    updated = await browser.put(
        f"/api/orders/{order['id']}",
        json={"description": "Widgets", "quantity": 3, "unit_price": 4.5, "status": "fulfilled"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "fulfilled"

    deleted = await browser.delete(f"/api/orders/{order['id']}")
    assert deleted.status_code == 204
    assert (await browser.get(f"/api/orders/{order['id']}")).status_code == 404


async def test_order_stats_total_each_client_without_drafts(browser: Browser) -> None:
    big = await create_client(browser, name="Big Co", email="big@example.com")
    small = await create_client(browser, name="Small Co", email="small@example.com")
    await create_order(browser, big["id"], quantity=10, unit_price=10.0)  # 100
    await create_order(browser, big["id"], quantity=2, unit_price=25.0, status="fulfilled")  # 50
    await create_order(browser, big["id"], quantity=99, unit_price=99.0, status="draft")  # excluded
    await create_order(browser, small["id"], quantity=1, unit_price=60.0)  # 60
    response = await browser.get("/api/orders/stats")

    assert response.status_code == 200
    # Sorted by total value, largest first.
    assert [(r["client_id"], r["order_count"], r["total_value"]) for r in response.json()] == [
        (big["id"], 2, 150.0),
        (small["id"], 1, 60.0),
    ]
