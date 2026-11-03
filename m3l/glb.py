"""Minimal binary glTF 2.0 exporter for M3L's primitive set (standard library only)."""
from __future__ import annotations

import json
import math
import struct
from typing import Any


_COMPONENT_FLOAT = 5126
_COMPONENT_UINT32 = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4
_UNIT_TO_METERS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}


def _normal(a, b, c):
    ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
    vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
    nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
    length = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
    return [nx/length, ny/length, nz/length]


def _box_mesh():
    # A unit cube with split face vertices for crisp normals.
    faces = [
        ([-.5,-.5,.5], [.5,-.5,.5], [.5,.5,.5], [-.5,.5,.5], [0,0,1]),
        ([.5,-.5,-.5], [-.5,-.5,-.5], [-.5,.5,-.5], [.5,.5,-.5], [0,0,-1]),
        ([.5,-.5,.5], [.5,-.5,-.5], [.5,.5,-.5], [.5,.5,.5], [1,0,0]),
        ([-.5,-.5,-.5], [-.5,-.5,.5], [-.5,.5,.5], [-.5,.5,-.5], [-1,0,0]),
        ([-.5,.5,.5], [.5,.5,.5], [.5,.5,-.5], [-.5,.5,-.5], [0,1,0]),
        ([-.5,-.5,-.5], [.5,-.5,-.5], [.5,-.5,.5], [-.5,-.5,.5], [0,-1,0]),
    ]
    pos, nor, idx = [], [], []
    for corners in faces:
        verts, normal = corners[:4], corners[4]
        base = len(pos)
        pos.extend(verts)
        nor.extend([normal] * 4)
        idx.extend([base, base+1, base+2, base, base+2, base+3])
    return pos, nor, idx


def _sphere_mesh(segments=24, rings=16):
    segments = max(6, min(int(segments), 256))
    rings = max(4, min(int(rings), 128))
    pos, nor, idx = [], [], []
    for y in range(rings + 1):
        v = y / rings
        theta = v * math.pi
        for x in range(segments + 1):
            u = x / segments
            phi = u * 2 * math.pi
            nx = math.sin(theta) * math.cos(phi)
            ny = math.cos(theta)
            nz = math.sin(theta) * math.sin(phi)
            pos.append([nx, ny, nz])
            nor.append([nx, ny, nz])
    for y in range(rings):
        for x in range(segments):
            a = y * (segments + 1) + x
            b = a + segments + 1
            # Reverse the theta/phi order so triangle fronts point outward.
            idx.extend([a, a+1, b, b, a+1, b+1])
    return pos, nor, idx


def _cylinder_mesh(segments=24):
    # Unit radius, unit height, centered at origin. Flat caps, smooth side normals.
    segments = max(6, min(int(segments), 256))
    pos, nor, idx = [], [], []
    # Side: two vertices per ring position to keep normals smooth.
    for y in (-.5, .5):
        for i in range(segments + 1):
            a = 2 * math.pi * i / segments
            x, z = math.cos(a), math.sin(a)
            pos.append([x, y, z])
            nor.append([x, 0.0, z])
    ring = segments + 1
    for i in range(segments):
        a, b = i, i + 1
        c, d = ring + i, ring + i + 1
        idx.extend([a, c, b, b, c, d])
    # Bottom cap
    bottom_center = len(pos)
    pos.append([0, -.5, 0]); nor.append([0, -1, 0])
    bottom_start = len(pos)
    for i in range(segments):
        a = 2 * math.pi * i / segments
        pos.append([math.cos(a), -.5, math.sin(a)]); nor.append([0, -1, 0])
    for i in range(segments):
        idx.extend([bottom_center, bottom_start + i, bottom_start + (i+1) % segments])
    # Top cap
    top_center = len(pos)
    pos.append([0, .5, 0]); nor.append([0, 1, 0])
    top_start = len(pos)
    for i in range(segments):
        a = 2 * math.pi * i / segments
        pos.append([math.cos(a), .5, math.sin(a)]); nor.append([0, 1, 0])
    for i in range(segments):
        idx.extend([top_center, top_start + (i+1) % segments, top_start + i])
    return pos, nor, idx


def _quat_from_euler_xyz(degrees):
    x, y, z = [math.radians(v) / 2.0 for v in degrees]
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    # glTF quaternion [x, y, z, w], XYZ Euler composition.
    return [sx*cy*cz + cx*sy*sz, cx*sy*cz - sx*cy*sz,
            cx*cy*sz + sx*sy*cz, cx*cy*cz - sx*sy*sz]


