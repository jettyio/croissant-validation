"""Jetty-backed pdf2croissant flow: submit a paper, poll the run, fetch outputs.

Mirrors the API flow of https://mlcroissant.jetty.bot (jettyio/pdf2croissant):
upload the PDF to Jetty storage, launch the runbook run over the OpenAI-compatible
endpoint with the `jetty` extension block, then poll the trajectory and download
output files. The runbook is vendored verbatim from jettyio/pdf2croissant.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Any

import httpx

from croissant_mcp import __version__

FLOWS_API = "https://flows-api.jetty.io"
COLLECTION = "pdf2croissant"
TASK = "pdf2mlcroissant"
SNAPSHOT = "python312-uv"
# Internal choice, deliberately not exposed through the MCP tool surface.
# The request's agent/model override the runbook frontmatter. Native OpenAI:
# credentials come from the collection's provider-token config on the Jetty
# side, not from anything this server sends.
AGENT = "codex"
MODEL = "gpt-5.6-terra"
MODEL_PROVIDER = "openai"
RESULTS_DIR = "/app/results"

PDF_MAX_BYTES = 15 * 1024 * 1024
_USER_AGENT = f"croissant-validation-mcp/{__version__} (+https://croissant-validation.jetty.bot)"
_RUNBOOK_PATH = Path(__file__).parent / "pdf2croissant_runbook.md"


class JettyError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("JETTY_API_TOKEN_PDF2CROISSANT")
    if not token:
        raise JettyError("JETTY_API_TOKEN_PDF2CROISSANT is not set")
    return token


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Authorization": f"Bearer {_token()}"},
    )


def _render_runbook(template_vars: dict[str, str]) -> str:
    raw = _RUNBOOK_PATH.read_text()
    return re.sub(r"\{\{(\w+)\}\}", lambda m: template_vars.get(m.group(1), m.group(0)), raw)


def sanitize_filename(name: str) -> str:
    """Storage-safe .pdf filename: basename only, simple ASCII."""
    filename = Path(name).name or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return re.sub(r"[^A-Za-z0-9._-]", "_", filename)


def download_pdf(pdf_url: str) -> tuple[bytes, str]:
    """Download a PDF (15 MB cap) and return (content, filename)."""
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/pdf,*/*"},
    ) as client:
        with client.stream("GET", pdf_url) as response:
            response.raise_for_status()
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > PDF_MAX_BYTES:
                    raise JettyError(f"PDF exceeds the {PDF_MAX_BYTES // (1024 * 1024)} MB limit.")

    if not body.startswith(b"%PDF"):
        raise JettyError("The URL did not return a PDF (missing %PDF header).")

    return body, sanitize_filename(httpx.URL(pdf_url).path)


def upload_pdf(content: bytes, filename: str) -> list[str]:
    """Upload the PDF to Jetty sandbox storage; returns storage file_paths."""
    with _client() as client:
        response = client.post(
            f"{FLOWS_API}/api/v1/sandbox/upload",
            files={"files": (filename, content, "application/pdf")},
        )
        if response.status_code >= 400:
            raise JettyError(f"Upload failed: {response.status_code} {response.text[:300]}")
        return response.json()["file_paths"]


def _upload_signing_key() -> bytes:
    # Derived from the Jetty token so the stateless server needs no extra
    # secret: an upload id must be mintable and verifiable across serverless
    # instances without any shared session store.
    return hashlib.sha256(b"croissant-mcp-upload-id:" + _token().encode()).digest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_upload_id(file_path: str) -> str:
    """Encode a storage path as a self-contained, tamper-evident upload id."""
    raw = file_path.encode()
    sig = hmac.new(_upload_signing_key(), raw, hashlib.sha256).digest()[:16]
    return f"{_b64url(raw)}.{_b64url(sig)}"


def verify_upload_id(upload_id: str) -> str:
    """Decode an upload id back to its storage path, rejecting anything not minted by us."""
    try:
        payload, sig = upload_id.split(".", 1)
        raw = _b64url_decode(payload)
        expected = hmac.new(_upload_signing_key(), raw, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            raise ValueError
        return raw.decode()
    except (ValueError, UnicodeDecodeError):
        raise JettyError("Invalid upload_id — obtain one by POSTing the PDF to /upload.") from None


def launch_run(
    file_paths: list[str],
    pdf_filename: str,
    dataset_name: str = "",
    huggingface_url: str = "",
) -> dict[str, str]:
    """Launch the pdf2croissant runbook run; returns trajectory_id + workflow_id."""
    template_vars = {
        "results_dir": RESULTS_DIR,
        "pdf_filename": pdf_filename,
        "dataset_name": dataset_name,
        "huggingface_url": huggingface_url,
        "email": "",
    }
    user_parts = [
        "Generate a Croissant JSON-LD file for the dataset described in the uploaded PDF.",
        f"PDF filename: {pdf_filename}",
    ]
    if dataset_name:
        user_parts.append(f"Dataset name: {dataset_name}")
    if huggingface_url:
        user_parts.append(f"HuggingFace URL: {huggingface_url}")

    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _render_runbook(template_vars)},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
        "stream": False,
        "jetty": {
            "runbook": True,
            "agent": AGENT,
            "model_provider": MODEL_PROVIDER,
            "collection": COLLECTION,
            "task": TASK,
            "snapshot": SNAPSHOT,
            "timeout_sec": 600,
            "timeout_hint": 5,
            "template_variables": template_vars,
            "labels": [{"key": "source", "value": "croissant-validation-mcp"}],
            "file_paths": file_paths,
        },
    }

    with _client() as client:
        response = client.post(f"{FLOWS_API}/v1/chat/completions", json=body)

    # The upstream may return 500 even when the task started successfully —
    # trust the presence of trajectory metadata over the status code.
    try:
        data = response.json()
    except ValueError:
        data = None

    metadata = (data or {}).get("jetty_metadata") or {}
    workflow_id = metadata.get("workflow_id") or (data or {}).get("id") or ""
    trajectory_id = metadata.get("trajectory_id") or (workflow_id.split("--")[-1] if workflow_id else "")

    if not trajectory_id:
        detail = None
        if isinstance(data, dict):
            error = data.get("error")
            detail = error.get("message") if isinstance(error, dict) else error or data.get("detail")
        raise JettyError(f"Failed to launch run: {detail or f'HTTP {response.status_code}'}")

    return {"trajectory_id": trajectory_id, "workflow_id": workflow_id}


def get_trajectory(trajectory_id: str) -> dict[str, Any]:
    with _client() as client:
        response = client.get(f"{FLOWS_API}/api/v1/db/trajectory/{COLLECTION}/{TASK}/{trajectory_id}")
        if response.status_code >= 400:
            raise JettyError(f"Failed to get trajectory: {response.status_code} {response.text[:300]}")
        return response.json()


def output_files(trajectory: dict[str, Any]) -> list[str]:
    """All output file paths across trajectory steps."""
    paths: list[str] = []
    for step in (trajectory.get("steps") or {}).values():
        files = (step or {}).get("outputs", {}).get("files") or []
        for f in files:
            if isinstance(f, dict) and f.get("path"):
                paths.append(f["path"])
    return paths


def download_output(trajectory_id: str, filename: str) -> bytes:
    """Download an output file (matched by suffix) from a run."""
    trajectory = get_trajectory(trajectory_id)
    paths = output_files(trajectory)
    match = next((p for p in paths if p.endswith(filename)), None)
    if match is None:
        raise JettyError(
            f"No output file matching {filename!r} in run {trajectory_id} "
            f"(status: {trajectory.get('status')}, files: {[p.rsplit('/', 1)[-1] for p in paths]})"
        )
    with _client() as client:
        response = client.get(f"{FLOWS_API}/api/v1/file/{match}")
        if response.status_code >= 400:
            raise JettyError(f"Failed to download {match}: {response.status_code}")
        return response.content
