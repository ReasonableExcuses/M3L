"""Multi-format exporters for M3L compiled scenes.

Supports:
- Wavefront OBJ (.obj): Universal exchange format for all DCC and game engines.
- Stereolithography STL (.stl): Binary and ASCII standards for 3D printing slicers.
- Universal Scene Description USDA (.usda): Human-readable USD for Apple Vision Pro, AR, and Omniverse.
"""
from __future__ import annotations

import math
import struct
from typing import Any

from .compiler import _get_object_world_mesh, _rot_matrix, _transform_point


def _extract_scene_meshes(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract resolved world-space meshes for all objects in the scene IR."""
    groups_by_name = {g["name"]: {"props": {
        "at": g["transform"]["translation"],
        "rotate": g["transform"]["rotation_euler_degrees"],
        "scale": g["transform"]["scale"],
    }} for g in scene.get("groups", [])}

    objects = scene.get("objects", [])
    extracted = []

    for obj in objects:
        name = obj["name"]
        material = obj.get("material", "default")
        t = obj.get("transform", {})
        pos = t.get("translation", [0.0, 0.0, 0.0])
        rot_deg = t.get("rotation_euler_degrees", [0.0, 0.0, 0.0])
        scale = t.get("scale", [1.0, 1.0, 1.0])
        rot = _rot_matrix(rot_deg)

        has_group = bool(obj.get("group") and obj["group"] in groups_by_name)
        if has_group:
            gp = groups_by_name[obj["group"]]["props"]
            g_pos = gp["at"]
            g_rot = _rot_matrix(gp["rotate"])
            g_scale = gp["scale"]

        geom = obj.get("geometry", {})
        raw_mesh = geom.get("mesh")

        if not raw_mesh:
            # Fallback for standard primitives if mesh not pre-built in IR
            mock_obj = {
                "type": obj["type"],
                "props": {**geom, "at": [0, 0, 0], "rotate": [0, 0, 0], "scale": [1, 1, 1]},
            }
            raw_mesh = _get_object_world_mesh(mock_obj, {})

        if not raw_mesh or not raw_mesh.get("vertices") or not raw_mesh.get("triangles"):
            continue

        world_verts = []
        for v in raw_mesh["vertices"]:
            pt = _transform_point(v, pos, rot, scale)
            if has_group:
                pt = _transform_point(pt, g_pos, g_rot, g_scale)
            world_verts.append(pt)

        # Transformed normals
        world_normals = []
        mesh_normals = raw_mesh.get("render_normals") or []
        for i, n in enumerate(mesh_normals[:len(raw_mesh["vertices"])]):
            # Normal transformation with inverse-transpose approximation
            local_n = [float(n[j]) for j in range(3)]
            rot_n = [sum(rot[j][k] * local_n[k] for k in range(3)) for j in range(3)]
            if has_group:
                rot_n = [sum(g_rot[j][k] * rot_n[k] for k in range(3)) for j in range(3)]
            mag = math.sqrt(sum(c * c for c in rot_n)) or 1.0
            world_normals.append([c / mag for c in rot_n])

        if len(world_normals) < len(world_verts):
            world_normals = [[0.0, 1.0, 0.0] for _ in world_verts]

        extracted.append({
            "name": name,
            "material": material,
            "vertices": world_verts,
            "normals": world_normals,
            "triangles": [list(tri) for tri in raw_mesh["triangles"]],
        })

    return extracted


def export_obj(scene: dict[str, Any]) -> str:
    """Export scene to Wavefront OBJ format."""
    lines = [
        "# M3L 3D Scene Language - Wavefront OBJ Exporter",
        "# Units: Meters (Y-up)",
        "",
    ]

    meshes = _extract_scene_meshes(scene)
    vert_offset = 1
    norm_offset = 1

    for mesh in meshes:
        lines.append(f"o {mesh['name']}")
        lines.append(f"usemtl {mesh['material']}")

        for v in mesh["vertices"]:
            lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")

        for n in mesh["normals"]:
            lines.append(f"vn {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}")

        for tri in mesh["triangles"]:
            i1 = tri[0] + vert_offset
            i2 = tri[1] + vert_offset
            i3 = tri[2] + vert_offset
            lines.append(f"f {i1}//{i1} {i2}//{i2} {i3}//{i3}")

        vert_offset += len(mesh["vertices"])
        norm_offset += len(mesh["normals"])
        lines.append("")

    return "\n".join(lines)


def export_stl(scene: dict[str, Any], binary: bool = True) -> bytes:
    """Export scene to Stereolithography (STL) format. Defaults to fast binary STL."""
    meshes = _extract_scene_meshes(scene)

    total_triangles = sum(len(m["triangles"]) for m in meshes)

    if binary:
        # Binary STL format: 80-byte header + uint32 tri_count + 50 bytes per triangle
        header = b"M3L Deterministic 3D Solid Engine - Binary STL Export".ljust(80, b"\0")[:80]
        payload = bytearray()
        payload.extend(header)
        payload.extend(struct.pack("<I", total_triangles))

        for mesh in meshes:
            verts = mesh["vertices"]
            for tri in mesh["triangles"]:
                p0 = verts[tri[0]]
                p1 = verts[tri[1]]
                p2 = verts[tri[2]]

                # Calculate facet normal
                ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0

                payload.extend(struct.pack(
                    "<12fH",
                    nx / length, ny / length, nz / length,
                    p0[0], p0[1], p0[2],
                    p1[0], p1[1], p1[2],
                    p2[0], p2[1], p2[2],
                    0,  # Attribute byte count
                ))

        return bytes(payload)
    else:
        # ASCII STL format
        lines = ["solid m3l_scene"]
        for mesh in meshes:
            verts = mesh["vertices"]
            for tri in mesh["triangles"]:
                p0 = verts[tri[0]]
                p1 = verts[tri[1]]
                p2 = verts[tri[2]]
                ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0

                lines.append(f"  facet normal {nx/length:.6e} {ny/length:.6e} {nz/length:.6e}")
                lines.append("    outer loop")
                lines.append(f"      vertex {p0[0]:.6e} {p0[1]:.6e} {p0[2]:.6e}")
                lines.append(f"      vertex {p1[0]:.6e} {p1[1]:.6e} {p1[2]:.6e}")
                lines.append(f"      vertex {p2[0]:.6e} {p2[1]:.6e} {p2[2]:.6e}")
                lines.append("    endloop")
                lines.append("  endfacet")
        lines.append("endsolid m3l_scene")
        return "\n".join(lines).encode("utf-8")


def export_usd(scene: dict[str, Any]) -> str:
    """Export scene to Universal Scene Description ASCII (.usda) format."""
    lines = [
        "#usda 1.0",
        "(",
        '    defaultPrim = "Root"',
        '    metersPerUnit = 1.0',
        '    upAxis = "Y"',
        ")",
        "",
        'def Xform "Root"',
        "{",
    ]

    meshes = _extract_scene_meshes(scene)

    for mesh in meshes:
        name = mesh["name"].replace("-", "_").replace(" ", "_")
        lines.append(f'    def Mesh "{name}"')
        lines.append("    {")

        # Points
        pts_str = ", ".join(f"({v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f})" for v in mesh["vertices"])
        lines.append(f"        point3f[] points = [{pts_str}]")

        # Face vertex counts (all triangles = 3)
        counts_str = ", ".join(["3"] * len(mesh["triangles"]))
        lines.append(f"        int[] faceVertexCounts = [{counts_str}]")

        # Face vertex indices
        indices_flat = [idx for tri in mesh["triangles"] for idx in tri]
        indices_str = ", ".join(str(idx) for idx in indices_flat)
        lines.append(f"        int[] faceVertexIndices = [{indices_str}]")

        # Normals
        normals_str = ", ".join(f"({n[0]:.4f}, {n[1]:.4f}, {n[2]:.4f})" for n in mesh["normals"])
        lines.append(f"        normal3f[] normals = [{normals_str}] (")
        lines.append('            interpolation = "vertex"')
        lines.append("        )")

        lines.append("    }")

    lines.append("}")
    return "\n".join(lines)

