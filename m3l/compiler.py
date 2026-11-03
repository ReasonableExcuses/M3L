"""Semantic validation and scene IR for M3L."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from .parser import M3LParseError, parse
from .geometry import (
    build_extrusion, build_revolve, build_sweep, validate_path, validate_profile,
    build_loft, validate_loft_sections, build_cone, build_torus,
    evaluate_spline, build_filleted_box, build_box, build_sphere, build_cylinder, build_boolean, build_subdivision
)

SCHEMA = "m3l.scene.v0.3"

MATERIAL_PRESETS: dict[str, dict[str, Any]] = {
    "chrome": {"base": "#e8e8ec", "roughness": 0.08, "metallic": 1.0, "clearcoat": 0.2},
    "gold": {"base": "#ffd700", "roughness": 0.15, "metallic": 1.0},
    "copper": {"base": "#c87d55", "roughness": 0.20, "metallic": 1.0},
    "silver": {"base": "#f5f5f5", "roughness": 0.10, "metallic": 1.0},
    "steel": {"base": "#a0a5aa", "roughness": 0.35, "metallic": 0.90},
    "titanium": {"base": "#888890", "roughness": 0.28, "metallic": 0.85},
    "aluminum": {"base": "#d0d4d8", "roughness": 0.30, "metallic": 0.88},
    "brass": {"base": "#d4af37", "roughness": 0.25, "metallic": 0.85},
    "glass": {"base": "#ffffff", "roughness": 0.05, "metallic": 0.0, "transmission": 0.95, "ior": 1.52},
    "water": {"base": "#eef8ff", "roughness": 0.02, "metallic": 0.0, "transmission": 0.98, "ior": 1.33},
    "plastic_matte": {"base": "#333333", "roughness": 0.85, "metallic": 0.0},
    "plastic_glossy": {"base": "#f0f0f0", "roughness": 0.12, "metallic": 0.0, "clearcoat": 0.6},
    "rubber": {"base": "#151515", "roughness": 0.92, "metallic": 0.0, "surface": "rubber"},
    "carbon_fiber": {"base": "#1a1a1a", "roughness": 0.32, "metallic": 0.15, "surface": "carbon_fiber"},
    "anodized_metal": {"base": "#2a4d69", "roughness": 0.22, "metallic": 0.80, "surface": "anodized_metal"},
    "brushed_metal": {"base": "#cccccc", "roughness": 0.35, "metallic": 0.90, "surface": "brushed_metal"},
}


def _semantic_value(value: Any) -> Any:
    """Strip source-location metadata before hashing or comparing scene data."""
    if isinstance(value, dict):
        return {key: _semantic_value(item) for key, item in sorted(value.items())
                if key not in {"line", "provenance", "revision"}}
    if isinstance(value, list):
        return [_semantic_value(item) for item in value]
    return value


def _revision(value: Any) -> str:
    encoded = json.dumps(_semantic_value(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _diff_summary(value: Any) -> Any:
    """Keep semantic diff reports compact when a whole geometry payload changes."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) <= 2048:
        return value
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "serialized_bytes": len(encoded)}


