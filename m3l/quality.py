"""Structural quality audit for binary glTF (GLB) assets.

This module deliberately reports machine-checkable asset health, not subjective
artistic quality. It has no required third-party dependencies; Pillow is used
optionally to inspect embedded image dimensions when available.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import struct
from collections import Counter
from typing import Any

_GLTF_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_COMPONENTS = {
    5120: ("b", 1, True), 5121: ("B", 1, False),
    5122: ("h", 2, True), 5123: ("H", 2, False),
    5125: ("I", 4, False), 5126: ("f", 4, True),
}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
                    "MAT2": 4, "MAT3": 9, "MAT4": 16}


class GLBFormatError(ValueError):
    """The file is not a well-formed GLB container or has unsafe structure."""


def parse_glb(data: bytes, *, max_bytes: int = 512 * 1024 * 1024) -> tuple[dict[str, Any], bytes, list[dict[str, Any]]]:
    """Parse the GLB container and return (JSON document, first BIN, chunk metadata)."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("GLB input must be bytes-like")
    data = bytes(data)
    if len(data) > max_bytes:
        raise GLBFormatError(f"GLB exceeds configured size limit ({max_bytes} bytes).")
    if len(data) < 20:
        raise GLBFormatError("GLB is too short to contain a header and JSON chunk.")
    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != _GLTF_MAGIC:
        raise GLBFormatError("Invalid GLB magic; expected 'glTF'.")
    if version != 2:
        raise GLBFormatError(f"Unsupported GLB version {version}; expected 2.")
    if declared_length != len(data):
        raise GLBFormatError(f"Declared GLB length {declared_length} does not match actual {len(data)}.")

    offset = 12
    chunks: list[dict[str, Any]] = []
    json_doc = None
    bin_blob = b""
    while offset < len(data):
        if offset + 8 > len(data):
            raise GLBFormatError("Truncated GLB chunk header.")
        length, chunk_type = struct.unpack_from("<II", data, offset)
        start = offset + 8
        end = start + length
        if length % 4 != 0:
            raise GLBFormatError("GLB chunk length is not four-byte aligned.")
        if end > len(data):
            raise GLBFormatError("GLB chunk extends beyond declared file length.")
        payload = data[start:end]
        chunks.append({"type": chunk_type, "length": length, "offset": start})
        if not chunks[:-1] and chunk_type != _JSON_CHUNK:
            raise GLBFormatError("The first GLB chunk must be JSON.")
        if chunk_type == _JSON_CHUNK:
            if json_doc is not None:
                raise GLBFormatError("GLB contains multiple JSON chunks.")
            try:
                json_doc = json.loads(payload.decode("utf-8").rstrip(" \x00\t\r\n"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GLBFormatError(f"GLB JSON chunk is invalid: {exc}") from exc
        elif chunk_type == _BIN_CHUNK:
            if bin_blob:
                raise GLBFormatError("GLB contains multiple BIN chunks.")
            bin_blob = payload
        offset = end
    if offset != len(data):
        raise GLBFormatError("GLB chunk layout does not end at file boundary.")
    if not isinstance(json_doc, dict):
        raise GLBFormatError("GLB JSON root must be an object.")
    if not chunks or chunks[0]["type"] != _JSON_CHUNK:
        raise GLBFormatError("Missing leading JSON chunk.")
    asset = json_doc.get("asset")
    if not isinstance(asset, dict) or not str(asset.get("version", "")).startswith("2"):
        raise GLBFormatError("glTF asset.version must identify glTF 2.x.")
    return json_doc, bin_blob, chunks


def _accessor_values(doc: dict[str, Any], bin_blob: bytes, accessor_index: int,
                     *, max_elements: int = 20_000_000) -> tuple[list[tuple[float, ...]], dict[str, Any]]:
    accessors = doc.get("accessors", [])
    views = doc.get("bufferViews", [])
    if not isinstance(accessor_index, int) or isinstance(accessor_index, bool) or not 0 <= accessor_index < len(accessors):
        raise GLBFormatError(f"Accessor index {accessor_index!r} is out of range.")
    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict):
        raise GLBFormatError(f"Accessor {accessor_index} is not an object.")
    count, comp_type, typ = accessor.get("count"), accessor.get("componentType"), accessor.get("type")
    if not isinstance(count, int) or count < 0 or count > max_elements:
        raise GLBFormatError(f"Accessor {accessor_index} has an invalid or excessive count.")
    if comp_type not in _COMPONENTS or typ not in _TYPE_COMPONENTS:
        raise GLBFormatError(f"Accessor {accessor_index} has unsupported componentType/type.")
    fmt, comp_size, signed_or_float = _COMPONENTS[comp_type]
    width = _TYPE_COMPONENTS[typ]
    elem_size = comp_size * width
    values: list[tuple[float, ...]]

    if "bufferView" not in accessor:
        # Accessors may validly have no base bufferView; they start with zero values.
        values = [tuple(0.0 for _ in range(width)) for _ in range(count)]
    else:
        view_index = accessor["bufferView"]
        if not isinstance(view_index, int) or not 0 <= view_index < len(views):
            raise GLBFormatError(f"Accessor {accessor_index} references invalid bufferView.")
        view = views[view_index]
        if view.get("buffer", 0) != 0:
            raise GLBFormatError(f"Accessor {accessor_index} references a non-GLB buffer.")
        view_offset = int(view.get("byteOffset", 0))
        accessor_offset = int(accessor.get("byteOffset", 0))
        stride = int(view.get("byteStride", elem_size))
        if stride < elem_size or stride % comp_size:
            raise GLBFormatError(f"Accessor {accessor_index} has an invalid byteStride.")
        required = accessor_offset if count == 0 else accessor_offset + (count - 1) * stride + elem_size
        view_length = int(view.get("byteLength", 0))
        if accessor_offset < 0 or required > view_length:
            raise GLBFormatError(f"Accessor {accessor_index} overruns its bufferView.")
        base = view_offset + accessor_offset
        if base + required - accessor_offset > len(bin_blob):
            raise GLBFormatError(f"Accessor {accessor_index} overruns GLB BIN data.")
        unpack = struct.Struct("<" + fmt * width).unpack_from
        values = [tuple(float(v) for v in unpack(bin_blob, base + i * stride)) for i in range(count)]

    # Apply normalized integer conversion before sparse values, as glTF accessor semantics require.
    if accessor.get("normalized") and comp_type != 5126:
        if comp_type == 5120:
            values = [tuple(max(x / 127.0, -1.0) for x in row) for row in values]
        elif comp_type == 5121:
            values = [tuple(x / 255.0 for x in row) for row in values]
        elif comp_type == 5122:
            values = [tuple(max(x / 32767.0, -1.0) for x in row) for row in values]
        elif comp_type == 5123:
            values = [tuple(x / 65535.0 for x in row) for row in values]

    sparse = accessor.get("sparse")
    if sparse:
        sparse_count = sparse.get("count")
        indices_spec = sparse.get("indices", {})
        values_spec = sparse.get("values", {})
        idx_type = indices_spec.get("componentType")
        if not isinstance(sparse_count, int) or sparse_count < 0 or sparse_count > count:
            raise GLBFormatError(f"Accessor {accessor_index} has invalid sparse.count.")
        if idx_type not in (5121, 5123, 5125):
            raise GLBFormatError(f"Accessor {accessor_index} has invalid sparse index componentType.")
        idx_fmt, idx_size, _ = _COMPONENTS[idx_type]

        def sparse_bytes(spec: dict[str, Any], expected_length: int, label: str) -> bytes:
            v_i = spec.get("bufferView")
            if not isinstance(v_i, int) or not 0 <= v_i < len(views):
                raise GLBFormatError(f"Accessor {accessor_index} sparse {label} has invalid bufferView.")
            view = views[v_i]
            if view.get("buffer", 0) != 0:
                raise GLBFormatError(f"Accessor {accessor_index} sparse {label} references a non-GLB buffer.")
            off = int(view.get("byteOffset", 0)) + int(spec.get("byteOffset", 0))
            end = off + expected_length
            view_end = int(view.get("byteOffset", 0)) + int(view.get("byteLength", 0))
            if off < int(view.get("byteOffset", 0)) or end > view_end or end > len(bin_blob):
                raise GLBFormatError(f"Accessor {accessor_index} sparse {label} data overruns bufferView.")
            return bin_blob[off:end]

        raw_indices = sparse_bytes(indices_spec, sparse_count * idx_size, "indices")
        idx_struct = struct.Struct("<" + idx_fmt)
        sparse_indices = [int(idx_struct.unpack_from(raw_indices, i * idx_size)[0]) for i in range(sparse_count)]
        if any(i >= count for i in sparse_indices):
            raise GLBFormatError(f"Accessor {accessor_index} sparse index is out of range.")
        if any(sparse_indices[i] >= sparse_indices[i+1] for i in range(len(sparse_indices)-1)):
            raise GLBFormatError(f"Accessor {accessor_index} sparse indices must be strictly increasing.")
        raw_values = sparse_bytes(values_spec, sparse_count * elem_size, "values")
        value_struct = struct.Struct("<" + fmt * width)
        for i, target_index in enumerate(sparse_indices):
            row = tuple(float(v) for v in value_struct.unpack_from(raw_values, i * elem_size))
            if accessor.get("normalized") and comp_type != 5126:
                if comp_type == 5120: row = tuple(max(x / 127.0, -1.0) for x in row)
                elif comp_type == 5121: row = tuple(x / 255.0 for x in row)
                elif comp_type == 5122: row = tuple(max(x / 32767.0, -1.0) for x in row)
                elif comp_type == 5123: row = tuple(x / 65535.0 for x in row)
            values[target_index] = row
    return values, accessor


def _image_info(doc: dict[str, Any], bin_blob: bytes) -> list[dict[str, Any]]:
    output = []
    images = doc.get("images", [])
    buffer_views = doc.get("bufferViews", [])
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        Image = None
        BytesIO = None
    for index, image in enumerate(images):
        info: dict[str, Any] = {"index": index, "name": image.get("name", f"image_{index}"),
                                "mime_type": image.get("mimeType"), "embedded": False}
        payload = None
        if "bufferView" in image:
            view_i = image.get("bufferView")
            if isinstance(view_i, int) and 0 <= view_i < len(buffer_views):
                view = buffer_views[view_i]
                if view.get("buffer", 0) == 0:
                    start = int(view.get("byteOffset", 0))
                    end = start + int(view.get("byteLength", 0))
                    if 0 <= start <= end <= len(bin_blob):
                        payload = bin_blob[start:end]
                        info["embedded"] = True
                    else:
                        info["error"] = "image bufferView exceeds BIN chunk"
                else:
                    info["error"] = "image references non-GLB buffer"
            else:
                info["error"] = "image references invalid bufferView"
        elif isinstance(image.get("uri"), str):
            uri = image["uri"]
            if uri.startswith("data:") and "," in uri:
                header, data = uri.split(",", 1)
                if ";base64" in header:
                    try:
                        payload = base64.b64decode(data, validate=True)
                        info["embedded"] = True
                    except (binascii.Error, ValueError):
                        info["error"] = "invalid base64 data URI"
            else:
                info["external_uri"] = uri
        else:
            info["error"] = "image has neither bufferView nor uri"
        if payload is not None:
            info["encoded_bytes"] = len(payload)
            info["sha256"] = hashlib.sha256(payload).hexdigest()
            if Image is not None:
                try:
                    with Image.open(BytesIO(payload)) as im:
                        info["width"], info["height"] = im.size
                        info["format"] = im.format
                        info["mode"] = im.mode
                        info["pixel_count"] = int(im.width * im.height)
                        im.verify()
                        info["decodes"] = True
                except Exception as exc:
                    info["decodes"] = False
                    info["decode_error"] = f"{type(exc).__name__}: {exc}"
        output.append(info)
    return output


def audit_glb(data: bytes, *, max_bytes: int = 512 * 1024 * 1024) -> dict[str, Any]:
    """Inspect GLB structural integrity, mesh attributes, materials, textures and capabilities."""
    doc, bin_blob, chunks = parse_glb(data, max_bytes=max_bytes)
    meshes = doc.get("meshes", [])
    nodes = doc.get("nodes", [])
    materials = doc.get("materials", [])
    textures = doc.get("textures", [])
    images = _image_info(doc, bin_blob)
    warnings: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    mesh_reports = []
    total_vertices = total_triangles = total_primitives = 0
    positions_present = normals_present = uv0_present = tangents_present = 0
    normals_bad = uv_bad = pos_nonfinite = degenerate_triangles = 0
    position_accessor_indices: set[int] = set()
    used_material_indices: set[int] = set()
    all_accessor_counts: dict[int, int] = {}

    def issue(where: str, code: str, message: str, severity: str = "warning"):
        target = errors if severity == "error" else warnings
        target.append({"where": where, "code": code, "message": message})

    # Validate the storage layer, including unused views/buffers that per-primitive checks may not visit.
    buffers = doc.get("buffers", [])
    if buffers:
        first_buffer = buffers[0]
        if first_buffer.get("uri") is None:
            declared_buffer_bytes = first_buffer.get("byteLength", 0)
            if not isinstance(declared_buffer_bytes, int) or declared_buffer_bytes < 0:
                issue("buffers[0]", "BUFFER_LENGTH_INVALID", "Buffer byteLength must be a non-negative integer.", "error")
            elif declared_buffer_bytes > len(bin_blob) or len(bin_blob) - declared_buffer_bytes > 3:
                issue("buffers[0]", "BUFFER_BIN_LENGTH_MISMATCH", "Embedded buffer byteLength does not match the BIN chunk (allowing at most 3 padding bytes).", "error")
        else:
            issue("buffers[0]", "EXTERNAL_BUFFER_URI", "Buffer references an external URI; the GLB audit does not fetch it.")
        if len(buffers) > 1:
            issue("buffers", "MULTIPLE_BUFFERS", "GLB declares multiple buffers; only the first embedded buffer is decoded by this audit.")
    elif bin_blob:
        issue("buffers", "BIN_WITHOUT_BUFFER", "A BIN chunk exists but the document has no buffers entry.")
    for vi, view in enumerate(doc.get("bufferViews", [])):
        buffer_i = view.get("buffer", 0)
        start = view.get("byteOffset", 0)
        length = view.get("byteLength")
        if not isinstance(buffer_i, int) or buffer_i < 0 or buffer_i >= max(1, len(buffers)):
            issue(f"bufferViews[{vi}]", "BUFFERVIEW_BUFFER_INVALID", f"Buffer index {buffer_i!r} is out of range.", "error")
            continue
        if not isinstance(start, int) or start < 0 or not isinstance(length, int) or length < 0:
            issue(f"bufferViews[{vi}]", "BUFFERVIEW_RANGE_INVALID", "bufferView byteOffset/byteLength must be non-negative integers.", "error")
            continue
        if buffer_i == 0 and start + length > len(bin_blob):
            issue(f"bufferViews[{vi}]", "BUFFERVIEW_OVERRUN", "bufferView exceeds the embedded BIN chunk.", "error")
        stride = view.get("byteStride")
        if stride is not None and (not isinstance(stride, int) or not 4 <= stride <= 252 or stride % 4 != 0):
            issue(f"bufferViews[{vi}]", "BUFFERVIEW_STRIDE_INVALID", "byteStride must be a multiple of four from 4 through 252.", "error")

    for mi, mesh in enumerate(meshes):
        m_report = {"index": mi, "name": mesh.get("name", f"mesh_{mi}"), "primitives": [],
                    "vertices": 0, "triangles": 0}
        for pi, prim in enumerate(mesh.get("primitives", [])):
            total_primitives += 1
            attrs = prim.get("attributes", {})
            mode = prim.get("mode", 4)
            pr = {"index": pi, "mode": mode, "attributes": sorted(attrs.keys()),
                  "material": prim.get("material"), "warnings": []}
            pos_index = attrs.get("POSITION")
            if pos_index is None:
                issue(f"meshes[{mi}].primitives[{pi}]", "POSITION_MISSING", "Primitive has no POSITION attribute.", "error")
                pos_values = []
                pos_acc = None
            else:
                positions_present += 1
                position_accessor_indices.add(pos_index)
                try:
                    pos_values, pos_acc = _accessor_values(doc, bin_blob, pos_index)
                    all_accessor_counts[pos_index] = len(pos_values)
                    pr["vertices"] = len(pos_values)
                    m_report["vertices"] += len(pos_values)
                    total_vertices += len(pos_values)
                    if pos_acc.get("type") != "VEC3" or pos_acc.get("componentType") != 5126:
                        issue(f"meshes[{mi}].primitives[{pi}]", "POSITION_FORMAT", "POSITION should normally be FLOAT VEC3.")
                    if any(not math.isfinite(x) for row in pos_values for x in row):
                        pos_nonfinite += 1
                        issue(f"meshes[{mi}].primitives[{pi}]", "POSITION_NONFINITE", "POSITION contains NaN or infinity.", "error")
                    pmin = [min(row[j] for row in pos_values) for j in range(3)] if pos_values else None
                    pmax = [max(row[j] for row in pos_values) for j in range(3)] if pos_values else None
                    pr["position_bounds"] = {"min": pmin, "max": pmax}
                except (GLBFormatError, ValueError, TypeError, struct.error) as exc:
                    issue(f"meshes[{mi}].primitives[{pi}]", "POSITION_ACCESSOR_INVALID", str(exc), "error")
                    pos_values, pos_acc = [], None
            if "NORMAL" in attrs:
                normals_present += 1
                try:
                    normals, na = _accessor_values(doc, bin_blob, attrs["NORMAL"])
                    all_accessor_counts[attrs["NORMAL"]] = len(normals)
                    if pos_acc and len(normals) != int(pos_acc.get("count", -1)):
                        issue(f"meshes[{mi}].primitives[{pi}]", "NORMAL_COUNT_MISMATCH", "NORMAL count differs from POSITION count.", "error")
                    local_bad_normals = 0
                    for row in normals:
                        length = math.sqrt(sum(x*x for x in row))
                        if not math.isfinite(length) or (length != 0.0 and abs(length - 1.0) > 0.06):
                            normals_bad += 1
                            local_bad_normals += 1
                    if local_bad_normals:
                        pr["normal_vectors_out_of_tolerance"] = local_bad_normals
                except (GLBFormatError, ValueError, TypeError, struct.error) as exc:
                    issue(f"meshes[{mi}].primitives[{pi}]", "NORMAL_ACCESSOR_INVALID", str(exc), "error")
            else:
                issue(f"meshes[{mi}].primitives[{pi}]", "NORMALS_MISSING", "Primitive has no NORMAL attribute; shading may be incorrect.")
            if "TEXCOORD_0" in attrs:
                uv0_present += 1
                try:
                    uvs, ua = _accessor_values(doc, bin_blob, attrs["TEXCOORD_0"])
                    all_accessor_counts[attrs["TEXCOORD_0"]] = len(uvs)
                    if pos_acc and len(uvs) != int(pos_acc.get("count", -1)):
                        issue(f"meshes[{mi}].primitives[{pi}]", "UV_COUNT_MISMATCH", "TEXCOORD_0 count differs from POSITION count.", "error")
                    if ua.get("type") != "VEC2":
                        issue(f"meshes[{mi}].primitives[{pi}]", "UV_FORMAT", "TEXCOORD_0 should be VEC2.")
                    if any(not math.isfinite(x) for row in uvs for x in row):
                        uv_bad += 1
                        issue(f"meshes[{mi}].primitives[{pi}]", "UV_NONFINITE", "UV coordinates contain NaN or infinity.", "error")
                except (GLBFormatError, ValueError, TypeError, struct.error) as exc:
                    issue(f"meshes[{mi}].primitives[{pi}]", "UV_ACCESSOR_INVALID", str(exc), "error")
            if "TANGENT" in attrs:
                tangents_present += 1
            material_index = prim.get("material")
            if material_index is not None:
                if not isinstance(material_index, int) or not 0 <= material_index < len(materials):
                    issue(f"meshes[{mi}].primitives[{pi}]", "MATERIAL_INDEX_INVALID", f"Material index {material_index!r} is out of range.", "error")
                else:
                    used_material_indices.add(material_index)

            # Validate index accessors and count triangles. Bounds checks are possible without remapping vertices.
            idx_values = None
            if "indices" in prim:
                try:
                    idx_values, ia = _accessor_values(doc, bin_blob, prim["indices"])
                    all_accessor_counts[prim["indices"]] = len(idx_values)
                    flat = [int(v[0]) for v in idx_values]
                    if ia.get("type") != "SCALAR" or ia.get("componentType") not in (5121, 5123, 5125):
                        issue(f"meshes[{mi}].primitives[{pi}]", "INDEX_FORMAT", "Indices should use unsigned scalar components.", "error")
                    if pos_acc and flat and (min(flat) < 0 or max(flat) >= int(pos_acc.get("count", 0))):
                        issue(f"meshes[{mi}].primitives[{pi}]", "INDEX_OUT_OF_RANGE", "An index exceeds POSITION accessor bounds.", "error")
                    pr["index_count"] = len(flat)
                    if mode == 4:
                        tris = len(flat) // 3
                        total_triangles += tris
                        m_report["triangles"] += tris
                        if len(flat) % 3:
                            issue(f"meshes[{mi}].primitives[{pi}]", "TRIANGLE_INDEX_REMAINDER", "TRIANGLES index count is not divisible by three.", "error")
                        degenerate = sum(1 for i in range(0, len(flat) - 2, 3)
                                         if flat[i] == flat[i+1] or flat[i+1] == flat[i+2] or flat[i] == flat[i+2])
                        degenerate_triangles += degenerate
                        if degenerate:
                            issue(f"meshes[{mi}].primitives[{pi}]", "DEGENERATE_TRIANGLE", f"{degenerate} triangles repeat an index.")
                    elif mode in (5, 6):
                        count = max(0, len(flat) - 2)
                        total_triangles += count
                        m_report["triangles"] += count
                except (GLBFormatError, ValueError, TypeError, struct.error) as exc:
                    issue(f"meshes[{mi}].primitives[{pi}]", "INDEX_ACCESSOR_INVALID", str(exc), "error")
            else:
                vert_count = len(pos_values)
                pr["index_count"] = 0
                if mode == 4:
                    tris = vert_count // 3
                    total_triangles += tris
                    m_report["triangles"] += tris
                    if vert_count % 3:
                        issue(f"meshes[{mi}].primitives[{pi}]", "TRIANGLE_VERTEX_REMAINDER", "Non-indexed triangle vertex count is not divisible by three.", "error")

            pr["triangle_count"] = (len(idx_values) // 3 if idx_values is not None and mode == 4 else
                                     (len(pos_values) // 3 if idx_values is None and mode == 4 else
                                      (max(0, (len(idx_values) if idx_values is not None else len(pos_values)) - 2) if mode in (5, 6) else 0)))
            if mode not in (4, 5, 6):
                issue(f"meshes[{mi}].primitives[{pi}]", "NONTRIANGLE_MODE", f"Primitive mode {mode} is not triangle-based.")
            if prim.get("extensions", {}).get("KHR_draco_mesh_compression"):
                issue(f"meshes[{mi}].primitives[{pi}]", "DRACO_NOT_DECODED", "Draco-compressed geometry was not decoded by this structural auditor.")
            m_report["primitives"].append(pr)
        mesh_reports.append(m_report)

    # Material and texture usage maps.
    material_reports = []
    map_counts = Counter()
    for index, material in enumerate(materials):
        pbr = material.get("pbrMetallicRoughness", {})
        mapping = {
            "base_color": pbr.get("baseColorTexture"),
            "metallic_roughness": pbr.get("metallicRoughnessTexture"),
            "normal": material.get("normalTexture"),
            "occlusion": material.get("occlusionTexture"),
            "emissive": material.get("emissiveTexture"),
        }
        used = [key for key, value in mapping.items() if value is not None]
        for key in used:
            map_counts[key] += 1
        if material.get("normalTexture"):
            # Tangents are strongly recommended when authored normal maps depend on tangents.
            if tangents_present == 0:
                issue(f"materials[{index}]", "NORMAL_MAP_WITHOUT_TANGENTS", "Material has a normal map but no mesh primitive declares TANGENT; renderer may need to generate tangent frames.")
        material_reports.append({"index": index, "name": material.get("name", f"material_{index}"),
                                 "alpha_mode": material.get("alphaMode", "OPAQUE"),
                                 "metallic_factor": pbr.get("metallicFactor", 1.0),
                                 "roughness_factor": pbr.get("roughnessFactor", 1.0),
                                 "texture_maps": used,
                                 "has_transmission": "KHR_materials_transmission" in material.get("extensions", {}),
                                 "has_ior": "KHR_materials_ior" in material.get("extensions", {}),
                                 "has_clearcoat": "KHR_materials_clearcoat" in material.get("extensions", {}),
                                 "has_sheen": "KHR_materials_sheen" in material.get("extensions", {})})
        for key, value in mapping.items():
            if value is not None:
                tex_i = value.get("index") if isinstance(value, dict) else None
                if not isinstance(tex_i, int) or not 0 <= tex_i < len(textures):
                    issue(f"materials[{index}]", "TEXTURE_INDEX_INVALID", f"{key} references invalid texture index {tex_i!r}.", "error")

    # Texture use requires matching TEXCOORD_n attributes on each primitive.
    for mi, mesh in enumerate(meshes):
        for pi, primitive in enumerate(mesh.get("primitives", [])):
            material_i = primitive.get("material")
            if not isinstance(material_i, int) or not 0 <= material_i < len(materials):
                continue
            material = materials[material_i]
            pbr = material.get("pbrMetallicRoughness", {})
            texture_infos = [pbr.get("baseColorTexture"), pbr.get("metallicRoughnessTexture"),
                             material.get("normalTexture"), material.get("occlusionTexture"), material.get("emissiveTexture")]
            attrs = primitive.get("attributes", {})
            for info in texture_infos:
                if not isinstance(info, dict):
                    continue
                uv_channel = info.get("texCoord", 0)
                uv_name = f"TEXCOORD_{uv_channel}"
                if uv_name not in attrs:
                    issue(f"meshes[{mi}].primitives[{pi}]", "TEXTURE_WITHOUT_UV", f"Material texture expects {uv_name}, but the primitive does not provide it.")
                    break

    # Validate texture sources.
    for index, texture in enumerate(textures):
        source_index = texture.get("source")
        ext_source = texture.get("extensions", {}).get("KHR_texture_basisu", {}).get("source")
        effective = source_index if source_index is not None else ext_source
        if effective is None:
            issue(f"textures[{index}]", "TEXTURE_SOURCE_MISSING", "Texture has no core image source or KHR_texture_basisu source.")
        elif not isinstance(effective, int) or not 0 <= effective < len(images):
            issue(f"textures[{index}]", "TEXTURE_SOURCE_INVALID", f"Texture references invalid image index {effective!r}.", "error")

    for index, image in enumerate(images):
        if image.get("decodes") is False:
            issue(f"images[{index}]", "IMAGE_DECODE_FAILED", image.get("decode_error", "Image payload could not be decoded."), "error")
        if image.get("external_uri"):
            issue(f"images[{index}]", "EXTERNAL_IMAGE_URI", "GLB image is referenced externally; this audit does not fetch external resources.")

    for index, node in enumerate(nodes):
        mesh_i = node.get("mesh")
        if mesh_i is not None and (not isinstance(mesh_i, int) or not 0 <= mesh_i < len(meshes)):
            issue(f"nodes[{index}]", "NODE_MESH_INVALID", f"Node mesh index {mesh_i!r} is out of range.", "error")
        for field, width in (("translation", 3), ("scale", 3), ("rotation", 4)):
            if field in node:
                vec = node[field]
                if not isinstance(vec, list) or len(vec) != width or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vec):
                    issue(f"nodes[{index}]", "NODE_TRANSFORM_INVALID", f"Node {field} must be a finite numeric array with {width} elements.", "error")
                elif field == "rotation" and abs(sum(float(x)*float(x) for x in vec) - 1.0) > 0.05:
                    issue(f"nodes[{index}]", "NODE_QUATERNION_NOT_NORMALIZED", "Node rotation quaternion is not approximately unit length.")
        if "matrix" in node and any(k in node for k in ("translation", "rotation", "scale")):
            issue(f"nodes[{index}]", "NODE_MATRIX_AND_TRS", "A glTF node must use matrix or TRS properties, not both.", "error")
        children = node.get("children", [])
        if not isinstance(children, list) or any(not isinstance(child, int) or child < 0 or child >= len(nodes) for child in children):
            issue(f"nodes[{index}]", "NODE_CHILD_INVALID", "Node children must reference valid node indices.", "error")
    for si, scene in enumerate(doc.get("scenes", [])):
        roots = scene.get("nodes", [])
        if not isinstance(roots, list) or any(not isinstance(root, int) or root < 0 or root >= len(nodes) for root in roots):
            issue(f"scenes[{si}]", "SCENE_NODE_INVALID", "Scene node list references an invalid node index.", "error")
    for i, material in enumerate(materials):
        if i not in used_material_indices:
            issue(f"materials[{i}]", "MATERIAL_UNUSED", "Material is not referenced by any primitive.")

    # Root-level requirements and capability notes.
    if not doc.get("scenes"):
        issue("scenes", "SCENE_MISSING", "glTF has no scenes array or no scene to display.")
    scene_index = doc.get("scene", 0 if doc.get("scenes") else None)
    if scene_index is not None and (not isinstance(scene_index, int) or not 0 <= scene_index < len(doc.get("scenes", []))):
        issue("scene", "DEFAULT_SCENE_INVALID", "Default scene index is out of range.", "error")
    if not meshes:
        issue("meshes", "NO_MESHES", "Asset contains no mesh objects.", "error")
    if not nodes:
        issue("nodes", "NO_NODES", "Asset contains no scene nodes.", "error")
    if materials and not used_material_indices:
        issue("materials", "MATERIALS_UNREFERENCED", "Materials exist but no primitive references them.")
    extensions_used = sorted(doc.get("extensionsUsed", []))
    extensions_required = sorted(doc.get("extensionsRequired", []))
    for required in extensions_required:
        if required not in extensions_used:
            issue("extensionsRequired", "REQUIRED_EXTENSION_NOT_USED", f"Required extension {required!r} is absent from extensionsUsed.", "error")

    primitive_count = max(total_primitives, 1)
    triangle_primitives = sum(1 for m in mesh_reports for p in m["primitives"] if p.get("mode") == 4)
    # UVs are only required when a referenced material uses a texture; tangent frames
    # are specifically useful for normal maps. Do not penalize a plain-color mesh for
    # not carrying attributes it does not consume.
    textured_material_indices = {m["index"] for m in material_reports if m["texture_maps"]}
    normal_mapped_material_indices = {m["index"] for m in material_reports if "normal" in m["texture_maps"]}
    textured_triangles = 0
    textured_uv0_present = 0
    normal_mapped_triangles = 0
    normal_mapped_tangent_present = 0
    for mesh_report in mesh_reports:
        for primitive_report in mesh_report["primitives"]:
            if primitive_report.get("mode") != 4:
                continue
            mat_i = primitive_report.get("material")
            attrs = set(primitive_report.get("attributes", []))
            if mat_i in textured_material_indices:
                textured_triangles += 1
                textured_uv0_present += int("TEXCOORD_0" in attrs)
            if mat_i in normal_mapped_material_indices:
                normal_mapped_triangles += 1
                normal_mapped_tangent_present += int("TANGENT" in attrs)
    geometry_score = 100.0
    geometry_score -= 30 * len([e for e in errors if e["code"].startswith(("POSITION", "INDEX", "NORMAL_COUNT", "UV_COUNT"))])
    geometry_score -= 12 * max(0, triangle_primitives - normals_present)
    geometry_score -= 6 * max(0, textured_triangles - textured_uv0_present)
    geometry_score -= 4 * max(0, normal_mapped_triangles - normal_mapped_tangent_present)
    geometry_score -= min(20.0, normals_bad * 0.5)
    geometry_score -= min(10.0, degenerate_triangles * 0.25)
    geometry_score = max(0, min(100, round(geometry_score, 1)))
    material_score = 100.0
    if materials:
        textured_materials = sum(bool(m["texture_maps"]) for m in material_reports)
        material_score -= 10 * max(0, len(materials) - len(used_material_indices))
        # A material need not have textures. Score only basic integrity here.
        material_score -= 20 * sum(1 for e in errors if e["code"].startswith("TEXTURE_"))
        material_score -= 10 * sum(1 for e in errors if e["code"].startswith("IMAGE_"))
    else:
        material_score = 85.0 if meshes else 0.0  # default glTF material is valid.
    material_score = max(0, min(100, round(material_score, 1)))
    delivery_score = 100.0 - min(60, 10 * sum(1 for w in warnings if w["code"] in {"EXTERNAL_IMAGE_URI", "DRACO_NOT_DECODED"}))
    delivery_score = max(0, min(100, round(delivery_score, 1)))
    structural_score = round(0.55 * geometry_score + 0.30 * material_score + 0.15 * delivery_score, 1)

    report = {
        "audit_version": "m3l.gltf_quality.v1",
        "asset": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                  "glb_version": 2, "generator": doc.get("asset", {}).get("generator"),
                  "asset_version": doc.get("asset", {}).get("version"),
                  "chunks": [{"type": "JSON" if c["type"] == _JSON_CHUNK else "BIN" if c["type"] == _BIN_CHUNK else f"0x{c['type']:08x}", "bytes": c["length"]} for c in chunks],
                  "bin_bytes": len(bin_blob)},
        "counts": {"nodes": len(nodes), "meshes": len(meshes), "primitives": total_primitives,
                   "vertices": total_vertices, "triangles": total_triangles, "materials": len(materials),
                   "textures": len(textures), "images": len(images), "animations": len(doc.get("animations", [])),
                   "skins": len(doc.get("skins", [])), "cameras": len(doc.get("cameras", []))},
        "geometry": {"mesh_reports": mesh_reports,
                     "primitive_normal_coverage": round(normals_present / primitive_count, 3),
                     "primitive_uv0_coverage": round(uv0_present / primitive_count, 3),
                     "primitive_tangent_coverage": round(tangents_present / primitive_count, 3),
                     "textured_primitive_uv0_coverage": round(textured_uv0_present / max(1, textured_triangles), 3),
                     "normal_mapped_primitive_tangent_coverage": round(normal_mapped_tangent_present / max(1, normal_mapped_triangles), 3),
                     "nonfinite_position_primitives": pos_nonfinite,
                     "degenerate_triangles_repeating_index": degenerate_triangles,
                     "note": "This does not test self-intersections, geometric deviation from reference, or artistic quality."},
        "materials": {"reports": material_reports, "texture_map_material_counts": dict(map_counts),
                      "images": images, "extensions_used": extensions_used, "extensions_required": extensions_required},
        "scores": {"technical_structural_score": structural_score,
                   "geometry_integrity_score": geometry_score,
                   "material_delivery_score": material_score,
                   "asset_delivery_score": delivery_score,
                   "interpretation": "Rule-based structural health indicator only; not a visual or artistic quality score."},
        "errors": errors, "warnings": warnings,
        "valid": len(errors) == 0,
    }
    return report
