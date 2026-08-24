"""The Phase 23 command line: build a render plan, audit a finished render.

The audit tests are the important ones. They stand in for a reviewer holding a
directory of images and asking whether it is really the episode it claims to
be -- so they attack the directory, not the code.
"""

import contextlib
import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from tests.render_execution.conftest import png_bytes

from living_diorama.cli import build_render_plan, verify_render
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution import build_episode_render_manifest_document
from living_diorama.render_execution.frame_image import mean_abs_difference
from living_diorama.render_execution.render_execution_spec import (
    render_profile_dimensions,
)

ENVIRONMENT = {"blender_version": "4.5.12", "engine": "CYCLES", "device": "OPTIX"}


def _image_digest(payload: bytes) -> str:
    """The digest of a PNG's image data alone, as the audit computes it."""
    image = bytearray()
    offset = 8
    while offset + 8 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        if payload[offset + 4 : offset + 8] == b"IDAT":
            image += payload[offset + 8 : offset + 8 + length]
        offset += length + 12
    return sha256_hex(zlib.decompress(bytes(image)))


def _write_render(tmp_path: Path, plan: dict[str, Any], *, witness_fill: int | None = None) -> Path:
    """Materialise a complete, truthful render directory for one plan."""
    render_dir = tmp_path / plan["destination"]["render_id"]
    (render_dir / "frames").mkdir(parents=True)
    (render_dir / "witness").mkdir(parents=True)
    (render_dir / "episode_render_plan.json").write_bytes(
        dumps_canonical(plan, "episode render plan")
    )

    results: dict[int, dict[str, object]] = {}
    for entry in plan["frames"]:
        folder = "witness" if entry["role"] == "witness" else "frames"
        # The witness frame is written from the final playback frame's bytes,
        # which is what a real render of an unchanged held scene produces.
        if entry["frame"] == 193:
            fill = 192 if witness_fill is None else witness_fill
        else:
            fill = entry["frame"] % 256
        payload = png_bytes(fill=fill)
        (render_dir / folder / entry["file"]).write_bytes(payload)
        results[entry["frame"]] = {
            "bytes": len(payload),
            "sha256": sha256_hex(payload),
            "image_sha256": _image_digest(payload),
        }
    # The manifest records the difference the frames on disk actually show, so
    # the audit -- which recomputes it -- has something true to agree with.
    measured = mean_abs_difference(
        render_dir / "frames" / plan["frames"][-2]["file"],
        render_dir / "witness" / plan["frames"][-1]["file"],
    )
    manifest = build_episode_render_manifest_document(
        render_plan=plan,
        results=results,
        environment=ENVIRONMENT,
        witness_difference=measured,
    )
    (render_dir / "episode_render_manifest.json").write_bytes(
        dumps_canonical(manifest, "episode render manifest")
    )
    return render_dir


# ------------------------------------------------------------ plan building


def _write_inputs(tmp_path: Path, shot_plan: dict, story_plan: dict) -> tuple[Path, Path]:
    """Write both canonical inputs the plan builder requires."""
    shot_path = tmp_path / "shot.json"
    story_path = tmp_path / "story.json"
    shot_path.write_bytes(dumps_canonical(shot_plan, "shot direction plan"))
    story_path.write_bytes(dumps_canonical(story_plan, "episode story plan"))
    return shot_path, story_path