def semantic_diff(before: dict[str, Any], after: dict[str, Any], *, max_changes: int = 500) -> dict[str, Any]:
    """Compare two compiled scene IR values by stable semantic paths."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise TypeError("semantic_diff expects two scene IR objects.")
    changes: list[dict[str, Any]] = []
    truncated = False

    def record(op: str, path: str, old: Any = None, new: Any = None) -> None:
        nonlocal truncated
        if len(changes) >= max_changes:
            truncated = True
            return
        row: dict[str, Any] = {"op": op, "path": path or "/"}
        if op != "add":
            row["before"] = _diff_summary(old)
        if op != "remove":
            row["after"] = _diff_summary(new)
        changes.append(row)

    def walk(old: Any, new: Any, path: str) -> None:
        if old == new:
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                child = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
                if key not in old:
                    record("add", child, new=new[key])
                elif key not in new:
                    record("remove", child, old=old[key])
                else:
                    walk(old[key], new[key], child)
            return
        if isinstance(old, list) and isinstance(new, list):
            if all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in old + new):
                old_by_name = {item["name"]: item for item in old}
                new_by_name = {item["name"]: item for item in new}
                for name in sorted(old_by_name.keys() | new_by_name.keys()):
                    child = f"{path}/{name.replace('~', '~0').replace('/', '~1')}"
                    if name not in old_by_name:
                        record("add", child, new=new_by_name[name])
                    elif name not in new_by_name:
                        record("remove", child, old=old_by_name[name])
                    else:
                        walk(old_by_name[name], new_by_name[name], child)
                return
            record("replace", path or "/", old, new)
            return
        record("replace", path or "/", old, new)

    clean_before = _semantic_value(before)
    clean_after = _semantic_value(after)
    walk(clean_before, clean_after, "")
    return {"schema": "m3l.semantic_diff.v1",
            "before_revision": _revision(before),
            "after_revision": _revision(after),
            "change_count": len(changes), "truncated": truncated, "changes": changes}


class M3LCompileError(Exception):
    pass


def diag(severity: str, code: str, message: str, target: str | None = None,
         suggestion: str | None = None, line: int | None = None, field: str | None = None) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message,
            "target": target, "field": field, "suggestion": suggestion, "line": line}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _vec(value: Any, length: int = 3) -> bool:
    return isinstance(value, list) and len(value) == length and all(_finite_number(x) for x in value)


def _color(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def _hex_rgb(value: str) -> list[float]:
    """Convert authored sRGB hex to linear RGB factors used by glTF PBR and lights."""
    srgb = [int(value[i:i+2], 16) / 255.0 for i in (1, 3, 5)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]


def _rot_matrix(euler_deg: list[float]) -> list[list[float]]:
    x, y, z = [math.radians(v) for v in euler_deg]
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    # Intrinsic XYZ rotation (Rx @ Ry @ Rz), matching glTF node quaternion composition.
    return [
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]


def object_dimensions(obj: dict[str, Any]) -> list[float]:
    p = obj.get("props") or obj.get("geometry", {})
    mesh = obj.get("_mesh_geometry") or obj.get("geometry", {}).get("mesh")
    if isinstance(mesh, dict) and mesh.get("vertices"):
        vertices = mesh["vertices"]
        return [max(float(v[i]) for v in vertices) - min(float(v[i]) for v in vertices) for i in range(3)]
    try:
        if obj["type"] == "box":
            candidate = p.get("size", [1, 1, 1])
            return [float(v) for v in candidate] if _vec(candidate) and all(0 < float(v) <= 1e6 for v in candidate) else [1.0, 1.0, 1.0]
        if obj["type"] == "sphere":
            r = float(p.get("radius", 0.5))
            return [2*r, 2*r, 2*r] if math.isfinite(r) and 0 < r <= 1e6 else [1, 1, 1]
        if obj["type"] == "cylinder":
            r, h = float(p.get("radius", 0.5)), float(p.get("height", 1.0))
            return [2*r, h, 2*r] if math.isfinite(r) and math.isfinite(h) and 0 < r <= 1e6 and 0 < h <= 1e6 else [1, 1, 1]
    except (TypeError, ValueError, OverflowError):
        pass
    return [1, 1, 1]


def _transform_point(pt: list[float], pos: list[float], rot: list[list[float]], scale: list[float]) -> list[float]:
    local = [float(pt[i]) * scale[i] for i in range(3)]
    return [pos[i] + sum(rot[i][j] * local[j] for j in range(3)) for i in range(3)]


def object_bounds(obj: dict[str, Any], groups_by_name: dict[str, Any] | None = None) -> dict[str, list[float]]:
    """Approximate transformed AABB without assuming invalid input is well-typed."""
    if "props" in obj:
        p = obj["props"]
        raw_pos = p.get("at", [0.0, 0.0, 0.0])
        raw_scale = p.get("scale", [1.0, 1.0, 1.0])
        raw_rotate = p.get("rotate", [0.0, 0.0, 0.0])
    else:
        t = obj.get("transform", {})
        p = obj.get("geometry", {})
        raw_pos = t.get("translation", [0.0, 0.0, 0.0])
        raw_scale = t.get("scale", [1.0, 1.0, 1.0])
        raw_rotate = t.get("rotation_euler_degrees", [0.0, 0.0, 0.0])

    pos = [float(v) for v in raw_pos] if _vec(raw_pos) and all(abs(float(v)) <= 1e6 for v in raw_pos) else [0.0, 0.0, 0.0]
    scale = [float(v) for v in raw_scale] if _vec(raw_scale) and all(abs(float(v)) <= 1e4 for v in raw_scale) else [1.0, 1.0, 1.0]
    rotate = [float(v) for v in raw_rotate] if _vec(raw_rotate) and all(abs(float(v)) <= 1e6 for v in raw_rotate) else [0.0, 0.0, 0.0]
    rot = _rot_matrix(rotate)

    has_group = bool(groups_by_name and obj.get("group") in groups_by_name)
    if has_group:
        gp = groups_by_name[obj["group"]].get("props") or groups_by_name[obj["group"]].get("transform", {})
        raw_gat = gp.get("at") or gp.get("translation", [0, 0, 0])
        raw_gscale = gp.get("scale", [1, 1, 1])
        raw_grot = gp.get("rotate") or gp.get("rotation_euler_degrees", [0, 0, 0])
        g_pos = [float(v) for v in raw_gat] if _vec(raw_gat) else [0.0, 0.0, 0.0]
        g_scale = [float(v) for v in raw_gscale] if _vec(raw_gscale) else [1.0, 1.0, 1.0]
        g_rot = _rot_matrix([float(v) for v in raw_grot] if _vec(raw_grot) else [0.0, 0.0, 0.0])

    mesh = obj.get("_mesh_geometry") or obj.get("geometry", {}).get("mesh")
    if isinstance(mesh, dict) and mesh.get("vertices"):
        world = []
        for vertex in mesh["vertices"]:
            pt = _transform_point(vertex, pos, rot, scale)
            if has_group:
                pt = _transform_point(pt, g_pos, g_rot, g_scale)
            world.append(pt)
        return {"min": [min(v[i] for v in world) for i in range(3)],
                "max": [max(v[i] for v in world) for i in range(3)]}
    size = object_dimensions(obj)
    corners = [
        [(sx * size[0] / 2), (sy * size[1] / 2), (sz * size[2] / 2)]
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ]
    world = []
    for corner in corners:
        pt = _transform_point(corner, pos, rot, scale)
        if has_group:
            pt = _transform_point(pt, g_pos, g_rot, g_scale)
        world.append(pt)
    return {"min": [min(v[i] for v in world) for i in range(3)],
            "max": [max(v[i] for v in world) for i in range(3)]}


def _get_object_world_mesh(obj: dict[str, Any], groups_by_name: dict[str, Any]) -> dict[str, Any] | None:
    typ = obj["type"]
    p = obj["props"]
    mesh = obj.get("_mesh_geometry")
    if mesh is None:
        if typ == "box":
            size = p.get("size", [1, 1, 1])
            if "fillet" in p and float(p.get("fillet", 0)) > 0:
                mesh = build_filleted_box([float(v) for v in size], float(p["fillet"]), int(p.get("fillet_segments", 4)))
            else:
                mesh = build_box([float(v) for v in size])
        elif typ == "sphere":
            r = float(p.get("radius", 0.5))
            mesh = build_sphere(r, int(p.get("segments", 24)), int(p.get("rings", 16)))
        elif typ == "cylinder":
            r = float(p.get("radius", 0.5))
            h = float(p.get("height", 1.0))
            mesh = build_cylinder(r, h, int(p.get("segments", 24)))
        elif typ == "cone":
            r_bot = float(p.get("radius_bottom", p.get("radius", 0.5)))
            r_top = float(p.get("radius_top", 0.0))
            h = float(p.get("height", 1.0))
            mesh = build_cone(r_bot, r_top, h, int(p.get("segments", 24)))
        elif typ == "torus":
            maj = float(p.get("major_radius", 0.5))
            min_r = float(p.get("minor_radius", 0.1))
            mesh = build_torus(maj, min_r, int(p.get("segments", 32)), int(p.get("rings", 16)))
        elif typ == "extrude":
            prof, _ = validate_profile(p.get("profile"))
            if prof:
                mesh = build_extrusion(prof, float(p.get("depth", 0.1)))
        elif typ == "revolve":
            prof, _ = validate_profile(p.get("profile"), nonnegative_x=True)
            if prof:
                mesh = build_revolve(prof, int(p.get("segments", 48)))
        elif typ == "sweep":
            path, _ = validate_path(p.get("control_points") or p.get("path"))
            if path:
                if p.get("path_type") and p.get("path_type") != "linear":
                    path = evaluate_spline(path, p.get("path_type"), int(p.get("path_segments", 48)))
                mesh = build_sweep(path, float(p.get("radius", 0.05)), int(p.get("segments", 16)))
        elif typ == "loft":
            sections, _ = validate_loft_sections(p.get("sections"))
            if sections:
                mesh = build_loft(sections, int(p.get("subdivisions", 1)))

    if mesh is None or not mesh.get("vertices"):
        return None

    pos = [float(v) for v in p.get("at", [0, 0, 0])] if _vec(p.get("at")) else [0.0, 0.0, 0.0]
    scale = [float(v) for v in p.get("scale", [1, 1, 1])] if _vec(p.get("scale")) else [1.0, 1.0, 1.0]
    rot = _rot_matrix([float(v) for v in p.get("rotate", [0, 0, 0])] if _vec(p.get("rotate")) else [0.0, 0.0, 0.0])

    g_name = obj.get("group")
    has_group = bool(g_name and g_name in groups_by_name)
    if has_group:
        gp = groups_by_name[g_name]["props"]
        g_pos = [float(v) for v in gp.get("at", [0, 0, 0])] if _vec(gp.get("at")) else [0.0, 0.0, 0.0]
        g_scale = [float(v) for v in gp.get("scale", [1, 1, 1])] if _vec(gp.get("scale")) else [1.0, 1.0, 1.0]
        g_rot = _rot_matrix([float(v) for v in gp.get("rotate", [0, 0, 0])] if _vec(gp.get("rotate")) else [0.0, 0.0, 0.0])

    world_verts = []
    for v in mesh["vertices"]:
        pt = _transform_point(v, pos, rot, scale)
        if has_group:
            pt = _transform_point(pt, g_pos, g_rot, g_scale)
        world_verts.append(pt)

    return {"vertices": world_verts, "triangles": list(mesh["triangles"])}


def _check_properties(props: dict[str, Any], allowed: set[str], required: set[str], target: str,
                      line: int, diagnostics: list[dict[str, Any]]) -> None:
    for name in props:
        if name == "__lines__":
            continue
        if name not in allowed:
            diagnostics.append(diag("error", "E101", f"Unknown property {name!r} for {target}.", target,
                                    "Remove it or use a property supported by this block.",
                                    props.get("__lines__", {}).get(name, line), name))
    for name in sorted(required):
        if name not in props:
            diagnostics.append(diag("error", "E102", f"Missing required property {name!r}.", target,
                                    f"Add `{name} = ...` to this block.", line, name))


def _point_on_segment_2d(point: tuple[float, float], a: tuple[float, float],
                          b: tuple[float, float], tolerance: float = 1e-8) -> bool:
    cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    if abs(cross) > tolerance:
        return False
    return (min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance
            and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance)


def _segments_intersect_2d(a: tuple[float, float], b: tuple[float, float],
                           c: tuple[float, float], d: tuple[float, float],
                           tolerance: float = 1e-8) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if (((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance)) and
        ((o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance))):
        return True
    return (_point_on_segment_2d(c, a, b, tolerance) or _point_on_segment_2d(d, a, b, tolerance) or
            _point_on_segment_2d(a, c, d, tolerance) or _point_on_segment_2d(b, c, d, tolerance))


def _point_in_polygon_2d(point: tuple[float, float], polygon: list[list[float]], tolerance: float = 1e-8) -> bool:
    inside = False
    x, y = point
    for i, p in enumerate(polygon):
        q = polygon[(i + 1) % len(polygon)]
        a, b = (float(p[0]), float(p[1])), (float(q[0]), float(q[1]))
        if _point_on_segment_2d(point, a, b, tolerance):
            return True
        if (a[1] > y) != (b[1] > y):
            crossing_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < crossing_x:
                inside = not inside
    return inside


def _rectangle_inside_polygon(rect: list[tuple[float, float]], polygon: list[list[float]],
                              tolerance: float = 1e-8) -> bool:
    """Conservative containment of a rectangle in a simple polygon, including concavities."""
    if not all(_point_in_polygon_2d(corner, polygon, tolerance) for corner in rect):
        return False
    rect_edges = [(rect[i], rect[(i + 1) % 4]) for i in range(4)]
    polygon_edges = [((float(p[0]), float(p[1])),
                      (float(polygon[(i + 1) % len(polygon)][0]), float(polygon[(i + 1) % len(polygon)][1])))
                     for i, p in enumerate(polygon)]
    # A profile boundary crossing the footprint means that its corners alone are insufficient.
    for a, b in polygon_edges:
        if any(_segments_intersect_2d(a, b, c, d, tolerance) for c, d in rect_edges):
            return False
    # Also reject a concave notch whose vertex lies inside the footprint.
    rx = [p[0] for p in rect]; rz = [p[1] for p in rect]
    for x, z in ((float(p[0]), float(p[1])) for p in polygon):
        if min(rx) + tolerance < x < max(rx) - tolerance and min(rz) + tolerance < z < max(rz) - tolerance:
            return False
    return True


def _support_failure(child: dict[str, Any], child_bounds: dict[str, list[float]],
                     target: dict[str, Any], target_bounds: dict[str, list[float]],
                     tolerance: float) -> str | None:
    """Check a Y-up object footprint against an axis-aligned box/extrusion support face."""
    child_props, target_props = child["props"], target["props"]
    child_rotate = child_props.get("rotate", [0, 0, 0])
    target_rotate = target_props.get("rotate", [0, 0, 0])
    if not _vec(child_rotate) or abs(float(child_rotate[0])) > 1e-7 or abs(float(child_rotate[2])) > 1e-7:
        return "the supported object must remain upright (no X/Z rotation)"
    if not _vec(target_rotate) or any(abs(float(v)) > 1e-7 for v in target_rotate):
        return "the target support must be unrotated in this version"
    target_scale = target_props.get("scale", [1, 1, 1])
    if not _vec(target_scale) or any(float(v) <= 0 for v in target_scale):
        return "the target support must have positive scale components"
    if any(float(v) > 1e4 for v in target_scale):
        return "the target support scale exceeds the supported safety limit"
    target_at = target_props.get("at", [0, 0, 0])
    if not _vec(target_at) or any(abs(float(v)) > 1e6 for v in target_at):
        return "the target support position is invalid or exceeds the supported safety limit"
    vertical_gap = child_bounds["min"][1] - target_bounds["max"][1]
    if abs(vertical_gap) > tolerance:
        return f"bottom-to-top contact gap is {vertical_gap:.5f}; tolerance is ±{tolerance:.5f}"

    x0, x1 = child_bounds["min"][0], child_bounds["max"][0]
    z0, z1 = child_bounds["min"][2], child_bounds["max"][2]
    world_rect = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    if target["type"] == "box":
        if all(target_bounds["min"][0] - tolerance <= x <= target_bounds["max"][0] + tolerance and
               target_bounds["min"][2] - tolerance <= z <= target_bounds["max"][2] + tolerance
               for x, z in world_rect):
            return None
        return "the object's footprint extends beyond the top face of the box"
    if target["type"] == "extrude":
        profile = target_props.get("profile")
        if (not isinstance(profile, list) or len(profile) < 3 or
            any(not isinstance(point, list) or len(point) != 2 or
                not all(_finite_number(v) for v in point) for point in profile)):
            return "the target extrusion profile is invalid"
        at = target_at
        scale = target_scale
        local_rect = [((x - float(at[0])) / float(scale[0]),
                       (z - float(at[2])) / float(scale[2])) for x, z in world_rect]
        if _rectangle_inside_polygon(local_rect, profile, tolerance=max(1e-8, tolerance * 1e-3)):
            return None
        return "the object's footprint is not wholly supported by the extrusion profile (possible overhang/notch)"
    return f"target type {target['type']!r} has no supported top-face test; use box or extrude"


def compile_source(source: str) -> dict[str, Any]:
    """Parse, validate, and compile M3L source to a stable scene IR.

    The returned result always includes machine-readable diagnostics when possible.
    Fatal parse errors are represented in the same structure so an LLM can repair them.
    """
    try:
        ast_scene = parse(source)
    except M3LParseError as exc:
        return {"valid": False, "scene": None, "diagnostics": [diag(
            "error", "E001", exc.message, suggestion="Fix the syntax error and compile again.", line=exc.line)],
            "summary": {"objects": 0, "materials": 0, "lights": 0, "constraints": 0}}

    diagnostics: list[dict[str, Any]] = []
    name = ast_scene["name"]
    if ast_scene.get("units") not in ("m", "cm", "mm", "in", "ft"):
        diagnostics.append(diag("error", "E103", f"Unsupported units {ast_scene.get('units')!r}.", name,
                                "Choose one of: m, cm, mm, in, ft.", 1, "units"))

    materials = ast_scene["materials"]
    material_lines = ast_scene.get("_material_lines", {})
    normalized_materials: dict[str, dict[str, Any]] = {
        "default": {"base": "#b9c2cc", "roughness": 0.72, "metallic": 0.0}
    }
    normalized_features: list[dict[str, Any]] = []
    normalized_variants: list[dict[str, Any]] = []
    for feature in ast_scene.get("features", []):
        props = {k: v for k, v in feature["props"].items() if k != "__lines__"}
        normalized_features.append({
            "name": feature["name"],
            "kind": props.get("kind", "generic"),
            "parent": props.get("parent"),
            "phase": props.get("phase", "form"),
            "layer": props.get("layer", "base_form"),
            "params": props.get("params", {}),
            "line": feature.get("line", 1),
        })
    for variant in ast_scene.get("variants", []):
        props = {k: v for k, v in variant["props"].items() if k != "__lines__"}
        normalized_variants.append({
            "name": variant["name"],
            "kind": str(props.get("kind", "variant")),
            "from": props.get("from"),
            "target": props.get("target"),
            "phase": props.get("phase", "delivery"),
            "params": props.get("params", {}),
            "line": variant.get("line", 1),
        })
    feature_names: dict[str, dict[str, Any]] = {}
    valid_phases = {"form", "refinement", "detail", "material", "variant"}
    valid_layers = {"base_form", "refinement", "detail", "material", "variant"}
    for feature in normalized_features:
        feature_name = feature["name"]
        target = f"feature:{feature_name}"
        if feature_name in feature_names:
            diagnostics.append(diag("error", "E190", f"Feature name {feature_name!r} is declared more than once.",
                                    target, "Give every feature a unique stable name.", feature["line"], "name"))
        else:
            feature_names[feature_name] = feature
        if not isinstance(feature["kind"], str) or not feature["kind"].strip():
            diagnostics.append(diag("error", "E191", "Feature kind must be a non-empty string.", target,
                                    "Use a stable operation or feature kind name.", feature["line"], "kind"))
            feature["kind"] = "generic"
        if (not isinstance(feature["phase"], str) or feature["phase"] not in valid_phases or
                not isinstance(feature["layer"], str) or feature["layer"] not in valid_layers):
            diagnostics.append(diag("error", "E192", "Feature phase or layer is not recognized.", target,
                                    "Choose a phase and layer from form, refinement, detail, material, or variant.",
                                    feature["line"], "phase/layer"))
            feature["phase"] = "form" if not isinstance(feature["phase"], str) else feature["phase"]
            feature["layer"] = "base_form" if not isinstance(feature["layer"], str) else feature["layer"]
        if not isinstance(feature["params"], dict):
            diagnostics.append(diag("error", "E193", "Feature params must be a dictionary.", target,
                                    "Store editable feature parameters in a dictionary.", feature["line"], "params"))
        parent = feature["parent"]
        if parent is not None and (not isinstance(parent, str) or not parent):
            diagnostics.append(diag("error", "E194", "Feature parent must be a feature name or 'root'.", target,
                                    "Reference an existing feature name or use 'root' for a root feature.",
                                    feature["line"], "parent"))
        elif isinstance(parent, str) and parent != "root" and parent not in feature_names and not any(
                candidate["name"] == parent for candidate in normalized_features):
            diagnostics.append(diag("error", "E194", f"Feature parent {parent!r} does not exist.", target,
                                    "Reference an existing feature or use parent = root.", feature["line"], "parent"))

    if len(normalized_features) > 512:
        diagnostics.append(diag("error", "E195", "Feature graph exceeds the 512-node limit.", name,
                                "Split the asset into smaller authored graphs.", 1, "features"))

    feature_state: dict[str, int] = {}
    feature_cycle_reported: set[str] = set()

    def visit_feature(feature_name: str, trail: list[str]) -> None:
        state = feature_state.get(feature_name, 0)
        if state == 2:
            return
        if state == 1:
            cycle_start = trail.index(feature_name) if feature_name in trail else 0
            cycle = trail[cycle_start:] + [feature_name]
            for member in cycle[:-1]:
                if member not in feature_cycle_reported:
                    feature_cycle_reported.add(member)
                    feature = feature_names[member]
                    diagnostics.append(diag("error", "E196", "Feature parent relationships contain a cycle: " + " -> ".join(cycle),
                                            f"feature:{member}", "Reparent the features to form an acyclic graph.",
                                            feature["line"], "parent"))
            return
        feature_state[feature_name] = 1
        parent = feature_names[feature_name].get("parent")
        if isinstance(parent, str) and parent in feature_names:
            visit_feature(parent, trail + [feature_name])
        feature_state[feature_name] = 2

    if len(normalized_features) <= 512:
        for feature_name in feature_names:
            visit_feature(feature_name, [])

    for mat_name, p in materials.items():
        line = material_lines.get(mat_name, 1)
        if mat_name == "default":
            diagnostics.append(diag("error", "E109", "The material name 'default' is reserved by the compiler.",
                                    "material:default", "Rename this material; 'default' is provided automatically.", line, "name"))
        preset = p.get("preset")
        if preset is not None:
            if not isinstance(preset, str) or preset not in MATERIAL_PRESETS:
                diagnostics.append(diag("error", "E115", f"Unsupported material preset {preset!r}.",
                                        f"material:{mat_name}", "Choose one of: " + ", ".join(sorted(MATERIAL_PRESETS)) + ".",
                                        p.get("__lines__", {}).get("preset", line), "preset"))
            else:
                for k, v in MATERIAL_PRESETS[preset].items():
                    if k not in p:
                        p[k] = v
        tint = p.get("tint")
        if tint is not None:
            if not _color(tint):
                diagnostics.append(diag("error", "E110", "tint must be a six-digit hex color like #aabbcc.",
                                        f"material:{mat_name}", 'Use a string such as "#c08040".',
                                        p.get("__lines__", {}).get("tint", line), "tint"))
            else:
                p["base"] = tint

        required_mat = set() if (preset in MATERIAL_PRESETS) else {"base"}
        _check_properties(p, {"base", "roughness", "metallic", "emissive", "surface", "texture_resolution",
                              "transmission", "ior", "clearcoat", "clearcoat_roughness", "preset", "tint", "double_sided",
                              "base_texture", "normal_texture", "roughness_texture", "metallic_texture", "occlusion_texture", "uv_scale", "uv_offset"}, required_mat,
                          f"material:{mat_name}", line, diagnostics)
        for key in ("base", "emissive"):
            if key in p and not _color(p[key]):
                diagnostics.append(diag("error", "E110", f"{key} must be a six-digit hex color like #aabbcc.",
                                        f"material:{mat_name}", "Use a string such as \"#c08040\".",
                                        p.get("__lines__", {}).get(key, line), key))
        for key in ("roughness", "metallic", "transmission", "clearcoat", "clearcoat_roughness"):
            if key in p and (not _finite_number(p[key]) or not 0 <= float(p[key]) <= 1):
                diagnostics.append(diag("error", "E111", f"{key} must be a number from 0 to 1.",
                                        f"material:{mat_name}", "Choose a value in the inclusive range [0, 1].",
                                        p.get("__lines__", {}).get(key, line), key))
        if "ior" in p and (not _finite_number(p["ior"]) or not 1.0 <= float(p["ior"]) <= 3.0):
            diagnostics.append(diag("error", "E114", "ior must be a number from 1.0 to 3.0.",
                                     f"material:{mat_name}", "Choose a plausible refractive index in the inclusive range [1, 3].",
                                     p.get("__lines__", {}).get("ior", line), "ior"))
        supported_surfaces = {"brushed_metal", "anodized_metal", "rubber", "ceramic_glaze",
                              "carbon_fiber", "leather_grain", "wood_grain", "fabric_weave"}
        if "surface" in p and (not isinstance(p["surface"], str) or p["surface"] not in supported_surfaces):
            diagnostics.append(diag("error", "E112", f"Unsupported procedural surface {p['surface']!r}.",
                                    f"material:{mat_name}", "Choose one of: " + ", ".join(sorted(supported_surfaces)) + ".",
                                    p.get("__lines__", {}).get("surface", line), "surface"))
        if "texture_resolution" in p and (isinstance(p["texture_resolution"], bool) or
                not isinstance(p["texture_resolution"], int) or p["texture_resolution"] not in (128, 256, 512, 1024)):
            diagnostics.append(diag("error", "E113", "texture_resolution must be one of 128, 256, 512, or 1024.",
                                    f"material:{mat_name}", "Use a bounded power-of-two texture resolution; 512 is recommended for close-up product assets.",
                                    p.get("__lines__", {}).get("texture_resolution", line), "texture_resolution"))
        if "base" in p and _color(p["base"]):
            normalized_materials[mat_name] = {
                "base_color": _hex_rgb(p["base"]),
                "roughness": float(p.get("roughness", 0.72)) if _finite_number(p.get("roughness", 0.72)) else 0.72,
                "metallic": float(p.get("metallic", 0.0)) if _finite_number(p.get("metallic", 0.0)) else 0.0,
                "emissive": _hex_rgb(p["emissive"]) if _color(p.get("emissive")) else [0, 0, 0],
                "source_color": p["base"],
                "double_sided": bool(p.get("double_sided", True)),
                **({key: float(p[key]) for key in ("transmission", "ior", "clearcoat", "clearcoat_roughness")
                    if key in p and _finite_number(p[key]) and
                    ((key == "ior" and 1.0 <= float(p[key]) <= 3.0) or
                     (key != "ior" and 0.0 <= float(p[key]) <= 1.0))}),
                **({"surface": p["surface"]} if isinstance(p.get("surface"), str) and p["surface"] in supported_surfaces else {}),
                **({"texture_resolution": p["texture_resolution"]} if isinstance(p.get("texture_resolution"), int) and not isinstance(p.get("texture_resolution"), bool) and p["texture_resolution"] in (128, 256, 512, 1024) else {}),
            }
    normalized_materials["default"] = {"base_color": _hex_rgb("#b9c2cc"), "roughness": 0.72,
                                        "metallic": 0.0, "emissive": [0, 0, 0], "source_color": "#b9c2cc",
                                        "double_sided": True}

    # Groups validation and normalization
    normalized_groups: list[dict[str, Any]] = []
    groups_by_name: dict[str, dict[str, Any]] = {}
    for group in ast_scene.get("groups", []):
        gname, gp, gline = group["name"], group["props"], group["line"]
        target = f"group:{gname}"
        if gname in groups_by_name:
            diagnostics.append(diag("error", "E193", f"Group name {gname!r} is declared more than once.",
                                    target, "Give every group a unique name.", gline, "name"))
        else:
            groups_by_name[gname] = group
        _check_properties(gp, {"at", "rotate", "scale"}, set(), target, gline, diagnostics)
        for key in ("at", "rotate", "scale"):
            if key in gp and not _vec(gp[key]):
                diagnostics.append(diag("error", "E121", f"Group {key} must be a numeric 3-vector.", target,
                                        f"Use e.g. `{key} = [0, 1, 0]`.", gp.get("__lines__", {}).get(key, gline), key))
        gat = gp.get("at", [0.0, 0.0, 0.0])
        grot = gp.get("rotate", [0.0, 0.0, 0.0])
        gscale = gp.get("scale", [1.0, 1.0, 1.0])
        normalized_groups.append({
            "name": gname,
            "transform": {
                "translation": list(gat) if _vec(gat) else [0.0, 0.0, 0.0],
                "rotation_euler_degrees": list(grot) if _vec(grot) else [0.0, 0.0, 0.0],
                "scale": list(gscale) if _vec(gscale) else [1.0, 1.0, 1.0],
            },
            "line": gline,
        })

    seen: dict[str, int] = {}
    normalized_objects: list[dict[str, Any]] = []
    COMMON_CONSTRAINTS = {"snap_to_ground", "align_bottom", "attach_to", "mirror_copy"}
    allowed_by_type = {
        "box": ({"size", "at", "rotate", "scale", "material", "fillet", "fillet_segments"} | COMMON_CONSTRAINTS, {"size"}),
        "sphere": ({"radius", "at", "rotate", "scale", "material", "segments", "rings"} | COMMON_CONSTRAINTS, {"radius"}),
        "cylinder": ({"radius", "height", "at", "rotate", "scale", "material", "segments"} | COMMON_CONSTRAINTS, {"radius", "height"}),
        "extrude": ({"profile", "depth", "at", "rotate", "scale", "material"} | COMMON_CONSTRAINTS, {"profile", "depth"}),
        "revolve": ({"profile", "segments", "at", "rotate", "scale", "material"} | COMMON_CONSTRAINTS, {"profile"}),
        "sweep": ({"path", "control_points", "path_type", "path_segments", "radius", "segments", "at", "rotate", "scale", "material"} | COMMON_CONSTRAINTS, {"radius"}),
        "loft": ({"sections", "subdivisions", "interpolation", "at", "rotate", "scale", "material"} | COMMON_CONSTRAINTS, {"sections"}),
        "cone": ({"radius_bottom", "radius_top", "radius", "height", "segments", "at", "rotate", "scale", "material"} | COMMON_CONSTRAINTS, {"height"}),
        "torus": ({"major_radius", "minor_radius", "segments", "rings", "at", "rotate", "scale", "material"} | COMMON_CONSTRAINTS, {"major_radius", "minor_radius"}),
        "boolean": ({"op", "base", "tools", "at", "rotate", "scale", "material", "hide_operands"} | COMMON_CONSTRAINTS, {"op", "base", "tools"}),
        "subdivision": ({"base", "levels", "at", "rotate", "scale", "material", "hide_base"} | COMMON_CONSTRAINTS, {"base"}),
    }

    # Collect prototype templates and filter out template objects from top-level scene objects
    prototype_templates: dict[str, list[dict[str, Any]]] = {}
    for obj in ast_scene.get("objects", []):
        proto_owner = obj.get("prototype")
        if proto_owner:
            prototype_templates.setdefault(proto_owner, []).append(obj)

    objects_for_compile = [obj for obj in ast_scene.get("objects", []) if not obj.get("prototype")]

    # Expand instances into objects and group nodes
    for instance in ast_scene.get("instances", []):
        inst_name, ip, iline = instance["name"], instance["props"], instance["line"]
        _check_properties(ip, {"prototype", "at", "rotate", "scale", "mirror", "material", "snap_to_ground", "align_bottom", "mirror_copy"}, {"prototype"}, f"instance:{inst_name}", iline, diagnostics)
        proto_name = ip.get("prototype")
        if not proto_name or proto_name not in prototype_templates:
            diagnostics.append(diag("error", "E214", f"Instance {inst_name!r} references unknown prototype {proto_name!r}.", f"instance:{inst_name}",
                                    "Define a matching prototype block before instancing.", iline, "prototype"))
            continue

        children = prototype_templates[proto_name]
        if not children:
            diagnostics.append(diag("warning", "W215", f"Prototype {proto_name!r} has no child objects.", f"instance:{inst_name}",
                                    "Add primitives inside the prototype block.", iline, "prototype"))
            continue

        iat = ip.get("at", [0.0, 0.0, 0.0])
        irot = ip.get("rotate", [0.0, 0.0, 0.0])
        iscale = list(ip.get("scale", [1.0, 1.0, 1.0])) if _vec(ip.get("scale")) else [1.0, 1.0, 1.0]

        mirror_axis = ip.get("mirror")
        if isinstance(mirror_axis, str):
            axis = mirror_axis.lower()
            if axis in ("x", "left_right"):
                iscale[0] *= -1.0
            elif axis in ("y", "up_down"):
                iscale[1] *= -1.0
            elif axis in ("z", "front_back"):
                iscale[2] *= -1.0

        inst_group = {
            "name": inst_name,
            "props": {
                "at": iat,
                "rotate": irot,
                "scale": iscale,
            },
            "line": iline,
        }
        groups_by_name[inst_name] = inst_group
        normalized_groups.append({
            "name": inst_name,
            "transform": {
                "translation": list(iat) if _vec(iat) else [0.0, 0.0, 0.0],
                "rotation_euler_degrees": list(irot) if _vec(irot) else [0.0, 0.0, 0.0],
                "scale": list(iscale) if _vec(iscale) else [1.0, 1.0, 1.0],
            },
            "line": iline,
        })

        for child in children:
            child_name = f"{inst_name}_{child['name']}"
            c_props = dict(child["props"])
            if "material" in ip and "material" not in c_props:
                c_props["material"] = ip["material"]
            objects_for_compile.append({
                "type": child["type"],
                "name": child_name,
                "props": c_props,
                "line": iline,
                "group": inst_name,
                "source_instance": inst_name,
            })

    # Expand AI-friendly grid arrays to ordinary named objects before semantic compilation.
    # The compiler bounds expansion to keep accidental LLM output from exploding in size.
    normalized_arrays = []
    common_array_fields = {"shape", "counts", "step", "at", "rotate", "scale", "material"}
    all_geometry_fields = {"size", "radius", "height", "segments", "rings"}
    for array in ast_scene.get("arrays", []):
        array_name, p, line = array["name"], array["props"], array["line"]
        shape = p.get("shape")
        shape_valid = isinstance(shape, str) and shape in ("box", "sphere", "cylinder")
        allowed = common_array_fields | (allowed_by_type[shape][0] if shape_valid else all_geometry_fields)
        required = {"shape", "counts", "step", "at"}
        if shape_valid:
            required |= allowed_by_type[shape][1]
        _check_properties(p, allowed, required, f"array:{array_name}", line, diagnostics)
        good = shape_valid
        if shape_valid and any(field not in p for field in allowed_by_type[shape][1]):
            good = False
        if not shape_valid:
            diagnostics.append(diag("error", "E170", f"Array shape {shape!r} is not supported.", f"array:{array_name}",
                                    "Use shape = box, sphere, or cylinder.", p.get("__lines__", {}).get("shape", line), "shape"))
        counts = p.get("counts")
        counts_valid = (isinstance(counts, list) and len(counts) == 3 and all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in counts))
        if not counts_valid:
            diagnostics.append(diag("error", "E171", "Array counts must be three positive integers.", f"array:{array_name}",
                                    "Use e.g. counts = [2, 1, 2].", p.get("__lines__", {}).get("counts", line), "counts"))
            good = False
        elif math.prod(counts) > 1024:
            diagnostics.append(diag("error", "E172", "Array expansion is capped at 1024 objects per array.", f"array:{array_name}",
                                    "Reduce the counts or split the array into smaller declarations.", p.get("__lines__", {}).get("counts", line), "counts"))
            good = False
        for field in ("at", "step"):
            if field in p and not _vec(p[field]):
                diagnostics.append(diag("error", "E173", f"Array {field} must be a numeric 3-vector.", f"array:{array_name}",
                                        f"Use `{field} = [x, y, z]`.", p.get("__lines__", {}).get(field, line), field))
                good = False
        for field in ("rotate", "scale"):
            if field in p and not _vec(p[field]):
                diagnostics.append(diag("error", "E174", f"Array {field} must be a numeric 3-vector.", f"array:{array_name}",
                                        f"Use `{field} = [x, y, z]`.", p.get("__lines__", {}).get(field, line), field))
                good = False
        if shape_valid:
            if shape == "box":
                size = p.get("size")
                if size is not None and (not _vec(size) or any(float(v) <= 0 for v in size)):
                    diagnostics.append(diag("error", "E122", "All array box size components must be positive numbers.", f"array:{array_name}",
                                            "Use a positive three-vector for size.", p.get("__lines__", {}).get("size", line), "size"))
                    good = False
            for field in (("radius", "height") if shape == "cylinder" else ("radius",) if shape == "sphere" else ()):
                val = p.get(field)
                if val is not None and (not _finite_number(val) or float(val) <= 0):
                    diagnostics.append(diag("error", "E123", f"Array {field} must be positive.", f"array:{array_name}",
                                            "Use a finite number greater than zero.", p.get("__lines__", {}).get(field, line), field))
                    good = False
            if shape in ("sphere", "cylinder") and "segments" in p and (
                not isinstance(p["segments"], int) or isinstance(p["segments"], bool) or not 6 <= p["segments"] <= 256):
                diagnostics.append(diag("error", "E124", "Array segments must be an integer between 6 and 256.", f"array:{array_name}",
                                        "Use 24 for a good default balance.", p.get("__lines__", {}).get("segments", line), "segments"))
                good = False
            if shape == "sphere" and "rings" in p and (
                not isinstance(p["rings"], int) or isinstance(p["rings"], bool) or not 4 <= p["rings"] <= 128):
                diagnostics.append(diag("error", "E125", "Array rings must be an integer between 4 and 128.", f"array:{array_name}",
                                        "Use 16 for a good default balance.", p.get("__lines__", {}).get("rings", line), "rings"))
                good = False
        at = p.get("at")
        step = p.get("step")
        if "at" not in p or not _vec(at) or "step" not in p or not _vec(step):
            good = False
        if "rotate" not in p:
            rotate = [0, 0, 0]
        else:
            rotate = p["rotate"] if _vec(p["rotate"]) else [0, 0, 0]
        if "scale" not in p:
            scale = [1, 1, 1]
        else:
            scale = p["scale"] if _vec(p["scale"]) else [1, 1, 1]
        material = p.get("material", "default")
        if not isinstance(material, str) or material not in normalized_materials:
            diagnostics.append(diag("error", "E130", f"Array references unknown or invalid material {material!r}.", f"array:{array_name}",
                                    "Reference a declared material or omit material to use default.", p.get("__lines__", {}).get("material", line), "material"))
            good = False
        generated_names = []
        if good:
            geometry = {k: p[k] for k in ("size", "radius", "height", "segments", "rings") if k in p}
            for ix in range(counts[0]):
                for iy in range(counts[1]):
                    for iz in range(counts[2]):
                        object_name = f"{array_name}_{ix}_{iy}_{iz}"
                        position = [float(at[d]) + [ix, iy, iz][d] * float(step[d]) for d in range(3)]
                        props = {**geometry, "at": position, "rotate": list(rotate), "scale": list(scale), "material": material}
                        props["__lines__"] = {k: p.get("__lines__", {}).get(k, line) for k in props}
                        objects_for_compile.append({"type": shape, "name": object_name, "props": props,
                                                    "line": line, "source_array": array_name})
                        generated_names.append(object_name)
        normalized_arrays.append({"name": array_name, "shape": shape if shape_valid else None,
                                  "counts": list(counts) if counts_valid else None,
                                  "step": list(step) if _vec(step) else None,
                                  "at": list(at) if _vec(at) else None,
                                  "object_names": generated_names, "line": line})

    consumed_by_boolean: set[str] = set()
    # Expand mirror_copy on objects
    mirrored_new_objects = []
    for obj in list(objects_for_compile):
        oprops = obj.get("props", {})
        m_copy = oprops.get("mirror_copy")
        if m_copy:
            m_axis = "x" if (m_copy is True or str(m_copy).lower() in ("x", "left_right")) else str(m_copy).lower()
            clone_props = dict(oprops)
            clone_props.pop("mirror_copy", None)
            c_at = list(oprops.get("at", [0.0, 0.0, 0.0]))
            c_rot = list(oprops.get("rotate", [0.0, 0.0, 0.0]))
            c_scale = list(oprops.get("scale", [1.0, 1.0, 1.0]))
            if m_axis in ("x", "left_right"):
                c_at[0] = -c_at[0]
                c_rot[1] = -c_rot[1]
                c_rot[2] = -c_rot[2]
            elif m_axis in ("y", "up_down"):
                c_at[1] = -c_at[1]
                c_rot[0] = -c_rot[0]
                c_rot[2] = -c_rot[2]
            elif m_axis in ("z", "front_back"):
                c_at[2] = -c_at[2]
                c_rot[0] = -c_rot[0]
                c_rot[1] = -c_rot[1]
            clone_props["at"] = c_at
            clone_props["rotate"] = c_rot
            clone_props["scale"] = c_scale
            mirrored_new_objects.append({
                "type": obj["type"],
                "name": f"{obj['name']}_mirrored",
                "props": clone_props,
                "line": obj["line"],
                "group": obj.get("group"),
            })
    objects_for_compile.extend(mirrored_new_objects)
    objects_by_name: dict[str, dict[str, Any]] = {o["name"]: o for o in objects_for_compile}

    for obj in objects_for_compile:
        obj_name, typ, p, line = obj["name"], obj["type"], obj["props"], obj["line"]
        if obj_name in seen:
            diagnostics.append(diag("error", "E120", f"Duplicate object name {obj_name!r}.", obj_name,
                                    "Every object needs a unique name.", line, "name"))
            continue
        seen[obj_name] = line
        allowed, required = allowed_by_type[typ]
        _check_properties(p, allowed, required, obj_name, line, diagnostics)
        for key in ("at", "rotate", "scale"):
            if key in p and not _vec(p[key]):
                diagnostics.append(diag("error", "E121", f"{key} must be a numeric 3-vector.", obj_name,
                                        f"Use e.g. `{key} = [0, 1, 0]`.", p.get("__lines__", {}).get(key, line), key))
            elif key in p and _vec(p[key]):
                limit = 1e4 if key == "scale" else 1e6
                if any(abs(float(v)) > limit for v in p[key]):
                    diagnostics.append(diag("error", "E189", f"{key} exceeds the safety limit of {limit:g}.", obj_name,
                                            "Keep transform values within the supported numeric range to avoid invalid float32 output.",
                                            p.get("__lines__", {}).get(key, line), key))
        if "at" not in p:
            p["at"] = [0.0, 0.0, 0.0]
        # Semantic attach_to constraint
        attach_target = p.get("attach_to")
        if isinstance(attach_target, str) and attach_target:
            target_parts = attach_target.split(".", 1)
            target_name = target_parts[0]
            anchor = target_parts[1].lower() if len(target_parts) > 1 else "center"
            target_obj = objects_by_name.get(target_name)
            if target_obj:
                tb = object_bounds(target_obj, groups_by_name)
                t_min = tb["min"]
                t_max = tb["max"]
                mid = [(t_min[i] + t_max[i]) / 2.0 for i in range(3)]
                anchor_pos = list(mid)
                if anchor == "top":
                    anchor_pos[1] = t_max[1]
                elif anchor == "bottom":
                    anchor_pos[1] = t_min[1]
                elif anchor == "front":
                    anchor_pos[2] = t_max[2]
                elif anchor == "back":
                    anchor_pos[2] = t_min[2]
                elif anchor == "left":
                    anchor_pos[0] = t_min[0]
                elif anchor == "right":
                    anchor_pos[0] = t_max[0]
                p["at"] = [anchor_pos[i] + float(p["at"][i]) for i in range(3)]
        if "rotate" not in p:
            p["rotate"] = [0.0, 0.0, 0.0]
        if "scale" not in p:
            p["scale"] = [1.0, 1.0, 1.0]
        if any(abs(float(x)) < 1e-12 for x in p.get("scale", [1, 1, 1])) if _vec(p.get("scale")) else False:
            diagnostics.append(diag("warning", "W121", "A zero scale can collapse this object to a flat or invisible shape.",
                                    obj_name, "Use non-zero scale components unless the collapse is intentional.", line, "scale"))
        if "size" in p:
            if not _vec(p["size"]):
                diagnostics.append(diag("error", "E122", "size must be a numeric 3-vector.", obj_name,
                                        "Use positive dimensions such as size = [1, 0.2, 1].",
                                        p.get("__lines__", {}).get("size", line), "size"))
            elif any(float(x) <= 0 for x in p["size"]):
                diagnostics.append(diag("error", "E122", "All size components must be greater than zero.", obj_name,
                                        "Use positive dimensions.", p.get("__lines__", {}).get("size", line), "size"))
            elif any(abs(float(x)) > 1e6 for x in p["size"]):
                diagnostics.append(diag("error", "E189", "size exceeds the supported limit of 1,000,000 units.", obj_name,
                                        "Keep geometry values within the supported numeric range.", p.get("__lines__", {}).get("size", line), "size"))
        for key in ("radius", "height"):
            if key in p and (not _finite_number(p[key]) or float(p[key]) <= 0):
                diagnostics.append(diag("error", "E123", f"{key} must be a positive finite number.", obj_name,
                                        "Use a value greater than zero.", p.get("__lines__", {}).get(key, line), key))
            elif key in p and float(p[key]) > 1e6:
                diagnostics.append(diag("error", "E189", f"{key} exceeds the supported limit of 1,000,000 units.", obj_name,
                                        "Keep geometry values within the supported numeric range.", p.get("__lines__", {}).get(key, line), key))
        if typ in ("sphere", "cylinder") and "segments" in p:
            if not isinstance(p["segments"], int) or isinstance(p["segments"], bool) or not 6 <= p["segments"] <= 256:
                diagnostics.append(diag("error", "E124", "segments must be an integer between 6 and 256.", obj_name,
                                        "Use 24 for a good default balance of quality and size.", p.get("__lines__", {}).get("segments", line), "segments"))
        if typ == "sphere" and "rings" in p:
            if not isinstance(p["rings"], int) or isinstance(p["rings"], bool) or not 4 <= p["rings"] <= 128:
                diagnostics.append(diag("error", "E125", "rings must be an integer between 4 and 128.", obj_name,
                                        "Use 16 for a good default balance of quality and size.", p.get("__lines__", {}).get("rings", line), "rings"))
        custom_mesh = None
        if typ == "box" and "fillet" in p:
            f_val = p.get("fillet")
            size = p.get("size")
            if not _finite_number(f_val) or float(f_val) <= 0:
                diagnostics.append(diag("error", "E205", "fillet must be a positive finite number.", obj_name,
                                        "Use a fillet radius such as fillet = 0.02.", p.get("__lines__", {}).get("fillet", line), "fillet"))
            elif _vec(size):
                min_half = min(float(v) for v in size) / 2.0
                if float(f_val) >= min_half:
                    diagnostics.append(diag("error", "E205", f"fillet ({f_val}) must be strictly less than half the smallest box dimension ({min_half}).", obj_name,
                                            f"Reduce fillet to less than {min_half}.", p.get("__lines__", {}).get("fillet", line), "fillet"))
                else:
                    f_segs = p.get("fillet_segments", 4)
                    if not isinstance(f_segs, int) or isinstance(f_segs, bool) or not 1 <= f_segs <= 16:
                        diagnostics.append(diag("error", "E206", "fillet_segments must be an integer between 1 and 16.", obj_name,
                                                "Use fillet_segments = 4.", p.get("__lines__", {}).get("fillet_segments", line), "fillet_segments"))
                        f_segs = 4
                    try:
                        custom_mesh = build_filleted_box([float(v) for v in size], float(f_val), f_segs)
                    except (ValueError, ArithmeticError) as exc:
                        diagnostics.append(diag("error", "E205", f"Could not build filleted box mesh: {exc}", obj_name,
                                                "Check box size and fillet parameters.", line, "fillet"))
        elif typ == "sweep":
            raw_pts = p.get("control_points") or p.get("path")
            path_type = p.get("path_type", "linear" if "path" in p and "control_points" not in p else "catmull_rom")
            if path_type not in ("linear", "catmull_rom", "cubic_bezier", "b_spline"):
                diagnostics.append(diag("error", "E210", f"Unknown path_type {path_type!r}.", obj_name,
                                        "Use linear, catmull_rom, cubic_bezier, or b_spline.", p.get("__lines__", {}).get("path_type", line), "path_type"))
                path_type = "catmull_rom"
            path_segs = p.get("path_segments", 48)
            if not isinstance(path_segs, int) or isinstance(path_segs, bool) or not 4 <= path_segs <= 512:
                diagnostics.append(diag("error", "E211", "path_segments must be an integer between 4 and 512.", obj_name,
                                        "Use path_segments = 48.", p.get("__lines__", {}).get("path_segments", line), "path_segments"))
                path_segs = 48

            path, path_error = validate_path(raw_pts)
            if path_error:
                diagnostics.append(diag("error", "E185", path_error, obj_name,
                                        "Provide 2..256 finite, non-duplicate [x, y, z] points.",
                                        p.get("__lines__", {}).get("control_points", p.get("__lines__", {}).get("path", line)), "path"))
            elif path is not None and path_type != "linear":
                try:
                    path = evaluate_spline(path, spline_type=path_type, samples=path_segs)
                except Exception as exc:
                    diagnostics.append(diag("error", "E212", f"Could not evaluate spline: {exc}", obj_name,
                                            "Check control points for valid 3D coordinates.", line, "control_points"))
                    path = None

            radius = p.get("radius")
            if not _finite_number(radius) or float(radius) <= 0 or float(radius) > 1e6:
                diagnostics.append(diag("error", "E186", "sweep radius must be positive and no greater than 1,000,000 units.", obj_name,
                                        "Use a positive tube radius, e.g. radius = 0.025.",
                                        p.get("__lines__", {}).get("radius", line), "radius"))
            segments = p.get("segments", 16)
            if not isinstance(segments, int) or isinstance(segments, bool) or not 6 <= segments <= 128:
                diagnostics.append(diag("error", "E187", "sweep segments must be an integer from 6 to 128.", obj_name,
                                        "Use 16 for a compact preview or 32 for a smoother tube.",
                                        p.get("__lines__", {}).get("segments", line), "segments"))
                segments = 16
            if path is not None and _finite_number(radius) and 0 < float(radius) <= 1e6 and isinstance(segments, int) and 6 <= segments <= 128:
                try:
                    custom_mesh = build_sweep(path, float(radius), segments)
                except (ValueError, ArithmeticError) as exc:
                    diagnostics.append(diag("error", "E188", f"Could not build sweep mesh: {exc}", obj_name,
                                            "Adjust the path so each segment is nonzero and adjacent tangents are well-defined.", line, "path"))
        elif typ in ("extrude", "revolve"):
            is_revolve = typ == "revolve"
            profile, profile_error = validate_profile(p.get("profile"), nonnegative_x=is_revolve)
            if profile_error:
                diagnostics.append(diag("error", "E180", profile_error, obj_name,
                                        "Provide a simple, non-degenerate polygon profile using finite [a, b] points.",
                                        p.get("__lines__", {}).get("profile", line), "profile"))
            if is_revolve:
                segments = p.get("segments", 48)
                if not isinstance(segments, int) or isinstance(segments, bool) or not 8 <= segments <= 256:
                    diagnostics.append(diag("error", "E181", "revolve segments must be an integer from 8 to 256.", obj_name,
                                            "Use segments = 48 for smooth product forms.",
                                            p.get("__lines__", {}).get("segments", line), "segments"))
                    segments = 48
                if profile is not None and isinstance(segments, int) and 8 <= segments <= 256:
                    try:
                        custom_mesh = build_revolve(profile, segments)
                    except (ValueError, ArithmeticError) as exc:
                        diagnostics.append(diag("error", "E182", f"Could not build revolve mesh: {exc}", obj_name,
                                                "Adjust profile points and confirm the profile is a simple closed polygon.", line, "profile"))
            else:
                depth = p.get("depth")
                if not _finite_number(depth) or float(depth) <= 0 or float(depth) > 1e6:
                    diagnostics.append(diag("error", "E183", "extrude depth must be positive and no greater than 1,000,000 units.", obj_name,
                                            "Use depth > 0, for example depth = 0.12.",
                                            p.get("__lines__", {}).get("depth", line), "depth"))
                if profile is not None and _finite_number(depth) and 0 < float(depth) <= 1e6:
                    try:
                        custom_mesh = build_extrusion(profile, float(depth))
                    except (ValueError, ArithmeticError) as exc:
                        diagnostics.append(diag("error", "E184", f"Could not build extrusion mesh: {exc}", obj_name,
                                                "Adjust profile points and confirm the polygon is simple.", line, "profile"))
        elif typ == "loft":
            sections, sec_err = validate_loft_sections(p.get("sections"))
            if sec_err:
                diagnostics.append(diag("error", "E195", sec_err, obj_name,
                                        "Provide at least 2 cross-sections, each having at least 3 points [x, y, z] or flat station [x, y0, z0, ...].",
                                        p.get("__lines__", {}).get("sections", line), "sections"))
            subdivisions = p.get("subdivisions", 1)
            if not isinstance(subdivisions, int) or isinstance(subdivisions, bool) or not 1 <= subdivisions <= 64:
                diagnostics.append(diag("error", "E196", "loft subdivisions must be an integer from 1 to 64.", obj_name,
                                        "Use subdivisions = 4 or 8 for smooth blends.",
                                        p.get("__lines__", {}).get("subdivisions", line), "subdivisions"))
                subdivisions = 1
            if sections is not None:
                try:
                    custom_mesh = build_loft(sections, subdivisions=subdivisions)
                except (ValueError, ArithmeticError) as exc:
                    diagnostics.append(diag("error", "E197", f"Could not build loft mesh: {exc}", obj_name,
                                            "Ensure loft sections are simple closed rings with non-degenerate station positions.", line, "sections"))
        elif typ == "cone":
            r_bot = p.get("radius_bottom", p.get("radius", 0.5))
            r_top = p.get("radius_top", 0.0)
            height = p.get("height")
            if not _finite_number(r_bot) or float(r_bot) < 0 or float(r_bot) > 1e6:
                diagnostics.append(diag("error", "E198", "cone radius_bottom must be a non-negative finite number.", obj_name,
                                        "Use radius_bottom = 0.5 or specify radius.", p.get("__lines__", {}).get("radius_bottom", line), "radius_bottom"))
            if not _finite_number(r_top) or float(r_top) < 0 or float(r_top) > 1e6:
                diagnostics.append(diag("error", "E198", "cone radius_top must be a non-negative finite number.", obj_name,
                                        "Use radius_top = 0.0 for a pointed cone, or > 0 for a frustum.", p.get("__lines__", {}).get("radius_top", line), "radius_top"))
            if _finite_number(r_bot) and _finite_number(r_top) and float(r_bot) == 0.0 and float(r_top) == 0.0:
                diagnostics.append(diag("error", "E198", "At least one of radius_bottom or radius_top must be greater than zero.", obj_name,
                                        "Set radius_bottom > 0.", line, "radius_bottom"))
            if not _finite_number(height) or float(height) <= 0 or float(height) > 1e6:
                diagnostics.append(diag("error", "E199", "cone height must be positive and no greater than 1,000,000 units.", obj_name,
                                        "Use height > 0, for example height = 1.0.", p.get("__lines__", {}).get("height", line), "height"))
            segments = p.get("segments", 24)
            if not isinstance(segments, int) or isinstance(segments, bool) or not 6 <= segments <= 256:
                diagnostics.append(diag("error", "E124", "cone segments must be an integer between 6 and 256.", obj_name,
                                        "Use segments = 24 for good quality.", p.get("__lines__", {}).get("segments", line), "segments"))
                segments = 24
            if (_finite_number(r_bot) and _finite_number(r_top) and (float(r_bot) > 0 or float(r_top) > 0) and
                    _finite_number(height) and float(height) > 0 and isinstance(segments, int) and 6 <= segments <= 256):
                try:
                    custom_mesh = build_cone(float(r_bot), float(r_top), float(height), segments)
                except (ValueError, ArithmeticError) as exc:
                    diagnostics.append(diag("error", "E199", f"Could not build cone mesh: {exc}", obj_name,
                                            "Check radius and height values.", line, "cone"))
        elif typ == "torus":
            major_r = p.get("major_radius")
            minor_r = p.get("minor_radius")
            if not _finite_number(major_r) or float(major_r) <= 0 or float(major_r) > 1e6:
                diagnostics.append(diag("error", "E201", "torus major_radius must be positive.", obj_name,
                                        "Use major_radius > 0, e.g. major_radius = 0.5.", p.get("__lines__", {}).get("major_radius", line), "major_radius"))
            if not _finite_number(minor_r) or float(minor_r) <= 0 or float(minor_r) > 1e6:
                diagnostics.append(diag("error", "E202", "torus minor_radius must be positive.", obj_name,
                                        "Use minor_radius > 0, e.g. minor_radius = 0.1.", p.get("__lines__", {}).get("minor_radius", line), "minor_radius"))
            if _finite_number(major_r) and _finite_number(minor_r) and float(minor_r) >= float(major_r):
                diagnostics.append(diag("error", "E203", "torus minor_radius must be smaller than major_radius to avoid self-intersection.", obj_name,
                                        "Set minor_radius < major_radius.", p.get("__lines__", {}).get("minor_radius", line), "minor_radius"))
            segments = p.get("segments", 32)
            rings = p.get("rings", 16)
            if not isinstance(segments, int) or isinstance(segments, bool) or not 6 <= segments <= 256:
                diagnostics.append(diag("error", "E124", "torus segments must be an integer between 6 and 256.", obj_name,
                                        "Use segments = 32.", p.get("__lines__", {}).get("segments", line), "segments"))
                segments = 32
            if not isinstance(rings, int) or isinstance(rings, bool) or not 4 <= rings <= 128:
                diagnostics.append(diag("error", "E125", "torus rings must be an integer between 4 and 128.", obj_name,
                                        "Use rings = 16.", p.get("__lines__", {}).get("rings", line), "rings"))
                rings = 16
            if (_finite_number(major_r) and _finite_number(minor_r) and 0 < float(minor_r) < float(major_r) and
                    isinstance(segments, int) and 6 <= segments <= 256 and isinstance(rings, int) and 4 <= rings <= 128):
                try:
                    custom_mesh = build_torus(float(major_r), float(minor_r), segments, rings)
                except (ValueError, ArithmeticError) as exc:
                    diagnostics.append(diag("error", "E204", f"Could not build torus mesh: {exc}", obj_name,
                                            "Check radius parameters.", line, "torus"))
        elif typ == "boolean":
            op = p.get("op", "difference")
            base_name = p.get("base")
            tools = p.get("tools")
            if isinstance(tools, str):
                tool_names = [tools]
            elif isinstance(tools, list):
                tool_names = tools
            else:
                tool_names = []

            if not isinstance(base_name, str) or not base_name:
                diagnostics.append(diag("error", "E200", "Boolean base must be the name of an object.", obj_name,
                                        "Use e.g. base = 'my_solid'.", p.get("__lines__", {}).get("base", line), "base"))
            if not tool_names:
                diagnostics.append(diag("error", "E200", "Boolean tools must contain at least one tool object name.", obj_name,
                                        "Use e.g. tools = ['cutter_1', 'cutter_2'].", p.get("__lines__", {}).get("tools", line), "tools"))

            base_obj = objects_by_name.get(base_name)
            if not base_obj:
                diagnostics.append(diag("error", "E200", f"Boolean base object {base_name!r} not found.", obj_name,
                                        "Reference a previously declared object.", p.get("__lines__", {}).get("base", line), "base"))

            tool_objs = []
            for tname in tool_names:
                t_obj = objects_by_name.get(tname)
                if not t_obj:
                    diagnostics.append(diag("error", "E200", f"Boolean tool object {tname!r} not found.", obj_name,
                                            "Reference a previously declared object.", p.get("__lines__", {}).get("tools", line), "tools"))
                else:
                    tool_objs.append(t_obj)

            if base_obj and len(tool_objs) == len(tool_names):
                base_world = _get_object_world_mesh(base_obj, groups_by_name)
                tool_worlds = [_get_object_world_mesh(to, groups_by_name) for to in tool_objs]
                if base_world and all(tw is not None for tw in tool_worlds):
                    try:
                        raw_bool_mesh = build_boolean(op, base_world, tool_worlds)
                        b_at = p.get("at", [0.0, 0.0, 0.0])
                        if _vec(b_at):
                            tx, ty, tz = [float(v) for v in b_at]
                            raw_bool_mesh["vertices"] = [[v[0] - tx, v[1] - ty, v[2] - tz] for v in raw_bool_mesh["vertices"]]
                        custom_mesh = raw_bool_mesh

                        if p.get("hide_operands", True):
                            consumed_by_boolean.add(base_name)
                            consumed_by_boolean.update(tool_names)
                    except Exception as exc:
                        diagnostics.append(diag("error", "E201", f"Boolean operation failed: {exc}", obj_name,
                                                "Ensure tool and base overlap cleanly without degenerate edges.", line, "op"))
        elif typ == "subdivision":
            base_ref = str(p.get("base", ""))
            levels = int(p.get("levels", 1))
            base_obj = objects_by_name.get(base_ref)
            if not base_obj:
                diagnostics.append(diag("error", "E210", f"Subdivision base object {base_ref!r} not found.", obj_name,
                                        "Reference an existing primitive or boolean object.", line, "base"))
            else:
                base_world = _get_object_world_mesh(base_obj, groups_by_name)
                if base_world:
                    if p.get("hide_base", True):
                        consumed_by_boolean.add(base_ref)
                    try:
                        raw_subd_mesh = build_subdivision(base_world, levels=levels)
                        s_at = p.get("at", [0.0, 0.0, 0.0])
                        if _vec(s_at):
                            tx, ty, tz = [float(v) for v in s_at]
                            raw_subd_mesh["vertices"] = [[v[0] - tx, v[1] - ty, v[2] - tz] for v in raw_subd_mesh["vertices"]]
                        custom_mesh = raw_subd_mesh
                    except Exception as exc:
                        diagnostics.append(diag("error", "E211", f"Subdivision failed on {base_ref!r}: {exc}", obj_name,
                                                "Ensure base object produces a valid 2-manifold closed solid.", line, "base"))
        if custom_mesh is not None:
            obj["_mesh_geometry"] = custom_mesh
        # Semantic ground snap / bottom alignment constraint
        if p.get("snap_to_ground") or "align_bottom" in p:
            target_y = float(p.get("align_bottom", 0.0))
            cur_bounds = object_bounds(obj, groups_by_name)
            curr_min_y = cur_bounds["min"][1]
            delta_y = target_y - curr_min_y
            p["at"][1] += delta_y

        material = p.get("material", "default")
        if not isinstance(material, str) or material not in normalized_materials:
            diagnostics.append(diag("error", "E130", f"Object references unknown or invalid material {material!r}.", obj_name,
                                    "Set material to the name of a material block, or omit it to use the default.",
                                    p.get("__lines__", {}).get("material", line), "material"))
        geometry = {}
        if custom_mesh is not None:
            geometry["mesh"] = custom_mesh
        if "size" in p and _vec(p["size"]):
            geometry["size"] = list(p["size"])
        for key in ("radius", "height"):
            if key in p and _finite_number(p[key]) and float(p[key]) > 0:
                geometry[key] = float(p[key])
        for key in ("segments", "rings"):
            if key in p and isinstance(p[key], int) and not isinstance(p[key], bool):
                geometry[key] = p[key]
        if typ in ("extrude", "revolve"):
            if isinstance(p.get("profile"), list):
                geometry["profile"] = p["profile"]
            if typ == "extrude" and _finite_number(p.get("depth")):
                geometry["depth"] = float(p["depth"])
            if typ == "revolve":
                geometry["segments"] = int(p.get("segments", 48)) if isinstance(p.get("segments", 48), int) and not isinstance(p.get("segments", 48), bool) else 48
        elif typ == "sweep":
            if isinstance(p.get("path"), list):
                geometry["path"] = p["path"]
            if _finite_number(p.get("radius")) and float(p["radius"]) > 0:
                geometry["radius"] = float(p["radius"])
            geometry["segments"] = int(p.get("segments", 16)) if isinstance(p.get("segments", 16), int) and not isinstance(p.get("segments", 16), bool) else 16
        elif typ == "loft":
            if isinstance(p.get("sections"), list):
                geometry["sections"] = p["sections"]
            if "subdivisions" in p:
                geometry["subdivisions"] = p["subdivisions"]
        elif typ == "cone":
            for k in ("radius_bottom", "radius_top", "radius", "height", "segments"):
                if k in p and _finite_number(p[k]):
                    geometry[k] = float(p[k]) if k != "segments" else int(p[k])
        elif typ == "torus":
            for k in ("major_radius", "minor_radius", "segments", "rings"):
                if k in p and _finite_number(p[k]):
                    geometry[k] = float(p[k]) if k not in ("segments", "rings") else int(p[k])
        at = p.get("at", [0, 0, 0])
        rotate = p.get("rotate", [0, 0, 0])
        scale = p.get("scale", [1, 1, 1])
        normalized_object = {"name": obj_name, "type": typ, "geometry": geometry,
            "transform": {"translation": list(at) if _vec(at) else [0, 0, 0],
                         "rotation_euler_degrees": list(rotate) if _vec(rotate) else [0, 0, 0],
                         "scale": list(scale) if _vec(scale) else [1, 1, 1]},
            "material": material, "line": line}
        if obj.get("source_array"):
            normalized_object["source_array"] = obj["source_array"]
        if obj.get("group"):
            normalized_object["group"] = obj["group"]
        normalized_objects.append(normalized_object)

    normalized_objects = [no for no in normalized_objects if no["name"] not in consumed_by_boolean]

    # Camera checks.
    camera = ast_scene.get("camera")
    normalized_camera = None
    if camera is not None:
        line = ast_scene.get("_camera_line", 1)
        _check_properties(camera, {"at", "target", "fov", "near", "far"}, {"at", "target"}, "camera", line, diagnostics)
        for key in ("at", "target"):
            if key in camera and not _vec(camera[key]):
                diagnostics.append(diag("error", "E140", f"Camera {key} must be a numeric 3-vector.", "camera",
                                        f"Use `{key} = [x, y, z]`.", camera.get("__lines__", {}).get(key, line), key))
        fov = camera.get("fov", 50)
        if not _finite_number(fov) or not 1 <= float(fov) <= 179:
            diagnostics.append(diag("error", "E141", "Camera fov must be between 1 and 179 degrees.", "camera",
                                    "A value between 35 and 60 is a useful starting point.", camera.get("__lines__", {}).get("fov", line), "fov"))
        camera_at = camera.get("at", [4, 3, 5])
        camera_target = camera.get("target", [0, 0, 0])
        normalized_camera = {"position": list(camera_at) if _vec(camera_at) else [4, 3, 5],
                             "target": list(camera_target) if _vec(camera_target) else [0, 0, 0],
                             "fov": float(fov) if _finite_number(fov) else 50.0,
                             "near": float(camera.get("near", 0.01)) if _finite_number(camera.get("near", 0.01)) else 0.01,
                             "far": float(camera.get("far", 1000)) if _finite_number(camera.get("far", 1000)) else 1000}
        if normalized_camera["near"] <= 0 or normalized_camera["far"] <= normalized_camera["near"]:
            diagnostics.append(diag("error", "E142", "Camera clipping planes must satisfy 0 < near < far.", "camera",
                                    "For example, near = 0.01 and far = 1000.", line, "near/far"))
    else:
        diagnostics.append(diag("warning", "W140", "No camera is defined; consumers will need to supply one.", name,
                                "Add a camera block for a directly previewable scene.", 1, "camera"))

    # Light checks.
    normalized_lights = []
    light_lines = ast_scene.get("_light_lines", {})
    for light in ast_scene["lights"]:
        light_name, p, line = light["name"], light["props"], light["line"]
        _check_properties(p, {"type", "at", "color", "intensity", "range"}, {"type", "at"},
                          f"light:{light_name}", line, diagnostics)
        if p.get("type") not in ("point", "directional", "spot"):
            diagnostics.append(diag("error", "E150", "Light type must be point, directional, or spot.",
                                    f"light:{light_name}", "Use type = point for a simple local light.", line, "type"))
        if "at" in p and not _vec(p["at"]):
            diagnostics.append(diag("error", "E151", "Light at must be a numeric 3-vector.", f"light:{light_name}",
                                    "Use e.g. at = [2, 3, 2].", p.get("__lines__", {}).get("at", line), "at"))
        color = p.get("color", "#ffffff")
        if not _color(color):
            diagnostics.append(diag("error", "E152", "Light color must be a six-digit hex color.", f"light:{light_name}",
                                    'Use color = "#ffffff".', p.get("__lines__", {}).get("color", line), "color"))
        intensity = p.get("intensity", 100)
        if not _finite_number(intensity) or float(intensity) < 0:
            diagnostics.append(diag("error", "E153", "Light intensity must be a non-negative number.", f"light:{light_name}",
                                    "Use a non-negative intensity.", p.get("__lines__", {}).get("intensity", line), "intensity"))
        light_at = p.get("at", [0, 2, 0])
        normalized_lights.append({"name": light_name, "type": p.get("type", "point"),
                                  "position": list(light_at) if _vec(light_at) else [0, 2, 0], "color": _hex_rgb(color) if _color(color) else [1, 1, 1],
                                  "source_color": color if _color(color) else "#ffffff",
                                  "intensity": float(intensity) if _finite_number(intensity) and float(intensity) >= 0 else 100,
                                  "range": float(p.get("range", 0)) if _finite_number(p.get("range", 0)) and p.get("range", 0) >= 0 else 0})

    # Compute estimated world-space AABBs for actionable geometric constraints.
    by_name_ast = {o["name"]: o for o in objects_for_compile}
    bounds_by_name = {o["name"]: object_bounds(o, groups_by_name) for o in objects_for_compile}
    array_member_names = {a["name"]: list(a.get("object_names", [])) for a in normalized_arrays}
    normalized_constraints = []
    known_constraint_kinds = {"above", "below", "inside", "separated", "supported_by"}
    for constraint in ast_scene["constraints"]:
        cname, p, line = constraint["name"], constraint["props"], constraint["line"]
        _check_properties(p, {"kind", "object", "target", "axis", "gap", "tolerance"},
                          {"kind", "object", "target"}, f"constraint:{cname}", line, diagnostics)
        kind, obj_name, target_name = p.get("kind"), p.get("object"), p.get("target")
        kind_valid = isinstance(kind, str) and kind in known_constraint_kinds
        if not kind_valid:
            diagnostics.append(diag("error", "E160", f"Unknown constraint kind {kind!r}.", f"constraint:{cname}",
                                    "Supported kinds: above, below, inside, separated, supported_by.", line, "kind"))
        object_name_valid = isinstance(obj_name, str) and (obj_name in by_name_ast or
            (kind == "supported_by" and obj_name in array_member_names))
        target_name_valid = isinstance(target_name, str) and target_name in by_name_ast
        if not object_name_valid or not target_name_valid:
            missing = obj_name if not object_name_valid else target_name
            diagnostics.append(diag("error", "E161", f"Constraint references unknown or invalid object {missing!r}.",
                                    f"constraint:{cname}", "Use names of objects declared in this scene; supported_by can target an array name.", line, "object/target"))
        elif kind_valid:
            gap = float(p.get("gap", 0.0)) if _finite_number(p.get("gap", 0.0)) else 0.0
            tolerance = float(p.get("tolerance", 0.01)) if _finite_number(p.get("tolerance", 0.01)) else 0.01
            if tolerance < 0:
                diagnostics.append(diag("error", "E164", "Constraint tolerance must be non-negative.", f"constraint:{cname}",
                                        "Use tolerance >= 0, for example tolerance = 0.01.", line, "tolerance"))
                tolerance = 0.01
            axis = p.get("axis", "y")
            if kind == "supported_by":
                member_names = array_member_names.get(obj_name, [obj_name])
                failures = []
                if not member_names:
                    failures.append(f"{obj_name}: array did not produce valid instances")
                else:
                    for member_name in member_names:
                        child = by_name_ast.get(member_name)
                        if child is None:
                            failures.append(f"{member_name}: object is unavailable")
                            continue
                        reason = _support_failure(child, bounds_by_name[member_name],
                                                  by_name_ast[target_name], bounds_by_name[target_name], tolerance)
                        if reason:
                            failures.append(f"{member_name}: {reason}")
                if failures:
                    diagnostics.append(diag("error", "E164", f"Constraint {cname!r} failed: " + "; ".join(failures[:8]) +
                                            (f"; and {len(failures)-8} more" if len(failures) > 8 else ""),
                                            f"constraint:{cname}",
                                            "Place every object's bottom on the target's top face and keep its full footprint inside the support profile.",
                                            line, "object/target"))
            elif kind in ("above", "below") and axis not in ("x", "y", "z"):
                diagnostics.append(diag("error", "E162", "Constraint axis must be x, y, or z.", f"constraint:{cname}",
                                        "Choose the coordinate axis used by above/below.", line, "axis"))
            else:
                a, b = bounds_by_name[obj_name], bounds_by_name[target_name]
                idx = {"x": 0, "y": 1, "z": 2}.get(axis, 1)
                satisfied = True
                detail = ""
                if kind == "above":
                    actual = a["min"][idx] - b["max"][idx]
                    satisfied = actual + tolerance >= gap
                    detail = f"measured gap {actual:.4f}, required at least {gap:.4f}"
                elif kind == "below":
                    actual = b["min"][idx] - a["max"][idx]
                    satisfied = actual + tolerance >= gap
                    detail = f"measured gap {actual:.4f}, required at least {gap:.4f}"
                elif kind == "inside":
                    satisfied = all(a["min"][i] >= b["min"][i] - tolerance and a["max"][i] <= b["max"][i] + tolerance for i in range(3))
                    detail = "object must fit inside target bounds"
                elif kind == "separated":
                    overlaps = [min(a["max"][i], b["max"][i]) - max(a["min"][i], b["min"][i]) for i in range(3)]
                    intersects_volume = all(v > tolerance for v in overlaps)
                    gaps = [max(b["min"][i] - a["max"][i], a["min"][i] - b["max"][i], 0.0) for i in range(3)]
                    actual = math.sqrt(sum(g*g for g in gaps))
                    satisfied = (not intersects_volume) and actual + tolerance >= gap
                    detail = ("the AABBs overlap in volume" if intersects_volume else
                              f"measured AABB separation {actual:.4f}, required at least {gap:.4f}")
                if not satisfied:
                    diagnostics.append(diag("error", "E163", f"Constraint {cname!r} failed: {detail}.",
                                            f"constraint:{cname}",
                                            "Adjust the object's position/size or revise the intended constraint.", line, "gap"))
        normalized_constraints.append({"name": cname, **{k: v for k, v in p.items() if k != "__lines__"}})

    # Attach bounds and a few geometry facts to the IR.
    object_ir_by_name = {o["name"]: o for o in normalized_objects}
    for object_bound_name, bounds in bounds_by_name.items():
        if object_bound_name in object_ir_by_name:
            object_ir_by_name[object_bound_name]["bounds"] = bounds

    errors = sum(d["severity"] == "error" for d in diagnostics)
    feature_nodes = []
    feature_edges = []
    feature_layers = {"base_form": [], "refinement": [], "detail": [], "material": [], "variant": []}
    for feature in normalized_features:
        node = {
            "name": feature["name"],
            "kind": feature["kind"],
            "parent": feature["parent"],
            "phase": feature["phase"],
            "layer": feature["layer"],
            "params": feature["params"],
            "line": feature["line"],
        }
        feature_nodes.append(node)
        if feature["parent"] is not None:
            feature_edges.append({"from": feature["parent"], "to": feature["name"], "relationship": "parent"})
        feature_layers.setdefault(feature["layer"], []).append(feature["name"])
    feature_graph = {
        "version": "phase1",
        "type": "feature_graph",
        "node_count": len(feature_nodes),
        "edge_count": len(feature_edges),
        "nodes": feature_nodes,
        "edges": feature_edges,
        "layers": {k: v for k, v in feature_layers.items() if v},
    }
    feature_graph["revision"] = _revision({"nodes": feature_nodes, "edges": feature_edges})
    scene_ir = {"schema": SCHEMA, "name": name, "units": ast_scene.get("units", "m"), "up_axis": "Y",
                "materials": normalized_materials, "objects": normalized_objects, "arrays": normalized_arrays,
                "groups": normalized_groups, "params": ast_scene.get("params", {}),
                "features": normalized_features, "variants": normalized_variants,
                "feature_graph": feature_graph, "camera": normalized_camera, "lights": normalized_lights,
                "constraints": normalized_constraints, "bounds": {k: v for k, v in bounds_by_name.items()},
                "stats": {"object_count": len(normalized_objects), "material_count": len(materials),
                          "light_count": len(normalized_lights), "constraint_count": len(normalized_constraints),
                          "array_count": len(normalized_arrays), "group_count": len(normalized_groups),
                          "param_count": len(ast_scene.get("params", {})),
                          "feature_count": len(normalized_features),
                          "variant_count": len(normalized_variants)}}
    scene_ir["provenance"] = {
        "asset_revision": _revision(scene_ir),
        "feature_revision": feature_graph["revision"],
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    return {"valid": errors == 0, "scene": scene_ir, "diagnostics": diagnostics,
            "summary": {**scene_ir["stats"], "errors": errors,
                        "warnings": sum(d["severity"] == "warning" for d in diagnostics)}}


def apply_patches(ast_scene: dict[str, Any], edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply safe, small AST patches.

    Supported ops: set, set_feature, delete_object, delete_feature.
    """
    applied = []
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise M3LCompileError(f"Edit {i} must be an object.")
        op = edit.get("op")
        target = edit.get("target")
        if op == "set":
            field, value = edit.get("field"), edit.get("value")
            if not isinstance(field, str) or not field or field.startswith("__"):
                raise M3LCompileError(f"Edit {i}: field must be a public property name.")
            obj = next((o for o in ast_scene["objects"] if o["name"] == target), None)
            if obj:
                obj["props"][field] = value
            elif isinstance(target, str) and target in ast_scene["materials"]:
                ast_scene["materials"][target][field] = value
            elif isinstance(target, str) and any(a["name"] == target for a in ast_scene.get("arrays", [])):
                next(a for a in ast_scene["arrays"] if a["name"] == target)["props"][field] = value
            elif isinstance(target, str) and any(g["name"] == target for g in ast_scene.get("groups", [])):
                next(g for g in ast_scene["groups"] if g["name"] == target)["props"][field] = value
            elif isinstance(target, str) and target in ast_scene.get("params", {}):
                ast_scene["params"][target] = value
            elif target == "camera" and ast_scene.get("camera") is not None:
                ast_scene["camera"][field] = value
            else:
                raise M3LCompileError(f"Edit {i}: target {target!r} was not found (objects, materials, groups, params, or camera).")
            applied.append({"op": op, "target": target, "field": field})
        elif op == "set_feature":
            field, value = edit.get("field"), edit.get("value")
            if not isinstance(field, str) or not field or field.startswith("__"):
                raise M3LCompileError(f"Edit {i}: field must be a public property name.")
            feature = next((item for item in ast_scene.get("features", []) if item["name"] == target), None)
            if feature is None:
                raise M3LCompileError(f"Edit {i}: feature {target!r} was not found.")
            feature["props"][field] = value
            applied.append({"op": op, "target": target, "field": field})
        elif op == "delete_object":
            before = len(ast_scene["objects"])
            ast_scene["objects"] = [o for o in ast_scene["objects"] if o["name"] != target]
            if len(ast_scene["objects"]) == before:
                raise M3LCompileError(f"Edit {i}: object {target!r} was not found.")
            applied.append({"op": op, "target": target})
        elif op == "delete_feature":
            before = len(ast_scene.get("features", []))
            ast_scene["features"] = [item for item in ast_scene.get("features", []) if item["name"] != target]
            if len(ast_scene.get("features", [])) == before:
                raise M3LCompileError(f"Edit {i}: feature {target!r} was not found.")
            applied.append({"op": op, "target": target})
        else:
            raise M3LCompileError(f"Edit {i}: unsupported op {op!r}; use set, set_feature, delete_object, or delete_feature.")
    return applied