def _quat_look_at(position, target):
    # Build an orthonormal frame whose local -Z points from camera to target.
    fx, fy, fz = [target[i] - position[i] for i in range(3)]
    fl = math.sqrt(fx*fx + fy*fy + fz*fz) or 1.0
    fx, fy, fz = fx/fl, fy/fl, fz/fl
    up = [0.0, 1.0, 0.0]
    # right = forward x up; fall back when view direction is vertical.
    rx, ry, rz = fy*up[2]-fz*up[1], fz*up[0]-fx*up[2], fx*up[1]-fy*up[0]
    rl = math.sqrt(rx*rx + ry*ry + rz*rz)
    if rl < 1e-8:
        up = [0.0, 0.0, 1.0]
        rx, ry, rz = fy*up[2]-fz*up[1], fz*up[0]-fx*up[2], fx*up[1]-fy*up[0]
        rl = math.sqrt(rx*rx + ry*ry + rz*rz) or 1.0
    rx, ry, rz = rx/rl, ry/rl, rz/rl
    ux, uy, uz = ry*fz-rz*fy, rz*fx-rx*fz, rx*fy-ry*fx
    # Camera local z points backward (-forward). Matrix columns are right, up, backward.
    m00, m01, m02 = rx, ux, -fx
    m10, m11, m12 = ry, uy, -fy
    m20, m21, m22 = rz, uz, -fz
    trace = m00 + m11 + m22
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        qw = 0.25 * s
        qx = (m21 - m12) / s
        qy = (m02 - m20) / s
        qz = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        qw = (m21 - m12) / s; qx = .25 * s; qy = (m01 + m10) / s; qz = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        qw = (m02 - m20) / s; qx = (m01 + m10) / s; qy = .25 * s; qz = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        qw = (m10 - m01) / s; qx = (m02 + m20) / s; qy = (m12 + m21) / s; qz = .25 * s
    return [qx, qy, qz, qw]


class _BinaryBuilder:
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def _align(self):
        while len(self.data) % 4:
            self.data.append(0)

    def add_floats(self, rows, type_name="VEC3", target=_ARRAY_BUFFER, bounds=False):
        self._align()
        offset = len(self.data)
        flat = [float(v) for row in rows for v in row]
        if flat:
            self.data.extend(struct.pack("<" + "f"*len(flat), *flat))
        size = len(self.data) - offset
        view_index = len(self.views)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": size}
        if target is not None:
            view["target"] = target
        self.views.append(view)
        accessor = {"bufferView": view_index, "byteOffset": 0, "componentType": _COMPONENT_FLOAT,
                    "count": len(rows), "type": type_name}
        if bounds and rows:
            mins = [min(row[i] for row in rows) for i in range(len(rows[0]))]
            maxs = [max(row[i] for row in rows) for i in range(len(rows[0]))]
            accessor["min"], accessor["max"] = mins, maxs
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def add_indices(self, indices):
        self._align()
        offset = len(self.data)
        use_u16 = max(indices, default=0) <= 65535
        ctype, code = (5123, "H") if use_u16 else (_COMPONENT_UINT32, "I")
        if indices:
            self.data.extend(struct.pack("<" + code*len(indices), *indices))
        view_index = len(self.views)
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(self.data)-offset, "target": _ELEMENT_ARRAY_BUFFER})
        self.accessors.append({"bufferView": view_index, "byteOffset": 0, "componentType": ctype,
                               "count": len(indices), "type": "SCALAR", "min": [min(indices)], "max": [max(indices)]})
        return len(self.accessors) - 1

    def add_bytes(self, payload: bytes):
        """Append an opaque payload, aligned for glTF bufferView use (e.g. PNG images)."""
        self._align()
        offset = len(self.data)
        self.data.extend(payload)
        view_index = len(self.views)
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload)})
        return view_index


def _face_normal(a, b, c):
    return _normal(a, b, c)


