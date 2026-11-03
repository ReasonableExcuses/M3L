"""Deterministic procedural mesh builders and topology checks for M3L.

Profiles are intentionally declarative data, never executable code. `extrude` profiles
use [x, z] pairs and thickness along Y. `revolve` profiles use [radius, y] pairs
and rotate around the Y axis.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

try:
    import m3l_core
    HAS_M3L_CORE = True
except ImportError:
    m3l_core = None  # type: ignore
    HAS_M3L_CORE = False

_EPS = 1e-9


def _cross2(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _area2(points: list[list[float]]) -> float:
    return sum(points[i][0] * points[(i + 1) % len(points)][1]
               - points[(i + 1) % len(points)][0] * points[i][1]
               for i in range(len(points))) / 2.0


def _on_segment(a, b, p) -> bool:
    return (min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS
            and abs(_cross2(a, b, p)) <= _EPS)


def _segments_intersect(a, b, c, d) -> bool:
    o1, o2, o3, o4 = _cross2(a, b, c), _cross2(a, b, d), _cross2(c, d, a), _cross2(c, d, b)
    if ((o1 > _EPS and o2 < -_EPS) or (o1 < -_EPS and o2 > _EPS)) and \
       ((o3 > _EPS and o4 < -_EPS) or (o3 < -_EPS and o4 > _EPS)):
        return True
    return ((abs(o1) <= _EPS and _on_segment(a, b, c)) or
            (abs(o2) <= _EPS and _on_segment(a, b, d)) or
            (abs(o3) <= _EPS and _on_segment(c, d, a)) or
            (abs(o4) <= _EPS and _on_segment(c, d, b)))


def validate_profile(profile: Any, *, nonnegative_x: bool = False) -> tuple[list[list[float]] | None, str | None]:
    """Validate a simple, non-degenerate 2D polygon profile."""
    if not isinstance(profile, list) or len(profile) < 3:
        return None, "profile must contain at least three [a, b] points."
    if len(profile) > 256:
        return None, "profile is capped at 256 points to keep LLM-generated meshes bounded."
    points: list[list[float]] = []
    for index, point in enumerate(profile):
        if not isinstance(point, list) or len(point) != 2:
            return None, f"profile point {index} must be a two-number array."
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in point):
            return None, f"profile point {index} must contain only finite numbers."
        x, y = float(point[0]), float(point[1])
        if abs(x) > 1_000_000 or abs(y) > 1_000_000:
            return None, f"profile point {index} exceeds the coordinate safety limit of 1,000,000 units."
        if nonnegative_x and x < 0:
            return None, f"profile point {index} has a negative radius; revolve radii must be >= 0."
        points.append([x, y])
    for i in range(len(points)):
        a, b = points[i], points[(i + 1) % len(points)]
        if math.dist(a, b) <= _EPS:
            return None, f"profile edge {i} has duplicate consecutive points."
    if abs(_area2(points)) <= _EPS:
        return None, "profile polygon has zero area."
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            # Adjacent edges share a vertex by design, including first/last.
            if j == i or j == (i + 1) % n or (j + 1) % n == i:
                continue
            c, d = points[j], points[(j + 1) % n]
            if _segments_intersect(a, b, c, d):
                return None, f"profile edges {i} and {j} intersect; profiles must be simple polygons."
    return points, None


def triangulate_polygon(points: list[list[float]]) -> list[list[int]]:
    """Ear-clip a simple polygon, preserving its input winding order."""
    if len(points) < 3:
        raise ValueError("A polygon needs at least three vertices.")
    orientation = 1.0 if _area2(points) > 0 else -1.0
    remaining = list(range(len(points)))
    triangles: list[list[int]] = []

    def in_triangle(p, a, b, c):
        c1 = orientation * _cross2(a, b, p)
        c2 = orientation * _cross2(b, c, p)
        c3 = orientation * _cross2(c, a, p)
        return c1 >= -_EPS and c2 >= -_EPS and c3 >= -_EPS

    guard = 0
    while len(remaining) > 3:
        found = False
        for k in range(len(remaining)):
            ia, ib, ic = remaining[k - 1], remaining[k], remaining[(k + 1) % len(remaining)]
            a, b, c = points[ia], points[ib], points[ic]
            if orientation * _cross2(a, b, c) <= _EPS:
                continue
            if any(in_triangle(points[q], a, b, c) for q in remaining if q not in (ia, ib, ic)):
                continue
            triangles.append([ia, ib, ic])
            del remaining[k]
            found = True
            break
        guard += 1
        if not found or guard > len(points) * len(points):
            raise ValueError("Could not triangulate profile; check for self-intersections or near-collinear edges.")
    triangles.append(remaining[:])
    return triangles


def _unit_normal(a, b, c) -> list[float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= _EPS:
        return [0.0, 1.0, 0.0]
    return [nx / length, ny / length, nz / length]


def _flat_render_mesh(vertices: list[list[float]], triangles: list[list[int]]) -> dict[str, Any]:
    render_vertices: list[list[float]] = []
    render_normals: list[list[float]] = []
    render_indices: list[int] = []
    for tri in triangles:
        a, b, c = (vertices[i] for i in tri)
        normal = _unit_normal(a, b, c)
        base = len(render_vertices)
        render_vertices.extend([list(a), list(b), list(c)])
        render_normals.extend([normal, normal, normal])
        render_indices.extend([base, base + 1, base + 2])
    return {"vertices": vertices, "triangles": triangles,
            "render_vertices": render_vertices, "render_normals": render_normals,
            "render_indices": render_indices, "shading": "flat"}


def _smooth_normals(vertices: list[list[float]], triangles: list[list[int]]) -> list[list[float]]:
    if HAS_M3L_CORE and vertices and triangles:
        try:
            return m3l_core.compute_normals(vertices, triangles)
        except Exception:
            pass
    normals = [[0.0, 0.0, 0.0] for _ in vertices]
    for tri in triangles:
        a, b, c = (vertices[i] for i in tri)
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]
        if sum(v * v for v in n) <= _EPS * _EPS:
            continue
        for index in tri:
            for axis in range(3):
                normals[index][axis] += n[axis]
    out = []
    for normal in normals:
        length = math.sqrt(sum(v * v for v in normal))
        out.append([v / length for v in normal] if length > _EPS else [0.0, 1.0, 0.0])
    return out


def _unique_triangles(vertices: list[list[float]], triangles: list[list[int]]) -> list[list[int]]:
    out = []
    for tri in triangles:
        if len(set(tri)) < 3:
            continue
        a, b, c = (vertices[i] for i in tri)
        if math.dist(a, b) <= _EPS or math.dist(b, c) <= _EPS or math.dist(c, a) <= _EPS:
            continue
        normal = _unit_normal(a, b, c)
        if sum(v * v for v in normal) < 0.5:
            continue
        out.append(tri)
    return out


def _validate_mesh_payload(mesh: dict[str, Any] | None) -> tuple[list[list[float]], list[list[int]] | None]:
    if not isinstance(mesh, dict):
        return [], None
    vertices = mesh.get("vertices")
    triangles = mesh.get("triangles")
    if not isinstance(vertices, list) or not isinstance(triangles, list):
        return [], None
    safe_vertices: list[list[float]] = []
    for v in vertices:
        if not isinstance(v, (list, tuple)) or len(v) != 3:
            return [], None
        safe_v = []
        for axis in v:
            if isinstance(axis, bool) or not isinstance(axis, (int, float)) or not math.isfinite(float(axis)):
                return [], None
            safe_v.append(float(axis))
        safe_vertices.append(safe_v)
    safe_triangles: list[list[int]] = []
    for tri in triangles:
        if not isinstance(tri, (list, tuple)) or len(tri) != 3:
            continue
        if any(not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(safe_vertices) for i in tri):
            continue
        if len(set(tri)) < 3:
            continue
        safe_triangles.append([int(i) for i in tri])
    if not safe_vertices or not safe_triangles:
        return [], None
    return safe_vertices, safe_triangles


def mesh_quality_summary(mesh: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact quality summary for a triangle mesh.

    This intentionally measures geometric cleanliness and detail density rather than
    artistic quality. It is meant to support repair loops and asset quality grading.
    """
    if not isinstance(mesh, dict):
        return {"quality_score": 0.0, "silhouette_score": 0.0, "triangle_count": 0, "vertex_count": 0,
                "normal_consistency": 0.0, "detail_density": 0.0, "surface_status": "missing"}
    vertices, triangles = _validate_mesh_payload(mesh)
    if not triangles or not vertices:
        return {"quality_score": 0.0, "silhouette_score": 0.0, "triangle_count": 0, "vertex_count": 0,
                "normal_consistency": 0.0, "detail_density": 0.0, "surface_status": "invalid"}

    triangle_count = len(triangles)
    vertex_count = len(vertices)
    face_normals: list[list[float]] = []
    edge_lengths: list[float] = []
    boundary_edges = 0
    edge_counts: Counter[tuple[int, int]] = Counter()
    for tri in triangles:
        a, b, c = (vertices[i] for i in tri)
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length <= _EPS:
            continue
        face_normals.append([nx / length, ny / length, nz / length])
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted(edge))
            edge_counts[key] += 1
            edge_lengths.append(math.dist(vertices[edge[0]], vertices[edge[1]]))

    if not face_normals:
        return {"quality_score": 0.0, "silhouette_score": 0.0, "triangle_count": triangle_count, "vertex_count": vertex_count,
                "normal_consistency": 0.0, "detail_density": 0.0, "surface_status": "degenerate"}

    normal_dots: list[float] = []
    for i in range(1, len(face_normals)):
        dot_value = abs(sum(face_normals[i][k] * face_normals[i - 1][k] for k in range(3)))
        normal_dots.append(max(0.0, min(1.0, dot_value)))
    normal_consistency = sum(normal_dots) / len(normal_dots) if normal_dots else 0.95
    if edge_lengths:
        avg_edge = sum(edge_lengths) / len(edge_lengths)
        detail_density = max(0.0, min(1.0, 1.0 / (1.0 + avg_edge * 0.85)))
    else:
        detail_density = 0.5
    boundary_edges = sum(1 for count in edge_counts.values() if count == 1)
    total_edges = sum(edge_counts.values())
    boundary_ratio = boundary_edges / total_edges if total_edges else 0.0
    silhouette_score = max(0.0, min(1.0, 0.65 * normal_consistency + 0.35 * (1.0 - boundary_ratio)))
    quality_score = 0.55 * normal_consistency + 0.30 * silhouette_score + 0.15 * detail_density
    quality_score = max(0.0, min(1.0, quality_score))
    surface_status = "clean" if quality_score >= 0.75 else "needs_refinement" if quality_score >= 0.4 else "rough"
    return {"quality_score": round(quality_score, 4), "silhouette_score": round(silhouette_score, 4),
            "triangle_count": triangle_count, "vertex_count": vertex_count, "normal_consistency": round(normal_consistency, 4),
            "detail_density": round(detail_density, 4), "boundary_edges": boundary_edges, "surface_status": surface_status}


