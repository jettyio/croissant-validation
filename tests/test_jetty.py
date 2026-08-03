"""Unit tests for the Jetty pdf2croissant flow (mocked HTTP — no live calls)."""

import httpx
import pytest

from croissant_mcp import jetty


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("JETTY_API_TOKEN_PDF2CROISSANT", "test-token")


def _mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    original_init = httpx.Client.__init__

    def patched_init(self, **kwargs):
        kwargs["transport"] = transport
        original_init(self, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)


def test_render_runbook_substitutes_vars():
    rendered = jetty._render_runbook(
        {"results_dir": "/app/results", "pdf_filename": "paper.pdf", "dataset_name": "", "huggingface_url": "", "email": ""}
    )
    assert "{{pdf_filename}}" not in rendered
    assert "{{results_dir}}" not in rendered
    assert "paper.pdf" in rendered


def test_download_pdf_rejects_non_pdf(monkeypatch):
    _mock_client(monkeypatch, lambda request: httpx.Response(200, content=b"<html>nope</html>"))
    with pytest.raises(jetty.JettyError, match="missing %PDF header"):
        jetty.download_pdf("https://example.com/paper.pdf")


def test_download_pdf_sanitizes_filename(monkeypatch):
    _mock_client(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF-1.4 fake"))
    _, filename = jetty.download_pdf("https://example.com/papers/My%20Paper(v2)")
    assert filename.endswith(".pdf")
    assert " " not in filename and "(" not in filename


def test_launch_run_tolerates_500_with_trajectory(monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        body = request.read().decode()
        assert '"runbook":true' in body
        assert '"model":"gpt-5.6-terra"' in body
        assert '"agent":"codex"' in body
        assert '"model_provider":"openai"' in body
        return httpx.Response(
            500,
            json={"jetty_metadata": {"workflow_id": "wf--abc--traj123", "trajectory_id": "traj123"}},
        )

    _mock_client(monkeypatch, handler)
    run = jetty.launch_run(["storage/paper.pdf"], "paper.pdf")
    assert run == {"trajectory_id": "traj123", "workflow_id": "wf--abc--traj123"}


def test_launch_run_derives_trajectory_from_workflow_suffix(monkeypatch):
    _mock_client(
        monkeypatch,
        lambda request: httpx.Response(200, json={"jetty_metadata": {"workflow_id": "runbook--x--tr999"}}),
    )
    run = jetty.launch_run(["storage/paper.pdf"], "paper.pdf")
    assert run["trajectory_id"] == "tr999"


def test_launch_run_raises_without_trajectory(monkeypatch):
    _mock_client(monkeypatch, lambda request: httpx.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(jetty.JettyError, match="boom"):
        jetty.launch_run(["storage/paper.pdf"], "paper.pdf")


def test_output_files_extraction():
    trajectory = {
        "steps": {
            "one": {"outputs": {"files": [{"path": "a/b/app--results--croissant.json"}]}},
            "two": {"outputs": {}},
            "three": {"outputs": {"files": [{"path": "a/b/app--results--summary.md"}, {"nope": True}]}},
        }
    }
    assert jetty.output_files(trajectory) == [
        "a/b/app--results--croissant.json",
        "a/b/app--results--summary.md",
    ]


def test_missing_token(monkeypatch):
    monkeypatch.delenv("JETTY_API_TOKEN_PDF2CROISSANT")
    with pytest.raises(jetty.JettyError, match="JETTY_API_TOKEN_PDF2CROISSANT"):
        jetty._token()


def test_upload_id_roundtrip():
    path = "pdf2croissant/uploads/abc123/paper.pdf"
    assert jetty.verify_upload_id(jetty.sign_upload_id(path)) == path


def test_upload_id_rejects_tampered_path():
    upload_id = jetty.sign_upload_id("pdf2croissant/uploads/abc123/paper.pdf")
    payload, sig = upload_id.split(".", 1)
    forged = jetty._b64url(b"pdf2croissant/uploads/OTHER/paper.pdf") + "." + sig
    with pytest.raises(jetty.JettyError, match="Invalid upload_id"):
        jetty.verify_upload_id(forged)


def test_upload_id_rejects_garbage():
    for bogus in ("", "no-dot", "not!base64.stuff", "YWJj.YWJj"):
        with pytest.raises(jetty.JettyError, match="Invalid upload_id"):
            jetty.verify_upload_id(bogus)


def test_upload_id_key_depends_on_token(monkeypatch):
    upload_id = jetty.sign_upload_id("storage/paper.pdf")
    monkeypatch.setenv("JETTY_API_TOKEN_PDF2CROISSANT", "different-token")
    with pytest.raises(jetty.JettyError, match="Invalid upload_id"):
        jetty.verify_upload_id(upload_id)


def test_sanitize_filename():
    assert jetty.sanitize_filename("/tmp/My Paper (v2).pdf") == "My_Paper__v2_.pdf"
    assert jetty.sanitize_filename("article/10.1088/pdf") == "pdf.pdf"
    assert jetty.sanitize_filename("") == "paper.pdf"
