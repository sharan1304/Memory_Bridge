"""FastAPI entrypoint: mounts the MCP server and the dashboard API/WebSocket."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import mcp_server
from config import get_settings
from dashboard.api import router as dashboard_router
from dashboard.ws import router as ws_router
from mcp_server import mcp, registered_resource_uris, registered_tool_names

logger = logging.getLogger(__name__)
settings = get_settings()

# Claude Code connects over streamable-HTTP at /mcp. Codex, per its own MCP
# client, discovers tools over SSE instead - so the same two tools
# (get_context, checkpoint) are also served at /sse via fastmcp's SSE
# transport. Both apps are built from the same `mcp` FastMCP instance, so
# tool registration only happens once in mcp_server.py either way.
#
# sse_app is built with path="/sse" (its own absolute route path) rather
# than "/", and its routes are merged directly into `app` below instead of
# nested under another app.mount("/sse", ...) - nesting it would otherwise
# make a bare `GET /sse` (no trailing slash) 307-redirect to "/sse/" before
# Starlette's inner router can match it, since the sub-app's own route is
# only registered at "/".  Building it with the absolute path avoids that
# extra hop so `curl http://localhost:8001/sse` streams directly.
mcp_app = mcp.http_app(path="/", transport="streamable-http")
sse_app = mcp.http_app(path="/sse", transport="sse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tool_names = await registered_tool_names()
    resource_uris = await registered_resource_uris()
    print(f"MENNBridge MCP tools registered: {tool_names}", flush=True)
    print(f"MENNBridge MCP resources registered: {resource_uris}", flush=True)
    try:
        await mcp_server.adapter.warmup()
    except Exception:
        # Tools still start; get_context falls back until Qdrant is reachable.
        logger.exception("memory store warmup failed")
    async with mcp_app.lifespan(app):
        async with sse_app.lifespan(app):
            yield


app = FastAPI(title="MENNBridge", lifespan=lifespan)


@app.middleware("http")
async def mcp_curl_discovery(request: Request, call_next):
    """Human-readable discovery for curl; MCP clients use POST /mcp."""
    accept = request.headers.get("accept", "")
    wants_mcp_stream = "text/event-stream" in accept
    if request.method == "GET" and request.url.path in ("/mcp", "/mcp/") and not wants_mcp_stream:
        return JSONResponse(
            {
                "server": "mennbridge",
                "transport": "streamable-http",
                "endpoint": "/mcp",
                "tools": await registered_tool_names(),
                "resources": await registered_resource_uris(),
            }
        )
    return await call_next(request)


app.mount("/mcp", mcp_app)
app.router.routes.extend(sse_app.routes)
app.include_router(dashboard_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "project": settings.mennbridge_project}