def beautify_mesh(mesh: dict[str, Any], smoothness: float = 1.0) -> dict[str, Any]:
    """Apply a lightweight smoothing pass to a mesh's render normals and attach quality metadata."""
    if not isinstance(mesh, dict):
        raise ValueError("beautify_mesh expects a mesh dictionary")
    vertices, triangles = _validate_mesh_payload(mesh)
    if not vertices or not triangles:
        raise ValueError("mesh must contain valid vertices and triangles")
    smoothness = max(0.0, min(1.0, float(smoothness)))
    mesh = dict(mesh)
    mesh["vertices"] = vertices
    mesh["triangles"] = triangles
    if not mesh.get("render_normals"):
        normals = _smooth_normals(vertices, triangles)
        if smoothness < 1.0:
            base = [0.0, 1.0, 0.0]
            normals = [[base[i] + (value - base[i]) * smoothness for i, value in enumerate(normal)] for normal in normals]
        mesh["render_normals"] = normals
    mesh["shading"] = "smooth"
    quality = mesh_quality_summary(mesh)
    mesh["quality"] = quality
    mesh["beauty_score"] = quality["quality_score"]
    return mesh


def build_extrusion(profile: list[list[float]], depth: float) -> dict[str, Any]:
    """Build a closed Y-axis extrusion from an X/Z polygon."""
    n = len(profile)
    bottom_y, top_y = -float(depth) / 2.0, float(depth) / 2.0
    vertices = [[p[0], bottom_y, p[1]] for p in profile] + [[p[0], top_y, p[1]] for p in profile]
    area_positive = _area2(profile) > 0
    caps = triangulate_polygon(profile)
    triangles: list[list[int]] = []
    # For a CCW X/Z profile, the same 3D winding points down (-Y).
    for tri in caps:
        lower, upper = list(tri), [i + n for i in tri]
        triangles.append(lower if area_positive else list(reversed(lower)))
        triangles.append(list(reversed(upper)) if area_positive else upper)
    # Build each side quad. Raw winding is inward for positive-area X/Z outlines.
    for i in range(n):
        j = (i + 1) % n
        a, b, c, d = i, j, j + n, i + n
        side = [[a, b, c], [a, c, d]]
        if area_positive:
            side = [[a, c, b], [a, d, c]]
        triangles.extend(side)
    triangles = _unique_triangles(vertices, triangles)
    return _flat_render_mesh(vertices, triangles)


