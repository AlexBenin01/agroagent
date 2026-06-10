"""Bearer auth sull'endpoint MCP (confronto constant-time)."""
import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class MCPBearerAuthMiddleware:
    """Middleware ASGI puro: richiede `Authorization: Bearer <token>` su /mcp.

    Gli endpoint /api, /events e /images restano pubblici (consumati dal browser).
    """

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/mcp" or path.startswith("/mcp/"):
                auth = Headers(scope=scope).get("authorization", "").encode()
                if not hmac.compare_digest(auth, self.expected):
                    response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
