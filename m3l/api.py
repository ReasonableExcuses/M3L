"""Local HTTP API for connecting LLMs and agents to M3L."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .compiler import apply_patches, compile_source, semantic_diff
from .glb import export_glb
from .judge import judge_result
from .parser import parse
from .blender_backend import BlenderUnavailableError, M3LRenderError, discover_blender, render_source
from .cadquery_backend import (CadQueryUnavailableError, CadQueryExportError,
                               discover_cadquery, export_step)
from .quality import audit_glb, GLBFormatError
from .reverse import decompile_glb, compile_asset_projection, pack_glb, restore_package
from .procedural_materials import ProceduralMaterialsUnavailableError


class Handler(BaseHTTPRequestHandler):
    server_version = "M3L/0.5"

    def _send(self, status, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"", "application/octet-stream")

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/health":
            self._send(200, {"ok": True, "name": "M3L", "version": "0.5.0"})
        elif route == "/v1/capabilities":
            self._send(200, {"language": "M3L", "version": "0.5.0",
                             "features": ["declarative primitives", "grid arrays", "polygon extrusion", "lathe/revolve forms", "path sweeps", "geometric constraints", "validated feature graph", "asset revision provenance", "semantic scene diff", "GLB export", "STEP B-rep export", "incremental patches", "deterministic topology audit", "GLB structural quality audit", "lossless GLB packaging", "restricted semantic reverse compiler", "deterministic procedural PBR textures", "UV coordinates and tangent frames for textured meshes", "KHR_materials_transmission", "KHR_materials_ior", "KHR_materials_clearcoat", "multi-view diagnostic preview"],
                             "procedural_materials": {"available": importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("PIL") is not None,
                                                       "install_hint": "Install with `pip install -e '.[materials]'` to generate PBR texture maps."},
                             "rendering": {"backend": "Blender", "available": discover_blender() is not None,
                                           "install_hint": "Install Blender or set M3L_BLENDER to its executable path."},
                             "cad_export": {"backend": "CadQuery/OpenCascade", "available": discover_cadquery(),
                                            "format": "STEP", "install_hint": "Install the optional CadQuery package to export B-rep solids."}})
        elif route == "/v1/schema":
            self._send(200, {
                "language": "M3L", "platform_version": "0.5.0", "version": "0.3", "units": ["m", "cm", "mm", "in", "ft"],
                "primitives": {
                    "box": {"required": {"size": "number[3]"}},
                    "sphere": {"required": {"radius": "number"}, "optional": {"segments": "int 6..256", "rings": "int 4..128"}},
                    "cylinder": {"required": {"radius": "number", "height": "number"}, "optional": {"segments": "int 6..256"}},
                    "extrude": {"required": {"profile": "simple polygon of [x,z] points", "depth": "positive number"}, "optional": {"at": "number[3]", "rotate": "degrees[3]", "scale": "number[3]", "material": "material_name"}},
                    "revolve": {"required": {"profile": "simple closed [radius,y] cross-section"}, "optional": {"segments": "int 8..256, default 48", "at": "number[3]", "rotate": "degrees[3]", "scale": "number[3]", "material": "material_name"}},
                    "sweep": {"required": {"path": "2..256 [x,y,z] points", "radius": "positive number"}, "optional": {"segments": "int 6..128, default 16", "at": "number[3]", "rotate": "degrees[3]", "scale": "number[3]", "material": "material_name"}}
                },
                "common_object_properties": {"at": "number[3]", "rotate": "degrees[3]", "scale": "number[3]", "material": "material_name"},
                "feature_graph": {"parent": "existing feature name or root", "phase": ["form", "refinement", "detail", "material", "variant"], "layer": ["base_form", "refinement", "detail", "material", "variant"], "params": "JSON object", "max_nodes": 512, "must_be_acyclic": True},
                "material_properties": {"base": "#rrggbb", "roughness": "0..1", "metallic": "0..1", "emissive": "#rrggbb", "surface": {"enum": ["brushed_metal", "anodized_metal", "rubber", "ceramic_glaze", "carbon_fiber", "leather_grain", "wood_grain", "fabric_weave"]}, "texture_resolution": {"enum": [128, 256, 512, 1024], "default": 512, "requires": "optional numpy and Pillow packages"}, "transmission": "0..1; KHR_materials_transmission", "ior": "1..3; KHR_materials_ior", "clearcoat": "0..1; KHR_materials_clearcoat", "clearcoat_roughness": "0..1; KHR_materials_clearcoat"},
                "array": {"required": {"shape": "box|sphere|cylinder", "counts": "positive-int[3]", "step": "number[3]", "at": "number[3]"}, "optional": {"size": "number[3] for box", "radius": "number for sphere/cylinder", "height": "number for cylinder", "material": "material_name", "rotate": "degrees[3]", "scale": "number[3]"}, "max_instances": 1024},
                "constraint_kinds": ["above", "below", "inside", "separated", "supported_by"],
                "cad_export": {"format": "STEP", "backend": "optional CadQuery/OpenCascade", "supported_shapes": ["box", "sphere", "cylinder", "extrude", "revolve", "sweep"], "output_units": ["M", "MM", "CM", "INCH", "FT"]},
                "constraint_details": {"supported_by": "object may be a named object or array name; requires upright supported object and unrotated box/extrude target, bottom/top contact within tolerance, and full projected footprint on the support face"},
                "profile_limits": {"max_points": 256, "extrude_depth": "positive", "revolve_radius": "non-negative"},
                "endpoints": {
                    "POST /v1/validate": {"body": {"source": "M3L string"}},
                    "POST /v1/diff": {"body": {"before_source": "M3L string", "after_source": "M3L string"}, "response": "Semantic changes between valid compiled scenes and their asset revisions"},
                    "POST /v1/compile": {"body": {"source": "M3L string", "include_scene": "boolean?", "format": "scene|glb?"}},
                    "POST /v1/patch": {"body": {"source": "M3L string", "expected_revision": "asset revision?", "edits": "array of up to 500 safe semantic edits"}, "response": "Candidate source, base/candidate revisions, diagnostics, and semantic diff"},
                    "POST /v1/judge": {"body": {"source": "M3L string", "require_camera": "boolean?"}},
                    "POST /v1/render": {"body": {"source": "M3L string", "resolution": "int 64..4096?", "engine": "eevee|cycles?", "samples": "int 1..1024?"}, "response": "render PNG base64 plus hashes and scene metrics; requires Blender"},
                    "POST /v1/export/step": {"body": {"source": "M3L string", "unit": "M|MM|CM|INCH|FT?"}, "response": "STEP assembly base64 plus per-body validity/volume metadata; requires CadQuery/OpenCascade"},
                    "POST /v1/quality/audit": {"body": {"glb_base64": "base64 GLB bytes"}, "response": "Structural quality report; not an artistic score"},
                    "POST /v1/glb/decompile": {"body": {"glb_base64": "base64 GLB bytes"}, "response": "Editable m3l.asset_projection.v1"},
                    "POST /v1/glb/compile-source": {"body": {"glb_base64": "original GLB", "source_projection": "edited projection"}, "response": "GLB with whitelisted JSON-only edits; non-JSON chunks preserved"},
                    "POST /v1/glb/pack": {"body": {"glb_base64": "base64 GLB bytes"}, "response": "Lossless .m3lp package base64"},
                    "POST /v1/glb/restore": {"body": {"package_base64": "base64 .m3lp package"}, "response": "Exact source GLB bytes after hash verification"}
                }
            })
        else:
            self._send(404, {"error": "not_found", "message": "Use /health, /v1/capabilities, /v1/schema, /v1/validate, /v1/diff, /v1/judge, /v1/compile, /v1/patch, /v1/render, /v1/export/step, /v1/quality/audit, or /v1/glb/*."})

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 80_000_000:
                self._send(400, {"error": "invalid_request", "message": "Body must be between 1 byte and 80 MB."})
                return
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                self._send(400, {"error": "invalid_request", "message": "JSON body must be an object."})
                return
            if route == "/v1/diff":
                before_source, after_source = body.get("before_source"), body.get("after_source")
                if not isinstance(before_source, str) or not isinstance(after_source, str):
                    self._send(400, {"error": "invalid_request", "message": "Body must include string fields 'before_source' and 'after_source'."})
                    return
                before = compile_source(before_source)
                after = compile_source(after_source)
                if not before["valid"] or before["scene"] is None or not after["valid"] or after["scene"] is None:
                    self._send(422, {"ok": False, "before_diagnostics": before["diagnostics"],
                                     "after_diagnostics": after["diagnostics"]})
                    return
                self._send(200, {"ok": True, **semantic_diff(before["scene"], after["scene"])})
                return
            asset_routes = {"/v1/quality/audit", "/v1/glb/decompile", "/v1/glb/compile-source", "/v1/glb/pack", "/v1/glb/restore"}
            if route in asset_routes:
                field = "package_base64" if route == "/v1/glb/restore" else "glb_base64"
                encoded = body.get(field)
                if not isinstance(encoded, str) or len(encoded) > 70_000_000:
                    self._send(400, {"error": "invalid_request", "message": f"Body must include base64 string '{field}' within the size limit."})
                    return
                try:
                    asset_bytes = base64.b64decode(encoded, validate=True)
                except Exception:
                    self._send(400, {"error": "invalid_request", "message": f"'{field}' is not valid base64."})
                    return
                if len(asset_bytes) > 52_000_000:
                    self._send(413, {"error": "asset_too_large", "message": "Decoded asset exceeds the 52 MB API limit."})
                    return
                if route == "/v1/quality/audit":
                    report = audit_glb(asset_bytes)
                    self._send(200 if report["valid"] else 422, {"ok": report["valid"], "quality": report})
                elif route == "/v1/glb/decompile":
                    projection = decompile_glb(asset_bytes)
                    self._send(200, {"ok": True, "source_projection": projection})
                elif route == "/v1/glb/compile-source":
                    projection = body.get("source_projection")
                    if not isinstance(projection, dict):
                        self._send(400, {"error": "invalid_request", "message": "source_projection must be a JSON object."})
                        return
                    output = compile_asset_projection(asset_bytes, projection)
                    self._send(200, {"ok": True, "exact_restore": output == asset_bytes,
                                     "bytes": len(output), "sha256": __import__("hashlib").sha256(output).hexdigest(),
                                     "glb_base64": base64.b64encode(output).decode("ascii"), "mime_type": "model/gltf-binary"})
                elif route == "/v1/glb/pack":
                    output = pack_glb(asset_bytes)
                    self._send(200, {"ok": True, "source_bytes": len(asset_bytes), "package_bytes": len(output),
                                     "package_base64": base64.b64encode(output).decode("ascii"), "mime_type": "application/zip"})
                elif route == "/v1/glb/restore":
                    output = restore_package(asset_bytes)
                    self._send(200, {"ok": True, "bytes": len(output),
                                     "sha256": __import__("hashlib").sha256(output).hexdigest(),
                                     "glb_base64": base64.b64encode(output).decode("ascii"), "mime_type": "model/gltf-binary"})
                return
            if not isinstance(body.get("source"), str):
                self._send(400, {"error": "invalid_request", "message": "JSON body must include a string field named 'source'."})
                return
            if route == "/v1/validate":
                result = compile_source(body["source"])
                self._send(200, {"valid": result["valid"], "summary": result["summary"], "diagnostics": result["diagnostics"]})
            elif route == "/v1/judge":
                result = compile_source(body["source"])
                self._send(200, judge_result(result, require_camera=bool(body.get("require_camera", False))))
            elif route == "/v1/compile":
                result = compile_source(body["source"])
                payload = {"valid": result["valid"], "summary": result["summary"], "diagnostics": result["diagnostics"]}
                if body.get("include_scene", True):
                    payload["scene"] = result["scene"]
                if body.get("format", "scene") == "glb":
                    if not result["valid"] or result["scene"] is None:
                        self._send(422, payload)
                        return
                    payload["glb_base64"] = base64.b64encode(export_glb(result["scene"])).decode("ascii")
                    payload["glb_mime_type"] = "model/gltf-binary"
                self._send(200 if result["valid"] else 422, payload)
            elif route == "/v1/export/step":
                unit = body.get("unit", "MM")
                with tempfile.TemporaryDirectory(prefix="m3l-api-step-") as temp_dir:
                    output_path = Path(temp_dir) / "scene.step"
                    result = compile_source(body["source"])
                    if not result["valid"] or result["scene"] is None:
                        self._send(422, {"error": "scene_invalid", "valid": False,
                                         "summary": result["summary"], "diagnostics": result["diagnostics"]})
                        return
                    report = export_step(result["scene"], output_path, output_unit=unit)
                    report_data = {k: v for k, v in report.items() if k != "path"}
                    self._send(200, {"ok": True, "step": report_data,
                                     "step_base64": base64.b64encode(output_path.read_bytes()).decode("ascii")})
            elif route == "/v1/render":
                resolution = body.get("resolution", 1024)
                samples = body.get("samples", 32)
                engine = body.get("engine", "eevee")
                if isinstance(resolution, bool) or not isinstance(resolution, int) or not 64 <= resolution <= 4096:
                    self._send(400, {"error": "invalid_request", "code": "INVALID_RENDER_SETTINGS", "message": "resolution must be an integer from 64 to 4096."})
                    return
                if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 1024:
                    self._send(400, {"error": "invalid_request", "code": "INVALID_RENDER_SETTINGS", "message": "samples must be an integer from 1 to 1024."})
                    return
                if engine not in ("eevee", "cycles"):
                    self._send(400, {"error": "invalid_request", "code": "INVALID_RENDER_SETTINGS", "message": "engine must be 'eevee' or 'cycles'."})
                    return
                with tempfile.TemporaryDirectory(prefix="m3l-api-render-") as temp_dir:
                    output_path = Path(temp_dir) / "preview.png"
                    report = render_source(body["source"], output_path, resolution=resolution,
                                           samples=samples, engine=engine)
                    image_bytes = output_path.read_bytes()
                    self._send(200, {"ok": True, "render": {k: v for k, v in report.items() if k != "path"},
                                     "png_base64": base64.b64encode(image_bytes).decode("ascii")})
            elif route == "/v1/patch":
                edits = body.get("edits")
                if not isinstance(edits, list):
                    self._send(400, {"error": "invalid_request", "message": "'edits' must be an array."})
                    return
                if len(edits) > 500:
                    self._send(400, {"error": "invalid_request", "message": "'edits' is limited to 500 operations per request."})
                    return
                base_result = compile_source(body["source"])
                if not base_result["valid"] or base_result["scene"] is None:
                    self._send(422, {"error": "scene_invalid", "valid": False,
                                     "diagnostics": base_result["diagnostics"]})
                    return
                base_revision = base_result["scene"]["provenance"]["asset_revision"]
                expected_revision = body.get("expected_revision")
                if expected_revision is not None and expected_revision != base_revision:
                    self._send(409, {"error": "stale_revision", "expected_revision": expected_revision,
                                     "actual_revision": base_revision,
                                     "message": "The supplied source does not match expected_revision."})
                    return
                ast_scene = parse(body["source"])
                applied = apply_patches(ast_scene, edits)
                # The patch endpoint compiles from patched AST by regenerating canonical source.
                patched_source = _serialize_ast(ast_scene)
                result = compile_source(patched_source)
                payload = {"valid": result["valid"], "applied": applied, "source": patched_source,
                           "summary": result["summary"], "diagnostics": result["diagnostics"], "scene": result["scene"]}
                payload["base_revision"] = base_revision
                if result["valid"] and result["scene"] is not None:
                    payload["candidate_revision"] = result["scene"]["provenance"]["asset_revision"]
                    payload["diff"] = semantic_diff(base_result["scene"], result["scene"])
                if body.get("format") == "glb" and result["valid"]:
                    payload["glb_base64"] = base64.b64encode(export_glb(result["scene"])).decode("ascii")
                    payload["glb_mime_type"] = "model/gltf-binary"
                self._send(200 if result["valid"] else 422, payload)
            else:
                self._send(404, {"error": "not_found"})
        except ProceduralMaterialsUnavailableError as exc:
            self._send(503, {"error": "procedural_materials_unavailable", "code": "PROCEDURAL_MATERIALS_UNAVAILABLE", "message": str(exc)})
        except GLBFormatError as exc:
            self._send(422, {"error": "invalid_glb", "message": str(exc)})
        except CadQueryUnavailableError as exc:
            self._send(503, {"error": "cad_backend_unavailable", "code": "CAD_BACKEND_UNAVAILABLE", "message": str(exc)})
        except CadQueryExportError as exc:
            self._send(422, {"error": "cad_export_failed", "code": "CAD_EXPORT_FAILED", "message": str(exc)})
        except BlenderUnavailableError as exc:
            self._send(503, {"error": "render_backend_unavailable", "code": "BLENDER_UNAVAILABLE", "message": str(exc)})
        except M3LRenderError as exc:
            status = 422 if exc.code == "SCENE_INVALID" else 500
            self._send(status, {"error": "render_failed", "code": exc.code, "message": str(exc), "details": exc.details})
        except Exception as exc:
            self._send(400, {"error": "request_failed", "message": str(exc)})

    def log_message(self, fmt, *args):
        # Keep the local API quiet by default; callers still receive structured responses.
        return


def _fmt_value(value):
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_value(v) for v in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{json.dumps(str(k))}: {_fmt_value(v)}" for k, v in value.items())
        return "{" + items + "}"
    return str(value)


def _serialize_ast(ast_scene):
    lines = [f'scene {json.dumps(ast_scene["name"])} {{', f'  units = {_fmt_value(ast_scene.get("units", "m"))}', '']
    for name, props in ast_scene["materials"].items():
        lines.append(f'  material {name} {{')
        for k, v in props.items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    for feature in ast_scene.get("features", []):
        lines.append(f'  feature {feature["name"]} {{')
        for k, v in feature["props"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    for variant in ast_scene.get("variants", []):
        lines.append(f'  variant {variant["name"]} {{')
        for k, v in variant["props"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    for array in ast_scene.get("arrays", []):
        lines.append(f'  array {array["name"]} {{')
        for k, v in array["props"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    for obj in ast_scene["objects"]:
        lines.append(f'  {obj["type"]} {obj["name"]} {{')
        for k, v in obj["props"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    if ast_scene.get("camera") is not None:
        lines.append('  camera {')
        for k, v in ast_scene["camera"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    for item in ast_scene["lights"]:
        lines.append(f'  light {item["name"]} {{')
        for k, v in item["props"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    for item in ast_scene["constraints"]:
        lines.append(f'  constraint {item["name"]} {{')
        for k, v in item["props"].items():
            if k != "__lines__": lines.append(f'    {k} = {_fmt_value(v)}')
        lines.extend(['  }', ''])
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description="Run a local M3L HTTP API (binds to loopback by default).")
    ap.add_argument("--host", default="127.0.0.1", help="Bind address; keep loopback unless you add authentication.")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"M3L API listening on http://{args.host}:{args.port}")
    print("Endpoints: /health, /v1/capabilities, /v1/schema, /v1/validate, /v1/diff, /v1/judge, /v1/compile, /v1/patch, /v1/render, /v1/export/step, /v1/quality/audit, /v1/glb/decompile, /v1/glb/compile-source, /v1/glb/pack, /v1/glb/restore")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping M3L API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
