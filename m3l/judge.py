"""Deterministic preflight judge; intentionally does not pretend to score aesthetics."""
from __future__ import annotations

import math
from typing import Any

from .geometry import audit_mesh


def judge_result(result: dict[str, Any], require_camera: bool = False) -> dict[str, Any]:
    """Return a machine-readable preflight report for a compile result.

    This judges objective readiness only. Visual quality requires a controlled render
    and an independent vision/human evaluator; the report always says so explicitly.
    """
    scene = result.get("scene")
    diagnostics = result.get("diagnostics", [])
    checks: list[dict[str, Any]] = []

    def add(name, status, message, details=None):
        checks.append({"name": name, "status": status, "message": message, "details": details})

    compiles = bool(result.get("valid")) and scene is not None
    add("language_and_semantics", "pass" if compiles else "fail",
        "Source parsed and semantic compilation passed." if compiles else "Compilation failed; repair diagnostics before judging quality.",
        {"errors": sum(d.get("severity") == "error" for d in diagnostics),
         "warnings": sum(d.get("severity") == "warning" for d in diagnostics)})
    if scene is None:
        add("geometry_sanity", "fail", "No scene IR exists, so geometry cannot be inspected.")
        add("constraints", "not_applicable", "Constraints could not be evaluated without scene IR.")
        add("presentation_setup", "not_applicable", "Camera and lights could not be inspected.")
        add("mesh_reuse", "not_applicable", "No scene IR exists.")
        return {"verdict": "needs_repair", "ready_for_visual_review": False,
                "visual_review_required": True, "checks": checks,
                "note": "This is a deterministic preflight report, not an artistic-quality score."}

    objects = scene.get("objects", [])
    bounds = scene.get("bounds", {})
    all_bounds_sane = bool(objects)
    bad_bounds = []
    for obj in objects:
        b = bounds.get(obj.get("name"))
        if not b or not isinstance(b.get("min"), list) or not isinstance(b.get("max"), list):
            all_bounds_sane = False
            bad_bounds.append(obj.get("name"))
            continue
        try:
            mn = [float(v) for v in b["min"]]
            mx = [float(v) for v in b["max"]]
            sane = len(mn) == 3 and len(mx) == 3 and all(math.isfinite(v) for v in mn + mx) and all(mx[i] > mn[i] for i in range(3))
        except (TypeError, ValueError, OverflowError):
            sane = False
        if not sane:
            all_bounds_sane = False
            bad_bounds.append(obj.get("name"))
    add("geometry_sanity", "pass" if all_bounds_sane else "fail",
        "All objects have finite, non-degenerate estimated world-space bounds." if all_bounds_sane else
        "At least one object has missing, non-finite, degenerate bounds, or the scene is empty.",
        {"object_count": len(objects), "invalid_objects": bad_bounds,
         "method": "transformed primitive AABBs; not an exact solid/topology test"})

    custom_objects = [o for o in objects if o.get("type") in ("extrude", "revolve", "sweep", "loft", "cone", "torus", "boolean") or "mesh" in o.get("geometry", {})]
    custom_audits = []
    for obj in custom_objects:
        mesh = obj.get("geometry", {}).get("mesh")
        audit = audit_mesh(mesh)
        custom_audits.append({"object": obj.get("name"), **audit})
    if custom_objects:
        topology_ok = all(a.get("valid") and a.get("watertight") for a in custom_audits)
        add("custom_mesh_topology", "pass" if topology_ok else "fail",
            "Every procedural solid has a valid, closed, two-manifold indexed mesh." if topology_ok else
            "At least one procedural solid failed triangle/topology checks; repair its profile before export.",
            {"custom_mesh_count": len(custom_objects), "meshes": custom_audits,
             "method": "edge-incidence audit on generated indexed mesh; not a self-intersection proof"})
    else:
        add("custom_mesh_topology", "not_applicable", "No custom procedural solids were declared.",
            {"custom_mesh_count": 0})

    constraint_diagnostics = [d for d in diagnostics if d.get("code") in {"E160", "E161", "E162", "E163", "E164"}]
    if scene.get("constraints"):
        constraints_ok = not any(d.get("severity") == "error" for d in constraint_diagnostics)
        add("constraints", "pass" if constraints_ok else "fail",
            "All declared constraints passed preflight." if constraints_ok else "One or more declared constraints failed or could not be resolved.",
            {"declared": len(scene.get("constraints", [])), "constraint_diagnostics": constraint_diagnostics})
    else:
        add("constraints", "not_applicable", "No explicit geometric constraints were declared.", {"declared": 0})
        constraints_ok = True

    camera_present = scene.get("camera") is not None
    lights_count = len(scene.get("lights", []))
    if camera_present and lights_count > 0:
        setup_status = "pass"
        setup_message = "Camera and at least one light are defined."
    else:
        setup_status = "warn"
        setup_message = "Preview setup is incomplete; consumer defaults may be needed."
    add("presentation_setup", setup_status, setup_message,
        {"camera_present": camera_present, "light_count": lights_count,
         "camera_required_by_request": require_camera})

    signatures = set()
    for obj in objects:
        geom = obj.get("geometry", {})
        signatures.add((obj.get("type"), geom.get("segments", 24), geom.get("rings", 16), obj.get("material", "default")))
    prototype_count = len(signatures)
    reuse_ratio = (1.0 - prototype_count / len(objects)) if objects else 0.0
    add("mesh_reuse", "pass", "Estimated reusable primitive/material prototypes were identified.",
        {"object_instances": len(objects), "estimated_mesh_prototypes": prototype_count,
         "reuse_ratio": round(max(0.0, reuse_ratio), 4),
         "meaning": "estimate based on primitive type, tessellation, and material; not a measured runtime speedup"})

    camera_ok = camera_present or not require_camera
    ready = compiles and all_bounds_sane and constraints_ok and camera_ok
    add("ready_for_visual_review", "pass" if ready else "fail",
        "Objective preflight passed; inspect a render before accepting the asset." if ready else
        "Do not accept yet; fix failing objective checks first.")
    return {"verdict": "ready_for_visual_review" if ready else "needs_repair",
            "ready_for_visual_review": ready, "visual_review_required": True, "checks": checks,
            "summary": {"objects": len(objects),
                        "materials": sum(name != "default" for name in scene.get("materials", {})),
                        "effective_materials_including_default": len(scene.get("materials", {})),
                        "lights": lights_count, "constraints": len(scene.get("constraints", [])),
                        "arrays": len(scene.get("arrays", []))},
            "note": "This is a deterministic preflight report, not an artistic-quality score. A render must be judged separately."}
