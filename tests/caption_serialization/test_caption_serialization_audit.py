"""Phase 34 caption serialization audit -- the self-contained directory audit.

Every test operates on a real published captions directory built by the real
publisher against a synthetic, standalone-valid Phase 32 caption plan, then on a
fresh ``shutil.copytree`` copy per tamper. The publisher's full locked Phase 32
source-verification gate is bypassed by the autouse fixture below (its truth is
proven by the locked Phase 32 suite and this package's conftest); these tests
attack the Phase 34 audit's own laws: the one manifest observation, missing and
foreign entries, canonical bytes, restated source/clock/accounting, byte-for-byte
sidecar re-derivation, the single-link sweep, and the never-trusted directory name.
"""

import inspect
import os
import shutil
from pathlib import Path

import pytest

import living_diorama.caption_serialization.caption_serialization_publisher as publisher_module
from living_diorama.caption import validate_episode_caption_plan
from living_diorama.caption_serialization.caption_serialization_audit import (
    _audit_caption_serialization_directory_with_observation,
    audit_caption_serialization_directory,
)
from living_diorama.caption_serialization.caption_serialization_publisher import (
    publish_episode_caption_serialization,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_PLAN_COPY_FILENAME,
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    SRT_SUFFIX,
    VTT_SUFFIX,
    WRITING_SUFFIX,
    caption_serialization_id,
    sidecar_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical

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


def _publish(output_root: Path) -> Path:
    """Publish one synthetic caption serialization and return the final directory."""
    output_root.mkdir(parents=True, exist_ok=True)
    plan = _make_caption_plan()
    return publish_episode_caption_serialization(
        caption_plan=plan,
        caption_plan_bytes=dumps_canonical(plan, "caption plan"),
        realization_plan=None,
        presentation_plan=None,
        delivery_plan=None,
        narration_plan=None,
        shot_plan=None,
        story_plan=None,
        current_export=None,
        output_root=output_root,
    )


def _published_copy(tmp_path: Path) -> Path:
    """Build a published dir via the real publisher, then return a fresh copy of it."""
    published = _publish(tmp_path / "out")
    copy = tmp_path / "copy"
    shutil.copytree(published, copy)
    return copy


def _load(path: Path) -> dict[str, object]:
    """Load one canonical JSON document from disk."""
    return loads_canonical(path.read_bytes(), path.name)


def _save(path: Path, document: dict[str, object]) -> None:
    """Write one document back to disk in its canonical byte form."""
    path.write_bytes(dumps_canonical(document, path.name))


def _can_hardlink(probe_dir: Path) -> bool:
    """Return whether this platform and filesystem can create a hardlink."""
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# The public API surface
# ---------------------------------------------------------------------------


def test_clean_published_directory_returns_no_problems(tmp_path: Path) -> None:
    """Clean published directory returns no problems."""
    assert audit_caption_serialization_directory(_publish(tmp_path / "out")) == []


def test_public_audit_takes_exactly_one_positional_argument() -> None:
    """Public audit takes exactly one positional argument."""
    signature = inspect.signature(audit_caption_serialization_directory)
    assert list(signature.parameters) == ["caption_dir"]


def test_the_private_helper_returns_the_one_manifest_observation(tmp_path: Path) -> None:
    """The private helper returns the one manifest observation it read."""
    published = _publish(tmp_path / "out")
    on_disk = (published / CAPTION_SERIALIZATION_MANIFEST_FILENAME).read_bytes()

    problems, observed_bytes, observed_document = (
        _audit_caption_serialization_directory_with_observation(published)
    )

    assert problems == []
    assert observed_bytes == on_disk
    assert observed_document == loads_canonical(on_disk, "episode caption serialization manifest")


def test_the_audit_writes_nothing(tmp_path: Path) -> None:
    """The audit writes nothing to the directory it inspects."""
    published = _publish(tmp_path / "out")
    before = {
        str(path.relative_to(published)): path.stat().st_mtime_ns
        for path in sorted(published.rglob("*"))
    }

    audit_caption_serialization_directory(published)

    after = {
        str(path.relative_to(published)): path.stat().st_mtime_ns
        for path in sorted(published.rglob("*"))
    }
    assert before == after


def test_audit_succeeds_with_every_upstream_path_deleted(tmp_path: Path) -> None:
    """The audit is self-contained: it needs nothing outside the directory handed to it."""
    published = _publish(tmp_path / "out")
    decoy_upstream = tmp_path / "nonexistent_upstream"
    assert not decoy_upstream.exists()
    assert audit_caption_serialization_directory(published) == []


# ---------------------------------------------------------------------------
# Missing owned files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        CAPTION_SERIALIZATION_MANIFEST_FILENAME,
        CAPTION_PLAN_COPY_FILENAME,
        sidecar_filename(FINAL_NAME, SRT_SUFFIX),
        sidecar_filename(FINAL_NAME, VTT_SUFFIX),
    ],
)
def test_a_missing_owned_file_is_a_problem(tmp_path: Path, filename: str) -> None:
    """A missing owned file is always a problem naming it as missing."""
    copy = _published_copy(tmp_path)
    (copy / filename).unlink()

    problems = audit_caption_serialization_directory(copy)

    assert problems != []
    assert any("is missing" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Canonical bytes and document validity
# ---------------------------------------------------------------------------


def test_a_non_canonical_manifest_is_a_problem(tmp_path: Path) -> None:
    """A manifest rewritten with an extra space is not canonical bytes."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    raw = manifest_path.read_bytes()
    assert b'"format":' in raw
    manifest_path.write_bytes(raw.replace(b'"format":', b'"format" :'))

    problems = audit_caption_serialization_directory(copy)

    assert any("not canonical bytes" in problem for problem in problems)


def test_an_invalid_manifest_is_a_problem(tmp_path: Path) -> None:
    """A manifest that no longer parses is an invalid manifest problem."""
    copy = _published_copy(tmp_path)
    (copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME).write_bytes(b"{not json")

    problems = audit_caption_serialization_directory(copy)

    assert any("manifest is invalid" in problem for problem in problems)


def test_an_invalid_plan_copy_is_a_problem(tmp_path: Path) -> None:
    """A copied caption plan that fails the locked Phase 32 schema is invalid."""
    copy = _published_copy(tmp_path)
    (copy / CAPTION_PLAN_COPY_FILENAME).write_bytes(b'{"schema_version": 99}')

    problems = audit_caption_serialization_directory(copy)

    assert any("copied caption plan is invalid" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The bound digest and the restated source, re-derived from the copy
# ---------------------------------------------------------------------------


def test_a_changed_plan_copy_causes_a_digest_mismatch_problem(tmp_path: Path) -> None:
    """A different valid plan copy makes the manifest's bound digest a problem."""
    copy = _published_copy(tmp_path)
    altered = _make_caption_plan(
        texts=[
            "First caption sentence.",
            "Second caption sentence, revised.",
            "Third caption sentence.",
        ]
    )
    (copy / CAPTION_PLAN_COPY_FILENAME).write_bytes(dumps_canonical(altered, "caption plan"))

    problems = audit_caption_serialization_directory(copy)

    assert any("the manifest binds caption_plan_sha256" in problem for problem in problems)


def test_a_restated_source_field_contradicting_the_plan_is_a_problem(tmp_path: Path) -> None:
    """A manifest source field edited against the copy is a restatement problem."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["source"]["presentation_plan_sha256"] = "a" * 64
    _save(manifest_path, manifest)

    problems = audit_caption_serialization_directory(copy)

    assert any(
        "the manifest's source.presentation_plan_sha256 is" in problem for problem in problems
    )


# ---------------------------------------------------------------------------
# The never-trusted directory name
# ---------------------------------------------------------------------------


def test_a_renamed_directory_is_refused_under_its_new_name(tmp_path: Path) -> None:
    """A directory renamed away from its plan-derived id is never trusted."""
    published = _publish(tmp_path / "out")
    renamed = tmp_path / "episode_0009_to_0010"
    shutil.copytree(published, renamed)

    problems = audit_caption_serialization_directory(renamed)

    assert any("never trusted under a name" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Restated clock and re-derived accounting
# ---------------------------------------------------------------------------


def test_a_clock_mismatch_is_a_problem(tmp_path: Path) -> None:
    """A manifest clock edited against the copied plan is a restatement problem."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["clock"]["fps"] = 25
    _save(manifest_path, manifest)

    problems = audit_caption_serialization_directory(copy)

    assert any("the manifest's clock.fps is 25" in problem for problem in problems)


def test_an_edited_manifest_accounting_is_a_problem(tmp_path: Path) -> None:
    """Manifest accounting edited away from the plan's re-derived counts is a problem."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["accounting"]["caption_frames_total"] = 119
    manifest["accounting"]["uncaptioned_frames_total"] = 1
    _save(manifest_path, manifest)

    problems = audit_caption_serialization_directory(copy)

    assert any(
        "the manifest's accounting.caption_frames_total is 119" in problem for problem in problems
    )


# ---------------------------------------------------------------------------
# Sidecars: byte-for-byte re-serialization and recorded values
# ---------------------------------------------------------------------------


def test_a_flipped_srt_byte_is_a_problem(tmp_path: Path) -> None:
    """One flipped SRT byte fails the byte for byte re-serialization law."""
    copy = _published_copy(tmp_path)
    srt_path = copy / sidecar_filename(FINAL_NAME, SRT_SUFFIX)
    mutated = bytearray(srt_path.read_bytes())
    mutated[-1] ^= 0xFF
    srt_path.write_bytes(bytes(mutated))

    problems = audit_caption_serialization_directory(copy)

    assert any("does not equal the srt artifact re-serialized" in problem for problem in problems)


def test_an_appended_vtt_byte_is_a_problem(tmp_path: Path) -> None:
    """One appended VTT byte fails re-serialization and the recorded length."""
    copy = _published_copy(tmp_path)
    vtt_path = copy / sidecar_filename(FINAL_NAME, VTT_SUFFIX)
    vtt_path.write_bytes(vtt_path.read_bytes() + b"x")

    problems = audit_caption_serialization_directory(copy)

    assert any("does not equal the vtt artifact re-serialized" in problem for problem in problems)
    assert any("the manifest's sidecars.vtt.bytes is" in problem for problem in problems)


def test_an_edited_sidecar_record_bytes_is_a_problem(tmp_path: Path) -> None:
    """A sidecar record's recorded byte length edited is a recorded-value problem."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["sidecars"]["srt"]["bytes"] += 1
    _save(manifest_path, manifest)

    problems = audit_caption_serialization_directory(copy)

    assert any("the manifest's sidecars.srt.bytes is" in problem for problem in problems)


def test_an_edited_sidecar_record_sha256_is_a_problem(tmp_path: Path) -> None:
    """A sidecar record's recorded digest edited is a recorded-value problem."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["sidecars"]["vtt"]["sha256"] = "0" * 64
    _save(manifest_path, manifest)

    problems = audit_caption_serialization_directory(copy)

    assert any("the manifest's sidecars.vtt.sha256 is" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Single-link sweep and indirections
# ---------------------------------------------------------------------------


def test_a_hardlinked_srt_sidecar_is_a_problem(tmp_path: Path) -> None:
    """An SRT sidecar realised as a hardlink is never a hardlink."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    copy = _published_copy(tmp_path)
    srt_path = copy / sidecar_filename(FINAL_NAME, SRT_SUFFIX)
    outside = copy.parent / "outside_sidecar.srt"
    shutil.copyfile(srt_path, outside)
    srt_path.unlink()
    os.link(outside, srt_path)

    problems = audit_caption_serialization_directory(copy)

    assert any("never a hardlink" in problem for problem in problems)


def test_a_symlinked_manifest_is_a_problem(tmp_path: Path) -> None:
    """A manifest reached through a symlink is refused before its content is trusted."""
    copy = _published_copy(tmp_path)
    manifest_path = copy / CAPTION_SERIALIZATION_MANIFEST_FILENAME
    real_bytes = manifest_path.read_bytes()
    manifest_path.unlink()
    elsewhere = copy.parent / "elsewhere_manifest.json"
    elsewhere.write_bytes(real_bytes)
    try:
        manifest_path.symlink_to(elsewhere)
    except OSError:
        pytest.skip("platform cannot create a symlink")

    problems = audit_caption_serialization_directory(copy)

    assert any("symlink or junction" in problem for problem in problems)


def test_a_symlinked_directory_is_never_audited_through(tmp_path: Path) -> None:
    """A captions directory reached through a symlink is refused outright."""
    published = _publish(tmp_path / "out")
    link = tmp_path / "linked_captions"
    try:
        link.symlink_to(published, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")

    problems = audit_caption_serialization_directory(link)

    assert any("never audits through one" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The inventory sweep: no foreign, leftover or nested entry
# ---------------------------------------------------------------------------


def test_a_foreign_file_is_a_problem(tmp_path: Path) -> None:
    """A foreign file inside the directory is not accounted for."""
    copy = _published_copy(tmp_path)
    (copy / "extra.txt").write_bytes(b"intruder")

    problems = audit_caption_serialization_directory(copy)

    assert any("not accounted for" in problem for problem in problems)


def test_a_writing_leftover_is_a_problem(tmp_path: Path) -> None:
    """An owned .writing working file is left behind by an unfinished run."""
    copy = _published_copy(tmp_path)
    (copy / (CAPTION_PLAN_COPY_FILENAME + WRITING_SUFFIX)).write_bytes(b"partial")

    problems = audit_caption_serialization_directory(copy)

    assert any("left behind" in problem for problem in problems)


def test_a_subdirectory_is_a_problem(tmp_path: Path) -> None:
    """A subdirectory inside a caption serialization is never permitted."""
    copy = _published_copy(tmp_path)
    (copy / "junk").mkdir()

    problems = audit_caption_serialization_directory(copy)

    assert any("never permitted" in problem for problem in problems)


def test_a_non_directory_input_path_is_a_problem(tmp_path: Path) -> None:
    """A regular file handed to the audit is not a directory."""
    published = _publish(tmp_path / "out")
    file_path = published / CAPTION_SERIALIZATION_MANIFEST_FILENAME

    problems = audit_caption_serialization_directory(file_path)

    assert any("is not a directory" in problem for problem in problems)