def test_the_cli_writes_a_valid_render_plan(
    tmp_path: Path,
    shot_plan_leg1: dict[str, Any],
    story_leg1: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end: a directed episode in, a render plan out."""
    shot_path, story_path = _write_inputs(tmp_path, shot_plan_leg1, story_leg1)
    output = tmp_path / "render_plan.json"
    code = build_render_plan.main(
        ["--shot-plan", str(shot_path), "--story-plan", str(story_path), "--output", str(output)]
    )
    assert code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["format"] == "living_diorama_episode_render_plan"
    assert document["emission"]["frame_count"] == 192
    assert "written" in capsys.readouterr().out


def test_the_cli_refuses_to_overwrite_an_existing_plan(
    tmp_path: Path, shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """A plan on disk is never replaced by a fresh build."""
    shot_path, story_path = _write_inputs(tmp_path, shot_plan_leg1, story_leg1)
    output = tmp_path / "render_plan.json"
    output.write_text("{}", encoding="utf-8")
    assert (
        build_render_plan.main(
            [
                "--shot-plan",
                str(shot_path),
                "--story-plan",
                str(story_path),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert output.read_text(encoding="utf-8") == "{}"


def test_the_cli_refuses_a_non_canonical_shot_plan(
    tmp_path: Path, shot_plan_leg1: dict[str, Any], story_leg1: dict[str, Any]
) -> None:
    """The digest claim has to be true, so the bytes must be the canonical ones."""
    _, story_path = _write_inputs(tmp_path, shot_plan_leg1, story_leg1)
    shot_path = tmp_path / "pretty.json"
    shot_path.write_text(json.dumps(shot_plan_leg1, indent=2), encoding="utf-8")
    output = tmp_path / "render_plan.json"
    assert (
        build_render_plan.main(
            [
                "--shot-plan",
                str(shot_path),
                "--story-plan",
                str(story_path),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()


def test_the_cli_refuses_a_story_plan_from_another_episode(
    tmp_path: Path,
    shot_plan_leg1: dict[str, Any],
    story_baseline: dict[str, Any],
) -> None:
    """A mixed pair of upstream documents is refused, not reconciled."""
    shot_path, story_path = _write_inputs(tmp_path, shot_plan_leg1, story_baseline)
    output = tmp_path / "render_plan.json"
    assert (
        build_render_plan.main(
            [
                "--shot-plan",
                str(shot_path),
                "--story-plan",
                str(story_path),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()


def test_the_cli_refuses_a_missing_input(tmp_path: Path) -> None:
    """A missing file is a refusal, not a traceback."""
    assert (
        build_render_plan.main(
            [
                "--shot-plan",
                str(tmp_path / "nope.json"),
                "--story-plan",
                str(tmp_path / "nostory.json"),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
        == 1
    )


# ------------------------------------------------------------------- audit


def test_a_truthful_render_directory_passes_the_audit(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The control: everything present, everything matching."""
    render_dir = _write_render(tmp_path, render_plan)
    assert verify_render.audit_render_directory(render_dir) == []
    assert verify_render.main(["--render-dir", str(render_dir)]) == 0


def test_the_audit_notices_a_missing_frame(tmp_path: Path, render_plan: dict[str, Any]) -> None:
    """A deleted frame cannot hide behind a manifest that still lists it."""
    render_dir = _write_render(tmp_path, render_plan)
    (render_dir / "frames" / "frame_0087.png").unlink()
    problems = verify_render.audit_render_directory(render_dir)
    assert any("frame 87 is missing" in problem for problem in problems)


def test_the_audit_notices_a_changed_frame(tmp_path: Path, render_plan: dict[str, Any]) -> None:
    """Every byte is re-read; the manifest's word is never taken for it."""
    render_dir = _write_render(tmp_path, render_plan)
    (render_dir / "frames" / "frame_0002.png").write_bytes(png_bytes(width=16, height=9, fill=1))
    problems = verify_render.audit_render_directory(render_dir)
    assert any("frame 2 on disk" in problem for problem in problems)


def test_the_audit_notices_an_unaccounted_file(tmp_path: Path, render_plan: dict[str, Any]) -> None:
    """A stray image in the frames directory is a problem, not a curiosity."""
    render_dir = _write_render(tmp_path, render_plan)
    (render_dir / "frames" / "frame_0500.png").write_bytes(png_bytes())
    problems = verify_render.audit_render_directory(render_dir)
    assert any("no frame record accounts for it" in problem for problem in problems)


def test_the_audit_notices_a_manifest_bound_to_another_plan(
    tmp_path: Path, render_plan: dict[str, Any], baseline_render_plan: dict[str, Any]
) -> None:
    """A manifest from another episode cannot certify this directory."""
    render_dir = _write_render(tmp_path, render_plan)
    other_dir = _write_render(tmp_path, baseline_render_plan)
    shutil.copyfile(
        other_dir / "episode_render_manifest.json", render_dir / "episode_render_manifest.json"
    )
    problems = verify_render.audit_render_directory(render_dir)
    assert problems


def test_the_audit_notices_a_missing_manifest(tmp_path: Path, render_plan: dict[str, Any]) -> None:
    """No manifest means the render never completed, whatever is on disk."""
    render_dir = _write_render(tmp_path, render_plan)
    (render_dir / "episode_render_manifest.json").unlink()
    problems = verify_render.audit_render_directory(render_dir)
    assert any("never completed" in problem for problem in problems)


def test_the_audit_notices_a_witness_beyond_tolerance(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """A boundary frame that drifted too far means the episode ended in motion."""
    render_dir = _write_render(tmp_path, render_plan, witness_fill=40)
    problems = verify_render.audit_render_directory(render_dir)
    assert any("beyond the tolerance" in problem for problem in problems)


def test_the_audit_recomputes_the_measurement_and_refuses_a_changed_number(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """A manifest number that the frames do not support is caught.

    The renderer's claim is not evidence about the renderer's own output, so
    the audit measures the two images itself and compares.
    """
    render_dir = _write_render(tmp_path, render_plan)
    path = render_dir / "episode_render_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["completeness"]["witness_mean_abs_difference"] = 0.5
    path.write_bytes(dumps_canonical(manifest, "episode render manifest"))
    problems = verify_render.audit_render_directory(render_dir)
    assert any("frames on disk measure" in problem for problem in problems)


def test_the_audit_refuses_a_flipped_verdict(tmp_path: Path, render_plan: dict[str, Any]) -> None:
    """The verdict must follow from the measurement, checked against the frames."""
    render_dir = _write_render(tmp_path, render_plan, witness_fill=40)
    path = render_dir / "episode_render_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    completeness = manifest["completeness"]
    completeness["witness_within_tolerance"] = True
    completeness["complete"] = True
    path.write_bytes(dumps_canonical(manifest, "episode render manifest"))
    problems = verify_render.audit_render_directory(render_dir)
    assert any(
        "opposite verdict" in problem or "does not follow" in problem for problem in problems
    )


def test_the_audit_refuses_a_directory_that_is_not_one(tmp_path: Path) -> None:
    """A path that is not a render directory is refused plainly."""
    assert verify_render.main(["--render-dir", str(tmp_path / "nothing")]) == 1


# --------------------------------------------------------------------------
# A replaced frame, with the manifest rewritten so every digest agrees
# --------------------------------------------------------------------------

ATTACKED_FRAME = 100
"""An interior playback frame: not the boundary pair the audit already opened."""


def _substitute_frame(render_dir: Path, payload: bytes, *, frame: int = ATTACKED_FRAME) -> None:
    """Replace one frame and update the manifest so all three digests match it.

    This is the attack the profile audit exists for. Re-hashing every file
    proves each is the one recorded; it cannot notice that the recorded file is
    not a frame. An attacker who controls the directory controls the manifest
    too, so the interesting question was never "do the hashes agree" -- they
    will -- but "is this thing an image of this render's profile".

    ``render_plan_sha256`` is deliberately left alone: a forgery that rewrote
    its own binding would be caught by something else entirely and would prove
    nothing about this check.
    """
    path = render_dir / "frames" / f"frame_{frame:04d}.png"
    path.write_bytes(payload)
    manifest_path = render_dir / "episode_render_manifest.json"
    manifest = loads_canonical(manifest_path.read_bytes(), "render manifest")
    for record in manifest["frames"]:
        if record["frame"] != frame:
            continue
        record["bytes"] = len(payload)
        record["sha256"] = sha256_hex(payload)
        # An undecompressable frame has no image digest to agree with. The
        # attacker leaves the old one; the audit must still refuse cleanly
        # rather than raise.
        with contextlib.suppress(ValueError, zlib.error):
            record["image_sha256"] = _image_digest(payload)
    manifest_path.write_bytes(dumps_canonical(manifest, "render manifest"))


def _raw_png(width: int, height: int, header: bytes, raw: bytes) -> bytes:
    """Assemble a structurally valid PNG around an arbitrary header and stream."""
    del width, height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk with a correct CRC."""
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def _rows(width: int, height: int, filter_byte: int = 0, channels: int = 3) -> bytes:
    """Scanlines of a flat picture, with a chosen per-row filter byte."""
    return b"".join(bytes([filter_byte]) + bytes([7] * width * channels) for _ in range(height))


def _wrong_size_png() -> bytes:
    """A real, well-formed RGB picture -- of the wrong episode's resolution."""
    return _raw_png(640, 360, struct.pack(">IIBBBBB", 640, 360, 8, 2, 0, 0, 0), _rows(640, 360))


def _greyscale_png() -> bytes:
    """The right size, eight bits, and not a colour picture."""
    width, height = render_profile_dimensions()
    return _raw_png(
        width,
        height,
        struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0),
        _rows(width, height, channels=1),
    )


def _interlaced_png() -> bytes:
    """Adam7: a picture this decoder would have to guess at."""
    width, height = render_profile_dimensions()
    return _raw_png(
        width, height, struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 1), _rows(width, height)
    )


def _short_scanlines_png() -> bytes:
    """One byte short of the scanlines the header promises."""
    width, height = render_profile_dimensions()
    return _raw_png(
        width,
        height,
        struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        _rows(width, height)[:-1],
    )


def _bad_filter_png() -> bytes:
    """A filter byte PNG does not define."""
    width, height = render_profile_dimensions()
    return _raw_png(
        width,
        height,
        struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        _rows(width, height, filter_byte=5),
    )


def _double_header_png() -> bytes:
    """Two headers are two claims about one picture."""
    width, height = render_profile_dimensions()
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(_rows(width, height)))
        + _png_chunk(b"IEND", b"")
    )


