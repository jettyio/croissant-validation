import json
from pathlib import Path

from croissant_mcp.validation import validate_document, validate_text

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _titanic() -> dict:
    return json.loads((EXAMPLES / "titanic.json").read_text())


def test_valid_document_passes():
    report = validate_document(_titanic())
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["checks"][0]["name"] == "croissant_schema"


def test_broken_source_reference_fails():
    doc = _titanic()
    del doc["distribution"]
    report = validate_document(doc)
    assert report["valid"] is False
    assert report["errors"]


def test_invalid_example_file_fails():
    doc = json.loads((EXAMPLES / "invalid-not-a-dataset.json").read_text())
    report = validate_document(doc)
    assert report["valid"] is False


def test_valid_text_includes_json_check():
    report = validate_text(json.dumps(_titanic()))
    assert report["valid"] is True
    assert [c["name"] for c in report["checks"]] == ["json", "croissant_schema"]


def test_malformed_json_text():
    report = validate_text("{not json")
    assert report["valid"] is False
    assert report["checks"][0]["name"] == "json"


def test_non_object_json_text():
    report = validate_text("[1, 2, 3]")
    assert report["valid"] is False
