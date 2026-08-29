"""Phase 34 caption serialization publisher -- publish, verified no-op and refusal laws.

Every test calls the real publisher against a synthetic, standalone-valid Phase 32
caption plan (positional ids, closing accounting; the ep1 transition 3-cue variant
by default, one baseline ep0 variant). The publisher's FIRST act -- the full locked
Phase 32 source-verification gate over eight real documents -- is bypassed by the
autouse fixture below: the gate's own truth is proven by the locked Phase 32 suite
(and by this package's conftest), so these tests target Phase 34's own laws:
single-capture bytes, the verified no-op, handled-refusal cleanup, crash-evidence
survival and the staged-name seam.
"""

import json
import shutil
from pathlib import Path

import pytest

import living_diorama.caption_serialization.caption_serialization_publisher as publisher_module
from living_diorama.caption import validate_episode_caption_plan
from living_diorama.caption_serialization.caption_serialization_audit import (
    audit_caption_serialization_directory,
)
from living_diorama.caption_serialization.caption_serialization_publisher import (
    publish_episode_caption_serialization,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    SRT_SUFFIX,
    VTT_SUFFIX,
    WRITING_SUFFIX,
    CaptionSerializationRefused,
    caption_serialization_id,
    sidecar_filename,
)
from living_diorama.caption_serialization.caption_serialization_staging import (
    CaptionSerializationDirectoryRefused,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

FINAL_NAME = caption_serialization_id(mode="transition", episode=1, previous_episode=0)
"""The deterministic final directory name for the default ep1 transition plan."""


@pytest.fixture(autouse=True)
def _bypass_phase_32_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the full locked Phase 32 gate, keeping the standalone Phase 32 schema.

    The publisher's first act is ``validate_episode_caption_plan_against_sources``
    over eight real documents -- building that chain belongs to this package's
    conftest. These tests target Phase 34's own laws, so the gate is replaced by a
    fake that runs the standalone Phase 32 schema validator on the caption plan:
    exactly the document the real gate would hand back after verification, and the
    only document these tests ever supply.
    """

    def _fake_gate(caption_plan: object, *args: object, **kwargs: object) -> dict[str, object]:
        return validate_episode_caption_plan(caption_plan)

    monkeypatch.setattr(
        publisher_module, "validate_episode_caption_plan_against_sources", _fake_gate
    )


def _make_caption_plan(
    *,
    texts: list[str] | None = None,
    mode: str = "transition",
    episode: int = 1,
    previous_episode: int | None = 0,
    fps: int = 24,
    presentation_frames_total: int = 120,
) -> dict[str, object]:
    """Return a standalone-valid Episode Caption Plan V1 with closing accounting."""
    if texts is None:
        texts = [
            "First caption sentence.",
            "Second caption sentence.",
            "Third caption sentence.",
        ]
    frames_per_cue = presentation_frames_total // len(texts)
    captions: list[dict[str, object]] = []
    start = 1
    for position, text in enumerate(texts, start=1):
        end = start + frames_per_cue - 1
        captions.append(
            {
                "caption_id": f"caption_{position:04d}",
                "caption_text": text,
                "presentation_end_frame": end,
                "presentation_start_frame": start,
                "realization_id": f"realization_{position:04d}",
                "unit_id": f"unit_{position:04d}",
                "window_id": f"window_{position:04d}",
            }
        )
        start = end + 1
    document: dict[str, object] = {
        "accounting": {
            "caption_frames_total": presentation_frames_total,
            "captions_total": len(texts),
            "uncaptioned_frames_total": 0,
        },
        "captions": captions,
        "clock": {"fps": fps, "presentation_frames_total": presentation_frames_total},
        "format": "living_diorama_episode_caption_plan",
        "policy": "caption_policy_v1",
        "schema_version": 1,
        "source": {
            "episode": episode,
            "mode": mode,
            "presentation_plan_sha256": "0" * 64,
            "presentation_schema_version": 1,
            "previous_episode": previous_episode if mode == "transition" else None,
            "realization_plan_sha256": "1" * 64,
            "realization_schema_version": 1,
        },
    }
    return validate_episode_caption_plan(document)


def _plan_bytes(plan: dict[str, object]) -> bytes:
    """Return the canonical byte form of one synthetic plan."""
    return dumps_canonical(plan, "caption plan")


def _publish(
    output_root: Path,
    *,
    plan: dict[str, object] | None = None,
    plan_bytes: bytes | None = None,
) -> Path:
    """Publish one synthetic caption serialization and return the final directory."""
    output_root.mkdir(parents=True, exist_ok=True)
    plan = _make_caption_plan() if plan is None else plan
    plan_bytes = _plan_bytes(plan) if plan_bytes is None else plan_bytes
    return publish_episode_caption_serialization(
        caption_plan=plan,
        caption_plan_bytes=plan_bytes,
        realization_plan=None,
        presentation_plan=None,
        delivery_plan=None,
        narration_plan=None,
        shot_plan=None,
        story_plan=None,
        current_export=None,
        output_root=output_root,
    )


def _expected_entries() -> set[str]:
    """Return the four owned filenames a published captions directory must hold."""
    return {
        CAPTION_SERIALIZATION_MANIFEST_FILENAME,
        CAPTION_PLAN_COPY_FILENAME,
        sidecar_filename(FINAL_NAME, SRT_SUFFIX),
        sidecar_filename(FINAL_NAME, VTT_SUFFIX),
    }


def _snapshot(directory: Path) -> dict[str, tuple[int, bytes]]:
    """Record every file's ``(mtime_ns, bytes)`` inside one published directory."""
    return {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(directory.iterdir())
    }


def _partials(output_root: Path) -> list[Path]:
    """Return every ``.partial`` sibling currently under the output root."""
    return [path for path in output_root.iterdir() if path.name.endswith(PARTIAL_SUFFIX)]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_publishes_four_owned_files_under_the_derived_name(
    tmp_path: Path,
) -> None:
    """Happy path publishes exactly four owned files under the derived name."""
    output_root = tmp_path / "out"
    published = _publish(output_root)

    assert published.name == FINAL_NAME
    assert published.parent == output_root
    assert {entry.name for entry in published.iterdir()} == _expected_entries()
    assert _partials(output_root) == []
    assert audit_caption_serialization_directory(published) == []


def test_happy_path_plan_copy_is_byte_identical_to_the_captured_observation(
    tmp_path: Path,
) -> None:
    """Happy path plan copy is byte identical to the captured observation."""
    plan = _make_caption_plan()
    captured = _plan_bytes(plan)
    published = _publish(tmp_path / "out", plan=plan, plan_bytes=captured)

    assert (published / CAPTION_PLAN_COPY_FILENAME).read_bytes() == captured


def test_happy_path_manifest_binds_the_captured_plan_digest(tmp_path: Path) -> None:
    """Happy path manifest binds the captured plan digest."""
    plan = _make_caption_plan()
    captured = _plan_bytes(plan)
    published = _publish(tmp_path / "out", plan=plan, plan_bytes=captured)
    manifest = loads_canonical(
        (published / CAPTION_SERIALIZATION_MANIFEST_FILENAME).read_bytes(), "manifest"
    )

    assert manifest["source"]["caption_plan_sha256"] == sha256_hex(captured)


def test_baseline_plan_publishes_under_episode_0000_baseline(tmp_path: Path) -> None:
    """A baseline ep0 plan publishes under episode_0000_baseline."""
    plan = _make_caption_plan(mode="baseline", episode=0, previous_episode=None)
    published = _publish(tmp_path / "out", plan=plan)

    assert published.name == "episode_0000_baseline"
    assert audit_caption_serialization_directory(published) == []


# ---------------------------------------------------------------------------
# Single-capture: the captured bytes must be the plan's own canonical encoding
# ---------------------------------------------------------------------------


def test_non_canonical_caption_plan_bytes_are_refused(tmp_path: Path) -> None:
    """Non canonical caption plan bytes are refused and nothing is written."""
    plan = _make_caption_plan()
    non_canonical = json.dumps(plan, sort_keys=True).encode("utf-8")
    assert non_canonical != _plan_bytes(plan)
    output_root = tmp_path / "out"
    output_root.mkdir()

    with pytest.raises(ValueError):
        _publish(output_root, plan=plan, plan_bytes=non_canonical)

    assert list(output_root.iterdir()) == []


def test_non_bytes_caption_plan_bytes_are_refused(tmp_path: Path) -> None:
    """A non bytes caption plan bytes value is refused as a TypeError."""
    plan = _make_caption_plan()
    output_root = tmp_path / "out"
    output_root.mkdir()

    with pytest.raises(TypeError):
        _publish(output_root, plan=plan, plan_bytes="not bytes")

    assert list(output_root.iterdir()) == []


# ---------------------------------------------------------------------------
# The verified no-op
# ---------------------------------------------------------------------------


def test_second_publish_is_a_verified_no_op_leaving_every_byte_and_mtime_unchanged(
    tmp_path: Path,
) -> None:
    """Second publish returns the same dir; all four files keep bytes and mtimes."""
    output_root = tmp_path / "out"
    first = _publish(output_root)
    before = _snapshot(first)

    second = _publish(output_root)

    assert second == first
    assert _snapshot(first) == before
    assert _partials(output_root) == []


# ---------------------------------------------------------------------------
# Existing-final refusals, nothing deleted and nothing repaired
# ---------------------------------------------------------------------------


def test_existing_final_with_a_different_plan_is_refused_and_nothing_is_deleted(
    tmp_path: Path,
) -> None:
    """Existing final with a different plan is refused without deleting anything."""
    output_root = tmp_path / "out"
    first = _publish(output_root)
    before = _snapshot(first)
    different = _make_caption_plan(
        texts=[
            "First caption sentence.",
            "Second caption sentence, revised.",
            "Third caption sentence.",
        ]
    )

    with pytest.raises(CaptionSerializationDirectoryRefused) as excinfo:
        _publish(output_root, plan=different)

    assert "serializes a different caption plan" in str(excinfo.value)
    assert _snapshot(first) == before
    assert _partials(output_root) == []


def test_existing_final_that_fails_its_own_audit_is_refused_and_nothing_is_repaired(
    tmp_path: Path,
) -> None:
    """Existing final that fails its own audit is refused and nothing is repaired."""
    output_root = tmp_path / "out"
    published = _publish(output_root)
    srt_path = published / sidecar_filename(FINAL_NAME, SRT_SUFFIX)
    mutated = bytearray(srt_path.read_bytes())
    mutated[-1] ^= 0xFF
    srt_path.write_bytes(bytes(mutated))

    with pytest.raises(CaptionSerializationDirectoryRefused) as excinfo:
        _publish(output_root)

    assert "not a truthful" in str(excinfo.value)
    assert srt_path.read_bytes() == bytes(mutated)
    assert _partials(output_root) == []


# ---------------------------------------------------------------------------
# Handled refusals discard this run's own staging
# ---------------------------------------------------------------------------


def test_a_handled_refusal_leaves_no_partial(tmp_path: Path) -> None:
    """A final name pre occupied by a file refuses and leaves no partial."""
    output_root = tmp_path / "out"
    output_root.mkdir()
    blocker = output_root / FINAL_NAME
    blocker.write_bytes(b"occupied")

    with pytest.raises(CaptionSerializationDirectoryRefused) as excinfo:
        _publish(output_root)

    assert "not a truthful" in str(excinfo.value)
    assert blocker.read_bytes() == b"occupied"
    assert _partials(output_root) == []


def test_a_staged_audit_refusal_discards_its_own_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal raised after staging creation discards that own staging tree."""
    monkeypatch.setattr(
        publisher_module, "_staged_serialization_problems", lambda *a, **k: ["staged audit failed"]
    )
    output_root = tmp_path / "out"
    output_root.mkdir()

    with pytest.raises(CaptionSerializationRefused):
        _publish(output_root)

    assert list(output_root.iterdir()) == []


# ---------------------------------------------------------------------------
# Stale staging from a prior run
# ---------------------------------------------------------------------------


def test_a_stale_prior_run_staging_tree_with_owned_content_is_discarded_and_rebuilt(
    tmp_path: Path,
) -> None:
    """A stale owned staging tree is discarded, then the run rebuilds and publishes."""
    output_root = tmp_path / "out"
    output_root.mkdir()
    stale = output_root / (FINAL_NAME + PARTIAL_SUFFIX)
    stale.mkdir()
    (stale / (CAPTION_PLAN_COPY_FILENAME + WRITING_SUFFIX)).write_bytes(b"owned leftover")

    published = _publish(output_root)

    assert not stale.exists()
    assert audit_caption_serialization_directory(published) == []
    assert _partials(output_root) == []


def test_a_foreign_staging_tree_refuses_without_deletion(tmp_path: Path) -> None:
    """A staging tree holding a foreign entry refuses and is never deleted."""
    output_root = tmp_path / "out"
    output_root.mkdir()
    stale = output_root / (FINAL_NAME + PARTIAL_SUFFIX)
    stale.mkdir()
    (stale / "definitely_not_ours").write_bytes(b"x")

    with pytest.raises(CaptionSerializationDirectoryRefused):
        _publish(output_root)

    assert stale.exists()
    assert (stale / "definitely_not_ours").exists()


# ---------------------------------------------------------------------------
# Crash evidence: an unrecognised exception class survives untouched
# ---------------------------------------------------------------------------


def test_a_crash_leaves_the_partial_tree_intact_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash inside the staged audit propagates with the partial tree intact."""

    def _boom(*args: object, **kwargs: object) -> list[str]:
        raise RuntimeError("simulated unrecognised crash")

    monkeypatch.setattr(publisher_module, "_staged_serialization_problems", _boom)
    output_root = tmp_path / "out"
    output_root.mkdir()

    with pytest.raises(RuntimeError):
        _publish(output_root)

    partial = output_root / (FINAL_NAME + PARTIAL_SUFFIX)
    assert partial.is_dir()
    assert (partial / CAPTION_PLAN_COPY_FILENAME).is_file()
    assert not (output_root / FINAL_NAME).exists()


# ---------------------------------------------------------------------------
# Indirections are never followed
# ---------------------------------------------------------------------------


def test_a_symlinked_output_root_is_refused(tmp_path: Path) -> None:
    """A symlinked output root is refused before anything is written."""
    real = tmp_path / "real_root"
    real.mkdir()
    link = tmp_path / "link_root"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    plan = _make_caption_plan()

    with pytest.raises(CaptionSerializationDirectoryRefused):
        publish_episode_caption_serialization(
            caption_plan=plan,
            caption_plan_bytes=_plan_bytes(plan),
            realization_plan=None,
            presentation_plan=None,
            delivery_plan=None,
            narration_plan=None,
            shot_plan=None,
            story_plan=None,
            current_export=None,
            output_root=link,
        )

    assert list(real.iterdir()) == []


def test_a_symlinked_final_directory_is_refused(tmp_path: Path) -> None:
    """A symlink sitting at the final name is refused, never followed."""
    output_root = tmp_path / "out"
    published = _publish(output_root)
    moved = tmp_path / "moved_final"
    shutil.move(str(published), str(moved))
    try:
        published.symlink_to(moved, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")

    with pytest.raises(CaptionSerializationDirectoryRefused):
        _publish(output_root)

    assert published.is_symlink()
    assert _partials(output_root) == []