def _undecompressable_png() -> bytes:
    """Correct structure, correct CRCs, and image data zlib cannot read."""
    width, height = render_profile_dimensions()
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", b"this is not a zlib stream")
        + _png_chunk(b"IEND", b"")
    )


def _duplicate_iend_png() -> bytes:
    """The reviewer's case A, at the render profile's own size."""
    width, height = render_profile_dimensions()
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(_rows(width, height)))
        + _png_chunk(b"IEND", b"")
        + _png_chunk(b"IEND", b"")
    )


def _header_after_data_png() -> bytes:
    """The reviewer's case B: the image header arrives after the image."""
    width, height = render_profile_dimensions()
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IDAT", zlib.compress(_rows(width, height)))
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IEND", b"")
    )


def _unknown_critical_png() -> bytes:
    """The reviewer's case C: a critical chunk no decoder understands."""
    width, height = render_profile_dimensions()
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"BAAD", b"\x00\x01\x02")
        + _png_chunk(b"IDAT", zlib.compress(_rows(width, height)))
        + _png_chunk(b"IEND", b"")
    )


SUBSTITUTIONS = {
    "a duplicated IEND chunk": _duplicate_iend_png,
    "an image header after the image data": _header_after_data_png,
    "an unknown critical chunk": _unknown_critical_png,
    "a valid picture of the wrong size": _wrong_size_png,
    "a greyscale picture": _greyscale_png,
    "an interlaced picture": _interlaced_png,
    "a stream one byte short of its scanlines": _short_scanlines_png,
    "a row filtered by an undefined method": _bad_filter_png,
    "two image headers": _double_header_png,
    "image data that cannot be decompressed": _undecompressable_png,
}
"""Every way an interior frame can be replaced by something that is not a frame."""


