"""Phase 33 -- Episode Media Assembly.

Mechanical assembly of one episode's already-decided visual presentation and
already-composed audio into one provenance-bound, self-contained, pre-encode media
assembly: a physical presentation-rate PNG sequence realized from the accepted Phase 23
Render Manifest and its playback frames per the accepted Phase 27 Presentation Plan, the
unchanged Phase 31 episode WAV carried alongside it, byte copies of every document this
phase bound -- including the two Phase 25 / Phase 22 verification witnesses that make the
render-to-timing join re-provable from the published directory alone -- and this phase's
own Episode Media Assembly Manifest.

PHASE 33 REALIZES A LOCKED PRESENTATION ONTO LOCKED RENDERED ASSETS. IT DECIDES NOTHING.

It never invents a semantic frame, drops one, reorders one, or exposes the terminal
witness frame; never changes world truth, simulation time, story truth, narration meaning,
realized wording, camera direction, speech placement or composed audio; never decodes,
re-renders, scales, colour-manages or transforms a pixel; never synthesizes, mixes,
normalizes or re-encodes audio; never reads, serializes, styles or burns a caption; never
encodes a video stream, creates a container, or muxes. Every realized frame is an
independent physical byte copy -- never a symlink, a Windows junction, or a hardlink -- and
every Phase 33-owned regular file is proven, by its own self-contained audit, to hold
exactly one directory entry.

This package is a read-only consumer of five finished documents: the Phase 23 Episode
Render Manifest and its playback PNGs, the Phase 27 Episode Presentation Plan, the
Phase 31 Episode Audio Composition, and the Phase 25 Narration Delivery Plan and Phase 22
Shot Direction Plan it carries forward only as digest-bound provenance witnesses. It must
never reach into live simulation, never import ``living_diorama.caption`` -- the paired
sibling this phase never consumes and is never consumed by -- and never import ``story``,
``narration``, ``language_realization``, ``voice``, ``voice_execution`` or ``audio_track``.
Before any upstream geometry becomes authoritative, this layer reuses -- in full,
unweakened -- the locked Phase 27 source-verification gate that already owns that proof.

Because this phase copies rather than generates, its own output earns byte-for-byte
determinism: the same bound input bytes produce byte-identical assembly output, on any
machine, in any run.

Downstream layers (caption serialization, video encode, container mux) consume the
artifacts this package and its sibling produce and are not part of it.
"""

from living_diorama.media_assembly.media_assembly_audit import audit_media_assembly_directory
from living_diorama.media_assembly.media_assembly_manifest import (
    build_episode_media_assembly_manifest_bytes,
    build_episode_media_assembly_manifest_document,
)
from living_diorama.media_assembly.media_assembly_mapping import MediaAssemblyRefused
from living_diorama.media_assembly.media_assembly_publisher import publish_episode_media_assembly
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_assembly.media_assembly_spec import media_assembly_id
from living_diorama.media_assembly.media_assembly_staging import MediaAssemblyDirectoryRefused

__all__ = [
    "MediaAssemblyDirectoryRefused",
    "MediaAssemblyRefused",
    "audit_media_assembly_directory",
    "build_episode_media_assembly_manifest_bytes",
    "build_episode_media_assembly_manifest_document",
    "media_assembly_id",
    "publish_episode_media_assembly",
    "validate_episode_media_assembly_manifest",
]
