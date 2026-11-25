"""The API serves the built SPA, and the two never get in each other's way.

Runs against the committed stand-in page, so what these check is the
mounting, the fallback rule, and the two headers FastAPI's static serving
leaves for us to set.

Two kinds of request throughout: a browser navigation, which accepts HTML and
is what the index.html fallback exists for, and a fetch, which does not and
must never be handed the SPA in place of a 404.
"""

from pytest import mark

from app.core.errors import ErrorModel
from tests.helpers import read_error
from tests.parties import NAVIGATION, Browser

pytestmark = mark.asyncio(loop_scope="session")


async def test_the_spa_is_served_at_the_root(anon_browser: Browser) -> None:
    response = await anon_browser.navigate("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "frontend fixture" in response.text


async def test_a_deep_link_gets_index_html_for_the_router_to_resolve(
    anon_browser: Browser,
) -> None:
    """A path only React Router knows about has no file behind it. A browser
    landing there must get the SPA, which then resolves the path itself."""
    response = await anon_browser.navigate("/clients/123")

    assert response.status_code == 200
    assert "frontend fixture" in response.text


async def test_an_unknown_api_path_visited_as_a_page_gets_the_spa(
    anon_browser: Browser,
) -> None:
    """Only a person typing the address does this. The SPA shows its own
    not-found page; a fetch for the same path still gets a JSON 404."""
    response = await anon_browser.navigate("/api/does-not-exist")

    assert response.status_code == 200
    assert "frontend fixture" in response.text


async def test_a_missing_asset_is_a_404_and_never_the_spa(anon_browser: Browser) -> None:
    """The fallback is for navigations only. A script tag or a fetch for a
    file that is not there must fail, or a broken build would ship index.html
    where JavaScript was expected and the error would surface as a parse
    failure in the browser.

    The 404 is Starlette's HTTPException, not FastAPI's subclass, and gets
    the app's error body all the same: the handler is registered on the base."""
    response = await anon_browser.get("/assets/missing.js")

    assert read_error(ErrorModel, response).status == 404
    # Mid-deploy the file may exist on another copy a moment later.
    assert "immutable" not in response.headers.get("cache-control", "")


async def test_hashed_assets_are_immutable_and_html_is_revalidated(
    anon_browser: Browser,
) -> None:
    """Vite hashes everything under /assets, so those can be cached for good;
    index.html carries no hash and must be checked on every visit or a deploy
    goes unseen."""
    asset = await anon_browser.get("/assets/app-0123abcd.js")
    html = await anon_browser.navigate("/")

    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert html.headers["cache-control"] == "no-cache"


async def test_a_conditional_request_for_an_asset_is_a_304(anon_browser: Browser) -> None:
    first = await anon_browser.get("/assets/app-0123abcd.js")
    second = await anon_browser.get(
        "/assets/app-0123abcd.js", headers={"if-none-match": first.headers["etag"]}
    )

    assert second.status_code == 304


async def test_responses_are_gzipped_when_the_client_accepts_it(anon_browser: Browser) -> None:
    """Nothing else compresses when the API is reached directly, and the real
    bundle is a third of its size on the wire with this. The stand-in asset
    is too small to compress, so the schema, also over the threshold, stands in."""
    response = await anon_browser.get("/api/openapi.json", headers={"accept-encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"


async def test_the_spa_refuses_methods_it_cannot_serve(anon_browser: Browser) -> None:
    """A POST to the root is a 405, shaped by the app's own handler."""
    response = await anon_browser.post("/", headers=NAVIGATION)

    assert response.status_code == 405
    assert response.json()["detail"]
