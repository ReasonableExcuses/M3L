# M3L asset-engine execution plan

This plan translates `ROADMAP_AI_3D_ASSET_ENGINE.md` into dependent engineering milestones. It keeps M3L's deterministic compiler as the source of truth and treats visual quality as a separately measured outcome.

## Milestone 1: Make authored design history trustworthy

**Roadmap areas:** Phase 1, Phase 5, Phase 8.

- Validate feature names, parent references, graph cycles, phase/layer values, and parameter value shapes.
- Give scene and feature graphs stable semantic revisions that do not change when source formatting or line numbers change.
- Expose semantic diffs through Python, CLI, and HTTP so repair loops can see named changes.
- Return patch base/candidate revisions and diffs; reject stale patch requests with an optimistic revision check.
- Bind feature operations to scene objects and define a typed, deterministic operation registry.
- Make parameter patches transactional: apply, recompile, and return the candidate diff without mutating accepted state.
- Persist parent revision, patch, diagnostics, and acceptance state in asset bundles.

**Acceptance:** invalid graphs produce stable diagnostics; formatting-only edits retain a revision; one parameter change produces a focused diff; rejected candidates cannot overwrite the accepted source or bundle.

## Milestone 2: Establish a repeatable visual review contract

**Roadmap areas:** Phase 4, Phase 10.

- Add named render profiles with pinned camera framing, light rig, background, color management, engine, samples, and resolution.
- Store the complete profile and renderer version beside each preview.
- Define a versioned visual-defect schema with evidence, confidence, view, and affected feature/object names.
- Keep deterministic readiness, image integrity, and subjective visual review as separate report sections.

**Acceptance:** equivalent source and profile yield reproducible render settings and comparable views; a missing renderer or unsupported setting is explicit; no structural score is presented as an aesthetic score.

## Milestone 3: Improve form, shading, and material control

**Roadmap areas:** Phase 2, Phase 3.

- Add mesh checks for normals, boundary quality, triangle density, and scale-aware degeneracy.
- Add controlled bevel/edge-treatment and subdivision-friendly profile operations where the backend supports them.
- Add material layers and colorway variants on top of existing deterministic PBR maps.
- Keep render geometry and delivery/runtime geometry separable through explicit export profiles.

**Acceptance:** each operation has bounded inputs, deterministic output, documented backend support, and fixtures showing both technical validity and rendered effect. Quality claims require a fixed view and a separate visual rubric.

## Milestone 4: Close the repair and asset-family loop

**Roadmap areas:** Phase 5, Phase 6, Phase 7, Phase 8.

- Map supported defect types to semantic parameters and candidate patches.
- Generate bounded color/material and geometry variants from named parameters.
- Add target profiles for preview, hero render, and real-time delivery; add LOD/deformation checks only where topology can be measured reliably.
- Extend asset bundles with revision history, previews, profiles, and per-variant audits.

**Acceptance:** every candidate is reproducible from source plus patch history, hard constraints remain enforced, and the selected variant records why it passed its stated checks.

## Milestone 5: Measure improvements against fixed tasks

**Roadmap areas:** Phase 9 and the evaluation principles in Phases 4 and 10.

- Freeze a small licensed task set with briefs, reference views, hard constraints, and expected deliverables.
- Record compile/render/review latency, repair rounds, resource use, technical failures, and human/vision rubric results separately.
- Compare against a stated baseline under equal model, prompt, renderer, and compute budgets.
- Publish raw results and failed outputs with any quality or efficiency claim.

**Acceptance:** the benchmark can be rerun from pinned inputs and reports technical correctness separately from subjective ratings.

## Current increment

The first increment implements feature graph validation, formatting-independent asset/feature revisions, and semantic scene diffs in the compiler, CLI, and HTTP API. Patch requests can use an expected revision and successful candidates return their base/candidate revisions and diff. Authored literal values are restricted to JSON-compatible data so revisions remain serializable. This is the foundation for operation binding and transactional repair; it does not yet make feature declarations generate geometry or provide visual-quality judgments.
