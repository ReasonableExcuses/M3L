# M3L AI 3D Asset Engine Roadmap

## Vision

This project should not be developed as a CAD replacement. It should be developed as an AI-native 3D asset-generation engine for premium-looking, detailed, realistic or stylized objects intended for rendering, games, and animation.

The current project already has the right technical foundations: a constrained authoring language, structured scene IR, validation and repair philosophy, export discipline, render integration, and evaluation methodology. The missing work is to evolve the engine from a valid toy prototype into a serious visual asset-generation system.

The target outcome is not merely a valid 3D object. The target is:

- realistic or gorgeous visual quality
- clean material response
- controlled form and silhouette
- structural correctness
- strong visual review loop
- repairability through semantic operations
- export-ready asset packaging for real-world production workflows

## Strategic direction

The strategic direction must be:

- Asset-first, not CAD-first
- Visual-quality-first, not just validity-first
- Repairable and versioned, not one-shot generation
- Production-oriented, not prototype-only

This roadmap focuses on the technical engine, not on timeline estimates.

---

## Phase 1: Upgrade the core model from a scene compiler to a real asset-generation engine

### Goal

Move from a constrained procedural scene format to a richer, feature-based design system for premium assets.

### What to build

- Parametric feature graph instead of a shallow scene AST
- Named feature operations with editable parameters
- Editable history and parameter provenance
- Multi-layer asset design:
  - base form
  - refinement layer
  - detail layer
  - material layer
  - variant layer
- Richer operation support:
  - primitives
  - booleans
  - offsets
  - bevels
  - shelling
  - fillets
  - trims
  - lofts
  - deformation patterns
  - micro-detail generators

### Why this matters

The current system is disciplined and safe, but too shallow for premium asset creation. Realistic and beautiful objects require deliberate form control, not just valid command sequences.

### Modules to evolve

- `m3l/parser.py`
- `m3l/compiler.py`
- `docs/ARCHITECTURE.md`

### Technical outputs

- editable feature graph
- parameter-level patching
- design provenance and versioning
- semantic diffing between asset iterations
- stable asset history across accepted variants

---

## Phase 2: Build a serious geometry engine for beauty, not just validity

### Goal

Generate objects that are not merely structurally valid, but visually polished and premium-looking.

### Current gap

The current geometry layer is strong for structural checks and topology audits, but beautiful assets require more than valid triangles. Beauty depends on silhouette quality, controlled edge treatment, clean normal behavior, proportion, and smooth detail.

### What to add

- remeshing passes
- curvature-aware triangulation
- subdivision-friendly mesh generation
- silhouette optimization
- normal consistency pass
- edge flow control for stylized forms
- detail preservation without noisy tessellation
- separate render mesh and gameplay mesh
- high-detail and low-detail variants

### Why this matters

This is the layer that separates “valid object” from “gorgeous object.”

### Modules to evolve

- `m3l/geometry.py`
- `m3l/glb.py`

### Technical outputs

- mesh quality score
- silhouette quality score
- normal consistency score
- remeshing pipeline
- clean asset variants for different outputs

---

## Phase 3: Upgrade procedural materials from technically valid to visually persuasive

### Goal

Materials should look intentional, rich, premium, and coherent with the form and lighting.

### Current strength

The project already has a strong direction in procedural materials and material quality documentation.

### What to add

- triplanar mapping
- world-space material consistency
- UV-aware material authoring
- material layering
- roughness, normal, and metallic tuning
- stylized presets for:
  - metal
  - painted surfaces
  - aged material
  - glossy plastic
  - ceramic
  - fabric
  - natural surfaces
- texture-generation pipeline for:
  - base color
  - normal
  - roughness
  - metalness
  - AO
  - emissive detail
- material variants for different style directions

### Why this matters

A good mesh with weak material behavior still looks fake. Premium assets are defined by material response as much as geometry.

### Modules to evolve

- `m3l/procedural_materials.py`
- `docs/QUALITY_BLUEPRINT.md`

### Technical outputs

- material quality scoring
- procedural texture library
- UV layout support
- premium material presets
- material variant generation system

---

## Phase 4: Build a visual critique engine that acts like a design reviewer

### Goal

Replace naive technical checking with real visual judgment.

### Current philosophy

The project already separates deterministic checks from visual review; this is the correct architectural direction.

### What to build

- fixed render review pipeline with controlled:
  - camera
  - lighting
  - environment
  - exposure
  - camera framing
  - resolution
  - background
- structured defect taxonomy:
  - silhouette mismatch
  - proportion issues
  - weak form language
  - shape noise
  - over-detailed regions
  - under-detailed regions
  - material incompatibility
  - shading issues
  - symmetry drift
  - edge hardness problems
- asset acceptance thresholds by category

### Why this matters

The AI must judge not only whether an asset is valid, but whether it is attractive, coherent, and on-goal.

### Modules to evolve

- `m3l/judge.py`
- `docs/EVALUATION.md`
- `docs/QUALITY_BLUEPRINT.md`
- `m3l/blender_backend.py`

### Technical outputs

- visual defect schema
- structured critique model
- style and reference scoring
- acceptance thresholds for asset classes
- render-based review loop

---

## Phase 5: Create a repair loop that operates on semantic defects

### Goal

Turn generation into a design optimization loop.

### The core loop

- generate asset candidate
- validate structure
- judge visual quality
- extract named defects
- patch the asset semantically
- re-render
- repeat until acceptance threshold is met

### What to implement

