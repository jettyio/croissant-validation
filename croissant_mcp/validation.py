"""Croissant JSON-LD validation built on mlcroissant.

Mirrors the checks from the MLCommons croissant-validator health app (and the
earlier mlcbakery MCP server): JSON well-formedness first, then full Croissant
schema validation via ``mlcroissant``.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

import mlcroissant as mlc


class Check(TypedDict):
    name: str
    passed: bool
    message: str


class ValidationReport(TypedDict):
    valid: bool
    checks: list[Check]
    errors: list[str]
    warnings: list[str]
    summary: str


def _split_issue_lines(message: str) -> list[str]:
    """mlcroissant formats issues as a header line followed by `-  ...` bullets."""
    bullets = [line.strip().lstrip("-").strip() for line in message.splitlines() if line.strip().startswith("-")]
    return bullets or [message.strip()]


def _build_report(checks: list[Check], errors: list[str], warnings: list[str]) -> ValidationReport:
    valid = bool(checks) and all(c["passed"] for c in checks)
    if valid:
        summary = "The document is valid Croissant."
        if warnings:
            summary += f" {len(warnings)} warning(s) — see `warnings`."
    else:
        failed = next((c for c in checks if not c["passed"]), None)
        summary = failed["message"] if failed else "Validation failed."
    return ValidationReport(valid=valid, checks=checks, errors=errors, warnings=warnings, summary=summary)


def validate_document(document: dict[str, Any]) -> ValidationReport:
    """Validate a parsed Croissant JSON-LD document against the Croissant schema."""
    checks: list[Check] = []
    errors: list[str] = []
    warnings: list[str] = []

    try:
        dataset = mlc.Dataset(jsonld=document)
    except mlc.ValidationError as e:
        errors.extend(_split_issue_lines(str(e)))
        checks.append(
            Check(
                name="croissant_schema",
                passed=False,
                message=f"Croissant schema validation failed with {len(errors)} error(s).",
            )
        )
    except Exception as e:  # mlcroissant can raise bare exceptions on malformed JSON-LD
        errors.append(f"{type(e).__name__}: {e}")
        checks.append(
            Check(
                name="croissant_schema",
                passed=False,
                message="Croissant validation raised an unexpected error; the document is likely malformed JSON-LD.",
            )
        )
    else:
        issues = dataset.metadata.ctx.issues
        warnings.extend(sorted(issues.warnings))
        checks.append(
            Check(
                name="croissant_schema",
                passed=True,
                message="The document passes Croissant schema validation.",
            )
        )

    return _build_report(checks, errors, warnings)


def validate_text(text: str) -> ValidationReport:
    """Validate Croissant metadata supplied as a JSON string."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        check = Check(name="json", passed=False, message=f"Invalid JSON: {e}")
        return _build_report([check], [str(e)], [])

    if not isinstance(document, dict):
        check = Check(name="json", passed=False, message="Top-level JSON value must be an object (the JSON-LD document).")
        return _build_report([check], ["Top-level JSON value is not an object."], [])

    report = validate_document(document)
    report["checks"].insert(0, Check(name="json", passed=True, message="The input is valid JSON."))
    return report
