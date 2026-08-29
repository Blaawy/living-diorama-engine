"""Phase 35 media-encode spec: profile constants, naming and directory-entry rails.

The constants and the classifier are the deterministic vocabulary the whole Phase 35
package shares; every test here pins a reviewed string or a three-way ownership answer.
"""

import pytest

from living_diorama.media_encode import media_encode_spec as spec

EPISODE_ID = "episode_0000_to_0001"

FIVE_OWNED_ENTRIES = frozenset(
    {
        "episode_media_encode_manifest.json",
        f"{EPISODE_ID}.mp4",
        f"{EPISODE_ID}.srt",
        f"{EPISODE_ID}.vtt",
        "provenance",
    }
)


# ------------------------------------------------------------- profile constants


def test_manifest_format_is_the_frozen_literal() -> None:
    """The format tag is the reviewed literal, not a derivation."""
    assert spec.MEDIA_ENCODE_MANIFEST_FORMAT == ("living_diorama_episode_media_encode_manifest")


def test_schema_version_is_one() -> None:
    """The media encode manifest schema this build reads and writes is version 1."""
    assert spec.MEDIA_ENCODE_SCHEMA_VERSION == 1


def test_profile_id_is_media_encode_profile_v1() -> None:
    """The one reviewed viewing-projection profile."""
    assert spec.MEDIA_ENCODE_PROFILE_V1 == "media_encode_profile_v1"


def test_suffixes_are_the_four_reviewed_literals() -> None:
    """The four suffix literals every working-name and final-name law builds on."""
    assert spec.MP4_SUFFIX == ".mp4"
    assert spec.PARTIAL_SUFFIX == ".partial"
    assert spec.WRITING_SUFFIX == ".writing"
    assert spec.ENCODING_SUFFIX == ".encoding"


def test_preflight_and_snapshot_filenames_are_frozen() -> None:
    """The three staging temporaries carry exact, reviewed names."""
    assert spec.PREFLIGHT_MEDIA_FILENAME == "preflight.mp4.encoding"
    assert spec.PREFLIGHT_AUDIO_FILENAME == "preflight_audio.wav.encoding"
    assert spec.SNAPSHOT_AUDIO_FILENAME == "source_audio.wav.encoding"


def test_codec_and_bitrate_profile_constants_are_frozen() -> None:
    """The reviewed encode profile numbers and strings, exactly."""
    assert spec.VIDEO_CODEC == "libx264"
    assert spec.AUDIO_CODEC == "aac"
    assert spec.PIX_FMT == "yuv420p"
    assert spec.X264_PRESET == "medium"
    assert spec.X264_CRF == 18
    assert spec.AAC_BITRATE == "128k"
    assert spec.VIDEO_THREADS == 0
    assert spec.FFMPEG_MAJOR == 9


def test_placeholder_tokens_are_the_two_reviewed_literals() -> None:
    """The only non-literal path prefixes canonical output may carry."""
    assert spec.ASSEMBLY_DIR_TOKEN == "{ASSEMBLY_DIR}"
    assert spec.STAGING_TOKEN == "{STAGING}"


# ------------------------------------------------------ media_encode_id delegation


def test_media_encode_id_baseline_delegates_to_render_id() -> None:
    """Baseline naming is render_id's, whole."""
    assert spec.media_encode_id(mode="baseline", episode=0, previous_episode=None) == (
        "episode_0000_baseline"
    )


def test_media_encode_id_transition_delegates_to_render_id() -> None:
    """Transition naming is render_id's, whole."""
    assert spec.media_encode_id(mode="transition", episode=1, previous_episode=0) == EPISODE_ID


def test_media_encode_id_matches_render_id_for_the_same_leg() -> None:
    """The delegation is real: identical inputs give render_id's identical output."""
    from living_diorama.render_execution.render_execution_spec import render_id

    assert spec.media_encode_id(mode="transition", episode=1, previous_episode=0) == render_id(
        mode="transition", episode=1, previous_episode=0
    )


def test_media_encode_id_refuses_unknown_mode() -> None:
    """render_id's refusal law is inherited unchanged."""
    with pytest.raises(ValueError):
        spec.media_encode_id(mode="snapshot", episode=0, previous_episode=None)


def test_media_encode_id_refuses_negative_episode() -> None:
    """A negative episode has no directory name."""
    with pytest.raises(ValueError):
        spec.media_encode_id(mode="baseline", episode=-1, previous_episode=None)