def build_revolve(profile: list[list[float]], segments: int) -> dict[str, Any]:
    """Revolve a closed [radius, y] cross-section about the Y axis."""
    segments = int(segments)
    vertices: list[list[float]] = []
    ring_index: dict[tuple[int, int], int] = {}
    axis_index: dict[int, int] = {}
    for i, (radius, y) in enumerate(profile):
        if abs(radius) <= _EPS:
            axis_index[i] = len(vertices)
            vertices.append([0.0, float(y), 0.0])
        else:
            for j in range(segments):
                angle = 2.0 * math.pi * j / segments
                ring_index[(i, j)] = len(vertices)
                vertices.append([float(radius) * math.cos(angle), float(y), float(radius) * math.sin(angle)])

    def ix(profile_index: int, angle_index: int) -> int:
        if profile_index in axis_index:
            return axis_index[profile_index]
        return ring_index[(profile_index, angle_index % segments)]

    area_positive = _area2(profile) > 0
    triangles: list[list[int]] = []
    n = len(profile)
    for i in range(n):
        k = (i + 1) % n
        for j in range(segments):
            jp = (j + 1) % segments
            a, b, c, d = ix(i, j), ix(k, j), ix(k, jp), ix(i, jp)
            quad = [[a, b, c], [a, c, d]]
            if not area_positive:
                quad = [[a, c, b], [a, d, c]]
            triangles.extend(quad)
    triangles = _unique_triangles(vertices, triangles)
    normals = _smooth_normals(vertices, triangles)
    return {"vertices": vertices, "triangles": triangles,
            "render_vertices": [list(v) for v in vertices], "render_normals": normals,
            "render_indices": [i for tri in triangles for i in tri], "shading": "smooth"}


def audit_mesh(mesh: dict[str, Any] | None) -> dict[str, Any]:
    """Topology audit on the indexed analytical mesh, not a visual-quality score."""
    if not isinstance(mesh, dict):
        return {"valid": False, "watertight": False, "reason": "No mesh payload."}
    vertices = mesh.get("vertices")
    triangles = mesh.get("triangles")
    if not isinstance(vertices, list) or not vertices or not isinstance(triangles, list) or not triangles:
        return {"valid": False, "watertight": False, "reason": "Mesh needs vertices and triangles."}
    finite = all(isinstance(v, list) and len(v) == 3 and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x)) for x in v)
        for v in vertices)
    if not finite:
        return {"valid": False, "watertight": False, "reason": "Vertex data contains invalid coordinates."}
    bad_indices = 0
    degenerate = 0
    edge_counts: Counter[tuple[int, int]] = Counter()
    edge_directions: dict[tuple[int, int], list[int]] = {}
    signed_volume = 0.0
    for tri in triangles:
        if (not isinstance(tri, list) or len(tri) != 3 or any(
            not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(vertices) for i in tri)):
            bad_indices += 1
            continue
        a, b, c = (vertices[i] for i in tri)
        cross = _unit_normal(a, b, c)
        if len(set(tri)) < 3 or math.dist(a, b) <= _EPS or math.dist(b, c) <= _EPS or math.dist(c, a) <= _EPS:
            degenerate += 1
        # Signed volume contribution for a closed triangle mesh.
        signed_volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                          + a[1] * (b[2] * c[0] - b[0] * c[2])
                          + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted(edge))
            edge_counts[key] += 1
            edge_directions.setdefault(key, []).append(1 if edge[0] < edge[1] else -1)
    boundary = sum(count == 1 for count in edge_counts.values())
    nonmanifold = sum(count > 2 or count == 0 for count in edge_counts.values())
    invalid_edge_use = sum(count != 2 for count in edge_counts.values())
    inconsistent_winding = sum(1 for edge, count in edge_counts.items()
                               if count == 2 and sum(edge_directions.get(edge, [])) != 0)
    valid = bad_indices == 0 and degenerate == 0 and bool(triangles)
    watertight = valid and invalid_edge_use == 0 and inconsistent_winding == 0 and abs(signed_volume) > _EPS
    return {"valid": valid, "watertight": watertight, "vertex_count": len(vertices),
            "triangle_count": len(triangles), "boundary_edges": boundary,
            "nonmanifold_edges": nonmanifold, "edges_not_used_twice": invalid_edge_use,
            "inconsistent_winding_edges": inconsistent_winding,
            "degenerate_triangles": degenerate, "invalid_triangles": bad_indices,
            "signed_volume": round(signed_volume, 9), "absolute_volume": round(abs(signed_volume), 9),
            "shading": mesh.get("shading", "unspecified"),
            "reason": None if watertight else "Mesh is invalid or not a closed, consistently usable solid."}


def validate_path(path: Any) -> tuple[list[list[float]] | None, str | None]:
    """Validate an open polyline used as a sweep centerline."""
    if not isinstance(path, list) or len(path) < 2:
        return None, "path must contain at least two [x, y, z] points."
    if len(path) > 256:
        return None, "path is capped at 256 points to keep generated tubes bounded."
    points: list[list[float]] = []
    for index, point in enumerate(path):
        if not isinstance(point, list) or len(point) != 3:
            return None, f"path point {index} must be a three-number array."
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in point):
            return None, f"path point {index} must contain only finite numbers."
        if any(abs(float(v)) > 1_000_000 for v in point):
            return None, f"path point {index} exceeds the coordinate safety limit of 1,000,000 units."
        points.append([float(v) for v in point])
    for index in range(len(points) - 1):
        if math.dist(points[index], points[index + 1]) <= _EPS:
            return None, f"path segment {index} has duplicate consecutive points."
    return points, None


