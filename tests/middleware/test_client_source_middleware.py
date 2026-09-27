# SPDX-License-Identifier: MIT
# ============================================================
# Task B-10: the desktop Electron app's `x-ainxt-surface: desktop` header
# (injected by desktop/src/main.js's webRequest.onBeforeSendHeaders) has to
# resolve to request.state.client_source == "desktop" for
# gateway.py's chat-streaming path (and anything else keyed off
# client_source) to ever see the desktop app as distinct from a plain
# browser tab. No test exercised middleware/client_source_middleware.py's
# actual header-detection logic through a real HTTP request before this --
# this file closes that gap with a minimal standalone Starlette app rather
# than importing all of gateway.py (a ~16k line module with heavy
# import-time side effects) just to reach one middleware class.
# ============================================================

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from middleware.client_source_middleware import ClientSourceMiddleware


def _echo(request):
    return JSONResponse({"client_source": request.state.client_source})


def _make_client() -> TestClient:
    app = Starlette(routes=[Route("/echo", _echo)], middleware=[])
    app.add_middleware(ClientSourceMiddleware)
    return TestClient(app)


def test_x_ainxt_surface_desktop_header_resolves_to_desktop_client_source():
    client = _make_client()
    resp = client.get("/echo", headers={"x-ainxt-surface": "desktop"})
    assert resp.json()["client_source"] == "desktop"


def test_x_ainxt_surface_desktop_response_echoes_detected_client_header():
    """response.headers["x-ainxt-client-detected"] is the debugging echo the
    middleware's own docstring documents -- pinning it here too since it's
    the one signal visible from outside the process (e.g. browser devtools)
    without server-side log access."""
    client = _make_client()
    resp = client.get("/echo", headers={"x-ainxt-surface": "desktop"})
    assert resp.headers["x-ainxt-client-detected"] == "desktop"


def test_no_surface_header_defaults_to_platform():
    client = _make_client()
    resp = client.get("/echo")
    assert resp.json()["client_source"] == "platform"


def test_explicit_cli_client_header_wins_over_a_stale_cowork_surface_header():
    """Documented precedence (middleware's own docstring, detection order
    point 2): a standalone CLI user whose config.toml still carries
    x-ainxt-surface: cowork from a prior Buddy session must still resolve
    to CLI, not buddy."""
    client = _make_client()
    resp = client.get("/echo", headers={"x-ainxt-surface": "cowork", "x-ainxt-client": "cli/1.0.0"})
    assert resp.json()["client_source"] == "cli"


def test_surface_desktop_is_checked_before_any_client_header():
    """Detection order point 1: x-ainxt-surface: desktop is checked first,
    so even an unrelated x-ainxt-client value never overrides it."""
    client = _make_client()
    resp = client.get("/echo", headers={"x-ainxt-surface": "desktop", "x-ainxt-client": "browser-agent/1.0"})
    assert resp.json()["client_source"] == "desktop"
