"""Manifest encoding contract: UTF-8, no BOM, valid JSON. Pure Python.

Review artifacts must be readable by any ordinary consumer::

    json.load(open(path, encoding="utf-8"))

A UTF-8 byte-order mark breaks exactly that call, so every manifest this
pipeline produces is written through :func:`write_manifest_json`, which can
never emit a BOM and refuses to return until the bytes on disk round-trip as
strict UTF-8 JSON. :func:`require_clean_utf8_json` is the standalone guard
for verifying any existing manifest file.
"""

import json
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"


def require_clean_utf8_json(path: str | Path) -> dict:
    """Return the parsed document, refusing BOMs and non-strict UTF-8.

    Raises:
        ValueError: If the file starts with a UTF-8 BOM.
        UnicodeDecodeError: If the bytes are not strict UTF-8.
        json.JSONDecodeError: If the text is not valid JSON.
    """
    data = Path(path).read_bytes()
    if data.startswith(UTF8_BOM):
        raise ValueError(f"{path} starts with a UTF-8 BOM; manifests must be plain UTF-8")
    document = json.loads(data.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must hold a JSON object at the top level")
    return document


def write_manifest_json(path: str | Path, document: dict) -> None:
    """Write one manifest as plain UTF-8 (never a BOM) and verify it back.

    The write itself cannot produce a BOM; the read-back guard exists so any
    future regression -- a changed writer, a filesystem surprise -- fails the
    generation run loudly instead of shipping a broken artifact.
    """
    target = Path(path)
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    require_clean_utf8_json(target)
