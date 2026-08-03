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
    assert names == {
        "validate_croissant",
        "validate_croissant_url",
        "pdf_to_croissant",
        "croissant_run_status",
        "croissant_run_result",
    }


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


# --- /upload side door -------------------------------------------------------

PDF_BYTES = b"%PDF-1.4 fake body for tests"


@pytest.fixture()
def jetty_env(monkeypatch):
    monkeypatch.setenv("JETTY_API_TOKEN_PDF2CROISSANT", "test-token")


def test_upload_multipart_returns_verifiable_id(client, jetty_env, monkeypatch):
    from croissant_mcp import jetty

    seen = {}

    def fake_upload(content, filename):
        seen["content"], seen["filename"] = content, filename
        return [f"pdf2croissant/uploads/xyz/{filename}"]

    monkeypatch.setattr(jetty, "upload_pdf", fake_upload)
    resp = client.post("/upload", files={"file": ("My Paper.pdf", PDF_BYTES, "application/pdf")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "My_Paper.pdf"
    assert body["size_bytes"] == len(PDF_BYTES)
    assert seen["content"] == PDF_BYTES
    assert jetty.verify_upload_id(body["upload_id"]) == "pdf2croissant/uploads/xyz/My_Paper.pdf"


def test_upload_raw_body(client, jetty_env, monkeypatch):
    from croissant_mcp import jetty

    monkeypatch.setattr(jetty, "upload_pdf", lambda content, filename: [f"p/u/{filename}"])
    resp = client.post(
        "/upload?filename=paper.pdf",
        content=PDF_BYTES,
        headers={"Content-Type": "application/pdf"},
    )
    assert resp.status_code == 200, resp.text
    assert jetty.verify_upload_id(resp.json()["upload_id"]) == "p/u/paper.pdf"


def test_upload_rejects_non_pdf(client, jetty_env):
    resp = client.post("/upload", files={"file": ("nope.pdf", b"<html>", "text/html")})
    assert resp.status_code == 400
    assert "%PDF" in resp.json()["error"]


def test_upload_rejects_missing_file_field(client, jetty_env):
    resp = client.post("/upload", files={"wrong": ("a.pdf", PDF_BYTES, "application/pdf")})
    assert resp.status_code == 400
    assert "field 'file'" in resp.json()["error"]


def test_upload_jetty_failure_maps_to_502(client, jetty_env, monkeypatch):
    from croissant_mcp import jetty

    def boom(content, filename):
        raise jetty.JettyError("Upload failed: 500 nope")

    monkeypatch.setattr(jetty, "upload_pdf", boom)
    resp = client.post("/upload", files={"file": ("a.pdf", PDF_BYTES, "application/pdf")})
    assert resp.status_code == 502
    assert "Upload failed" in resp.json()["error"]


def _call_pdf_to_croissant(client, arguments):
    return client.post(
        "/mcp",
        headers={**BASE_HEADERS, "Mcp-Method": "tools/call", "Mcp-Name": "pdf_to_croissant"},
        json=_rpc("tools/call", {"name": "pdf_to_croissant", "arguments": arguments}),
    )


def test_pdf_to_croissant_accepts_upload_id(client, jetty_env, monkeypatch):
    from croissant_mcp import jetty

    launched = {}

    def fake_launch(file_paths, filename, dataset_name="", huggingface_url=""):
        launched["file_paths"], launched["filename"] = file_paths, filename
        return {"trajectory_id": "tr123", "workflow_id": "pdf2croissant-pdf2mlcroissant--tr123"}

    monkeypatch.setattr(jetty, "launch_run", fake_launch)
    upload_id = jetty.sign_upload_id("pdf2croissant/uploads/xyz/paper.pdf")
    resp = _call_pdf_to_croissant(client, {"upload_id": upload_id})
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result.get("isError") is not True, result
    assert result["structuredContent"]["trajectory_id"] == "tr123"
    assert launched["file_paths"] == ["pdf2croissant/uploads/xyz/paper.pdf"]
    assert launched["filename"] == "paper.pdf"


def test_pdf_to_croissant_rejects_bad_upload_id(client, jetty_env):
    resp = _call_pdf_to_croissant(client, {"upload_id": "forged.nonsense"})
    result = resp.json()["result"]
    assert result["isError"] is True
    assert "Invalid upload_id" in json.dumps(result["content"])


def test_pdf_to_croissant_requires_exactly_one_source(client, jetty_env):
    for arguments in ({}, {"pdf_url": "https://x.test/a.pdf", "upload_id": "abc.def"}):
        resp = _call_pdf_to_croissant(client, arguments)
        result = resp.json()["result"]
        assert result["isError"] is True
        assert "exactly one" in json.dumps(result["content"])
