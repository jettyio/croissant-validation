"""End-to-end stateless MCP requests over Streamable HTTP — no handshake, no session."""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from croissant_mcp.server import build_app

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2026-07-28",
}

# The 2026-07-28 stateless envelope: every request carries its protocol
# version and client capabilities in params._meta — this replaces the
# initialize handshake entirely.
_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


@pytest.fixture()
def client():
    with TestClient(build_app()) as c:
        yield c


def _rpc(method: str, params: dict | None = None, id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": {**(params or {}), "_meta": _META}}


def test_landing_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Croissant Validator" in resp.text


def test_tools_list_without_handshake(client):
    resp = client.post(
        "/mcp",
        headers={**BASE_HEADERS, "Mcp-Method": "tools/list"},
        json=_rpc("tools/list"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = {t["name"] for t in body["result"]["tools"]}
    assert names == {"validate_croissant", "validate_croissant_url"}


def test_tools_call_valid_document(client):
    doc = json.loads((EXAMPLES / "titanic.json").read_text())
    resp = client.post(
        "/mcp",
        headers={**BASE_HEADERS, "Mcp-Method": "tools/call", "Mcp-Name": "validate_croissant"},
        json=_rpc("tools/call", {"name": "validate_croissant", "arguments": {"croissant": doc}}),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result["structuredContent"]["valid"] is True


def test_tools_call_invalid_document(client):
    resp = client.post(
        "/mcp",
        headers={**BASE_HEADERS, "Mcp-Method": "tools/call", "Mcp-Name": "validate_croissant"},
        json=_rpc("tools/call", {"name": "validate_croissant", "arguments": {"croissant": {"@type": "sc:Dataset"}}}),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result["structuredContent"]["valid"] is False
    assert result["structuredContent"]["errors"]


def test_two_independent_servers_share_nothing():
    """The stateless core: bare requests against two fresh app instances both succeed."""
    for _ in range(2):
        with TestClient(build_app()) as client:
            resp = client.post(
                "/mcp",
                headers={**BASE_HEADERS, "Mcp-Method": "tools/list"},
                json=_rpc("tools/list"),
            )
            assert resp.status_code == 200
            assert "Mcp-Session-Id" not in resp.headers
