# M3L GLB audit, lossless packaging, and semantic reverse compiler

## Commands

```bash
# Full structural audit to stdout and JSON report
python -m m3l.cli audit-glb dist/robot.glb --out dist/robot.quality.json

# Create editable source projection and lossless archive
python -m m3l.cli glb-decompile dist/robot.glb --out dist/robot.m3la
python -m m3l.cli glb-pack dist/robot.glb --out dist/robot.m3lp

# Restore the exact original bytes from the archive
python -m m3l.cli glb-restore dist/robot.m3lp --out dist/robot.restored.glb

# Apply an edit to a projection; the original GLB is required as the fidelity anchor
python -m m3l.cli glb-compile-source dist/robot.glb dist/robot.m3la --out dist/robot.edited.glb
```

A no-op `glb-compile-source` returns the exact original bytes when the projection equals the canonical projection. A supported edit rewrites only the JSON chunk; the binary and unknown non-JSON chunk payloads are kept byte-for-byte unchanged. JSON padding, whitespace, and chunk length may change for edits, so an edited asset is not expected to be byte-identical to the source.

## Editable projection schema

The `.m3la` file is JSON using schema `m3l.asset_projection.v1`. It records the exact source SHA-256 and source byte length. The current editable fields are:

- Nodes: `name`, `translation`, `rotation` (quaternion), `scale`.
- Standard material fields: `name`, base-color factor, metallic factor, roughness factor, emissive factor, alpha mode/cutoff, and double-sided flag.

Read-only fields include mesh assignments, node hierarchy, geometry, index buffers, normals/tangents, UVs, texture/image payloads and references, animations, skins, cameras, and arbitrary extensions. Structural edits are rejected instead of silently altering a referenced buffer layout. The projection is not a reconstruction of the original artist's CAD or procedural feature history.

## HTTP routes

The local API also provides:

- `POST /v1/quality/audit` with `{ "glb_base64": "..." }`
- `POST /v1/glb/decompile` with `{ "glb_base64": "..." }`
- `POST /v1/glb/compile-source` with `{ "glb_base64": "...", "source_projection": { ... } }`
- `POST /v1/glb/pack` with `{ "glb_base64": "..." }`
- `POST /v1/glb/restore` with `{ "package_base64": "..." }`

These asset routes have a decoded input limit of 52 MB. The HTTP API is unauthenticated; bind it to loopback or add authentication, network isolation, and request throttling before exposing it.

## Integrity model

- `.m3lp` is a ZIP container containing the original GLB, the projection, and a manifest with SHA-256/length.
- Restore checks the package schema, hash and length before returning the original payload.
- The projection is tied to the exact original GLB hash. It cannot be applied to a different file, even if that file looks similar.
- Asset audit scores only structural technical health. A separate production render and reference-driven vision review are required for visual quality claims.
