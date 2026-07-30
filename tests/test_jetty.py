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
        assert '"model":"openai/gpt-5.6-terra"' in body
        assert '"agent":"codex"' in body
        assert '"model_provider":"openrouter"' in body
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
