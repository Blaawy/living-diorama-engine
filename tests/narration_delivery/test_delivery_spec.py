"""The delivery policy vocabulary: closed constants and exact arithmetic.

The spec module is the reviewable surface of the whole policy: the identity
strings a document declares, the two placement classes, and the partition
arithmetic every slot comes from. These tests pin each of them, because a
policy constant that can drift silently is not a policy.
"""

import pytest

from living_diorama.narration_delivery import (
    DELIVERY_ID_FORM,
    DELIVERY_PLAN_FORMAT,
    DELIVERY_POLICY_V1,
    DELIVERY_SCHEMA_VERSION,
    MIN_SLOT_FRAMES,
    PLACEMENT_ALLOCATED_UNSHOWN,
    PLACEMENT_CLASSES,
    PLACEMENT_SHOT_ANCHORED,
    partition_equally,
    playback_domain,
)

# ---- identity


def test_the_format_tag_is_pinned() -> None:
    """The format string names this exact contract and nothing else."""
    assert DELIVERY_PLAN_FORMAT == "living_diorama_episode_narration_delivery_plan"


def test_the_schema_version_is_one() -> None:
    """V1 is the version this build reads and writes."""
    assert DELIVERY_SCHEMA_VERSION == 1


def test_the_policy_identifier_is_pinned() -> None:
    """A slot cut under another policy must never be mistaken for one of these."""
    assert DELIVERY_POLICY_V1 == "narration_delivery_policy_v1"


def test_the_delivery_id_form_is_positional() -> None:
    """The identifier is derivable from the position, so it carries no freedom."""
    assert DELIVERY_ID_FORM % 1 == "delivery_0001"
    assert DELIVERY_ID_FORM % 412 == "delivery_0412"


def test_the_placement_classes_are_exactly_two() -> None:
    """A slot is anchored to a shot or allocated to an unshown unit; no third way."""
    assert PLACEMENT_CLASSES == (PLACEMENT_ALLOCATED_UNSHOWN, PLACEMENT_SHOT_ANCHORED)
    assert PLACEMENT_SHOT_ANCHORED == "SHOT_ANCHORED"
    assert PLACEMENT_ALLOCATED_UNSHOWN == "ALLOCATED_UNSHOWN"


def test_the_slot_floor_is_one_frame() -> None:
    """The floor is structural existence, not a smuggled speaking-rate opinion."""
    assert MIN_SLOT_FRAMES == 1


# ---- the playback domain


def test_the_canonical_playback_domain_excludes_the_witness() -> None:
    """Frames 1..192 play back; frame 193 is rendered once as evidence."""
    assert playback_domain(1, 193) == (1, 192)


def test_a_single_playback_frame_is_a_domain() -> None:
    """The smallest schedulable episode is one playback frame plus its witness."""
    assert playback_domain(5, 6) == (5, 5)


def test_an_empty_playback_domain_is_refused() -> None:
    """A timeline whose boundary is its start offers nothing to schedule on."""
    with pytest.raises(ValueError, match="no playback frame"):
        playback_domain(1, 1)


def test_an_inverted_playback_domain_is_refused() -> None:
    """A boundary before the start is not a domain at all."""
    with pytest.raises(ValueError, match="no playback frame"):
        playback_domain(10, 4)


# ---- equal partition: shape


def test_a_sole_claimant_takes_the_whole_span() -> None:
    """One claimant, one slot, every frame."""
    assert partition_equally(25, 144, 1) == [(25, 144)]


def test_the_canonical_fold_split_is_thirty_six_and_thirty_five() -> None:
    """71 frames across two claimants: the earliest takes the leftover frame."""
    assert partition_equally(25, 95, 2) == [(25, 60), (61, 95)]


def test_an_even_split_has_no_leftover() -> None:
    """When the arithmetic is exact, every slot is the same size."""
    assert partition_equally(1, 24, 4) == [(1, 6), (7, 12), (13, 18), (19, 24)]


def test_the_remainder_goes_to_the_earliest_claimants() -> None:
    """Largest remainder with equal weights ties everywhere, so index decides."""
    assert partition_equally(1, 10, 3) == [(1, 4), (5, 7), (8, 10)]


def test_every_claimant_gets_at_least_the_floor() -> None:
    """As many claimants as frames: one frame each, in order."""
    assert partition_equally(7, 9, 3) == [(7, 7), (8, 8), (9, 9)]


# ---- equal partition: invariants


@pytest.mark.parametrize(
    ("first", "last", "claimants"),
    [(1, 192, 1), (1, 192, 3), (25, 95, 2), (145, 192, 5), (10, 10, 1), (1, 7, 7)],
)
def test_slices_tile_the_span_exactly(first: int, last: int, claimants: int) -> None:
    """No frame dropped, none counted twice, order preserved, floor respected."""
    slices = partition_equally(first, last, claimants)
    assert len(slices) == claimants
    cursor = first
    for start, end in slices:
        assert start == cursor
        assert end >= start
        assert end - start + 1 >= MIN_SLOT_FRAMES
        cursor = end + 1
    assert cursor == last + 1


def test_slice_sizes_never_differ_by_more_than_one_frame() -> None:
    """Equal weights mean equal slots, up to the indivisible remainder."""
    sizes = [end - start + 1 for start, end in partition_equally(1, 100, 7)]
    assert max(sizes) - min(sizes) <= 1
    assert sizes == sorted(sizes, reverse=True)


# ---- equal partition: refusals


def test_zero_claimants_are_refused() -> None:
    """Partitioning among nobody is a defect, not an empty schedule."""
    with pytest.raises(ValueError, match="0 claimants"):
        partition_equally(1, 10, 0)


def test_a_negative_claimant_count_is_refused() -> None:
    """A count below zero is the same defect wearing a sign."""
    with pytest.raises(ValueError, match="-1 claimants"):
        partition_equally(1, 10, -1)


def test_an_empty_span_is_refused() -> None:
    """A span with no frames cannot host a slot of any size."""
    with pytest.raises(ValueError, match="empty frame span"):
        partition_equally(10, 9, 1)


def test_more_claimants_than_frames_are_refused() -> None:
    """A slot below the structural floor is refused, never shrunk to fit."""
    with pytest.raises(ValueError, match="cannot fit 25 delivery slots"):
        partition_equally(1, 24, 25)


def test_the_refusal_names_the_span_and_the_count() -> None:
    """A refusal that names its numbers is a refusal somebody can act on."""
    with pytest.raises(ValueError, match=r"3 delivery slots .* 2 frames .*\[5, 6\]"):
        partition_equally(5, 6, 3)