def _uv_for_vertex(kind, position, normal, bounds, geom):
    x, y, z = (float(v) for v in position)
    nx, ny, nz = (float(v) for v in normal)
    if kind == "sphere":
        # Latitude/longitude mapping; seam is unwrapped per triangle below.
        u = (math.atan2(z, x) / (2 * math.pi)) % 1.0
        v = math.acos(max(-1.0, min(1.0, y))) / math.pi
        return [u, 1.0 - v]
    if kind in ("cylinder", "cone"):
        if abs(ny) > 0.72:
            spans = [max(bounds[1][i] - bounds[0][i], 1e-8) for i in range(3)]
            return [(x - bounds[0][0]) / spans[0], (z - bounds[0][2]) / spans[2]]
        u = (math.atan2(z, x) / (2 * math.pi)) % 1.0
        yspan = max(bounds[1][1] - bounds[0][1], 1e-8)
        v = (y - bounds[0][1]) / yspan
        return [u, v]
    if kind == "torus":
        u = (math.atan2(z, x) / (2 * math.pi)) % 1.0
        r_xz = math.sqrt(x*x + z*z)
        major_r = float(geom.get("major_radius", 0.5)) if isinstance(geom, dict) else 0.5
        v = (math.atan2(y, r_xz - major_r) / (2 * math.pi)) % 1.0
        return [u, v]
    if kind == "revolve":
        # End/shoulder faces need planar mapping; only radial surfaces use cylindrical UVs.
        if abs(ny) > 0.72:
            spans = [max(bounds[1][i] - bounds[0][i], 1e-8) for i in range(3)]
            return [(x - bounds[0][0]) / spans[0], (z - bounds[0][2]) / spans[2]]
        u = (math.atan2(z, x) / (2 * math.pi)) % 1.0
        yspan = max(bounds[1][1] - bounds[0][1], 1e-8)
        v = (y - bounds[0][1]) / yspan
        return [u, v]
    # Dominant-axis planar projection for boxes and arbitrary swept/extruded faces.
    # Coordinates are normalized by the full mesh bounds and clamped only for zero spans.
    spans = [max(bounds[1][i] - bounds[0][i], 1e-8) for i in range(3)]
    q = [(position[i] - bounds[0][i]) / spans[i] for i in range(3)]
    axis = max(range(3), key=lambda i: abs((nx, ny, nz)[i]))
    if axis == 0:
        return [q[2], q[1]]
    if axis == 1:
        return [q[0], q[2]]
    return [q[0], q[1]]


def _expand_textured_mesh(kind, positions, normals, indices, geom):
    """Duplicate triangle corners to permit face UVs and a seam-safe wrap coordinate."""
    if not indices or len(indices) % 3:
        raise ValueError("Textured meshes must use a non-empty triangle index list.")
    bounds = ([min(p[i] for p in positions) for i in range(3)],
              [max(p[i] for p in positions) for i in range(3)])
    out_pos, out_nor, out_uv, out_tan, out_idx = [], [], [], [], []
    for start in range(0, len(indices), 3):
        tri_indices = indices[start:start+3]
        tri_pos = [positions[i] for i in tri_indices]
        if normals is None:
            face_n = _face_normal(*tri_pos)
            tri_nor = [face_n, face_n, face_n]
        else:
            tri_nor = [normals[i] for i in tri_indices]
        tri_uv = [_uv_for_vertex(kind, tri_pos[i], tri_nor[i], bounds, geom) for i in range(3)]
        # For cylinder-like U coordinates, ensure adjacent corners take the short path
        # across 0/1 rather than interpolating across almost a full texture width.
        u_values = [uv[0] for uv in tri_uv]
        if kind in ("sphere", "cylinder", "revolve", "cone", "torus") and max(u_values) - min(u_values) > 0.5:
            for uv in tri_uv:
                if uv[0] < 0.5:
                    uv[0] += 1.0
        # Compute a tangent frame from position/UV derivatives. Expanded triangle corners
        # make seam handling explicit, so a tangent never blends across a UV discontinuity.
        e1 = [tri_pos[1][i] - tri_pos[0][i] for i in range(3)]
        e2 = [tri_pos[2][i] - tri_pos[0][i] for i in range(3)]
        du1 = tri_uv[1][0] - tri_uv[0][0]; dv1 = tri_uv[1][1] - tri_uv[0][1]
        du2 = tri_uv[2][0] - tri_uv[0][0]; dv2 = tri_uv[2][1] - tri_uv[0][1]
        det = du1 * dv2 - du2 * dv1
        if abs(det) > 1e-10:
            tangent = [(e1[i] * dv2 - e2[i] * dv1) / det for i in range(3)]
            bitangent = [(e2[i] * du1 - e1[i] * du2) / det for i in range(3)]
        else:
            n0 = tri_nor[0]
            seed = [1.0, 0.0, 0.0] if abs(n0[0]) < 0.85 else [0.0, 0.0, 1.0]
            tangent = [seed[i] - n0[i] * sum(seed[j] * n0[j] for j in range(3)) for i in range(3)]
            bitangent = [0.0, 0.0, 0.0]
        tlen = math.sqrt(sum(v*v for v in tangent)) or 1.0
        tangent = [v/tlen for v in tangent]
        handedness = 1.0
        cross_nt = [tri_nor[0][1]*tangent[2]-tri_nor[0][2]*tangent[1],
                    tri_nor[0][2]*tangent[0]-tri_nor[0][0]*tangent[2],
                    tri_nor[0][0]*tangent[1]-tri_nor[0][1]*tangent[0]]
        if sum(cross_nt[i] * bitangent[i] for i in range(3)) < 0:
            handedness = -1.0
        base = len(out_pos)
        for p, n, uv in zip(tri_pos, tri_nor, tri_uv):
            # Re-orthogonalize the tangent for each corner against its vertex normal.
            dot = sum(tangent[i] * n[i] for i in range(3))
            t = [tangent[i] - dot * n[i] for i in range(3)]
            tlen = math.sqrt(sum(v*v for v in t)) or 1.0
            t = [v/tlen for v in t]
            out_pos.append(list(p)); out_nor.append(list(n)); out_uv.append(uv)
            out_tan.append([t[0], t[1], t[2], handedness])
        out_idx.extend([base, base+1, base+2])
    return out_pos, out_nor, out_uv, out_tan, out_idx


