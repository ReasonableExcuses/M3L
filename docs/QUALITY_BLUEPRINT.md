# Quality blueprint for extreme-quality 3D assets

## What has to be solved

A high-quality 3D asset is not a mesh with a large triangle count. Its perceived quality comes from the combined result of silhouette and shape, geometric continuity, normals/tangents, UVs, material response, texture resolution and filtering, lighting, camera, and the target renderer. A structural audit can detect a subset of technical defects; it cannot establish that the shape matches a reference or looks artistically convincing.

### Reference objects and production lessons

The Khronos glTF Sample Assets catalog is a useful public benchmark because each asset has a feature description, preview, and license entry. It includes the Flight Helmet, Damaged Helmet, Chronograph Watch, Commercial Refrigerator, and assets demonstrating transmission, sheen, clearcoat, anisotropy and other PBR extensions:

- Catalog: https://github.khronos.org/glTF-Assets/
- Asset repository and model index: https://github.com/KhronosGroup/glTF-Sample-Assets
- Damaged Helmet GLB: https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/DamagedHelmet/glTF-Binary/DamagedHelmet.glb
- Chronograph Watch modeling/optimization notes: https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/ChronographWatch/README.md
- glTF 2.0 specification: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html

The Chronograph Watch documentation is especially instructive. Its source is described as roughly 885,000 triangles before optimization. The final runtime asset demonstrates careful mesh/texture tradeoffs: normal maps are used where appropriate, but extra geometry is retained for a smooth metallic backplate because low-resolution geometry and 8-bit normal maps created visible tessellation or shading artifacts. It also uses texture transforms, AO, and transmission/material variants. This is evidence that the correct representation is feature-dependent; more polygons or more maps are not always better.

The Flight Helmet notes document texture compression choices. In the published comparison, KTX2/Basis compression reduces several large texture sets, while normal maps use a higher-fidelity compression mode to reduce visible damage. The general design requirement is to treat color textures and data textures (normal, roughness/metalness, AO) differently, rather than blindly compressing every image the same way.

### Procedural PBR material path (implemented in platform v0.5)

M3L material blocks now accept `surface` presets and a bounded `texture_resolution` (128, 256, 512, or 1024). Presets bake standard PNG base-color variation, a tangent-space normal map, and a packed ORM map into the GLB. Textured primitives receive `TEXCOORD_0` plus a computed `TANGENT` frame; cylindrical/revolved seams are unwrapped per triangle. This makes materials portable to normal glTF PBR renderers.

The presets are controlled procedural patterns, not photogrammetry or physically calibrated scanned materials. For high-end hero assets, the next material steps are triplanar/world-space consistency for arbitrary topology, artist/reference-based texture calibration, mip/normal compression policy, UV stretch metrics, and production-render visual review. The current VTK preview should not be used to rate metallic appearance or transmission.

### M3L quality gates

1. **Container integrity:** GLB header/version/declared length, ordered chunks, valid JSON, valid buffer views, accessor bounds, and valid references.
2. **Geometry structure:** valid POSITION/indices, attribute count agreement, normals and UV coverage, finite values, degenerate primitives, triangle counts and bounds. Sparse accessors are decoded; compressed geometry that this tool cannot decode is reported rather than silently treated as valid geometry.
3. **Material/texture package:** material references, PBR factors, texture references, image payload integrity, decodable embedded image dimensions, and presence of normal/roughness/AO maps where authored.
4. **Rendering review:** standardized turntable views for silhouette/part inspection. The optional Blender backend is the route for production Eevee/Cycles renders; VTK views are diagnostic only and may not reproduce all glTF material extensions.
5. **Reference-driven visual evaluation:** compare standardized renders with a reference and have a separate vision model identify specific defects. Keep artistic/semantic scores separate from structural score. Record the review prompt, model, renderer version, exposure, resolution, and seed so results are reproducible.
6. **Targeted repair:** revise named parameters or source operations, recompile, and rerun only checks invalidated by the edit. Never call a render “better” without comparing the same camera/render setup.

### What the score means

`m3l audit-glb` reports a `technical_structural_score` from rules over geometry, material, and delivery checks. It is not trained on human preferences and must not be interpreted as photorealism, beauty, reference similarity, manufacturability, or artistic quality. The report includes raw counts and concrete warnings so an LLM can repair issues directly.

## Why reverse compilation cannot recover everything

glTF is a runtime delivery format. It stores scene graphs, vertex attributes, materials, images, animations, and extensions, but it does not generally preserve the original CAD feature tree, procedural parameters, sculpt history, retopology decisions, or authoring operations. The mapping from a modeling workflow to its final triangle mesh is many-to-one, so there is no unique inverse compiler for arbitrary geometry.

M3L therefore uses two lanes:

- **Lossless lane:** package the exact original GLB and verify SHA-256 so it can be restored byte-for-byte.
- **Semantic lane:** project supported node transforms/names and standard material factors into editable JSON. Compilation applies a narrow whitelist and preserves non-JSON chunks. Mesh data, textures, animations, skins, cameras, material texture references, and arbitrary extension payloads are read-only in this release.

For assets created by M3L itself, future versions should persist the actual parametric construction graph as it is authored. Imported arbitrary assets can be decomposed and approximated, but reconstructed history must be labeled as inferred rather than original.
