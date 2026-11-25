"""What a provider is told about this app, checked against what the app does.

Registration happens out of band, and a provider refuses any URL it was not
given — with an error that reaches the user mid-redirect, not this codebase.
Nothing else here fails early enough to catch a stale registration, so these
tests stand in: the metadata has to name routes that exist, and the client the
dev provider reads at startup has to be the document this app generates.
"""

import json
import re

from app.core.auth import client_metadata
from app.main import app
from tests.helpers import ROOT
from tests.parties import FakeProvider

DEV_CLIENT = ROOT / "services" / "dev-idp" / "src" / "client.json"
PROVIDER_CONFIG = ROOT / "services" / "dev-idp" / "src" / "provider.mjs"
# The dev stack's own origin, which the committed dev client is registered for.
(DEV_APP_URL,) = re.findall(
    r"^APP_URL=(.*)$", (ROOT / "services" / "api" / ".env.dev").read_text(), re.MULTILINE
)


def test_every_registered_url_names_a_route_this_app_serves(provider: FakeProvider) -> None:
    """A renamed route would otherwise leave a registered URL pointing at a 404,
    and the provider would keep sending people to it."""
    metadata = provider.registration

    # The post-logout URL is left out: it is the SPA's login page, served by
    # the frontend, and this app has no route for it.
    for endpoint, url in (
        ("callback", metadata.redirect_uris[0]),
        ("frontchannel_logout", metadata.frontchannel_logout_uri),
        ("backchannel_logout", metadata.backchannel_logout_uri),
        ("jwks", metadata.jwks_uri),
    ):
        # Asked of the mounted app, so the /api prefix is checked as well as
        # the route's own path.
        assert url.path == app.url_path_for(endpoint)


def test_every_registered_url_is_on_the_one_origin(provider: FakeProvider) -> None:
    """The app has a single APP_URL, as it would against a real provider. The
    back-channel URL is no exception: in Compose the provider cannot resolve
    the browser's origin, but that is the provider's problem, and the dev
    provider translates it there rather than this app learning a second name
    for itself."""
    metadata = provider.registration
    origins = {
        url.netloc
        for url in [
            *metadata.redirect_uris,
            *metadata.post_logout_redirect_uris,
            metadata.frontchannel_logout_uri,
            metadata.backchannel_logout_uri,
            metadata.jwks_uri,
        ]
    }
    assert len(origins) == 1, origins


def test_the_dev_client_is_this_apps_own_document() -> None:
    """The dev stack signs in with no clicking only while the committed client
    matches the model. It is generated, not written, so a mismatch means the
    app changed and the client was not regenerated."""
    generated = client_metadata(DEV_APP_URL).model_dump(mode="json")
    assert json.loads(DEV_CLIENT.read_text()) == generated


def test_the_dev_provider_drops_only_front_channel_logout() -> None:
    """node-oidc-provider 9 does not implement Front-Channel Logout, and it
    validates a statically configured client strictly rather than ignoring
    what it does not know, so the dev provider has to drop those two fields. That
    is the whole list: anything else missing from the dev client is a mistake,
    not a version gap. `/auth/frontchannel-logout` is exercised by tests only.
    """
    declared = PROVIDER_CONFIG.read_text().split("const UNIMPLEMENTED = [")[1].split("]")[0]
    assert set(re.findall(r"'([a-z_]+)'", declared)) == {
        "frontchannel_logout_uri",
        "frontchannel_logout_session_required",
    }
