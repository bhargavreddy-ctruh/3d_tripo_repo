# Branch: `structured-coplanar-quad-strip` — Experiment: Quad-Strip Engine

**Status:** Experiment — not merged. Promising approach for future work when input mesh has clean quad structure.

## What This Branch Tried

A fundamental shift: instead of coplanar flood-fill merge, operate strictly along **continuous quad strips** (coordinate ribbons). Step across opposite edges (`e_i → e_{i+2}`) and only decimate **complete transverse chords** — strips that run all the way from one mesh boundary to another (or close into a full ring).

Rail vertices (the vertices along the dissolved chord) have valence 2 after the chord is removed, so they dissolve cleanly along the rail — no T-junctions, no n-gons at any point in the process.

### Guarantees (on a clean quad mesh)

- 100% quads in output — zero n-gons at any step
- Zero T-junctions — partial chords are never dissolved
- Perfect field-alignment — grid direction preserved along all feature flows
- Zero ear-clipping artifacts — no interior diagonal generation

### Why it's not the default yet

The quad-strip engine requires a **dense, well-structured quad mesh** as input (pure quads with clean opposite-edge traversal). On meshes where Instant Meshes falls back to quadric decimation — which produces a triangle/quad mixture — there are no continuous quad strips to trace. The engine has nothing to work with.

The current default (`coplanar_merge.py`) handles mixed tri/quad/n-gon input gracefully. As remesher reliability improves (fewer fallbacks to quadric decimation), switching to the quad-strip engine would produce cleaner output.

### Key file

`core/quad_strip_engine.py` — full implementation of the strip-tracing and chord-decimation algorithm.

See `QUAD_STRIP_PIPELINE_ARCHITECTURE.md` on this branch for the full mathematical treatment, failure-mode analysis, and comparison with the five prior local heuristics that were tried before this approach.

## Key Commits

- `3dea35e` — feat(retopo): structured coplanar ribbon reduction and quad-strip engine
- `f0d9142` — clean: remove obsolete benchmark files, legacy test infrastructure, unused docs

## Relationship to `field-aligned-merge-experiments`

This branch diverged from `field-aligned-merge-experiments`. The dome/saddle caps (`dome_caps.py`) from that branch are present here too. The quad-strip engine is an **alternative** to `coplanar_merge.py`, not a replacement for the rest of the pipeline.

## For Future Work

If the remesher step can be tuned to reliably produce pure-quad output (e.g. by using Instant Meshes' `--face-count` and `--align` flags more aggressively), switching `finalize_component.py` to use `quad_strip_engine` instead of `coplanar_merge` would yield cleaner results with mathematical guarantees.
