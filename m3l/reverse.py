"""Lossless GLB packaging and restricted semantic reverse-compilation.

The archive preserves the source GLB as the fidelity anchor. The .m3la projection
exposes a deliberately small set of editable scene/material properties; it does
not claim to reconstruct original CAD or procedural modeling history.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from .quality import GLBFormatError, audit_glb, parse_glb

PROJECTION_SCHEMA = "m3l.asset_projection.v1"
PACKAGE_SCHEMA = "m3l.lossless_package.v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clone(value):
    return json.loads(json.dumps(value))


def decompile_glb(data: bytes) -> dict[str, Any]:
    """Produce an editable semantic projection tied to exact source bytes."""
    doc, _bin_blob, _chunks = parse_glb(data)
    nodes = []
    for i, node in enumerate(doc.get("nodes", [])):
        nodes.append({"index": i, "name": node.get("name"),
                      "translation": _clone(node.get("translation")),
                      "rotation": _clone(node.get("rotation")),
                      "scale": _clone(node.get("scale")),
                      "mesh": node.get("mesh"), "children": _clone(node.get("children", []))})
    materials = []
    for i, material in enumerate(doc.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        materials.append({
            "index": i, "name": material.get("name"),
            "base_color_factor": _clone(pbr.get("baseColorFactor")),
            "metallic_factor": pbr.get("metallicFactor"),
            "roughness_factor": pbr.get("roughnessFactor"),
            "emissive_factor": _clone(material.get("emissiveFactor")),
            "alpha_mode": material.get("alphaMode"),
            "alpha_cutoff": material.get("alphaCutoff"),
            "double_sided": material.get("doubleSided"),
            "texture_refs": {
                "base_color": _clone(pbr.get("baseColorTexture")),
                "metallic_roughness": _clone(pbr.get("metallicRoughnessTexture")),
                "normal": _clone(material.get("normalTexture")),
                "occlusion": _clone(material.get("occlusionTexture")),
                "emissive": _clone(material.get("emissiveTexture")),
            },
            "extensions": sorted(material.get("extensions", {}).keys()),
        })
    meshes = []
    for i, mesh in enumerate(doc.get("meshes", [])):
        primitive_reports = []
        for pi, primitive in enumerate(mesh.get("primitives", [])):
            primitive_reports.append({"index": pi, "mode": primitive.get("mode", 4),
                                     "attributes": sorted(primitive.get("attributes", {}).keys()),
                                     "material": primitive.get("material"),
                                     "indices_accessor": primitive.get("indices")})
        meshes.append({"index": i, "name": mesh.get("name"), "primitives": primitive_reports})
    audit = audit_glb(data)
    return {
        "schema": PROJECTION_SCHEMA,
        "source_sha256": _sha(data),
        "source_bytes": len(data),
        "asset": {"version": doc.get("asset", {}).get("version"),
                  "generator": doc.get("asset", {}).get("generator"),
                  "scene_count": len(doc.get("scenes", [])),
                  "default_scene": doc.get("scene", 0 if doc.get("scenes") else None),
                  "extensions_used": sorted(doc.get("extensionsUsed", [])),
                  "extensions_required": sorted(doc.get("extensionsRequired", []))},
        "edit_contract": {
            "editable_node_fields": ["name", "translation", "rotation", "scale"],
            "editable_material_fields": ["name", "base_color_factor", "metallic_factor", "roughness_factor", "emissive_factor", "alpha_mode", "alpha_cutoff", "double_sided"],
            "read_only": ["mesh geometry", "indices", "normals", "tangents", "UVs", "textures and image payloads", "animations", "skins", "cameras", "extension payloads", "texture references", "node hierarchy", "mesh/material indices"],
            "note": "This is a semantic projection of a final asset, not recovered authoring/CAD history."},
        "nodes": nodes, "meshes": meshes, "materials": materials,
        "summary": audit["counts"],
    }


def _json_chunks(data: bytes):
    doc, _bin_blob, chunks = parse_glb(data)
    records = []
    for chunk in chunks:
        start = chunk["offset"]
        payload = data[start:start + chunk["length"]]
        records.append((chunk["type"], payload))
    return doc, records


def _rewrite_json_chunk(original: bytes, new_doc: dict[str, Any]) -> bytes:
    _old_doc, records = _json_chunks(original)
    encoded = json.dumps(new_doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    rewritten = []
    saw_json = False
    for chunk_type, payload in records:
        if chunk_type == 0x4E4F534A:
            if saw_json:
                raise GLBFormatError("Cannot rewrite GLB with multiple JSON chunks.")
            rewritten.append((chunk_type, encoded))
            saw_json = True
        else:
            rewritten.append((chunk_type, payload))
    if not saw_json:
        raise GLBFormatError("GLB has no JSON chunk.")
    total_length = 12 + sum(8 + len(payload) for _, payload in rewritten)
    out = bytearray(struct_pack_header(total_length))
    for chunk_type, payload in rewritten:
        out.extend(struct_pack_chunk_header(len(payload), chunk_type))
        out.extend(payload)
    # Validate generated binary structure before returning it.
    parse_glb(bytes(out))
    return bytes(out)


def struct_pack_header(total_length: int) -> bytes:
    import struct
    return struct.pack("<4sII", b"glTF", 2, total_length)


def struct_pack_chunk_header(length: int, chunk_type: int) -> bytes:
    import struct
    return struct.pack("<II", length, chunk_type)


def compile_asset_projection(original: bytes, projection: dict[str, Any]) -> bytes:
    """Apply whitelisted projection edits; preserve all non-JSON chunk payloads."""
    if not isinstance(projection, dict) or projection.get("schema") != PROJECTION_SCHEMA:
        raise ValueError(f"Expected projection schema {PROJECTION_SCHEMA!r}.")
    source_hash = _sha(original)
    if projection.get("source_sha256") != source_hash:
        raise ValueError("Projection source_sha256 does not match the supplied original GLB. Use the exact source asset this projection was derived from.")
    canonical = decompile_glb(original)
    allowed_top_level = {"schema", "source_sha256", "source_bytes", "asset", "edit_contract", "nodes", "meshes", "materials", "summary"}
    unknown_top = set(projection) - allowed_top_level
    if unknown_top:
        raise ValueError(f"Unsupported projection top-level fields: {sorted(unknown_top)}")
    if projection.get("asset") != canonical.get("asset") or projection.get("edit_contract") != canonical.get("edit_contract") or projection.get("meshes") != canonical.get("meshes") or projection.get("summary") != canonical.get("summary") or projection.get("source_bytes") != canonical.get("source_bytes"):
        raise ValueError("Asset metadata, mesh structure, summary, and edit contract are read-only.")
    # No-op path is a special exact restore, preserving original JSON formatting and padding.
    if projection == canonical:
        return original
    doc, _bin_blob, _chunks = parse_glb(original)
    input_nodes = projection.get("nodes")
    input_materials = projection.get("materials")
    if not isinstance(input_nodes, list) or len(input_nodes) != len(doc.get("nodes", [])):
        raise ValueError("Projection nodes must match the original node table length; structural node edits are not supported.")
    if not isinstance(input_materials, list) or len(input_materials) != len(doc.get("materials", [])):
        raise ValueError("Projection materials must match the original material table length; structural material edits are not supported.")

    node_allowed = {"name", "translation", "rotation", "scale"}
    for expected_index, item in enumerate(input_nodes):
        if not isinstance(item, dict) or item.get("index") != expected_index:
            raise ValueError("Projection node indices must be stable and in original order.")
        if item.get("mesh") != canonical["nodes"][expected_index].get("mesh") or item.get("children", []) != canonical["nodes"][expected_index].get("children", []):
            raise ValueError(f"Node {expected_index}: mesh assignment and hierarchy are read-only.")
        unknown = set(item) - ({"index", "mesh", "children"} | node_allowed)
        if unknown:
            raise ValueError(f"Node {expected_index}: unsupported projection fields: {sorted(unknown)}")
        target = doc["nodes"][expected_index]
        for key in node_allowed:
            val = item.get(key)
            if val is None:
                target.pop(key, None)
            else:
                if key in ("translation", "scale"):
                    if not isinstance(val, list) or len(val) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math_isfinite(x) for x in val):
                        raise ValueError(f"Node {expected_index} {key} must be three finite numbers or null.")
                    if key == "scale" and any(float(x) == 0 for x in val):
                        raise ValueError(f"Node {expected_index} scale components must be non-zero.")
                elif key == "rotation":
                    if not isinstance(val, list) or len(val) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math_isfinite(x) for x in val):
                        raise ValueError(f"Node {expected_index} rotation must be four finite quaternion components or null.")
                    norm = sum(float(x) ** 2 for x in val) ** 0.5
                    if norm < 1e-12:
                        raise ValueError(f"Node {expected_index} rotation quaternion cannot be zero.")
                elif key == "name" and not isinstance(val, str):
                    raise ValueError(f"Node {expected_index} name must be a string or null.")
                target[key] = _clone(val)

    material_allowed = {"name", "base_color_factor", "metallic_factor", "roughness_factor", "emissive_factor", "alpha_mode", "alpha_cutoff", "double_sided"}
    for expected_index, item in enumerate(input_materials):
        if not isinstance(item, dict) or item.get("index") != expected_index:
            raise ValueError("Projection material indices must be stable and in original order.")
        original_m = canonical["materials"][expected_index]
        if item.get("texture_refs") != original_m.get("texture_refs") or item.get("extensions", []) != original_m.get("extensions", []):
            raise ValueError(f"Material {expected_index}: texture references and extension payloads are read-only.")
        unknown = set(item) - ({"index", "texture_refs", "extensions"} | material_allowed)
        if unknown:
            raise ValueError(f"Material {expected_index}: unsupported projection fields: {sorted(unknown)}")
        target = doc["materials"][expected_index]
        pbr = target.setdefault("pbrMetallicRoughness", {})
        for proj_key, gltf_key in (("name", "name"), ("base_color_factor", "baseColorFactor"),
                                   ("metallic_factor", "metallicFactor"), ("roughness_factor", "roughnessFactor"),
                                   ("emissive_factor", "emissiveFactor"), ("alpha_mode", "alphaMode"),
                                   ("alpha_cutoff", "alphaCutoff"), ("double_sided", "doubleSided")):
            val = item.get(proj_key)
            if proj_key == "name":
                dest = target
            elif proj_key in ("base_color_factor", "metallic_factor", "roughness_factor"):
                dest = pbr
            elif proj_key in ("emissive_factor", "alpha_mode", "alpha_cutoff", "double_sided"):
                dest = target
            else:
                dest = target
            if val is None:
                dest.pop(gltf_key, None)
                continue
            if proj_key in ("metallic_factor", "roughness_factor", "alpha_cutoff"):
                if isinstance(val, bool) or not isinstance(val, (int, float)) or not math_isfinite(val):
                    raise ValueError(f"Material {expected_index} {proj_key} must be a finite number or null.")
                if proj_key in ("metallic_factor", "roughness_factor") and not 0 <= val <= 1:
                    raise ValueError(f"Material {expected_index} {proj_key} must be in [0,1].")
                if proj_key == "alpha_cutoff" and val < 0:
                    raise ValueError("alpha_cutoff must be >= 0.")
            elif proj_key in ("base_color_factor", "emissive_factor"):
                width = 4 if proj_key == "base_color_factor" else 3
                if not isinstance(val, list) or len(val) != width or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math_isfinite(x) for x in val):
                    raise ValueError(f"Material {expected_index} {proj_key} must be a {width}-element finite numeric array or null.")
                if proj_key == "base_color_factor" and any(x < 0 or x > 1 for x in val):
                    raise ValueError("base_color_factor values must be in [0,1].")
            elif proj_key == "alpha_mode" and val not in ("OPAQUE", "MASK", "BLEND"):
                raise ValueError("alpha_mode must be OPAQUE, MASK, BLEND, or null.")
            elif proj_key == "double_sided" and not isinstance(val, bool):
                raise ValueError("double_sided must be boolean or null.")
            elif proj_key == "name" and not isinstance(val, str):
                raise ValueError("material name must be string or null.")
            dest[gltf_key] = _clone(val)
        if not pbr:
            target.pop("pbrMetallicRoughness", None)

    return _rewrite_json_chunk(original, doc)


def math_isfinite(value: Any) -> bool:
    import math
    return math.isfinite(float(value))


def pack_glb(data: bytes) -> bytes:
    """Create a ZIP-based .m3lp package holding the exact source and projection."""
    projection = decompile_glb(data)
    manifest = {"schema": PACKAGE_SCHEMA, "source_sha256": _sha(data), "source_bytes": len(data),
                "projection_file": "source.m3la", "asset_file": "source.glb",
                "note": "The original GLB is the lossless fidelity anchor; the projection is a constrained editor view."}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, payload in (("manifest.json", (json.dumps(manifest, indent=2) + "\n").encode()),
                              ("source.m3la", (json.dumps(projection, indent=2, ensure_ascii=False) + "\n").encode()),
                              ("source.glb", data)):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, payload)
    return out.getvalue()


def restore_package(package: bytes) -> bytes:
    """Restore exact source bytes from a .m3lp package after integrity verification."""
    try:
        with zipfile.ZipFile(io.BytesIO(package), "r") as zf:
            names = set(zf.namelist())
            if not {"manifest.json", "source.glb", "source.m3la"}.issubset(names):
                raise ValueError("Package is missing one or more required files.")
            manifest = json.loads(zf.read("manifest.json"))
            original = zf.read("source.glb")
            projection = json.loads(zf.read("source.m3la"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid M3L lossless package: {exc}") from exc
    if manifest.get("schema") != PACKAGE_SCHEMA:
        raise ValueError("Unsupported M3L package schema.")
    digest = _sha(original)
    if digest != manifest.get("source_sha256") or digest != projection.get("source_sha256"):
        raise ValueError("Package source hash validation failed.")
    if len(original) != manifest.get("source_bytes"):
        raise ValueError("Package source length validation failed.")
    parse_glb(original)
    return original


def write_json(path: str | Path, value: Any):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