@pytest.mark.parametrize("name", sorted(SUBSTITUTIONS))
def test_a_substituted_frame_is_refused_however_well_the_digests_agree(
    name: str, tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """Blocker C, one row at a time: hashes agreeing is not the frame being sound."""
    render_dir = _write_render(tmp_path, render_plan)
    _substitute_frame(render_dir, SUBSTITUTIONS[name]())
    problems = verify_render.audit_render_directory(render_dir)
    assert problems, name
    assert any(f"frame {ATTACKED_FRAME}" in problem for problem in problems)
    assert verify_render.main(["--render-dir", str(render_dir)]) == 1


def test_a_malformed_frame_does_not_stop_the_audit_reaching_the_others(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """A corrupt frame is a finding, not a traceback.

    ``zlib.error`` is not a ``ValueError``, so an undecompressable frame used to
    escape the audit as an exception -- which reads as the tool breaking, and
    which also meant the other 192 frames were never looked at.
    """
    render_dir = _write_render(tmp_path, render_plan)
    _substitute_frame(render_dir, _undecompressable_png())
    (render_dir / "frames" / "frame_0007.png").unlink()

    problems = verify_render.audit_render_directory(render_dir)
    assert any(f"frame {ATTACKED_FRAME}" in problem for problem in problems)
    assert any("frame 7 is missing" in problem for problem in problems)


def _write_checkpoint(render_dir: Path, *, frames: int | None = None) -> Path:
    """Write a truthful checkpoint agreeing with the manifest already in place.

    A checkpoint is not decoration: the audit now reads it, because a directory
    whose two records disagree about a file has no truthful reading and an
    independent verifier that never opened one could not say so.
    """
    manifest = loads_canonical(
        (render_dir / "episode_render_manifest.json").read_bytes(), "render manifest"
    )
    records = manifest["frames"] if frames is None else manifest["frames"][:frames]
    checkpoint = {
        "render_plan_sha256": manifest["source"]["render_plan_sha256"],
        "render_profile_sha256": manifest["source"]["render_profile_sha256"],
        "environment": manifest["environment"],
        "frames": {
            str(entry["frame"]): {
                "bytes": entry["bytes"],
                "sha256": entry["sha256"],
                "image_sha256": entry["image_sha256"],
            }
            for entry in records
        },
    }
    path = render_dir / "render_checkpoint.json"
    path.write_bytes(dumps_canonical(checkpoint, "render checkpoint"))
    return path


@pytest.mark.parametrize(
    "name", ["render_checkpoint.json", "episode_render_plan.json", "frames", "witness"]
)
def test_the_entries_a_finished_render_owns_are_accepted(
    name: str, tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The control for the root scan: its own artifacts are not strays."""
    render_dir = _write_render(tmp_path, render_plan)
    _write_checkpoint(render_dir)
    assert (render_dir / name).exists()
    assert verify_render.audit_render_directory(render_dir) == []


def test_a_partial_checkpoint_beside_a_finished_manifest_is_accepted(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """A checkpoint from an interrupted run legitimately knows fewer frames.

    That is what resuming means, so holding fewer frames than the manifest is
    not a contradiction. Only disagreeing about a shared frame is.
    """
    render_dir = _write_render(tmp_path, render_plan)
    _write_checkpoint(render_dir, frames=40)
    assert verify_render.audit_render_directory(render_dir) == []


MALFORMED_CHECKPOINT_BYTES = {
    "invalid JSON": b"{bad json",
    "invalid UTF-8": b'{"render_plan_sha256": "\xff\xfe"}',
    "duplicate JSON object key": b'{"a": 1, "a": 2}',
    "non-standard JSON constant": b'{"render_plan_sha256": NaN}',
    "truncated JSON": None,  # filled in per-test from a truthful checkpoint's own bytes
}
"""Malformed bytes on disk, not a malformed document -- the parse itself must fail.

Every one of these must never reach ``validate_render_checkpoint`` or
``require_checkpoint_matches_manifest`` at all: ``loads_canonical`` raises
before either function is called, exactly as it does for the plan and the
manifest beside it.
"""


@pytest.mark.parametrize("name", sorted(MALFORMED_CHECKPOINT_BYTES))
def test_a_malformed_checkpoint_is_refused_by_the_audit_not_crashed(
    name: str, tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The checkpoint's own parse is exactly as fallible as the plan's or the manifest's.

    `require_manifest_matches_plan`'s plan and manifest reads are wrapped in
    `try/except (TypeError, ValueError)`; the checkpoint read that follows
    them was not, so malformed bytes on disk raised straight out of
    `audit_render_directory` as an uncaught exception instead of becoming an
    ordinary reported problem. A malformed on-disk file is exactly the kind of
    input an independent auditor of someone else's directory must survive.
    """
    render_dir = _write_render(tmp_path, render_plan)
    path = _write_checkpoint(render_dir)
    payload = MALFORMED_CHECKPOINT_BYTES[name]
    if payload is None:
        payload = path.read_bytes()[:8]
    path.write_bytes(payload)

    problems = verify_render.audit_render_directory(render_dir)
    assert any("checkpoint" in problem for problem in problems), problems
    assert verify_render.main(["--render-dir", str(render_dir)]) == 1


CHECKPOINT_CONTRADICTIONS = {
    "bytes": lambda c: c["frames"]["1"].update(bytes=999_999),
    "sha256": lambda c: c["frames"]["1"].update(sha256="0" * 64),
    "image_sha256": lambda c: c["frames"]["1"].update(image_sha256="0" * 64),
    "environment": lambda c: c["environment"].update(device="SOMEWHERE_ELSE"),
}
"""Ways a checkpoint can contradict the manifest it sits beside."""


@pytest.mark.parametrize("field", sorted(CHECKPOINT_CONTRADICTIONS))
def test_a_checkpoint_contradicting_the_manifest_is_refused_by_the_audit(
    field: str, tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """Both halves enforce the same three-way agreement, not just production."""
    render_dir = _write_render(tmp_path, render_plan)
    path = _write_checkpoint(render_dir)
    checkpoint = loads_canonical(path.read_bytes(), "render checkpoint")
    CHECKPOINT_CONTRADICTIONS[field](checkpoint)
    path.write_bytes(dumps_canonical(checkpoint, "render checkpoint"))

    problems = verify_render.audit_render_directory(render_dir)
    assert any("checkpoint" in problem for problem in problems), problems
    assert verify_render.main(["--render-dir", str(render_dir)]) == 1


CHECKPOINT_PLAN_IDENTITY_ATTACKS = {
    "wrong render_plan_sha256": (
        lambda c: c.update(render_plan_sha256="0" * 64),
        "does not match its own render plan",
    ),
    "wrong render_profile_sha256": (
        lambda c: c.update(render_profile_sha256="0" * 64),
        "does not match its own render plan",
    ),
}
"""The reviewer's exact reproductions: a checkpoint claiming a different plan
or profile while every frame file and every frame record stays truthful.

Neither mutation touches a single frame result, so a check that only compared
the checkpoint to the manifest -- and never opened the Render Plan -- would
have nothing to object to. That was the hole: the independent audit accepted
both of these in V5.
"""


@pytest.mark.parametrize("name", sorted(CHECKPOINT_PLAN_IDENTITY_ATTACKS))
def test_a_checkpoint_claiming_a_different_plan_is_refused_by_the_audit(
    name: str, tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The independent audit now opens the plan, not only the manifest."""
    mutate, expected_substring = CHECKPOINT_PLAN_IDENTITY_ATTACKS[name]
    render_dir = _write_render(tmp_path, render_plan)
    path = _write_checkpoint(render_dir)
    checkpoint = loads_canonical(path.read_bytes(), "render checkpoint")
    mutate(checkpoint)
    path.write_bytes(dumps_canonical(checkpoint, "render checkpoint"))

    problems = verify_render.audit_render_directory(render_dir)
    assert any(expected_substring in problem for problem in problems), problems
    assert verify_render.main(["--render-dir", str(render_dir)]) == 1


CANONICAL_FRAME_KEY_ATTACKS = {
    "leading zero": "01",
    "leading zeros": "001",
    "unicode digit": "\u0661",
    "plus-prefixed": "+1",
    "leading space": " 1",
    "trailing space": "1 ",
}
"""Non-canonical spellings of frame 1's checkpoint key.

`str.isdigit()` and `int()` both accept far more than ASCII decimal digits --
every one of these used to be silently believed as frame 1.
"""


@pytest.mark.parametrize("name", sorted(CANONICAL_FRAME_KEY_ATTACKS))
def test_a_non_canonical_frame_key_is_refused_by_the_audit(
    name: str, tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """Only `record_checkpoint`'s own spelling -- `str(frame)` -- is believed."""
    render_dir = _write_render(tmp_path, render_plan)
    path = _write_checkpoint(render_dir)
    checkpoint = loads_canonical(path.read_bytes(), "render checkpoint")
    checkpoint["frames"][CANONICAL_FRAME_KEY_ATTACKS[name]] = checkpoint["frames"].pop("1")
    path.write_bytes(dumps_canonical(checkpoint, "render checkpoint"))

    problems = verify_render.audit_render_directory(render_dir)
    assert any(
        "frame number" in problem or "canonical spelling" in problem for problem in problems
    ), problems


def test_the_canonical_frame_key_is_accepted_by_the_audit(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The control: the spelling every real checkpoint actually carries."""
    render_dir = _write_render(tmp_path, render_plan)
    _write_checkpoint(render_dir)
    assert verify_render.audit_render_directory(render_dir) == []


def test_a_checkpoint_naming_a_frame_the_manifest_does_not_is_refused(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """A checkpoint cannot vouch for a frame the finished render never recorded."""
    render_dir = _write_render(tmp_path, render_plan)
    path = _write_checkpoint(render_dir)
    checkpoint = loads_canonical(path.read_bytes(), "render checkpoint")
    checkpoint["frames"]["9999"] = checkpoint["frames"]["1"]
    path.write_bytes(dumps_canonical(checkpoint, "render checkpoint"))

    problems = verify_render.audit_render_directory(render_dir)
    assert any("9999" in problem for problem in problems), problems


def test_a_surviving_partial_directory_is_refused(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """A `.partial` here means a render died mid-frame, whatever else looks finished.

    The executor removes it as each frame is published, so its presence
    contradicts the manifest sitting beside it.
    """
    render_dir = _write_render(tmp_path, render_plan)
    (render_dir / ".partial").mkdir()
    problems = verify_render.audit_render_directory(render_dir)
    assert any(".partial" in problem for problem in problems)


def test_a_stray_file_beside_the_manifest_is_refused(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The module always claimed this; until V3 it only checked the two subdirectories."""
    render_dir = _write_render(tmp_path, render_plan)
    (render_dir / "notes.txt").write_text("left here by somebody", encoding="utf-8")
    problems = verify_render.audit_render_directory(render_dir)
    assert any("notes.txt" in problem for problem in problems)
    assert verify_render.main(["--render-dir", str(render_dir)]) == 1


def test_every_frame_is_decoded_not_only_the_boundary_pair(
    tmp_path: Path, render_plan: dict[str, Any]
) -> None:
    """The coverage claim itself: each of the 193 files is opened as an image.

    V2 decoded exactly two -- the final playback frame and the witness -- because
    those are the two the boundary measurement needs. Every other frame was
    checked by digest alone.
    """
    render_dir = _write_render(tmp_path, render_plan)
    decoded: list[Path] = []
    original = verify_render.verify_frame_image

    def recording(path: Path, **kwargs: int) -> list[str]:
        decoded.append(Path(path))
        return original(path, **kwargs)

    verify_render.verify_frame_image = recording
    try:
        assert verify_render.audit_render_directory(render_dir) == []
    finally:
        verify_render.verify_frame_image = original

    assert len(decoded) == len(render_plan["frames"]) == 193
    assert {path.name for path in decoded} == {entry["file"] for entry in render_plan["frames"]}
