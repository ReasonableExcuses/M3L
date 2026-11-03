# Lamborghini Revuelto-inspired exterior — asset notes

## Deliverables

- Editable authored scene text: `examples/lamborghini_revuelto_outer.m3l`
- Ready-to-open binary glTF: `dist/lamborghini_revuelto_outer.glb`
- Multi-view diagnostic contact sheet: `dist/lamborghini_revuelto_v06_color/contact_sheet.png`
- Structural audit: `dist/lamborghini_revuelto_glb_audit.json`
- Refined Blender scene: `dist/lamborghini_revuelto_refined.blend`
- Refined, presentation-ready GLB: `dist/lamborghini_revuelto_refined.glb`
- Cycles hero render: `dist/lamborghini_revuelto_hero.png`
- Refined GLB audit: `dist/lamborghini_revuelto_refined_audit.json`
- Reproducible Blender refinement script: `scripts/refine_lamborghini_revuelto.py`

## Scope

This is a procedural exterior-body concept inspired by public images of a Lamborghini Revuelto. It focuses on the external body, greenhouse, aero accents, wheels and visual signatures. It is not factory CAD, not a scan and not a claim of exact OEM dimensions. Interior, drivetrain and engineering detail are outside the stated scope.

## GLB audit snapshot

The included audit reports a valid glTF 2.0 GLB, 1,962,256 bytes, with 123 nodes, 42 meshes/primitives, 20,624 vertices, 21,580 triangles, 9 materials and 12 embedded images/textures. It reports zero errors and a set of missing-normal warnings on several primitives. The rule-based structural score is 60.4/100, which is a technical diagnostic rather than a visual-quality score.

## Known gaps

1. The car scene uses the v0.6 `loft` primitive, but the bundled Python CLI is the v0.5.0 core. The source is provided for inspection, not as a guaranteed-rebuildable example in this archive.
2. A STEP assembly was not included. The latest CAD export attempt failed validation on a hood-detail body and should be repaired before claiming CAD round-trip quality.
3. The provided view sheet is a diagnostic preview, not a Blender Cycles/EEVEE production render. Visual inspection and refinement remain necessary before treating the body as production-ready.

## Blender refinement pass — 2026-10-28

The refined GLB is built from the included exterior concept GLB. The pass tunes the orange clearcoat paint, smoked glazing and studio reflections; smooths and recalculates the main shell normals; replaces the basic wheel faces with forged split spokes, drilled carbon-ceramic rotors, red calipers and machined hubs; adds a minimal cockpit, and cleans up the Y-shaped front light guides. The new GLB audits as valid glTF 2.0 with 52,533 vertices, 60,980 triangles, 16 materials, and no structural errors.

This is a substantial visual refinement and product render, but it is still a procedural concept rather than a photogrammetric or factory-CAD model. The included M3L source still uses `loft`, which the bundled v0.5.0 CLI cannot compile.
