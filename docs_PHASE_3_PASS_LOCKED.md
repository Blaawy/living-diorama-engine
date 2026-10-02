# PHASE 3 — PASS & LOCKED

Director lock date: 2026-10-03

Locked candidate:
- pre-lock HEAD: 0795305
- Phase 3 MASTER SHA-256: 494d945853138d401678bed726c80e829667a873fcb1a186f0928556babf2d78
- MASTER size: 64,277,558 bytes
- MASTER members: 248
- fresh-extraction tests: 1808 PASS
- Phase 2 rev10 remains locked
- historical canonical remains untouched

Director acceptances:
1. Accept the two independent read-only Claude round-2 reviewers as the final red-team substitute because the requested DeepSeek rerun could not run without the missing DPAPI credential. They used the same briefs, found 29 issues including four high-severity findings, and the actionable findings were fixed with regression coverage.
2. Accept deterministic record -> bake -> engine pose evaluation as the Phase-3 determinism requirement. Pixels are repeatable to the measured 67.6 dB same-frame floor but are NOT claimed byte-identical.
3. Accept whole-street avoidance as declared agent policy. World truth remains the actually closed edge; the twin-direction avoidance is logged separately as avoided_by_policy.
4. Remaining disclosed limitations in the Phase-3 lock review request are non-blocking.

Accepted complete:
- real agent -> TraCI/SUMO integration
- SUMO remains mobility truth
- sealed 24-agent replan/control proof
- 24/24 agents complete both goals in both arms
- 18 treatment agents replan; baseline has zero closure reroutes
- explicit Phase-3 schema versions with legacy admission preserved
- runtime extractor identity/truth guard
- Phase-2 production playback driven from the sealed Phase-3 record
- record/hash binding through bake, engine evaluation and render evidence
- closure/access, speed/routing, traffic-light/control, demand/flow
- deterministic replay and save/reload lineage
- adversarial and long-duration/performance evidence
- fresh-extraction MASTER verification

Lock rule: Phase 3 is closed. Reopen only on a concrete regression.

Next: Phase 4 — YouTube Factory.
