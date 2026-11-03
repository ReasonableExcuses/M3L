# Changelog and package notes

## Bundle update — 2026-10-28

- Added feature graph validation, formatting-independent scene/feature revisions, semantic diffs, and revision-guarded patch candidates in Python, CLI, and HTTP API; documented the staged roadmap execution plan.
- Added `m3l build` and `m3l verify-bundle` to produce reviewable asset bundles and verify payload hashes and sizes.
- Bundled the Lamborghini Revuelto-inspired exterior source, GLB, contact sheet and GLB audit from the experimental v0.6 generation pass.
- Added a Blender Cycles refinement pass for the Revuelto concept, including a polished orange clearcoat render, detailed split-spoke wheels with drilled rotors and calipers, cockpit geometry, a refined GLB, editable Blender scene and structural audit.
- **Important:** the complete Python compiler implementation in this archive remains v0.5.0. Its `pyproject.toml`, CLI, scene IR capability reporting and tests identify that release; the v0.6 `loft` compiler changes were not fully integrated into the source tree included here. See `GETTING_STARTED.md` and `VEHICLE_ASSET_NOTES.md` before attempting to rebuild the car.
- No car STEP assembly is included because the latest CAD export has an unresolved invalid hood-detail body.

## 0.5.0 — 2026-10-28 (included executable source core)

- Added eight deterministic procedural PBR surface presets: brushed/anodized metal, rubber, ceramic glaze, carbon fiber, leather grain, wood grain, fabric weave.
- Added embedded base-color, tangent-space normal and packed ORM textures; bounded texture resolutions; UV/tangent generation and GLB audit coverage.
- Added standard `KHR_materials_transmission`, `KHR_materials_ior`, and `KHR_materials_clearcoat` serialization.
- Added the procedural precision-lens study, multi-view diagnostic previews and a STEP export with 38 valid B-rep solids.
- Added GLB structural quality auditing, a restricted reverse compiler, lossless `.m3lp` packaging and API endpoints for supported operations.

## 0.3.0–0.4.0

- Added deterministic extrusion, revolve/lathe and sweep geometry; support constraints; custom-mesh topology audits; optional CadQuery/OpenCascade STEP export; optional Blender render bridge; GLB audits, reverse-compiler and package/restore workflow.