def _dot(a: list[float], b: list[float]) -> float:
    return sum(a[i] * b[i] for i in range(3))


def _sub(a: list[float], b: list[float]) -> list[float]:
    return [a[i] - b[i] for i in range(3)]


def _cross3(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit3(v: list[float]) -> list[float]:
    length = math.sqrt(_dot(v, v))
    if length <= _EPS:
        raise ValueError("Cannot normalize a zero-length vector.")
    return [x / length for x in v]


def build_sweep(path: list[list[float]], radius: float, segments: int) -> dict[str, Any]:
    """Build a capped constant-radius tube along an open polyline using transported frames."""
    segments = int(segments)
    tangents: list[list[float]] = []
    for i in range(len(path)):
        if i == 0:
            delta = _sub(path[1], path[0])
        elif i == len(path) - 1:
            delta = _sub(path[-1], path[-2])
        else:
            delta = _sub(path[i + 1], path[i - 1])
            if math.sqrt(_dot(delta, delta)) <= _EPS:
                delta = _sub(path[i + 1], path[i])
        tangents.append(_unit3(delta))

    # Start with a basis axis least parallel to the tangent; then parallel-transport
    # the previous normal by projection, minimizing unwanted twist along the path.
    reference_axes = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
    reference = min(reference_axes, key=lambda axis: abs(_dot(axis, tangents[0])))
    normal = _unit3(_cross3(reference, tangents[0]))
    frames: list[tuple[list[float], list[float]]] = []
    for i, tangent in enumerate(tangents):
        if i > 0:
            previous_normal = frames[-1][0]
            projection = [previous_normal[k] - _dot(previous_normal, tangent) * tangent[k] for k in range(3)]
            if math.sqrt(_dot(projection, projection)) <= _EPS:
                reference = min(reference_axes, key=lambda axis: abs(_dot(axis, tangent)))
                projection = _cross3(reference, tangent)
            normal = _unit3(projection)
        binormal = _unit3(_cross3(normal, tangent))
        frames.append((normal, binormal))

    vertices: list[list[float]] = []
    ring_count = len(path)
    for i, point in enumerate(path):
        n, b = frames[i]
        for j in range(segments):
            theta = 2.0 * math.pi * j / segments
            co, si = math.cos(theta), math.sin(theta)
            vertices.append([point[k] + float(radius) * (co * n[k] + si * b[k]) for k in range(3)])
    start_center = len(vertices)
    vertices.append(list(path[0]))
    end_center = len(vertices)
    vertices.append(list(path[-1]))

    triangles: list[list[int]] = []
    for i in range(ring_count - 1):
        for j in range(segments):
            jp = (j + 1) % segments
            a = i * segments + j
            b = (i + 1) * segments + j
            c = (i + 1) * segments + jp
            d = i * segments + jp
            triangles.extend([[a, b, c], [a, c, d]])
    for j in range(segments):
        jp = (j + 1) % segments
        triangles.append([start_center, j, jp])
        end_base = (ring_count - 1) * segments
        triangles.append([end_center, end_base + jp, end_base + j])
    triangles = _unique_triangles(vertices, triangles)
    vol = 0.0
    for a, b, c in triangles:
        p0, p1, p2 = vertices[a], vertices[b], vertices[c]
        v321 = p2[0]*p1[1]*p0[2]
        v231 = p1[0]*p2[1]*p0[2]
        v312 = p2[0]*p0[1]*p1[2]
        v132 = p0[0]*p2[1]*p1[2]
        v213 = p1[0]*p0[1]*p2[2]
        v123 = p0[0]*p1[1]*p2[2]
        vol += (1.0 / 6.0) * (-v321 + v231 + v312 - v132 - v213 + v123)
    if vol < 0:
        triangles = [[t[0], t[2], t[1]] for t in triangles]

    normals = _smooth_normals(vertices, triangles)
    return {"vertices": vertices, "triangles": triangles,
            "render_vertices": [list(v) for v in vertices], "render_normals": normals,
            "render_indices": [i for tri in triangles for i in tri], "shading": "smooth"}


def validate_loft_sections(raw_sections: Any) -> tuple[list[list[list[float]]] | None, str | None]:
    """Validate loft section data into a list of 3D rings."""
    if not isinstance(raw_sections, list) or len(raw_sections) < 2:
        return None, "loft requires at least two cross-section profiles."
    if len(raw_sections) > 512:
        return None, "loft sections capped at 512."

    rings: list[list[list[float]]] = []
    for s_idx, sec in enumerate(raw_sections):
        if not isinstance(sec, list) or len(sec) < 3:
            return None, f"loft section {s_idx} must contain at least 3 values."
        # Format 1: flat list of numbers [axis_coord, u0, v0, u1, v1, ...]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) for v in sec):
            if len(sec) % 2 == 1 and len(sec) >= 7:
                x = float(sec[0])
                ring = [[x, float(sec[j]), float(sec[j + 1])] for j in range(1, len(sec), 2)]
                rings.append(ring)
            elif len(sec) % 3 == 0 and len(sec) >= 9:
                ring = [[float(sec[j]), float(sec[j + 1]), float(sec[j + 2])] for j in range(0, len(sec), 3)]
                rings.append(ring)
            else:
                return None, f"loft section {s_idx} flat array must have odd length >= 7 (axis + pairs) or multiple of 3 (triplets)."
        # Format 2: list of 3D points [[x, y, z], ...]
        elif all(isinstance(pt, list) and len(pt) == 3 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) for v in pt) for pt in sec):
            rings.append([[float(v) for v in pt] for pt in sec])
        else:
            return None, f"loft section {s_idx} has invalid point format."
    return rings, None


