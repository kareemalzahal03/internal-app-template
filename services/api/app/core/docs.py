"""The interactive API docs: FastAPI's Swagger UI page, under its own policy,
sending calls as the signed-in browser does."""

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from app.core.auth import csrf_header

# Swagger UI runs beside the signed-in session, so the browser runs only the
# exact files pinned here: a hash that does not match blocks the file. To
# upgrade, change the version and take each file's hash from the package on
# npm (`openssl dgst -sha384 -binary FILE | openssl base64 -A`).
SWAGGER_UI = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.34.1"
SWAGGER_JS = f"{SWAGGER_UI}/swagger-ui-bundle.js"
SWAGGER_JS_HASH = "sha384-XFYN47VzPiDY6qPtxYKg0nqUeW/upo20xf1j2SUE7gT/i35FJB4cuS/71Iegzk8Z"
SWAGGER_CSS = f"{SWAGGER_UI}/swagger-ui.css"
SWAGGER_CSS_HASH = "sha384-4c3vsE5f+trhFyHrFrLM1fFGUn531NIaC7dcqEWIJdoRQJ5CkJbSuSCwXLpaS1KF"

# Swagger UI loads from a CDN and starts with an inline script, so its page
# allows both. It shows only this app's own schema.
DOCS_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)

SWAGGER_UI_PARAMETERS = {
    # A search box over the routes, by tag.
    "filter": True,
    # How long each call took, beside its response.
    "displayRequestDuration": True,
    # Every route can be sent at once, without first clicking "Try it out".
    "tryItOutEnabled": True,
}

# Fills in the X-CSRF header under "Authorize", as the SPA sends it. Swagger UI
# can fill it only once it has loaded the schema, and refuses until then. A
# schema that never loads stops the trying after ten seconds.
PREAUTHORIZE_CSRF = f"""
<script>
const preauthorized = setInterval(() => {{
    if (ui.preauthorizeApiKey("{csrf_header.scheme_name}", "1")) clearInterval(preauthorized);
}}, 100);
setTimeout(() => clearInterval(preauthorized), 10000);
</script>
"""

docs_router = APIRouter()


@docs_router.get("/docs", include_in_schema=False)
async def swagger_ui(request: Request) -> HTMLResponse:
    """The interactive API docs, signed in as the browser is."""
    page = get_swagger_ui_html(
        openapi_url=request.app.openapi_url or "",
        title=request.app.title,
        swagger_js_url=SWAGGER_JS,
        swagger_css_url=SWAGGER_CSS,
        swagger_favicon_url="/favicon.svg",
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
    )
    html = (
        bytes(page.body)
        .decode()
        # Subresource Integrity, which a cross-origin file checks only in CORS mode.
        .replace(
            f'src="{SWAGGER_JS}"',
            f'src="{SWAGGER_JS}" integrity="{SWAGGER_JS_HASH}" crossorigin="anonymous"',
        )
        .replace(
            f'href="{SWAGGER_CSS}"',
            f'href="{SWAGGER_CSS}" integrity="{SWAGGER_CSS_HASH}" crossorigin="anonymous"',
        )
        .replace("</body>", f"{PREAUTHORIZE_CSRF}</body>")
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": DOCS_POLICY})