- defect-to-edit mapping
- repair grammar
- semantic patch operations for geometry and materials
- convergence rules
- accepted/rejected state handling
- candidate versioning and comparison

### Why this matters

This is the heart of the AI-native workflow. A system that generates once and stops is not enough. A production asset system must learn to repair and improve itself.

### Technical outputs

- visual repair pipeline
- defect-driven patching
- iterative asset optimization
- accepted asset archive with revision history

---

## Phase 6: Create a real asset-variant system

### Goal

Generate asset families, not single disconnected outputs.

### What to produce

- hero asset
- standard asset
- game-ready asset
- preview asset
- texture/material variants
- colorway variants
- optimized low-detail variant
- high-detail concept variant

### Why this matters

Realistic and gorgeous assets are not usually one model; they are a family of outputs for different contexts.

### Modules to evolve

- `m3l/api.py`
- `m3l/glb.py`
- `m3l/blender_backend.py`

### Technical outputs

- export profiles
- asset families
- variant registry
- LOD generation
- target-specific packaging

---

## Phase 7: Treat deformation and animation compatibility as a first-class requirement

### Goal

Assets should be not only beautiful, but also useful in games and animation pipelines.

### What to add

- animation suitability scoring
- topology quality checks for deformation
- clean edge distribution
- rigging-friendly topology heuristics
- separate deformation mesh from render mesh
- simplified mesh variants for motion workflows

### Why this matters

A static asset can look premium but still be useless for animation or real-time use.

### Technical outputs

- deformation quality measures
- animation-ready topology checks
- rigging-friendly mesh variants
- motion-optimized asset profiles

---

## Phase 8: Build the engine around a proper asset build pipeline

### Goal

The engine should output a usable asset package, not a single exported mesh file.

### What the pipeline should produce

- source model
- parameter history
- validated mesh
- optimized mesh
- render mesh
- texture set
- material package
- metadata
- variant set
- preview renders
- benchmark report

### Why this matters

A real asset engine produces a package, not just a geometry artifact.

### Technical outputs

- asset manifest
- export profile system
- preview bundle
- material package
- versioned asset archive

---

## Phase 9: Upgrade the benchmark system from compile-time metrics to asset-quality metrics

### Goal

Measure what matters for visual and production asset quality.

### What to add

- silhouette quality
- material coherence
- realism score
- detail quality
- form cleanliness
- edge quality
- defect reduction across repair loops
- visual acceptance rate
- export readiness
- animation suitability
- variation quality

### Why this matters

Compile-time validation is necessary but not sufficient. The product needs a quality engine that measures beauty and usability.

### Modules to evolve

- `docs/EVALUATION.md`
- benchmark scripts
- asset test reporting

### Technical outputs

- quality benchmark suite
- visual evaluation pipeline
- repeated acceptance metrics
- comparison against reference goals

---

## Phase 10: Make the system visually reproducible and technically defensible

### Goal

No vague claims like “looks better.” Every asset and every result must be evaluated under controlled conditions.

### What to enforce

- fixed camera setup
- fixed lighting setup
- fixed environment and exposure
- versioned render conditions
- structured defect logs
- deterministic comparison against references
- consistent visual review pass

### Why this matters

A premium asset engine requires a reproducible quality pipeline.

### Technical outputs

- render benchmark fixtures
- fixed studio setups
- consistent review environment
- versioned render metadata

---

## Phase 11: Make the engine product-ready for real asset creation

### Goal

The system must move from “can compile a scene” to “can generate premium assets with a controlled, repeatable pipeline.”

### What this includes

- stronger form generation
- richer material generation
- visual critique and repair
- production export profiles
- variant generation
- visual quality evaluation
- real-world asset packaging

### Why this matters

This is the layer that transforms the project from a clever prototype into a meaningful engine for beautiful asset creation.

---

## Core technical architecture direction

The engine should be organized into the following layers:

1. Prompt and design intent layer
   - user brief
   - style direction
   - target context
   - asset category
   - quality target

2. Form generation layer
   - feature graph
   - parametric control
   - iterative variation generation

3. Structural validation layer
   - geometry validity
   - mesh integrity
   - semantic constraints

4. Beauty optimization layer
   - remeshing
   - silhouette tuning
   - normal smoothing
   - detail management

5. Material generation layer
   - procedural and texture-based material systems
   - style-aware material variants

6. Render review layer
   - fixed lighting/camera evaluation
   - defect detection
   - score generation

7. Repair layer
   - semantic patching
   - defect-driven optimization

8. Asset packaging layer
   - export profiles
   - LODs
   - variants
   - metadata

9. Benchmark and trace layer
   - technical and visual scoring
   - version tracking
   - acceptance reporting

---

## Final goal

The final goal is not simply to generate a valid 3D mesh. The final goal is:

- create realistic or gorgeous assets with premium surface response
- maintain strong silhouette and form language
- produce coherent materials and detail
- pass structural validation
- repair visual defects automatically
- package outputs for real production use

This is the technical direction that will transform the current prototype into a serious AI 3D asset-generation engine.

---

## Summary

The current project is already strong as a foundation, but it remains too much like a valid scene compiler and too little like a visual asset engine. The breakthrough will come when the system gains the following capabilities:

- richer design graph
- stronger surface and mesh quality
- material realism and richness
- visual critique and repair loops
- variant generation and export profiles
- asset packaging for real-world use

These are the core technical moves required to make M3L evolve from a toy prototype into a genuinely beautiful, realistic, and production-valuable AI 3D asset engine.