def test_media_encode_id_refuses_a_non_direct_succession() -> None:
    """Only the one reviewed pairing is derivable."""
    with pytest.raises(ValueError):
        spec.media_encode_id(mode="transition", episode=2, previous_episode=0)


def test_media_encode_id_refuses_a_baseline_with_a_previous_episode() -> None:
    """A baseline has no predecessor by law."""
    with pytest.raises(ValueError):
        spec.media_encode_id(mode="baseline", episode=0, previous_episode=0)


def test_media_encode_id_refuses_a_bool_episode() -> None:
    """Bool is not an int here; render_id's exact-type law holds."""
    with pytest.raises(TypeError):
        spec.media_encode_id(mode="baseline", episode=True, previous_episode=None)


# ------------------------------------------------------- file names and directory


def test_media_filename_appends_mp4_to_the_episode_id() -> None:
    """The final episode file's deterministic name."""
    assert spec.media_filename(EPISODE_ID) == f"{EPISODE_ID}.mp4"


def test_media_temp_filename_appends_the_encoding_suffix() -> None:
    """The tool-written encode temporary's deterministic name."""
    assert spec.media_temp_filename(EPISODE_ID) == f"{EPISODE_ID}.mp4.encoding"


def test_media_filename_refuses_a_non_str_episode_id() -> None:
    """An episode id is a str, exactly."""
    with pytest.raises(TypeError):
        spec.media_filename(None)


def test_final_media_directory_entries_are_exactly_the_five_names() -> None:
    """A finished directory owns the manifest, the file, the two sidecars and provenance."""
    assert spec.final_media_directory_entries(EPISODE_ID) == FIVE_OWNED_ENTRIES
    assert len(FIVE_OWNED_ENTRIES) == 5


# -------------------------------------------------------- the entry classifier


@pytest.mark.parametrize("name", sorted(FIVE_OWNED_ENTRIES))
def test_classify_owned_for_each_final_directory_entry(name: str) -> None:
    """Each of the five finished entries is owned."""
    assert spec.classify_media_encode_directory_entry(name, episode_id=EPISODE_ID) == "owned"


@pytest.mark.parametrize(
    "name",
    [
        "episode_media_encode_manifest.json.writing",
        f"{EPISODE_ID}.mp4.encoding",
        "preflight.mp4.encoding",
        "preflight_audio.wav.encoding",
        "source_audio.wav.encoding",
    ],
)
def test_classify_partial_for_working_forms(name: str) -> None:
    """.writing and .encoding working forms of this phase's own files are partial."""
    assert spec.classify_media_encode_directory_entry(name, episode_id=EPISODE_ID) == "partial"


def test_classify_foreign_for_an_unrelated_file() -> None:
    """A name this phase never writes is foreign."""
    assert spec.classify_media_encode_directory_entry("x.txt", episode_id=EPISODE_ID) == "foreign"


def test_classify_foreign_for_a_directory_named_like_the_snapshot() -> None:
    """A DIRECTORY carrying the snapshot's name is foreign, never partial."""
    assert (
        spec.classify_media_encode_directory_entry(
            "source_audio.wav.encoding", episode_id=EPISODE_ID, is_directory=True
        )
        == "foreign"
    )


def test_provenance_directory_entries_are_the_two_manifest_copies() -> None:
    """Exactly the two bound manifest copies live in provenance/."""
    assert (
        frozenset(
            {
                "episode_media_assembly_manifest.json",
                "episode_caption_serialization_manifest.json",
            }
        )
        == spec.PROVENANCE_DIRECTORY_ENTRIES
    )


def test_classify_provenance_entry_owned_partial_foreign_trio() -> None:
    """The provenance classifier answers the same three-way contract."""
    assert (
        spec.classify_media_encode_provenance_entry("episode_media_assembly_manifest.json")
        == "owned"
    )
    assert (
        spec.classify_media_encode_provenance_entry("episode_caption_serialization_manifest.json")
        == "owned"
    )
    assert (
        spec.classify_media_encode_provenance_entry("episode_media_assembly_manifest.json.writing")
        == "partial"
    )
    assert spec.classify_media_encode_provenance_entry("x.txt") == "foreign"
    assert (
        spec.classify_media_encode_provenance_entry(
            "episode_media_assembly_manifest.json.writing", is_directory=True
        )
        == "foreign"
    )