def _resample_ring(pts: list[list[float]], target_count: int) -> list[list[float]]:
    """Resample a closed 3D polygon ring to target_count equidistant points via arc-length."""
    if len(pts) == target_count:
        return [list(p) for p in pts]
    dists = [0.0]
    for i in range(len(pts)):
        p1 = pts[i]
        p2 = pts[(i + 1) % len(pts)]
        dists.append(dists[-1] + math.dist(p1, p2))
    total = dists[-1]
    if total <= _EPS:
        return [list(pts[0]) for _ in range(target_count)]
    res = []
    seg = 0
    for i in range(target_count):
        target = (i / target_count) * total
        while seg < len(pts) - 1 and dists[seg + 1] < target:
            seg += 1
        seg_len = dists[seg + 1] - dists[seg]
        t = 0.0 if seg_len <= _EPS else (target - dists[seg]) / seg_len
        p1 = pts[seg % len(pts)]
        p2 = pts[(seg + 1) % len(pts)]
        res.append([p1[k] + t * (p2[k] - p1[k]) for k in range(3)])
    return res


def build_loft(rings: list[list[list[float]]], subdivisions: int | None = None) -> dict[str, Any]:
    """Build a watertight loft mesh connecting multiple cross-section rings."""
    counts = [len(r) for r in rings]
    target_n = counts[0] if len(set(counts)) == 1 else max(max(counts), 32)
    normalized_rings = [_resample_ring(r, target_n) for r in rings]

    vertices: list[list[float]] = []
    for r in normalized_rings:
        vertices.extend(r)

    N = target_n
    M = len(normalized_rings)
    triangles: list[list[int]] = []

    # Connect adjacent rings with quad strips
    for i in range(M - 1):
        for k in range(N):
            kn = (k + 1) % N
            p0 = i * N + k
            p1 = (i + 1) * N + k
            p2 = (i + 1) * N + kn
            p3 = i * N + kn
            triangles.append([p0, p1, p2])
            triangles.append([p0, p2, p3])

    # End cap for Ring 0
    ring0 = normalized_rings[0]
    ring0_span = [max(p[k] for p in ring0) - min(p[k] for p in ring0) for k in range(3)]
    if max(ring0_span) > _EPS:
        dims = sorted(range(3), key=lambda k: ring0_span[k], reverse=True)[:2]
        poly0 = [[p[dims[0]], p[dims[1]]] for p in ring0]
        try:
            cap0 = triangulate_polygon(poly0)
            edges_fwd = sum(1 for t in cap0 for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])) if (a + 1) % N == b)
            edges_bwd = sum(1 for t in cap0 for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])) if (b + 1) % N == a)
            reverse_cap0 = edges_fwd < edges_bwd
            for tri in cap0:
                if reverse_cap0:
                    triangles.append([tri[0], tri[2], tri[1]])
                else:
                    triangles.append([tri[0], tri[1], tri[2]])
        except Exception:
            pass

    # End cap for Ring M-1
    ring_end = normalized_rings[-1]
    ring_end_span = [max(p[k] for p in ring_end) - min(p[k] for p in ring_end) for k in range(3)]
    if max(ring_end_span) > _EPS:
        dims = sorted(range(3), key=lambda k: ring_end_span[k], reverse=True)[:2]
        poly_end = [[p[dims[0]], p[dims[1]]] for p in ring_end]
        try:
            cap_end = triangulate_polygon(poly_end)
            edges_fwd = sum(1 for t in cap_end for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])) if (a + 1) % N == b)
            edges_bwd = sum(1 for t in cap_end for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])) if (b + 1) % N == a)
            reverse_cap_end = edges_fwd > edges_bwd
            offset = (M - 1) * N
            for tri in cap_end:
                if reverse_cap_end:
                    triangles.append([offset + tri[0], offset + tri[2], offset + tri[1]])
                else:
                    triangles.append([offset + tri[0], offset + tri[1], offset + tri[2]])
        except Exception:
            pass

    vol = 0.0
    for a, b, c in triangles:
        p0, p1, p2 = vertices[a], vertices[b], vertices[c]
        v321 = p2[0]*p1[1]*p0[2]
        v231 = p1[0]*p2[1]*p0[2]
        v312 = p2[0]*p0[1]*p1[2]
        v132 = p0[0]*p2[1]*p1[2]
        v213 = p1[0]*p0[1]*p2[2]
        v123 = p0[0]*p1[1]*p2[2]
        vol += (1.0 / 6.0) * (-v321 + v231 + v312 - v132 - v213 + v123)
    if vol < 0:
        triangles = [[t[0], t[2], t[1]] for t in triangles]

    normals = _smooth_normals(vertices, triangles)
    return {"vertices": vertices, "triangles": triangles,
            "render_vertices": [list(v) for v in vertices], "render_normals": normals,
            "render_indices": [i for tri in triangles for i in tri], "shading": "smooth"}


def build_cone(radius_bottom: float, radius_top: float, height: float, segments: int = 24) -> dict[str, Any]:
    """Build a watertight cone or frustum solid centered along Y."""
    segments = max(6, min(int(segments), 256))
    r_bot, r_top, h = float(radius_bottom), float(radius_top), float(height)
    y_bot, y_top = -h / 2.0, h / 2.0
    verts: list[list[float]] = []
    triangles: list[list[int]] = []

    has_bot_disk = r_bot > 1e-6
    has_top_disk = r_top > 1e-6

    if has_bot_disk and has_top_disk:
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            verts.append([r_bot * math.cos(a), y_bot, r_bot * math.sin(a)])
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            verts.append([r_top * math.cos(a), y_top, r_top * math.sin(a)])
        for i in range(segments):
            ni = (i + 1) % segments
            b0, b1 = i, ni
            t0, t1 = segments + i, segments + ni
            triangles.append([b0, t0, b1])
            triangles.append([t0, t1, b1])
        c_bot = len(verts)
        verts.append([0.0, y_bot, 0.0])
        for i in range(segments):
            ni = (i + 1) % segments
            triangles.append([c_bot, i, ni])
        c_top = len(verts)
        verts.append([0.0, y_top, 0.0])
        for i in range(segments):
            ni = (i + 1) % segments
            triangles.append([c_top, segments + ni, segments + i])
    elif has_bot_disk and not has_top_disk:
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            verts.append([r_bot * math.cos(a), y_bot, r_bot * math.sin(a)])
        apex = len(verts)
        verts.append([0.0, y_top, 0.0])
        for i in range(segments):
            ni = (i + 1) % segments
            triangles.append([i, apex, ni])
        c_bot = len(verts)
        verts.append([0.0, y_bot, 0.0])
        for i in range(segments):
            ni = (i + 1) % segments
            triangles.append([c_bot, i, ni])
    else:
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            verts.append([r_top * math.cos(a), y_top, r_top * math.sin(a)])
        apex = len(verts)
        verts.append([0.0, y_bot, 0.0])
        for i in range(segments):
            ni = (i + 1) % segments
            triangles.append([apex, i, ni])
        c_top = len(verts)
        verts.append([0.0, y_top, 0.0])
        for i in range(segments):
            ni = (i + 1) % segments
            triangles.append([c_top, ni, i])

    normals = _smooth_normals(verts, triangles)
    return {"vertices": verts, "triangles": triangles,
            "render_vertices": [list(v) for v in verts], "render_normals": normals,
            "render_indices": [i for tri in triangles for i in tri], "shading": "smooth"}


