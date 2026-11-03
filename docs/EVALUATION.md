# Evaluation protocol: make the AI prove its scene

M3L has two kinds of evaluator: deterministic checks for properties we can establish by code, and an independent visual/task review for perceptual and goal-level judgments. They must not be collapsed into one claim.

## Gate A — language/compiler correctness

- parser and semantic validation succeed;
- required fields and references are valid;
- dimensions, units and material values are legal;
- arrays and procedural inputs stay within configured caps;
- all declared constraints pass;
- `supported_by` contact/footprint checks pass for the supported axis-aligned cases, including all members of a named array;
- failures return stable diagnostics instead of crashing.

## Gate B — geometry integrity

For custom meshes, test triangle indices, degenerates, edge incidence, consistent winding and approximate signed volume. Measure dimension error, bounds, contact, symmetry, clearances and mesh complexity where task requirements define them. Use a solid-modeling kernel for exact booleans, self-intersection checks, CAD tolerances or manufacturing acceptance. The v0.3 `supported_by` check is limited to upright children on unrotated box/extrusion targets; it conservatively tests concave extrusion footprints but is not a physics engine. Current topology checks do not prove geometric non-self-intersection.

## Gate C — render integrity

On a machine with Blender, render using pinned Blender version, engine, resolution, samples, color management, camera, and lighting. Verify output exists, can be decoded, and is not blank or corrupted. Record render duration, warning logs, and output hashes. The current development environment does not have Blender installed; the Blender adapter is source-validated but render regression must be run elsewhere.

## Gate D — visual/task quality

Give renders to a separate vision-capable judge with the task brief, constraints, and reference images. Request structured defects: missing components, silhouette and proportion mismatches, framing, intersections, materials, unwanted artifacts and requirement coverage. Include confidence and evidence. Human review remains appropriate for subjective or safety-critical decisions. Compare reference-image similarity only with a documented metric and controls.

## Gate E — agent efficiency

Compare M3L against a baseline using the same model, prompt, task, hardware, output renderer and compute budget:

- wall-clock total and per-stage latency;
- LLM tokens and tool/API calls;
- first-compile and first-render success rates;
- number of repairs and accepted-output rate;
- geometry/visual rubric scores and constraint violations;
- memory, triangle count, scene/GLB size and renderer time.

The included `benchmarks/run_benchmark.py` measures local compile/GLB export, and `benchmarks/run_cad_benchmark.py` measures local B-rep/STEP export when CadQuery is installed. Neither measures LLM inference, network, visual judging, Blender render, or a competing workflow. They must not be used to claim end-to-end performance superiority.

## Release criterion

Every release should publish the tested environment, exact task set, prompts, accepted and failed outputs, model/render versions, and raw metrics. Improve at least one primary metric without regressing correctness. Do not claim a speed/quality multiplier until an independently reproducible baseline comparison exists.
