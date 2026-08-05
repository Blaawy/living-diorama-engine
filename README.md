# Living Diorama Engine

## Mission

Living Diorama Engine is a production simulation engine, not a game and
not a simulation toy. It exists to produce **one controlled system
experiment per episode** for a YouTube series.

Each episode changes exactly **one rule**. The world evolves. The
consequences become permanent. The next episode starts from the exact
world state the previous episode saved. The world never resets.

The viewer is not watching gameplay -- the viewer is watching history
being created. Everything in this repository exists to generate
believable, persistent, deterministic history as cheaply and reliably as
possible.

## Current MVP Scope

The MVP simulates at **district level**, using aggregate statistics
(population counts, resource stock, and scarcity/fear/trust/pressure
scores) rather than individual citizen agents.

The MVP's vertical slice must prove:

1. A baseline multi-district world loads and runs stably.
2. Removing a law (e.g. movement/resource-sharing between districts)
   causes district-level scarcity, fear, trust, and institutional
   pressure to evolve.
3. A wall may emerge between two districts, but only from **sustained**
   causal conditions -- never a single-tick spike, and never hard-coded.
4. Infrastructure connected to a wall gradually becomes dependent on it.
5. The law can later be restored -- and the wall is **not** deleted.
   Wall persistence through a law restoration is an explicit,
   structurally-enforced domain invariant (see `docs/architecture.md`,
   section 7), not an accident of system ordering.
6. The resulting world saves as a new, immutable episode folder and
   reloads with the wall and its dependency values intact.

Full architectural detail -- entity model, system order and rationale,
save format, event/memory pipeline, dependency graph, roadmap, and
acceptance tests -- lives in [`docs/architecture.md`](docs/architecture.md).

## Explicit Non-Goals (for this phase and the MVP overall)

This project deliberately does **not**, in its current phase:

- Build a full game, graphics, or any UI.
- Simulate individual citizens -- relationships, individual mortality,
  reproduction, and per-citizen memory are deferred to Post-MVP
  (`docs/architecture.md`, section 11).
- Call any LLM from inside the simulation loop. Simulation is entirely
  deterministic: state machines, probabilities, and mathematical rules.
  LLMs are reserved for a future, strictly downstream narration stage.
- Integrate Godot or Blender. `render/` and `narration/` exist as
  package stubs with docstrings only -- no implementation yet.
- Add networking, multiplayer, or any runtime optimization.
- Depend on any paid service. Everything runs locally.

This repository (Phase 0) additionally does not yet contain any entities,
systems, or simulation logic -- only the package scaffold, tooling
configuration, and a single smoke test proving the package installs and
imports.

## Local Setup

Requires Python 3.13.

```bash
# From the repository root
python3.13 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

This installs the package in editable mode along with its development
tools (`pytest`, `mypy`, `ruff`). There are no runtime dependencies.

## Quality Commands

Run all four before committing -- this is exactly what CI runs
(`.github/workflows/ci.yml`):

```bash
ruff check .            # lint
ruff format --check .   # formatting check (use `ruff format .` to fix)
mypy                    # strict type checking
pytest                  # test suite
```

## Project Layout

```
src/living_diorama/   # the engine package (src-layout)
tests/                 # test suite, mirrors src/living_diorama structure as it grows
docs/                  # architecture document and decision records
saves/                 # episode save folders (git-tracked; each episode is immutable)
```

See `docs/architecture.md` for what each package under `src/living_diorama/`
is responsible for, and for the fixed per-tick system execution order once
systems exist.