def build_torus(major_radius: float, minor_radius: float, segments: int = 36, rings: int = 24) -> dict[str, Any]:
    """Build a watertight donut-shaped torus around the Y axis."""
    segments = max(6, min(int(segments), 256))
    rings = max(4, min(int(rings), 128))
    major_r, minor_r = float(major_radius), float(minor_radius)
    verts: list[list[float]] = []
    for i in range(segments):
        phi = 2.0 * math.pi * i / segments
        cp, sp = math.cos(phi), math.sin(phi)
        for j in range(rings):
            theta = 2.0 * math.pi * j / rings
            ct, st = math.cos(theta), math.sin(theta)
            verts.append([(major_r + minor_r * ct) * cp, minor_r * st, (major_r + minor_r * ct) * sp])
    triangles: list[list[int]] = []
    for i in range(segments):
        ni = (i + 1) % segments
        for j in range(rings):
            nj = (j + 1) % rings
            p0 = i * rings + j
            p1 = ni * rings + j
            p2 = ni * rings + nj
            p3 = i * rings + nj
            triangles.append([p0, p2, p1])
            triangles.append([p0, p3, p2])
    normals = _smooth_normals(verts, triangles)
    return {"vertices": verts, "triangles": triangles,
            "render_vertices": [list(v) for v in verts], "render_normals": normals,
            "render_indices": [i for tri in triangles for i in tri], "shading": "smooth"}


