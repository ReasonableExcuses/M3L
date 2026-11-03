# Package Contents — M3L v0.7.0

This repository contains the complete M3L v0.7.0 source code, native Rust core crate, test suites, CLI tools, documentation, showcase assets, and multi-format deliverables.

- `crates/m3l_core/`: High-performance Rust geometry crate with PyO3 bindings and WebAssembly target.
- `m3l/`: Complete Python engine modules:
  - `compiler.py`: Semantic AST compiler, instancing, and kinematic constraint solver (`snap_to_ground`, `align_bottom`, `attach_to`, `mirror_copy`).
  - `geometry.py`: Procedural solids, Lofts, CSG Booleans (`manifold3d`), Loop subdivision, splines, and hybrid Rust routing.
  - `exporters.py`: Multi-format exporters (`export_obj`, `export_stl`, `export_usd`).
  - `glb.py`: Deterministic binary glTF 2.0 serializer.
  - `blender_backend.py`: Headless Blender 4.4 EEVEE/Cycles photorealistic rendering.
  - `mcp_server.py`: Model Context Protocol JSON-RPC server with 8 tools for AI pair programming.
  - `parser.py`: Dependency-free M3L declarative grammar parser with recursive-descent math evaluator.
  - `cli.py`: Unified command-line interface.
- `skills/m3l_authoring/SKILL.md`: Authoritative guide and formulas for AI agents and human authors.
- `viewer/index.html`: Modern client-side multi-format 3D viewer supporting GLB, OBJ, and STL with OrbitControls, studio lighting, wireframe inspection, and topology statistics.
- `examples/`: Production-grade showcase models (`industrial_drone_showcase.m3l`, `lamborghini_revuelto_outer.m3l`, `apex_orbital_probe.m3l`, etc.).
- `dist/`: Pre-compiled deliverables including:
  - `industrial_drone_showcase.glb`, `drone.obj`, `drone.stl`, `drone.usda`
  - `lamborghini_revuelto.glb`, `apex_orbital_probe.glb`
  - High-resolution Blender Cycles renders (`drone_hero_render.png`, `lamborghini_revuelto_hero.png`)
- `tests/`: Full pytest suite (91 passing, 4 skipped, 0 failures, 100% pass rate).
