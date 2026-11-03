"""Optional CadQuery/OpenCascade B-rep backend for STEP export.

The core M3L compiler stays standard-library-only. This module converts validated
scene IR into analytic/trimmed OpenCascade solids so downstream CAD systems can
operate on B-rep geometry rather than only triangulated display meshes.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


class CadQueryUnavailableError(RuntimeError):
    """Raised when the optional CadQuery dependency is unavailable."""


class CadQueryExportError(RuntimeError):
    """Raised when a scene cannot be translated to a valid B-rep assembly."""


_SCENE_TO_CQ_UNIT = {"m": "M", "cm": "CM", "mm": "MM", "in": "INCH", "ft": "FT"}
_ALLOWED_OUTPUT_UNITS = {"M", "MM", "CM", "INCH", "FT"}


def discover_cadquery() -> bool:
    try:
        import cadquery  # noqa: F401
        return True
    except Exception:
        return False


def _cadquery():
    try:
        import cadquery as cq
        return cq
    except Exception as exc:  # keep optional import failure actionable
        raise CadQueryUnavailableError(
            "CadQuery/OpenCascade is not installed. Install the optional 'cadquery' package to export STEP."
        ) from exc


def _vec3(point: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(point, (list, tuple)) or len(point) != 3:
        raise CadQueryExportError(f"{label} must be a 3-vector.")
    try:
        values = tuple(float(v) for v in point)
    except (TypeError, ValueError) as exc:
        raise CadQueryExportError(f"{label} must contain numeric values.") from exc
    if not all(math.isfinite(v) for v in values):
        raise CadQueryExportError(f"{label} must contain finite values.")
    return values


def _apply_transform(shape, transform: dict[str, Any], cq):
    translation = _vec3(transform.get("translation", [0, 0, 0]), "translation")
    rotation = _vec3(transform.get("rotation_euler_degrees", [0, 0, 0]), "rotation")
    scale = _vec3(transform.get("scale", [1, 1, 1]), "scale")
    if any(abs(v) < 1e-12 for v in scale):
        raise CadQueryExportError("Zero scale collapses a solid and cannot be exported as a valid STEP body.")
    # M3L transforms use XYZ Euler angles. Compose Rz * Ry * Rx, then local scale,
    # then world translation. A single affine operation also supports nonuniform scale.
    rx, ry, rz = (math.radians(v) for v in rotation)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rxm = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    rym = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rzm = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def matmul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    rot = matmul(matmul(rzm, rym), rxm)
    linear = [[rot[i][j] * scale[j] for j in range(3)] for i in range(3)]
    matrix = cq.Matrix([
        [linear[0][0], linear[0][1], linear[0][2], translation[0]],
        [linear[1][0], linear[1][1], linear[1][2], translation[1]],
        [linear[2][0], linear[2][1], linear[2][2], translation[2]],
        [0, 0, 0, 1],
    ])
    try:
        return shape.transformGeometry(matrix)
    except Exception as exc:
        raise CadQueryExportError(f"Could not apply transform to solid: {exc}") from exc


def _shape_for_object(obj: dict[str, Any], cq):
    from cadquery import Vector

    name = obj.get("name", "<unnamed>")
    typ = obj.get("type")
    geometry = obj.get("geometry", {})
    try:
        if typ == "box":
            size = _vec3(geometry.get("size"), f"{name}.size")
            shape = cq.Workplane("XY").box(*size).val()
        elif typ == "sphere":
            radius = float(geometry.get("radius", 0))
            if not math.isfinite(radius) or radius <= 0:
                raise CadQueryExportError(f"{name}.radius must be positive.")
            shape = cq.Workplane("XY").sphere(radius).val()
        elif typ == "cylinder":
            radius, height = float(geometry.get("radius", 0)), float(geometry.get("height", 0))
            if not (math.isfinite(radius) and math.isfinite(height) and radius > 0 and height > 0):
                raise CadQueryExportError(f"{name} requires positive finite radius and height.")
            shape = cq.Solid.makeCylinder(radius, height, Vector(0, -height / 2, 0), Vector(0, 1, 0))
        elif typ == "extrude":
            profile = geometry.get("profile")
            depth = float(geometry.get("depth", 0))
            if not isinstance(profile, list) or len(profile) < 3 or not math.isfinite(depth) or depth <= 0:
                raise CadQueryExportError(f"{name} has an invalid extrusion profile/depth.")
            points = []
            for i, point in enumerate(profile):
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise CadQueryExportError(f"{name}.profile[{i}] must be [x,z].")
                x, z = float(point[0]), float(point[1])
                if not math.isfinite(x) or not math.isfinite(z):
                    raise CadQueryExportError(f"{name}.profile[{i}] must be finite.")
                points.append(Vector(x, -depth / 2, z))
            outer = cq.Wire.makePolygon(points, close=True)
            shape = cq.Solid.extrudeLinear(outer, [], Vector(0, depth, 0))
        elif typ == "revolve":
            profile = geometry.get("profile")
            if not isinstance(profile, list) or len(profile) < 3:
                raise CadQueryExportError(f"{name} has an invalid revolve profile.")
            points = []
            for i, point in enumerate(profile):
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise CadQueryExportError(f"{name}.profile[{i}] must be [radius,y].")
                radius, y = float(point[0]), float(point[1])
                if not math.isfinite(radius) or not math.isfinite(y) or radius < 0:
                    raise CadQueryExportError(f"{name}.profile[{i}] must contain finite values and non-negative radius.")
                points.append(Vector(radius, y, 0))
            outer = cq.Wire.makePolygon(points, close=True)
            shape = cq.Solid.revolve(outer, [], 360.0, Vector(0, 0, 0), Vector(0, 1, 0))
        elif typ == "sweep":
            path = geometry.get("path")
            radius = float(geometry.get("radius", 0))
            if not isinstance(path, list) or len(path) < 2 or not math.isfinite(radius) or radius <= 0:
                raise CadQueryExportError(f"{name} has an invalid sweep path/radius.")
            points = [Vector(*_vec3(point, f"{name}.path[{i}]")) for i, point in enumerate(path)]
            tangent = points[1].sub(points[0])
            if tangent.Length < 1e-10:
                raise CadQueryExportError(f"{name} sweep starts with a zero-length segment.")
            spine = cq.Wire.makePolygon(points, close=False)
            profile = cq.Wire.makeCircle(radius, points[0], tangent.normalized())
            # 'round' transitions avoid near-zero solids at polyline corners.
            shape = cq.Solid.sweep(profile, [], spine, True, False, transitionMode="round")
        else:
            raise CadQueryExportError(f"Unsupported object type {typ!r} for CAD export.")
    except CadQueryExportError:
        raise
    except Exception as exc:
        raise CadQueryExportError(f"Could not construct B-rep for {name!r} ({typ}): {exc}") from exc

    transform = obj.get("transform", {})
    shape = _apply_transform(shape, transform, cq)
    try:
        valid = bool(shape.isValid())
        solids = shape.Solids()
        volume = float(shape.Volume())
    except Exception as exc:
        raise CadQueryExportError(f"OpenCascade failed to audit {name!r}: {exc}") from exc
    if not valid or not solids or not math.isfinite(volume) or volume <= 0:
        raise CadQueryExportError(
            f"OpenCascade returned an invalid/non-positive-volume body for {name!r}; no STEP was written."
        )
    return shape, volume, len(solids)


def build_brep_assembly(scene: dict[str, Any]):
    """Build a CadQuery assembly from validated M3L scene IR and return audit metadata."""
    cq = _cadquery()
    if not isinstance(scene, dict) or not isinstance(scene.get("objects"), list):
        raise CadQueryExportError("Scene IR must contain an objects array.")
    assembly = cq.Assembly(name=str(scene.get("name", "M3L scene")))
    reports = []
    material_table = scene.get("materials", {})
    for obj in scene.get("objects", []):
        if not isinstance(obj, dict):
            raise CadQueryExportError("Scene objects must be structured objects.")
        shape, volume, solid_count = _shape_for_object(obj, cq)
        material = material_table.get(obj.get("material", "default"), {})
        rgb = material.get("base_color", [0.72, 0.76, 0.8])
        try:
            color = cq.Color(*(max(0.0, min(1.0, float(v))) for v in rgb[:3]))
        except Exception:
            color = cq.Color(0.72, 0.76, 0.8)
        assembly.add(shape, name=obj["name"], color=color)
        reports.append({"object": obj["name"], "type": obj.get("type"), "valid": True,
                        "solid_count": solid_count, "volume_scene_units_cubed": volume,
                        "face_count": len(shape.Faces()), "edge_count": len(shape.Edges())})
    if not reports:
        raise CadQueryExportError("The scene has no objects to export.")
    return assembly, reports


def export_step(scene: dict[str, Any], path: str | Path, output_unit: str = "MM") -> dict[str, Any]:
    """Export M3L IR to a colored STEP assembly, validating each B-rep first.

    Coordinates are interpreted in the scene's declared unit. ``output_unit`` may be
    M, MM, CM, INCH or FT; the exporter converts the units in the STEP file.
    """
    cq = _cadquery()
    output_unit = str(output_unit).upper()
    if output_unit not in _ALLOWED_OUTPUT_UNITS:
        raise CadQueryExportError(f"Unsupported STEP output unit {output_unit!r}; use one of {sorted(_ALLOWED_OUTPUT_UNITS)}.")
    source_unit = _SCENE_TO_CQ_UNIT.get(scene.get("units", "m"))
    if not source_unit:
        raise CadQueryExportError(f"Unsupported M3L scene unit {scene.get('units')!r}.")
    assembly, reports = build_brep_assembly(scene)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        assembly.export(str(output_path), exportType="STEP", unit=source_unit, outputUnit=output_unit)
    except Exception as exc:
        raise CadQueryExportError(f"OpenCascade STEP export failed: {exc}") from exc
    if not output_path.is_file() or output_path.stat().st_size < 256:
        raise CadQueryExportError("OpenCascade did not produce a usable STEP file.")
    return {"path": str(output_path), "bytes": output_path.stat().st_size,
            "sha256": _sha256_file(output_path), "format": "STEP",
            "source_unit": source_unit, "output_unit": output_unit,
            "object_count": len(reports), "objects": reports,
            "kernel": f"CadQuery {cq.__version__} / OpenCascade"}


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
