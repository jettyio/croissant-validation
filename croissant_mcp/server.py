"""Stateless MCP server (spec 2026-07-28) for validating MLCommons Croissant metadata.

Built on the MCP Python SDK v2. Every request is self-contained — no initialize
handshake, no Mcp-Session-Id — so the server runs happily on serverless
infrastructure behind any load balancer.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse

from croissant_mcp import __version__
from croissant_mcp.landing import LANDING_HTML
from croissant_mcp.validation import ValidationReport, validate_document, validate_text

_FETCH_TIMEOUT_SECONDS = 20
_FETCH_MAX_BYTES = 10 * 1024 * 1024
_USER_AGENT = f"croissant-validation-mcp/{__version__} (+https://croissant-validation.jetty.bot)"

mcp = MCPServer(
    name="croissant-validation",
    title="Croissant Validator",
    description=(
        "Validates MLCommons Croissant dataset metadata (JSON-LD) using the "
        "official mlcroissant library."
    ),
    website_url="https://croissant-validation.jetty.bot",
    version=__version__,
    instructions=(
        "Use `validate_croissant` with the Croissant JSON-LD document (as an "
        "object or a JSON string) to check it against the Croissant schema. "
        "Use `validate_croissant_url` to fetch and validate metadata hosted at "
        "a URL (e.g. a Hugging Face dataset's /croissant endpoint). A report "
        "lists each check, blocking errors, and non-blocking warnings."
    ),
)


@mcp.tool()
def validate_croissant(croissant: dict[str, Any] | str) -> ValidationReport:
    """Validate a Croissant JSON-LD document against the MLCommons Croissant schema.

    Accepts the metadata either as a JSON object or as a JSON string. Returns a
    report with per-check results (`json`, `croissant_schema`), blocking
    `errors`, and non-blocking `warnings` (recommended-but-missing properties).
    """
    if isinstance(croissant, str):
        return validate_text(croissant)
    return validate_document(croissant)


@mcp.tool()
def validate_croissant_url(url: str) -> ValidationReport:
    """Fetch Croissant JSON-LD metadata from a URL and validate it.

    Works with any URL serving Croissant metadata, e.g.
    `https://huggingface.co/api/datasets/<id>/croissant`. Responses are capped
    at 10 MB.
    """
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json, application/ld+json"},
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > _FETCH_MAX_BYTES:
                        raise ValueError(f"Response exceeds the {_FETCH_MAX_BYTES // (1024 * 1024)} MB limit.")
    except (httpx.HTTPError, ValueError) as e:
        return ValidationReport(
            valid=False,
            checks=[{"name": "fetch", "passed": False, "message": f"Could not fetch {url}: {e}"}],
            errors=[str(e)],
            warnings=[],
            summary=f"Could not fetch {url}.",
        )

    report = validate_text(body.decode("utf-8", errors="replace"))
    report["checks"].insert(0, {"name": "fetch", "passed": True, "message": f"Fetched {len(body)} bytes from {url}."})
    return report


@mcp.custom_route("/", methods=["GET"])
async def homepage(request: Request) -> HTMLResponse:
    return HTMLResponse(LANDING_HTML)


def build_app():
    """Build a fresh ASGI app; each instance owns one session manager (run-once).

    Stateless + plain-JSON responses: every POST is independent, ideal for
    serverless. DNS-rebinding protection is disabled because the public
    endpoint serves arbitrary Host headers and holds no ambient credentials.
    """
    return mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


app = build_app()
