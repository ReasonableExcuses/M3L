# M3L quality evaluation loop

## Two separate reports

1. `audit-glb` produces objective structural metrics and machine-actionable diagnostics. It checks GLB container/accessor structure, geometry attribute consistency, material references, embedded images where Pillow is installed, and common glTF structural defects.
2. `scripts/render_asset_turntable.py` generates a fixed 4–16 view diagnostic turntable with optional VTK. The output can be supplied to a separate vision-capable model for an explicit critique of silhouette, part relationships, visual balance and visible defects.

For a production render, use the optional Blender backend:

```bash
python -m m3l.cli render examples/vase.m3l --out dist/vase_cycles.png --engine cycles --resolution 1024 --samples 128
```

Blender is an external optional dependency. If it is not installed or `M3L_BLENDER` is unset, M3L reports `BLENDER_UNAVAILABLE`; it never silently substitutes its diagnostic preview and calls it a production render.

## Turntable command

```bash
pip install -e '.[preview]'
python scripts/render_asset_turntable.py dist/vase.glb --out-dir dist/turntable/vase --views 8 --size 768
# Geometry-only shading helps inspect silhouette/parts without judging PBR material fidelity.
python scripts/render_asset_turntable.py dist/vase.glb --out-dir dist/turntable/vase-geometry --views 8 --size 768 --neutral-materials
```

The folder contains `view_00.png`…`view_07.png`, a contact sheet, and `turntable_report.json`. Lighting and camera conventions are standardized across all angles, and every image is hashed. VTK is not a full fidelity glTF PBR reference renderer, especially for transmission or newer material extensions.

## Procedural material coverage

Platform v0.5 accepts eight deterministic PBR surface presets and validates that a material's texture references have UVs; generated normal maps also include tangents. It writes glass/coating parameters through standard `KHR_materials_transmission`, `KHR_materials_ior`, and `KHR_materials_clearcoat` glTF extensions when a scene material declares them. The roughness and metallic channels in generated ORM maps act as multipliers for the material's authored scalar factors. The structural score evaluates UVs only on textured primitives and tangents only where normal maps are referenced. Raw coverage percentages remain global diagnostics, so an untextured component is not penalized for omitting unused UV attributes.

## Recommended closed loop

1. Compile or import the asset and record source hash and asset version.
2. Run `audit-glb`; turn every error and applicable warning into a repair task.
3. Render the identical turntable/lighting configuration before and after a proposed edit.
4. Ask an independent vision model for a structured critique with categories: silhouette, proportion, surface continuity, material plausibility, texture artifacts, clipping, composition, and task/reference match. Require it to cite view indices and describe visible evidence.
5. Translate each accepted critique into a named parameter/source patch, not an unbounded rewrite.
6. Re-run structural audit, renders, and round-trip tests. Keep all versions so regressions are measurable.

Do not collapse these into one score: a valid GLB can look poor, and a beautiful render can come from a technically fragile or non-editable asset. Future benchmark tasks should include public reference assets with explicit licenses, held-out object briefs, and human preference comparisons.
