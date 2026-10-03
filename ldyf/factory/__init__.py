"""Phase 4 -- the YouTube factory.

One command turns an episode brief into a reviewable episode package:

    brief -> rule manifest -> deterministic simulation (both arms, sealed)
          -> facts (evidence-bound consequence extraction)
          -> story (beats selected from measured outcomes)
          -> shots (cameras planned from the record, visibility measured)
          -> narration (every line bound to a fact or a shot)
          -> voice, captions, music bed, timeline
          -> Unreal / Movie Render Queue segments -> assembled preview
          -> truth audit + lineage

The laws inherited from Phases 1-3 hold here unchanged: SUMO is mobility
truth, Unreal is presentation, a consequence is only ever computed by
re-reading sealed artefacts, and no model is called at runtime. Language is
produced by templates filled from measured values, so a sentence that states a
number can be traced to the artefact field it came from -- and is refused when
it cannot be.

Every stage FAILS CLOSED: missing evidence, a conflicting measurement, a camera
that does not hold its subject, a line that outruns its evidence, a stale
upstream hash or an incomplete render stops the pipeline with a typed error.
Nothing downstream of a failed stage is produced.
"""

FACTORY_VERSION = "factory_v1"


class FactoryError(RuntimeError):
    """Base of every fail-closed refusal in the factory.

    `stage` names the pipeline stage that refused and `code` is a stable
    machine-readable reason, so a caller (and a test) can tell a missing
    artefact from a conflicting one without parsing prose.
    """

    stage = "factory"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{self.stage}:{code}] {message}")
        self.code = code
        self.message = message