def export_glb(scene: dict[str, Any]) -> bytes:
    """Export a validated M3L scene IR as a binary glTF 2.0 (GLB) byte string."""
    b = _BinaryBuilder()
    unit_factor = _UNIT_TO_METERS.get(scene.get("units", "m"), 1.0)
    gltf: dict[str, Any] = {"asset": {"version": "2.0", "generator": "M3L compiler 0.5"},
                            "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                            "materials": [], "accessors": b.accessors, "bufferViews": b.views,
                            "buffers": [{"byteLength": 0}]}
    material_ids = {}
    surface_bindings = {}
    images, textures = [], []
    # PNG maps are embedded directly in the GLB BIN chunk. They are normal glTF images,
    # not runtime shader code, so stock viewers can load them without an M3L plugin.
    textured_materials = [m for m in scene.get("materials", {}).values() if m.get("surface")]
    if textured_materials:
        gltf["images"], gltf["textures"] = images, textures
        gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    used_material_names = {obj.get("material", "default") for obj in scene.get("objects", [])}
    for name, mat in scene.get("materials", {}).items():
        # Do not emit orphaned PBR materials: every material in the delivery file should
        # be reachable from a primitive, which keeps audits clear and saves metadata.
        if name not in used_material_names:
            continue
        color = list(mat.get("base_color", [0.72, 0.76, 0.8])) + [1.0]
        pbr = {"baseColorFactor": color, "metallicFactor": float(mat.get("metallic", 0)),
               "roughnessFactor": float(mat.get("roughness", 0.72))}
        material_doc = {"name": name, "pbrMetallicRoughness": pbr,
                        "emissiveFactor": list(mat.get("emissive", [0, 0, 0])),
                        "doubleSided": bool(mat.get("double_sided", True))}
        # Use standard glTF material extensions so capable PBR renderers can handle
        # glass transmission, refractive index, and clear-coated surfaces. These are
        # optional extensions with ordinary metallic/roughness fallback behavior.
        material_extensions = {}
        if float(mat.get("transmission", 0.0)) > 0.0:
            material_extensions["KHR_materials_transmission"] = {"transmissionFactor": float(mat["transmission"])}
            gltf.setdefault("extensionsUsed", []).append("KHR_materials_transmission")
        if "ior" in mat:
            material_extensions["KHR_materials_ior"] = {"ior": float(mat["ior"])}
            gltf.setdefault("extensionsUsed", []).append("KHR_materials_ior")
        if float(mat.get("clearcoat", 0.0)) > 0.0:
            material_extensions["KHR_materials_clearcoat"] = {
                "clearcoatFactor": float(mat["clearcoat"]),
                "clearcoatRoughnessFactor": float(mat.get("clearcoat_roughness", 0.0)),
            }
            gltf.setdefault("extensionsUsed", []).append("KHR_materials_clearcoat")
        if material_extensions:
            material_doc["extensions"] = material_extensions
        # Image file texture maps (base_texture, normal_texture, roughness_texture)
        import os
        base_tex_path = mat.get("base_texture")
        if base_tex_path and isinstance(base_tex_path, str) and os.path.exists(base_tex_path):
            with open(base_tex_path, "rb") as tf:
                tbytes = tf.read()
            mime = "image/png" if base_tex_path.lower().endswith(".png") else "image/jpeg"
            view_index = b.add_bytes(tbytes)
            image_index = len(images)
            images.append({"name": f"{name}_baseTex", "bufferView": view_index, "mimeType": mime})
            texture_index = len(textures)
            textures.append({"sampler": 0, "source": image_index, "name": f"{name}_baseTex"})
            pbr["baseColorTexture"] = {"index": texture_index}

        norm_tex_path = mat.get("normal_texture")
        if norm_tex_path and isinstance(norm_tex_path, str) and os.path.exists(norm_tex_path):
            with open(norm_tex_path, "rb") as tf:
                tbytes = tf.read()
            mime = "image/png" if norm_tex_path.lower().endswith(".png") else "image/jpeg"
            view_index = b.add_bytes(tbytes)
            image_index = len(images)
            images.append({"name": f"{name}_normTex", "bufferView": view_index, "mimeType": mime})
            texture_index = len(textures)
            textures.append({"sampler": 0, "source": image_index, "name": f"{name}_normTex"})
            material_doc["normalTexture"] = {"index": texture_index, "scale": 1.0}

        surface = mat.get("surface")
        if surface:
            from .procedural_materials import generate_surface_maps
            resolution = int(mat.get("texture_resolution", 256))
            maps = generate_surface_maps(surface, resolution)
            map_indices = {}
            for key, label in (("base_color_png", "baseColor"), ("normal_png", "normal"), ("orm_png", "occlusionRoughnessMetallic")):
                view_index = b.add_bytes(maps[key])
                image_index = len(images)
                images.append({"name": f"{name}_{label}", "bufferView": view_index, "mimeType": "image/png"})
                texture_index = len(textures)
                textures.append({"sampler": 0, "source": image_index, "name": f"{name}_{label}"})
                map_indices[label] = texture_index
            pbr["baseColorTexture"] = {"index": map_indices["baseColor"]}
            pbr["metallicRoughnessTexture"] = {"index": map_indices["occlusionRoughnessMetallic"]}
            material_doc["normalTexture"] = {"index": map_indices["normal"], "scale": 0.7}
            material_doc["occlusionTexture"] = {"index": map_indices["occlusionRoughnessMetallic"], "strength": 0.65}
            surface_bindings[name] = maps["bytes"]
        gltf["materials"].append(material_doc)
        material_ids[name] = len(gltf["materials"]) - 1

    geometry_cache = {}
    accessor_cache = {}
    mesh_cache = {}

    group_node_indices: dict[str, int] = {}
    node_name_to_index: dict[str, int] = {}
    rest_transforms: dict[str, dict[str, Any]] = {}

    for group in scene.get("groups", []):
        gtr = group.get("transform", {})
        g_scale = [float(v) for v in gtr.get("scale", [1, 1, 1])]
        g_node = {
            "name": group["name"],
            "translation": [float(v) * unit_factor for v in gtr.get("translation", [0, 0, 0])],
            "rotation": _quat_from_euler_xyz(gtr.get("rotation_euler_degrees", [0, 0, 0])),
            "scale": g_scale,
            "children": [],
        }
        gltf["nodes"].append(g_node)
        group_idx = len(gltf["nodes"]) - 1
        group_node_indices[group["name"]] = group_idx
        node_name_to_index[group["name"]] = group_idx
        rest_transforms[group["name"]] = {
            "translation": gtr.get("translation", [0, 0, 0]),
            "rotation_euler": gtr.get("rotation_euler_degrees", [0, 0, 0]),
            "scale": g_scale,
        }
        gltf["scenes"][0]["nodes"].append(group_idx)

    for obj in scene.get("objects", []):
        typ, geom = obj["type"], obj.get("geometry", {})
        custom_mesh = geom.get("mesh") if isinstance(geom, dict) else None
        if isinstance(custom_mesh, dict):
            # Profile geometry is data. Hash the stable payload so identical procedural
            # meshes can share a glTF mesh while each node keeps an independent transform.
            cache_key = (typ, json.dumps(custom_mesh, sort_keys=True, separators=(",", ":")))
            if cache_key not in geometry_cache:
                if custom_mesh.get("shading") == "flat":
                    # Keep shared topological vertices in GLB and omit NORMAL so consumers
                    # use the glTF-specified flat face normals. Per-face duplicate vertices
                    # would look similar but would destroy manifold connectivity for editors.
                    positions = custom_mesh.get("vertices", [])
                    normals = None
                    indices = [i for tri in custom_mesh.get("triangles", []) for i in tri]
                else:
                    positions = custom_mesh.get("render_vertices", custom_mesh.get("vertices", []))
                    normals = custom_mesh.get("render_normals", [])
                    indices = custom_mesh.get("render_indices", [i for tri in custom_mesh.get("triangles", []) for i in tri])
                if not positions or (normals is not None and len(positions) != len(normals)):
                    raise ValueError(f"Custom mesh for {obj['name']!r} has inconsistent position/normal data.")
                if not indices or any(not isinstance(i, int) or i < 0 or i >= len(positions) for i in indices):
                    raise ValueError(f"Custom mesh for {obj['name']!r} has invalid triangle indices.")
                geometry_cache[cache_key] = (positions, normals, indices)
        else:
            cache_key = (typ, geom.get("segments", 24), geom.get("rings", 16))
            if cache_key not in geometry_cache:
                if typ == "box":
                    geometry_cache[cache_key] = _box_mesh()
                elif typ == "sphere":
                    geometry_cache[cache_key] = _sphere_mesh(geom.get("segments", 24), geom.get("rings", 16))
                elif typ == "cylinder":
                    geometry_cache[cache_key] = _cylinder_mesh(geom.get("segments", 24))
                else:
                    raise ValueError(f"No geometry generator for primitive {typ!r}.")
        material_name = obj.get("material", "default")
        wants_uv = material_name in surface_bindings
        accessor_key = (cache_key, wants_uv)
        if accessor_key not in accessor_cache:
            positions, normals, indices = geometry_cache[cache_key]
            uvs, tangents = None, None
            if wants_uv:
                positions, normals, uvs, tangents, indices = _expand_textured_mesh(typ, positions, normals, indices, geom)
            pos_accessor = b.add_floats(positions, "VEC3", _ARRAY_BUFFER, bounds=True)
            norm_accessor = b.add_floats(normals, "VEC3", _ARRAY_BUFFER) if normals is not None else None
            uv_accessor = b.add_floats(uvs, "VEC2", _ARRAY_BUFFER) if uvs is not None else None
            tangent_accessor = b.add_floats(tangents, "VEC4", _ARRAY_BUFFER) if tangents is not None else None
            index_accessor = b.add_indices(indices)
            accessor_cache[accessor_key] = (pos_accessor, norm_accessor, uv_accessor, tangent_accessor, index_accessor)
        pos_accessor, norm_accessor, uv_accessor, tangent_accessor, index_accessor = accessor_cache[accessor_key]
        mesh_key = (cache_key, material_name)
        if mesh_key not in mesh_cache:
            attributes = {"POSITION": pos_accessor}
            if norm_accessor is not None:
                attributes["NORMAL"] = norm_accessor
            if uv_accessor is not None:
                attributes["TEXCOORD_0"] = uv_accessor
            if tangent_accessor is not None:
                attributes["TANGENT"] = tangent_accessor
            primitive = {"attributes": attributes,
                         "indices": index_accessor, "mode": _TRIANGLES,
                         "material": material_ids.get(material_name, 0)}
            gltf["meshes"].append({"name": f"{typ}_{len(gltf['meshes'])}", "primitives": [primitive]})
            mesh_cache[mesh_key] = len(gltf["meshes"]) - 1
        tr = obj["transform"]
        instance_scale = list(tr.get("scale", [1, 1, 1]))
        # Canonical primitives put authored dimensions in node scale. Procedural meshes
        # carry their own profile coordinates, so their node scale only converts units.
        if isinstance(custom_mesh, dict):
            base_scale = [unit_factor, unit_factor, unit_factor]
        elif typ == "box":
            base_scale = [float(v) * unit_factor for v in geom.get("size", [1, 1, 1])]
        elif typ == "sphere":
            radius = float(geom.get("radius", 0.5)) * unit_factor
            base_scale = [radius, radius, radius]
        elif typ == "cylinder":
            base_scale = [float(geom.get("radius", 0.5)) * unit_factor,
                          float(geom.get("height", 1.0)) * unit_factor,
                          float(geom.get("radius", 0.5)) * unit_factor]
        else:
            base_scale = [unit_factor, unit_factor, unit_factor]
        final_scale = [float(base_scale[i]) * float(instance_scale[i]) for i in range(3)]
        node = {"name": obj["name"], "mesh": mesh_cache[mesh_key],
                "translation": [float(v) * unit_factor for v in tr.get("translation", [0, 0, 0])],
                "rotation": _quat_from_euler_xyz(tr.get("rotation_euler_degrees", [0, 0, 0])),
                "scale": final_scale}
        gltf["nodes"].append(node)
        obj_node_idx = len(gltf["nodes"]) - 1
        node_name_to_index[obj["name"]] = obj_node_idx
        rest_transforms[obj["name"]] = {
            "translation": tr.get("translation", [0, 0, 0]),
            "rotation_euler": tr.get("rotation_euler_degrees", [0, 0, 0]),
            "scale": final_scale,
        }
        group_name = obj.get("group")
        if group_name and group_name in group_node_indices:
            gltf["nodes"][group_node_indices[group_name]]["children"].append(obj_node_idx)
        else:
            gltf["scenes"][0]["nodes"].append(obj_node_idx)

    for g_idx in group_node_indices.values():
        if not gltf["nodes"][g_idx]["children"]:
            del gltf["nodes"][g_idx]["children"]

    camera = scene.get("camera")
    if camera:
        gltf.setdefault("cameras", []).append({"type": "perspective", "perspective": {
            "aspectRatio": 1.7777778, "yfov": math.radians(float(camera.get("fov", 50))),
            "znear": float(camera.get("near", 0.01)) * unit_factor,
            "zfar": float(camera.get("far", 1000)) * unit_factor}})
        camera_position = [float(v) * unit_factor for v in camera["position"]]
        camera_target = [float(v) * unit_factor for v in camera["target"]]
        node = {"name": "M3L_Camera", "camera": 0, "translation": camera_position,
                "rotation": _quat_look_at(camera_position, camera_target)}
        gltf["nodes"].append(node)
        gltf["scenes"][0]["nodes"].append(len(gltf["nodes"]) - 1)

    lights_ext = []
    for light in scene.get("lights", []):
        light_def = {"name": light["name"], "type": light["type"], "color": list(light.get("color", [1, 1, 1])),
                     "intensity": float(light.get("intensity", 100))}
        if light.get("range", 0) > 0 and light["type"] != "directional":
            light_def["range"] = float(light["range"]) * unit_factor
        lights_ext.append(light_def)
        node = {"name": light["name"], "translation": [float(v) * unit_factor for v in light.get("position", [0, 2, 0])],
                "extensions": {"KHR_lights_punctual": {"light": len(lights_ext)-1}}}
        gltf["nodes"].append(node)
        gltf["scenes"][0]["nodes"].append(len(gltf["nodes"]) - 1)
    if lights_ext:
        gltf.setdefault("extensionsUsed", []).append("KHR_lights_punctual")
        gltf.setdefault("extensions", {})["KHR_lights_punctual"] = {"lights": lights_ext}

    # Animations (Tier 7)
    animations_list = scene.get("animations", [])
    if animations_list:
        gltf["animations"] = []
        for anim in animations_list:
            target_name = anim.get("target")
            if target_name not in node_name_to_index:
                continue
            node_idx = node_name_to_index[target_name]
            channel_type = anim.get("channel", "rotation_y")
            keyframes = anim.get("keyframes", [])
            if not keyframes:
                continue

            rest = rest_transforms.get(target_name, {
                "translation": [0, 0, 0],
                "rotation_euler": [0, 0, 0],
                "scale": [1, 1, 1],
            })

            times = [[float(kf["time"])] for kf in keyframes]
            output_rows = []
            if channel_type in ("rotation_x", "rotation_y", "rotation_z", "rotation"):
                path = "rotation"
                type_name = "VEC4"
                base_rot = list(rest.get("rotation_euler", [0, 0, 0]))
                for kf in keyframes:
                    val = kf.get("value", 0.0)
                    if channel_type == "rotation_x":
                        euler = [base_rot[0] + float(val), base_rot[1], base_rot[2]]
                        quat = _quat_from_euler_xyz(euler)
                    elif channel_type == "rotation_y":
                        euler = [base_rot[0], base_rot[1] + float(val), base_rot[2]]
                        quat = _quat_from_euler_xyz(euler)
                    elif channel_type == "rotation_z":
                        euler = [base_rot[0], base_rot[1], base_rot[2] + float(val)]
                        quat = _quat_from_euler_xyz(euler)
                    else:  # "rotation"
                        if isinstance(val, (list, tuple)) and len(val) == 4:
                            quat = [float(v) for v in val]
                        elif isinstance(val, (list, tuple)) and len(val) == 3:
                            quat = _quat_from_euler_xyz([float(v) for v in val])
                        else:
                            quat = _quat_from_euler_xyz([0, float(val), 0])
                    output_rows.append(quat)

            elif channel_type in ("translation_x", "translation_y", "translation_z", "translation"):
                path = "translation"
                type_name = "VEC3"
                base_pos = [float(v) * unit_factor for v in rest.get("translation", [0, 0, 0])]
                for kf in keyframes:
                    val = kf.get("value", 0.0)
                    if channel_type == "translation_x":
                        row = [base_pos[0] + float(val) * unit_factor, base_pos[1], base_pos[2]]
                    elif channel_type == "translation_y":
                        row = [base_pos[0], base_pos[1] + float(val) * unit_factor, base_pos[2]]
                    elif channel_type == "translation_z":
                        row = [base_pos[0], base_pos[1], base_pos[2] + float(val) * unit_factor]
                    else:  # "translation"
                        row = [float(v) * unit_factor for v in val]
                    output_rows.append(row)

            elif channel_type in ("scale", "scale_x", "scale_y", "scale_z"):
                path = "scale"
                type_name = "VEC3"
                base_s = [float(v) for v in rest.get("scale", [1, 1, 1])]
                for kf in keyframes:
                    val = kf.get("value", 1.0)
                    if channel_type == "scale":
                        if isinstance(val, (list, tuple)):
                            row = [base_s[0] * float(val[0]), base_s[1] * float(val[1]), base_s[2] * float(val[2])]
                        else:
                            s = float(val)
                            row = [base_s[0] * s, base_s[1] * s, base_s[2] * s]
                    elif channel_type == "scale_x":
                        row = [base_s[0] * float(val), base_s[1], base_s[2]]
                    elif channel_type == "scale_y":
                        row = [base_s[0], base_s[1] * float(val), base_s[2]]
                    elif channel_type == "scale_z":
                        row = [base_s[0], base_s[1], base_s[2] * float(val)]
                    output_rows.append(row)
            else:
                continue

            time_accessor = b.add_floats(times, type_name="SCALAR", target=None, bounds=True)
            val_accessor = b.add_floats(output_rows, type_name=type_name, target=None)

            interp = anim.get("interpolation", "linear").upper()
            if interp not in ("LINEAR", "STEP", "CUBICSPLINE"):
                interp = "LINEAR"

            sampler_doc = {
                "input": time_accessor,
                "interpolation": interp,
                "output": val_accessor
            }
            channel_doc = {
                "sampler": 0,
                "target": {
                    "node": node_idx,
                    "path": path
                }
            }
            gltf["animations"].append({
                "name": anim.get("name", f"anim_{len(gltf['animations'])}"),
                "samplers": [sampler_doc],
                "channels": [channel_doc]
            })

    # Extension declarations are sets in glTF semantics; canonicalize order and
    # remove duplicates when many materials use the same extension.
    if gltf.get("extensionsUsed"):
        gltf["extensionsUsed"] = sorted(set(gltf["extensionsUsed"]))
    # Buffer views/accessors share the builder's lists, which were populated during mesh creation.
    while len(b.data) % 4:
        b.data.append(0)
    gltf["buffers"][0]["byteLength"] = len(b.data)
    json_bytes = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(b.data)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    header = struct.pack("<4sII", b"glTF", 2, total)
    json_chunk = struct.pack("<I4s", len(json_bytes), b"JSON") + json_bytes
    bin_chunk = struct.pack("<I4s", len(bin_bytes), b"BIN\x00") + bin_bytes
    return header + json_chunk + bin_chunk
