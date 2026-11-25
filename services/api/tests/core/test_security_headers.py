"""Every response carries the security headers, and the two pages that need a
different Content-Security-Policy carry their own instead.

The SPA's policy allows nothing but this origin. That holds only while the
build has no inline code and loads nothing from elsewhere, which these tests
cannot see: the page they are served is a stand-in, not the build.
"""

import re

from pytest import mark

from tests.helpers import cause_a_server_error
from tests.parties import Browser, FakeProvider

pytestmark = mark.asyncio(loop_scope="session")


def directives(policy: str) -> dict[str, str]:
    """A Content-Security-Policy as {directive: its sources}."""
    pairs = (part.strip().partition(" ") for part in policy.split(";"))
    return {name: sources for name, _, sources in pairs}


async def test_the_spa_loads_only_from_this_origin_and_cannot_be_framed(
    anon_browser: Browser,
) -> None:
    """Injected markup can neither run inline script nor load one from
    elsewhere, and no other site can frame the app to trick a click. Over
    HTTPS, browsers then refuse plain HTTP to the host."""
    response = await anon_browser.navigate("/")

    policy = directives(response.headers["content-security-policy"])
    assert policy["default-src"] == "'self'"
    assert policy["frame-ancestors"] == "'none'"
    assert policy["object-src"] == "'none'"
    assert policy["base-uri"] == "'none'"
    assert policy["form-action"] == "'self'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["strict-transport-security"] == "max-age=31536000"


async def test_api_responses_and_errors_carry_them_too(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """A JSON body opened in a tab, or sniffed as HTML, is a page like any
    other. The 500 is answered below the middleware that adds them, so it
    has them as every other response does."""
    responses = [
        await anon_browser.get("/api/health"),
        await anon_browser.get("/api/does-not-exist"),
        await cause_a_server_error(provider),
    ]
    assert [r.status_code for r in responses] == [200, 404, 500]
    for response in responses:
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"


async def test_front_channel_logout_can_be_framed(
    anon_browser: Browser, provider: FakeProvider
) -> None:
    """The provider's logout page loads it in an iframe, so its policy has no
    frame-ancestors, and loads nothing because the page is empty."""
    response = await anon_browser.navigate(provider.frontchannel_logout_url())

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "default-src 'none'"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_api_docs_may_load_swagger_ui_and_nothing_more(anon_browser: Browser) -> None:
    """Swagger UI comes from a CDN and starts with an inline script. Its page
    allows those and is otherwise as strict as the rest."""
    response = await anon_browser.navigate("/api/docs")

    assert response.status_code == 200
    policy = directives(response.headers["content-security-policy"])
    assert "https://cdn.jsdelivr.net" in policy["script-src"]
    assert policy["frame-ancestors"] == "'none'"


async def test_the_api_docs_run_only_the_pinned_swagger_ui(anon_browser: Browser) -> None:
    """The page runs beside the signed-in session, so every file it loads
    from elsewhere carries a hash, and a changed file is blocked."""
    page = (await anon_browser.navigate("/api/docs")).text

    external = re.findall(r"<(?:script|link)\b[^>]*(?:src|href)=\"https://[^>]*>", page)
    assert len(external) == 2, external
    for tag in external:
        assert 'integrity="sha384-' in tag, tag
        assert 'crossorigin="anonymous"' in tag, tag


async def test_redoc_is_not_served(anon_browser: Browser) -> None:
    """Its page would need a policy of its own, and /api/docs covers the same."""
    response = await anon_browser.navigate("/redoc")

    assert "redoc" not in response.text.lower()


async def test_hsts_is_never_sent_over_plain_http(anon_browser: Browser) -> None:
    """RFC 6797 §7.2. As in local dev, or behind a proxy not trusted to say
    the browser used HTTPS."""
    response = await anon_browser.navigate(str(anon_browser.base_url.copy_with(scheme="http")))

    assert "strict-transport-security" not in response.headers
