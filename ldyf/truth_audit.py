"""Truth audit -- every number a claim states must come from a cited machine file.

A `doc` is a LIST of claims, each `{"text": <prose>, "cites": [(artefact, field), ...]}`,
and an `artefact` is a JSON file inside `evidence_dir` while a `field` is a
dotted path into it (`a.b.0.c` accepts list indices). `audit_claims` re-reads
each cited file from disk and resolves each cited field, then compares what the
claim SAYS with what the artefacts MEASURE.

It refuses, claim by claim, when:

* the claim cites nothing (no `cites`, or an empty list) -- an uncited claim is
  an assertion, not evidence;
* a citation does not name an artefact at all (the file is not under
  `evidence_dir`, so a claim cannot cite its own prose, an absolute host path, a
  path that climbs out with `..`, or a file that simply does not exist);
* the artefact exists but is not parseable JSON, or has no such field;
* the claim states a number that differs from every number its citations
  measure. Every numeric literal in `text` must equal some cited measured value
  at the precision the claim states it (`12.5` matches 12.53, `12.6` does not),
  and a claim that states a number while citing no numeric field is refused too.
  This is deliberate: "no typed numbers that are not from the record" is only a
  law if stray numerals in prose are caught as well.

A refused claim is REPORTED, not thrown: `audit_claims` returns a report with a
per-claim `verdict` and machine-readable `reasons`, plus a top-level `pass`.
Pass `strict=True` when the caller wants the first refusal raised instead; the
error carries the same reasons.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evidence import _unsafe_relative_path

TRUTH_AUDIT_VERSION = "truth_audit_v1"

# A numeric literal: optional sign, digits, optional single decimal part. The
# lookbehind keeps a version string like "1.27.1" from matching its tail and a
# word like "Phase2" from matching its digit run alone.
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


class TruthAuditError(RuntimeError):
    """Raised when a claim document cannot be audited, or under strict=True."""


def _resolve_field(node: Any, field: str) -> tuple[bool, Any]:
    """Resolve a dotted path. Dict keys by name, lists by decimal index."""
    current = node
    for part in field.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                return False, None
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _numbers_in(text: str) -> list[tuple[str, float]]:
    return [(m.group(0), float(m.group(0))) for m in _NUMBER.finditer(text)]


def _decimals(literal: str) -> int:
    return len(literal.split(".", 1)[1]) if "." in literal else 0


def _resolve_cite(position: int, cite: Any, evidence_dir: Path) -> dict[str, Any]:
    """Resolve one `(artefact, field)` citation, or say exactly why it cannot be."""
    out: dict[str, Any] = {
        "position": position,
        "artefact": None,
        "field": None,
        "value": None,
        "error": None,
    }
    if isinstance(cite, str) or not isinstance(cite, (list, tuple)) or len(cite) != 2:
        out["error"] = (
            f"citation {position} is not an (artefact, field) pair; a citation must name both"
        )
        return out
    artefact, field = cite
    if not isinstance(artefact, str) or not isinstance(field, str):
        out["error"] = f"citation {position} must name the artefact and the field as strings"
        return out
    out["artefact"] = artefact
    out["field"] = field
    if _unsafe_relative_path(artefact):
        out["error"] = (
            f"citation {position} names {artefact!r}, which is not a plain relative path inside "
            "the evidence directory"
        )
        return out
    full = evidence_dir / artefact
    if not full.exists():
        out["error"] = (
            f"citation {position} names artefact {artefact!r}, which does not exist under the "
            "evidence directory"
        )
        return out
    if not full.is_file():
        out["error"] = f"citation {position} names {artefact!r}, which is not a regular file"
        return out
    try:
        parsed = json.loads(full.read_text(encoding="utf-8"))
    except Exception as e:
        out["error"] = (
            f"citation {position}: artefact {artefact!r} is not parseable JSON ({e}), so its "
            "fields cannot be read"
        )
        return out
    found, value = _resolve_field(parsed, field)
    if not found:
        out["error"] = f"citation {position}: artefact {artefact!r} has no field {field!r}"
        return out
    out["value"] = value
    return out


def _audit_one(index: int, claim: Any, evidence_dir: Path) -> dict[str, Any]:
    reasons: list[str] = []
    if not isinstance(claim, dict):
        return {
            "index": index,
            "text": None,
            "verdict": "refused",
            "reasons": [f"claim {index} is not an object with {{text, cites}}"],
            "citations": [],
        }

    text = claim.get("text")
    if not isinstance(text, str) or not text.strip():
        reasons.append(f"claim {index} has no text to audit")
        text = "" if text is None else str(text)

    cites = claim.get("cites")
    if cites is None or not isinstance(cites, (list, tuple)) or len(cites) == 0:
        reasons.append(
            f"claim {index} cites nothing; a claim with no citation is an assertion, not evidence"
        )
        cites = []

    citations = [_resolve_cite(pos, cite, evidence_dir) for pos, cite in enumerate(cites)]
    for citation in citations:
        if citation["error"]:
            reasons.append(citation["error"])

    measured = [
        c["value"]
        for c in citations
        if c["error"] is None
        and isinstance(c["value"], (int, float))
        and not isinstance(c["value"], bool)
    ]
    stated = _numbers_in(text)
    for literal, value in stated:
        if not measured:
            reasons.append(
                f"claim {index} states the number {literal}, but none of its citations "
                "resolves to a measured number"
            )
            continue
        decimals = _decimals(literal)
        if not any(abs(round(float(m), decimals) - value) < 1e-9 for m in measured):
            shown = ", ".join(repr(m) for m in measured[:4])
            reasons.append(
                f"claim {index} states {literal}, which differs from the cited measurement(s) "
                f"{shown}"
            )

    return {
        "index": index,
        "text": text,
        "verdict": "refused" if reasons else "supported",
        "reasons": reasons,
        "citations": citations,
    }


def audit_claims(doc: list, evidence_dir, *, strict: bool = False) -> dict[str, Any]:
    """Audit a list of claims against the artefacts they cite.

    Returns a report whose `pass` is True only when every claim is supported.
    With `strict=True`, raises `TruthAuditError` naming the refusals instead.
    """
    if not isinstance(doc, (list, tuple)):
        raise TruthAuditError(
            "a claim document is a LIST of {text, cites} claims, got "
            f"{type(doc).__name__}"
        )
    base = Path(evidence_dir)
    if not base.is_dir():
        raise TruthAuditError(f"evidence_dir {base} is not a directory")

    audited = [_audit_one(index, claim, base) for index, claim in enumerate(doc)]
    refused = [c["index"] for c in audited if c["verdict"] == "refused"]
    report = {
        "schema_version": TRUTH_AUDIT_VERSION,
        "claims_total": len(audited),
        "supported_claims": len(audited) - len(refused),
        "refused_claims": refused,
        "claims": audited,
        "pass": not refused,
    }
    if strict and refused:
        first = next(c for c in audited if c["verdict"] == "refused")
        raise TruthAuditError(
            f"truth audit refused {len(refused)} of {len(audited)} claim(s) "
            f"(first: claim {first['index']}): " + " | ".join(first["reasons"])
        )
    return report
