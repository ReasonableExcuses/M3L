"""Model Context Protocol (MCP) server for M3L (JSON-RPC 2.0 stdio transport).

Allows AI agents and IDEs to directly validate, compile, judge, diff, patch,
and discover M3L 3D assets deterministically over standard input/output.
"""
from __future__ import annotations

import base64
import json
import sys
from typing import Any

from .compiler import compile_source, semantic_diff, apply_patches, MATERIAL_PRESETS
from .glb import export_glb
from .judge import judge_result


TOOLS = [
    {
        "name": "m3l_validate",
        "description": "Parse and validate M3L 3D declarative source without full mesh compilation. Returns structured diagnostics (errors, warnings, line numbers, repair suggestions).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The complete M3L scene source text."
                }
            },
            "required": ["source"]
        }
    },
    {
        "name": "m3l_compile",
        "description": "Compile M3L source to a binary glTF (GLB) 3D asset with procedural meshes and materials. Returns compilation status, summary, byte count, base64-encoded GLB, and diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The complete M3L scene source text."
                },
                "out_path": {
                    "type": "string",
                    "description": "Optional file path to write the compiled GLB directly to disk."
                }
            },
            "required": ["source"]
        }
    },
    {
        "name": "m3l_judge",
        "description": "Execute deterministic preflight quality judge on M3L source: audits 2-manifold closure, boundary edges, nonmanifold edges, signed volumes, and presentation readiness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The complete M3L scene source text."
                },
                "require_camera": {
                    "type": "boolean",
                    "description": "Whether to require an explicit camera block for pass verdict."
                }
            },
            "required": ["source"]
        }
    },
    {
        "name": "m3l_diff",
        "description": "Compute semantic AST difference between two versions of an M3L scene source.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_a": {
                    "type": "string",
                    "description": "The baseline M3L source text."
                },
                "source_b": {
                    "type": "string",
                    "description": "The updated M3L source text."
                }
            },
            "required": ["source_a", "source_b"]
        }
    },
    {
        "name": "m3l_patch",
        "description": "Apply targeted semantic property updates or geometric patches to an M3L scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The original M3L source text."
                },
                "patches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "op": {"type": "string", "enum": ["set", "delete"]},
                            "field": {"type": "string"},
                            "value": {}
                        },
                        "required": ["target", "op", "field"]
                    },
                    "description": "List of patch operations to apply."
                }
            },
            "required": ["source", "patches"]
        }
    },
    {
        "name": "m3l_export",
        "description": "Export M3L scene to industry-standard 3D formats: 'glb', 'obj', 'stl', or 'usd'. Returns content/base64 and summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The complete M3L scene source text."
                },
                "format": {
                    "type": "string",
                    "enum": ["glb", "obj", "stl", "usd"],
                    "description": "Target export format (default: 'glb')."
                },
                "out_path": {
                    "type": "string",
                    "description": "Optional file path to write directly to disk."
                }
            },
            "required": ["source"]
        }
    },
    {
        "name": "m3l_capabilities",
        "description": "Discover all active capabilities of the M3L 3D engine: CSG booleans, lofts, splines, subdivision, filleted primitives, materials, and instancing.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "m3l_schema",
        "description": "Retrieve the complete declarative language grammar, primitive dictionary, and diagnostic error codes schema for AI prompt conditioning.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def handle_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "m3l_validate":
        res = compile_source(args["source"])
        diags = res.get("diagnostics", [])
        errors = sum(1 for d in diags if d.get("severity") == "error")
        warnings = sum(1 for d in diags if d.get("severity") == "warning")
        return {
            "valid": res.get("valid", False),
            "errors": errors,
            "warnings": warnings,
            "diagnostics": diags,
        }

    elif name == "m3l_compile":
        res = compile_source(args["source"])
        if not res.get("valid"):
            return {
                "valid": False,
                "summary": res.get("summary", {}),
                "diagnostics": res.get("diagnostics", []),
            }
        glb_bytes = export_glb(res["scene"])
        out_path = args.get("out_path")
        if out_path:
            with open(out_path, "wb") as f:
                f.write(glb_bytes)
        return {
            "valid": True,
            "glb_bytes": len(glb_bytes),
            "glb_base64": base64.b64encode(glb_bytes).decode("ascii"),
            "out_path": out_path,
            "summary": res.get("summary", {}),
            "diagnostics": res.get("diagnostics", []),
        }

    elif name == "m3l_judge":
        res = compile_source(args["source"])
        if not res.get("valid"):
            return {
                "verdict": "rejected",
                "ready_for_visual_review": False,
                "diagnostics": res.get("diagnostics", []),
            }
        judge = judge_result(res, require_camera=bool(args.get("require_camera", False)))
        return judge

    elif name == "m3l_diff":
        res_a = compile_source(args["source_a"]) if isinstance(args["source_a"], str) else {"scene": args["source_a"]}
        res_b = compile_source(args["source_b"]) if isinstance(args["source_b"], str) else {"scene": args["source_b"]}
        if not res_a.get("scene") or not res_b.get("scene"):
            return {"error": "Both sources must be valid M3L scenes to compute semantic diff."}
        diff = semantic_diff(res_a["scene"], res_b["scene"])
        return diff

    elif name == "m3l_patch":
        res = compile_source(args["source"])
        if not res.get("valid"):
            return {"ok": False, "error": "Source must be syntactically valid before applying patches."}
        patched_scene = apply_patches(res["scene"], args.get("patches", []))
        return {"ok": True, "scene": patched_scene}

    elif name == "m3l_export":
        src = args.get("source", "")
        fmt = args.get("format", "glb").lower()
        out_path = args.get("out_path")
        res = compile_source(src)
        if not res["valid"] or res["scene"] is None:
            return {"ok": False, "valid": False, "diagnostics": res["diagnostics"], "summary": res["summary"]}

        from .exporters import export_obj, export_stl, export_usd
        if fmt == "obj":
            content = export_obj(res["scene"])
            if out_path:
                Path(out_path).write_text(content, encoding="utf-8")
            return {"ok": True, "format": "obj", "content": content, "summary": res["summary"]}
        elif fmt == "stl":
            data = export_stl(res["scene"], binary=True)
            if out_path:
                Path(out_path).write_bytes(data)
            return {"ok": True, "format": "stl", "base64": base64.b64encode(data).decode("ascii"), "bytes": len(data), "summary": res["summary"]}
        elif fmt == "usd":
            content = export_usd(res["scene"])
            if out_path:
                Path(out_path).write_text(content, encoding="utf-8")
            return {"ok": True, "format": "usd", "content": content, "summary": res["summary"]}
        else:
            glb_bytes = export_glb(res["scene"])
            if out_path:
                Path(out_path).write_bytes(glb_bytes)
            return {"ok": True, "format": "glb", "base64": base64.b64encode(glb_bytes).decode("ascii"), "bytes": len(glb_bytes), "summary": res["summary"]}

    elif name == "m3l_capabilities":
        return {
            "engine": "M3L v0.7.0 Supremacy Edition",
            "primitives": [
                "box", "sphere", "cylinder", "cone", "torus",
                "extrude", "revolve", "sweep", "loft",
                "boolean", "subdivision"
            ],
            "kinematics": ["snap_to_ground", "align_bottom", "attach_to", "mirror_copy"],
            "joints": ["revolute", "prismatic", "ball", "fixed"],
            "animation": ["rotation", "translation", "scale", "keyframes", "linear", "step", "cubic_spline"],
            "lods": ["decimate_mesh", "generate_lods", "multi_lod_export"],
            "exporters": ["glb", "obj", "stl", "usd", "step"],
            "splines": ["linear", "catmull_rom", "cubic_bezier", "b_spline"],
            "booleans": ["difference", "union", "intersection"],
            "fillets": ["box.fillet", "box.fillet_segments"],
            "instancing": ["prototype", "instance"],
            "scene_graph": ["group", "param"],
            "material_presets": sorted(list(MATERIAL_PRESETS.keys())),
            "procedural_surfaces": [
                "carbon_fiber", "brushed_metal", "anodized_metal",
                "rubber", "ceramic_glaze", "leather_grain", "wood_grain", "fabric_weave"
            ],
            "textures": ["base_texture", "normal_texture", "roughness_texture", "uv_scale", "uv_offset"],
            "render_flags": ["double_sided"],
            "topology_guarantees": [
                "guaranteed_2_manifold",
                "watertight_zero_boundary",
                "deterministic_byte_for_byte_glb",
                "zero_eval_ai_safety"
            ]
        }

    elif name == "m3l_schema":
        return {
            "format": "m3l",
            "version": "0.7.0",
            "syntax_rules": [
                "Declarative block syntax: <type> <name> { <prop> = <value> }",
                "Top-level blocks: scene, material, param, prototype, group, instance, camera, light, joint, animation",
                "Primitives: box, sphere, cylinder, cone, torus, extrude, revolve, sweep, loft, boolean, subdivision",
                "Joints: joint <name> { type = revolute; parent = ...; child = ...; anchor = [...]; axis = [...]; limits = [...] }",
                "Animations: animation <name> { target = ...; channel = rotation_y; keyframes = [{time: 0, value: 0}, ...] }",
                "Units default to meters (m)",
                "Vectors are bracketed lists: [x, y, z]",
                "Colors are hex strings: #rrggbb",
                "Double-sided rendering enabled by default for mirrored instances and thin shells"
            ]
        }

    else:
        raise ValueError(f"Unknown MCP tool: {name!r}")


def run_mcp_server():
    """Main JSON-RPC stdio event loop."""
    sys.stderr.write("M3L MCP Server running on stdio...\n")
    sys.stderr.flush()

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "m3l-mcp-server",
                        "version": "0.6.0"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOLS
                }
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            try:
                result_payload = handle_tool_call(tool_name, tool_args)
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result_payload, indent=2)
                            }
                        ]
                    }
                }
            except Exception as e:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing {tool_name}: {e}"
                            }
                        ]
                    }
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_mcp_server()