def evaluate_spline(control_points: list[list[float]], spline_type: str = "catmull_rom", samples: int = 48) -> list[list[float]]:
    samples = max(4, min(int(samples), 512))
    pts = [[float(v) for v in p] for p in control_points]
    n = len(pts)
    if n < 2:
        raise ValueError("Spline requires at least 2 control points.")
    if n == 2:
        return [
            [pts[0][k] + (t / (samples - 1)) * (pts[1][k] - pts[0][k]) for k in range(3)]
            for t in range(samples)
        ]

    spline_type = spline_type.lower()
    out: list[list[float]] = []

    if spline_type == "catmull_rom":
        p_ext = [
            [2 * pts[0][k] - pts[1][k] for k in range(3)]
        ] + pts + [
            [2 * pts[-1][k] - pts[-2][k] for k in range(3)]
        ]
        num_segments = n - 1
        samples_per_seg = max(2, samples // num_segments)
        for seg in range(num_segments):
            p0, p1, p2, p3 = p_ext[seg], p_ext[seg + 1], p_ext[seg + 2], p_ext[seg + 3]
            start_idx = 0 if seg == 0 else 1
            for s in range(start_idx, samples_per_seg + 1):
                t = s / samples_per_seg
                t2 = t * t
                t3 = t2 * t
                pt = [
                    0.5 * ((2.0 * p1[k]) +
                           (-p0[k] + p2[k]) * t +
                           (2.0 * p0[k] - 5.0 * p1[k] + 4.0 * p2[k] - p3[k]) * t2 +
                           (-p0[k] + 3.0 * p1[k] - 3.0 * p2[k] + p3[k]) * t3)
                    for k in range(3)
                ]
                out.append(pt)
        return out

    elif spline_type == "cubic_bezier":
        if n == 4:
            for s in range(samples):
                t = s / (samples - 1)
                u = 1.0 - t
                pt = [
                    (u**3) * pts[0][k] +
                    3.0 * (u**2) * t * pts[1][k] +
                    3.0 * u * (t**2) * pts[2][k] +
                    (t**3) * pts[3][k]
                    for k in range(3)
                ]
                out.append(pt)
            return out
        else:
            num_beziers = (n - 1) // 3
            if num_beziers > 0 and (n - 1) % 3 == 0:
                samples_per_seg = max(2, samples // num_beziers)
                for b_idx in range(num_beziers):
                    base = b_idx * 3
                    b0, b1, b2, b3 = pts[base], pts[base + 1], pts[base + 2], pts[base + 3]
                    start_s = 0 if b_idx == 0 else 1
                    for s in range(start_s, samples_per_seg + 1):
                        t = s / samples_per_seg
                        u = 1.0 - t
                        pt = [
                            (u**3) * b0[k] +
                            3.0 * (u**2) * t * b1[k] +
                            3.0 * u * (t**2) * b2[k] +
                            (t**3) * b3[k]
                            for k in range(3)
                        ]
                        out.append(pt)
                return out
            else:
                for s in range(samples):
                    t = s / (samples - 1)
                    pt = [0.0, 0.0, 0.0]
                    for i in range(n):
                        coeff = math.comb(n - 1, i) * ((1.0 - t) ** (n - 1 - i)) * (t ** i)
                        for k in range(3):
                            pt[k] += coeff * pts[i][k]
                    out.append(pt)
                return out

    elif spline_type == "b_spline":
        if n < 4:
            return evaluate_spline(control_points, "catmull_rom", samples)
        p_ext = [pts[0], pts[0]] + pts + [pts[-1], pts[-1]]
        num_segments = len(p_ext) - 3
        samples_per_seg = max(2, samples // num_segments)
        for seg in range(num_segments):
            p0, p1, p2, p3 = p_ext[seg], p_ext[seg + 1], p_ext[seg + 2], p_ext[seg + 3]
            start_idx = 0 if seg == 0 else 1
            for s in range(start_idx, samples_per_seg + 1):
                t = s / samples_per_seg
                t2 = t * t
                t3 = t2 * t
                pt = [
                    (1.0 / 6.0) * (
                        (-p0[k] + 3.0 * p1[k] - 3.0 * p2[k] + p3[k]) * t3 +
                        (3.0 * p0[k] - 6.0 * p1[k] + 3.0 * p2[k]) * t2 +
                        (-3.0 * p0[k] + 3.0 * p2[k]) * t +
                        (p0[k] + 4.0 * p1[k] + p2[k])
                    )
                    for k in range(3)
                ]
                out.append(pt)
        return out
    else:
        raise ValueError(f"Unknown spline_type {spline_type!r}.")


def build_filleted_box(size: list[float], fillet: float, segments: int = 4) -> dict[str, Any]:
    """Build an analytically watertight filleted box with smooth rounded edges and corners."""
    W, H, D = [float(v) for v in size]
    R = min(float(fillet), min(W, H, D) / 2.0 - 1e-4)
    R = max(0.0, R)
    wx, wy, wz = W / 2.0 - R, H / 2.0 - R, D / 2.0 - R

    segments = max(2, min(int(segments), 32))
    knots = []
    for s in range(segments + 1):
        th = math.pi + (math.pi / 2.0) * (s / segments)
        knots.append((-1.0, math.cos(th), math.sin(th)))
    for s in range(segments + 1):
        th = 1.5 * math.pi + (math.pi / 2.0) * (s / segments)
        knots.append((1.0, math.cos(th), math.sin(th)))

    K = len(knots)

    def eval_coord(knot, half_inner):
        inner_sign, n_val, _ = knot
        return inner_sign * half_inner + R * n_val

    faces = [
        (0, 1, 2,  1.0), # +Z
        (0, 1, 2, -1.0), # -Z
        (2, 1, 0,  1.0), # +X
        (2, 1, 0, -1.0), # -X
        (0, 2, 1,  1.0), # +Y
        (0, 2, 1, -1.0), # -Y
    ]

    spans = [wx, wy, wz]
    all_verts = []
    all_tris = []

    vert_map = {}
    def get_vertex(p):
        q = (round(p[0], 6), round(p[1], 6), round(p[2], 6))
        if q not in vert_map:
            vert_map[q] = len(all_verts)
            all_verts.append([q[0], q[1], q[2]])
        return vert_map[q]

    for u_ax, v_ax, n_ax, n_sign in faces:
        u_span = spans[u_ax]
        v_span = spans[v_ax]
        n_span = spans[n_ax]

        grid = []
        for v_idx in range(K):
            row = []
            vk = knots[v_idx]
            v_val = eval_coord(vk, v_span)
            v_norm = vk[1]

            for u_idx in range(K):
                uk = knots[u_idx]
                u_val = eval_coord(uk, u_span)
                u_norm = uk[1]

                u_corner = uk[0] * u_span
                v_corner = vk[0] * v_span
                n_corner = n_sign * n_span

                nx = u_norm
                ny = v_norm
                nz = 1.0

                l = math.sqrt(nx*nx + ny*ny + nz*nz)
                d_u = (nx / l) * R
                d_v = (ny / l) * R
                d_n = (nz / l) * R * n_sign

                pos = [0.0, 0.0, 0.0]
                pos[u_ax] = u_corner + d_u
                pos[v_ax] = v_corner + d_v
                pos[n_ax] = n_corner + d_n

                row.append(get_vertex(pos))
            grid.append(row)

        for i in range(K - 1):
            for j in range(K - 1):
                p00 = grid[i][j]
                p10 = grid[i + 1][j]
                p11 = grid[i + 1][j + 1]
                p01 = grid[i][j + 1]

                for tri in ([p00, p10, p11], [p00, p11, p01]):
                    v0 = all_verts[tri[0]]
                    v1 = all_verts[tri[1]]
                    v2 = all_verts[tri[2]]
                    e1 = [v1[k] - v0[k] for k in range(3)]
                    e2 = [v2[k] - v0[k] for k in range(3)]
                    n = [e1[1]*e2[2] - e1[2]*e2[1], e1[2]*e2[0] - e1[0]*e2[2], e1[0]*e2[1] - e1[1]*e2[0]]
                    c = [v0[k] + v1[k] + v2[k] for k in range(3)]
                    if sum(n[k]*c[k] for k in range(3)) < 0:
                        all_tris.append([tri[0], tri[2], tri[1]])
                    else:
                        all_tris.append(tri)

    normals = _smooth_normals(all_verts, all_tris)
    return {"vertices": all_verts, "triangles": all_tris,
            "render_vertices": all_verts, "render_normals": normals,
            "render_indices": [i for t in all_tris for i in t], "shading": "smooth"}


def build_box(size: list[float]) -> dict[str, Any]:
    """Watertight 8-vertex, 12-triangle box centered at origin."""
    sx, sy, sz = [float(v) for v in size]
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    verts = [
        [-hx, -hy, -hz], [hx, -hy, -hz], [hx, hy, -hz], [-hx, hy, -hz],
        [-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz]
    ]
    tris = [
        [0, 1, 5], [0, 5, 4],  # -Y
        [3, 7, 6], [3, 6, 2],  # +Y
        [4, 5, 6], [4, 6, 7],  # +Z
        [1, 0, 3], [1, 3, 2],  # -Z
        [1, 2, 6], [1, 6, 5],  # +X
        [0, 4, 7], [0, 7, 3],  # -X
    ]
    normals = _smooth_normals(verts, tris)
    return {
        "vertices": verts,
        "triangles": tris,
        "render_vertices": verts,
        "render_normals": normals,
        "render_indices": [i for t in tris for i in t],
        "shading": "flat",
    }


def build_sphere(radius: float = 0.5, segments: int = 24, rings: int = 16) -> dict[str, Any]:
    """Watertight shared-vertex UV sphere."""
    radius = float(radius)
    segments = max(6, min(int(segments), 256))
    rings = max(4, min(int(rings), 128))
    verts = [[0.0, radius, 0.0]]
    for j in range(1, rings):
        phi = math.pi * j / rings
        y = radius * math.cos(phi)
        r_ring = radius * math.sin(phi)
        for i in range(segments):
            theta = 2.0 * math.pi * i / segments
            verts.append([r_ring * math.cos(theta), y, r_ring * math.sin(theta)])
    south_pole = len(verts)
    verts.append([0.0, -radius, 0.0])

    tris = []
    for i in range(segments):
        nxt = (i + 1) % segments
        tris.append([0, 1 + nxt, 1 + i])

    for j in range(rings - 2):
        row_a = 1 + j * segments
        row_b = 1 + (j + 1) * segments
        for i in range(segments):
            nxt = (i + 1) % segments
            tris.append([row_a + i, row_b + nxt, row_b + i])
            tris.append([row_a + i, row_a + nxt, row_b + nxt])

    last_row = 1 + (rings - 2) * segments
    for i in range(segments):
        nxt = (i + 1) % segments
        tris.append([south_pole, last_row + i, last_row + nxt])

    normals = _smooth_normals(verts, tris)
    return {
        "vertices": verts,
        "triangles": tris,
        "render_vertices": verts,
        "render_normals": normals,
        "render_indices": [i for t in tris for i in t],
        "shading": "smooth",
    }


def build_cylinder(radius: float = 0.5, height: float = 1.0, segments: int = 24) -> dict[str, Any]:
    """Watertight cylinder centered at origin."""
    return build_cone(radius_bottom=radius, radius_top=radius, height=height, segments=segments)


def build_boolean(op: str, base_mesh: dict[str, Any], tool_meshes: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute CSG Boolean operations (difference, union, intersection) using Manifold."""
    try:
        import manifold3d as m3d
        import numpy as np
    except ImportError as e:
        raise RuntimeError("manifold3d is required for CSG boolean operations. Install with `pip install manifold3d`.") from e

    def to_manifold(m: dict[str, Any]) -> m3d.Manifold:
        v = np.array(m["vertices"], dtype=np.float32)
        t = np.array(m["triangles"], dtype=np.uint32)
        return m3d.Manifold(m3d.Mesh(vert_properties=v, tri_verts=t))

    res = to_manifold(base_mesh)
    op_clean = op.strip().lower()

    for tm in tool_meshes:
        tool = to_manifold(tm)
        if op_clean in ("difference", "sub", "diff", "-"):
            res = res - tool
        elif op_clean in ("union", "add", "+"):
            res = res + tool
        elif op_clean in ("intersection", "intersect", "and", "&", "^"):
            res = res ^ tool
        else:
            raise ValueError(f"Unsupported boolean operation {op!r}. Supported: difference, union, intersection.")

    if res.is_empty():
        raise ValueError("Boolean operation produced an empty or degenerate solid with zero volume.")

    out_mesh = res.to_mesh()
    vertices = out_mesh.vert_properties.tolist()
    triangles = out_mesh.tri_verts.tolist()
    normals = _smooth_normals(vertices, triangles)
    return {
        "vertices": vertices,
        "triangles": triangles,
        "render_vertices": vertices,
        "render_normals": normals,
        "render_indices": [i for t in triangles for i in t],
        "shading": "smooth",
    }


def build_subdivision(base_mesh: dict[str, Any], levels: int = 1) -> dict[str, Any]:
    """Perform Loop subdivision on a 2-manifold triangle mesh."""
    if not isinstance(base_mesh, dict) or not base_mesh.get("vertices") or not base_mesh.get("triangles"):
        raise ValueError("Subdivision requires a valid base mesh with vertices and triangles.")

    levels = max(1, min(int(levels), 4))
    verts = [[float(x) for x in v] for v in base_mesh["vertices"]]
    tris = [list(t) for t in base_mesh["triangles"]]

    if HAS_M3L_CORE:
        try:
            sub_verts, sub_tris = m3l_core.subdivide_loop(verts, tris, levels)
            normals = m3l_core.compute_normals(sub_verts, sub_tris)
            return {
                "vertices": sub_verts,
                "triangles": sub_tris,
                "render_vertices": [list(v) for v in sub_verts],
                "render_normals": normals,
                "render_indices": [i for tri in sub_tris for i in tri],
                "shading": "smooth",
            }
        except Exception:
            pass

    for _ in range(levels):
        edge_opposites: dict[tuple[int, int], list[int]] = {}
        vertex_neighbors: list[set[int]] = [set() for _ in range(len(verts))]

        for t in tris:
            for i in range(3):
                u, v = t[i], t[(i + 1) % 3]
                opp = t[(i + 2) % 3]
                vertex_neighbors[u].add(v)
                vertex_neighbors[v].add(u)
                edge_key = (u, v) if u < v else (v, u)
                edge_opposites.setdefault(edge_key, []).append(opp)

        edge_midpoints: dict[tuple[int, int], int] = {}
        for edge_key, opps in edge_opposites.items():
            u, v = edge_key
            if len(opps) == 2:
                c, d = opps
                m = [3.0 / 8.0 * (verts[u][k] + verts[v][k]) + 1.0 / 8.0 * (verts[c][k] + verts[d][k]) for k in range(3)]
            else:
                m = [0.5 * (verts[u][k] + verts[v][k]) for k in range(3)]
            mid_idx = len(verts)
            verts.append(m)
            edge_midpoints[edge_key] = mid_idx

        new_verts: list[list[float]] = []
        for i, v in enumerate(verts[:len(vertex_neighbors)]):
            nbrs = list(vertex_neighbors[i])
            k = len(nbrs)
            if k == 0:
                new_verts.append(v)
                continue
            beta = (1.0 / k) * (5.0 / 8.0 - (3.0 / 8.0 + 1.0 / 4.0 * math.cos(2.0 * math.pi / k)) ** 2)
            sum_nbrs = [sum(verts[n][dim] for n in nbrs) for dim in range(3)]
            upd = [(1.0 - k * beta) * v[dim] + beta * sum_nbrs[dim] for dim in range(3)]
            new_verts.append(upd)

        verts[:len(new_verts)] = new_verts

        new_tris: list[list[int]] = []
        for t in tris:
            a, b, c = t
            m_ab = edge_midpoints[(a, b) if a < b else (b, a)]
            m_bc = edge_midpoints[(b, c) if b < c else (c, b)]
            m_ca = edge_midpoints[(c, a) if c < a else (a, c)]
            new_tris.append([a, m_ab, m_ca])
            new_tris.append([m_ab, b, m_bc])
            new_tris.append([m_ca, m_bc, c])
            new_tris.append([m_ab, m_bc, m_ca])
        tris = new_tris

    normals = _smooth_normals(verts, tris)
    return {
        "vertices": verts,
        "triangles": tris,
        "render_vertices": [list(v) for v in verts],
        "render_normals": normals,
        "render_indices": [i for tri in tris for i in tri],
        "shading": "smooth",
    }
