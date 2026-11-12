"""Headers every response gets: browser safety rules and cache rules."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Only this site's own files load or run, the page cannot be framed, and no referrer leaves it.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
# FastAPI's own documentation pages load their scripts from a CDN, so the policy skips them.
_DOCS_PATHS = ("/docs", "/redoc")
_YEAR = 31_536_000
_MONTH = 2_592_000


def cache_rule(path: str) -> str:
    """API answers hold CV text and are never stored. The built frontend files have a hash in
    their name, so a year is safe; fonts change rarely; the page itself is checked every time."""
    if path.startswith("/api/"):
        return "no-store"
    if path.startswith("/assets/"):
        return f"public, max-age={_YEAR}, immutable"
    if path.startswith("/fonts/"):
        return f"public, max-age={_MONTH}"
    return "no-cache"


class ResponseHeaders:
    """Pure ASGI middleware, so streamed responses pass through untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if not path.startswith(_DOCS_PATHS):
                    headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                headers["Cache-Control"] = cache_rule(path)
            await send(message)

        await self.app(scope, receive, send_with_headers)
