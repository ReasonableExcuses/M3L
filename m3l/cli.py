from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compiler import compile_source, semantic_diff
from .glb import export_glb
from .judge import judge_result
from .blender_backend import BlenderUnavailableError, M3LRenderError, render_source
from .cadquery_backend import CadQueryUnavailableError, CadQueryExportError, export_step
from .quality import audit_glb, GLBFormatError
from .reverse import decompile_glb, compile_asset_projection, pack_glb, restore_package, write_json
from .procedural_materials import ProceduralMaterialsUnavailableError
from .build import build_asset, verify_asset_bundle
from .exporters import export_obj, export_stl, export_usd


def main(argv=None):
    ap = argparse.ArgumentParser(prog="m3l", description="Compile AI-authored M3L scenes.")
    sub = ap.add_subparsers(dest="command", required=True)
    for cmd in ("validate", "compile", "inspect", "judge"):
        p = sub.add_parser(cmd)
        p.add_argument("source", help="Path to a .m3l source file")
        if cmd == "compile":
            p.add_argument("--out", default="scene.glb", help="Output file path")
            p.add_argument("--format", choices=("glb", "obj", "stl", "usd"), default="glb", help="Output format (default: glb)")
            p.add_argument("--json", dest="json_out", help="Optional compiled scene IR JSON path")
        if cmd == "inspect":
            p.add_argument("--pretty", action="store_true", help="Pretty-print full scene IR")
        if cmd == "judge":
            p.add_argument("--require-camera", action="store_true", help="Treat a missing camera as a hard preflight failure")
    build_parser = sub.add_parser("build", help="Build a reviewable asset bundle from M3L source")
    build_parser.add_argument("source", help="Path to a .m3l source file")
    build_parser.add_argument("--out", default="asset_bundle", help="Output bundle directory")
    build_parser.add_argument("--require-camera", action="store_true",
                              help="Require a camera for visual-review readiness")
    verify_parser = sub.add_parser("verify-bundle", help="Verify asset bundle files against manifest hashes")
    verify_parser.add_argument("bundle", help="Asset bundle directory containing manifest.json")
    diff_parser = sub.add_parser("diff", help="Compare two M3L sources by compiled semantic changes")
    diff_parser.add_argument("before", help="Earlier .m3l source")
    diff_parser.add_argument("after", help="Later .m3l source")
    diff_parser.add_argument("--out", help="Optional JSON report path")
    obj_parser = sub.add_parser("export-obj", help="Export scene to Wavefront OBJ format")
    obj_parser.add_argument("source", help="Path to a .m3l source file")
    obj_parser.add_argument("--out", default="scene.obj", help="Output OBJ path")

    stl_parser = sub.add_parser("export-stl", help="Export scene to Stereolithography (STL) format")
    stl_parser.add_argument("source", help="Path to a .m3l source file")
    stl_parser.add_argument("--out", default="scene.stl", help="Output STL path")
    stl_parser.add_argument("--ascii", action="store_true", help="Output ASCII STL instead of binary")

    usd_parser = sub.add_parser("export-usd", help="Export scene to Universal Scene Description (USDA) format")
    usd_parser.add_argument("source", help="Path to a .m3l source file")
    usd_parser.add_argument("--out", default="scene.usda", help="Output USDA path")

    step_parser = sub.add_parser("export-step", help="Export B-rep solids to STEP with optional CadQuery/OpenCascade")
    step_parser.add_argument("source", help="Path to a .m3l source file")
    step_parser.add_argument("--out", default="scene.step", help="Output STEP path")
    step_parser.add_argument("--unit", choices=("M", "MM", "CM", "INCH", "FT"), default="MM",
                             help="STEP output unit (default: MM)")
    audit_parser = sub.add_parser("audit-glb", help="Audit GLB geometry attributes, materials, textures, and container structure")
    audit_parser.add_argument("asset", help="Input .glb file")
    audit_parser.add_argument("--out", help="Optional JSON report path")
    projection_parser = sub.add_parser("glb-decompile", help="Create an editable semantic .m3la projection from GLB")
    projection_parser.add_argument("asset", help="Input .glb file")
    projection_parser.add_argument("--out", default="asset.m3la", help="Output projection JSON path")
    pack_parser = sub.add_parser("glb-pack", help="Create a lossless .m3lp package from GLB")
    pack_parser.add_argument("asset", help="Input .glb file")
    pack_parser.add_argument("--out", default="asset.m3lp", help="Output package path")
    restore_parser = sub.add_parser("glb-restore", help="Restore exact source bytes from an M3L .m3lp package")
    restore_parser.add_argument("package", help="Input .m3lp package")
    restore_parser.add_argument("--out", default="restored.glb", help="Output GLB path")
    source_compile_parser = sub.add_parser("glb-compile-source", help="Apply approved .m3la edits to the exact original GLB")
    source_compile_parser.add_argument("asset", help="Original GLB used to create the projection")
    source_compile_parser.add_argument("projection", help="Edited .m3la projection JSON")
    source_compile_parser.add_argument("--out", default="edited.glb", help="Output GLB path")
    render_parser = sub.add_parser("render", help="Render a scene preview with Blender (optional dependency)")
    render_parser.add_argument("source", help="Path to a .m3l source file")
    render_parser.add_argument("--out", default="preview.png", help="Output PNG path")
    render_parser.add_argument("--blender", help="Blender executable path; otherwise uses M3L_BLENDER or PATH")
    render_parser.add_argument("--resolution", type=int, default=1024, help="Square render resolution: 64..4096")
    render_parser.add_argument("--samples", type=int, default=32, help="Cycles samples: 1..1024")
    render_parser.add_argument("--engine", choices=("eevee", "cycles"), default="eevee")
    render_parser.add_argument("--timeout", type=int, default=240, help="Render process timeout in seconds")
    mcp_parser = sub.add_parser("mcp", help="Run Model Context Protocol (MCP) server on stdio")
    args = ap.parse_args(argv)
    # Asset-level commands operate on GLB or package bytes rather than M3L source.
    if args.command == "mcp":
        from .mcp_server import run_mcp_server
        run_mcp_server()
        return 0
    if args.command == "audit-glb":
        try:
            report = audit_glb(Path(args.asset).read_bytes())
        except (OSError, GLBFormatError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 2
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if report["valid"] else 1
    if args.command == "glb-decompile":
        try:
            projection = decompile_glb(Path(args.asset).read_bytes())
            write_json(args.out, projection)
            print(json.dumps({"ok": True, "projection": args.out, "source_sha256": projection["source_sha256"],
                              "nodes": len(projection["nodes"]), "materials": len(projection["materials"]),
                              "meshes": len(projection["meshes"])}, indent=2))
            return 0
        except (OSError, GLBFormatError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 2
    if args.command == "glb-pack":
        try:
            data = Path(args.asset).read_bytes()
            payload = pack_glb(data)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_bytes(payload)
            print(json.dumps({"ok": True, "package": args.out, "source_bytes": len(data), "package_bytes": len(payload),
                              "source_sha256": __import__("hashlib").sha256(data).hexdigest()}, indent=2))
            return 0
        except (OSError, GLBFormatError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 2
    if args.command == "glb-restore":
        try:
            payload = restore_package(Path(args.package).read_bytes())
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_bytes(payload)
            print(json.dumps({"ok": True, "restored": args.out, "bytes": len(payload),
                              "sha256": __import__("hashlib").sha256(payload).hexdigest()}, indent=2))
            return 0
        except (OSError, ValueError, GLBFormatError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 2
    if args.command == "glb-compile-source":
        try:
            original = Path(args.asset).read_bytes()
            projection = json.loads(Path(args.projection).read_text(encoding="utf-8"))
            output = compile_asset_projection(original, projection)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_bytes(output)
            print(json.dumps({"ok": True, "asset": args.out, "bytes": len(output),
                              "sha256": __import__("hashlib").sha256(output).hexdigest(),
                              "exact_restore": output == original}, indent=2))
            return 0
        except (OSError, ValueError, GLBFormatError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 2

    if args.command == "build":
        report = build_asset(args.source, args.out, require_camera=args.require_camera)
        print(json.dumps(report, indent=2, ensure_ascii=False),
              file=sys.stdout if report.get("ok") else sys.stderr)
        return 0 if report.get("ok") else 1
    if args.command == "verify-bundle":
        report = verify_asset_bundle(args.bundle)
        print(json.dumps(report, indent=2, ensure_ascii=False),
              file=sys.stdout if report.get("ok") else sys.stderr)
        return 0 if report.get("ok") else 1
    if args.command == "diff":
        try:
            before = compile_source(Path(args.before).read_text(encoding="utf-8"))
            after = compile_source(Path(args.after).read_text(encoding="utf-8"))
        except OSError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 2
        if not before["valid"] or before["scene"] is None or not after["valid"] or after["scene"] is None:
            report = {"ok": False, "before_diagnostics": before["diagnostics"],
                      "after_diagnostics": after["diagnostics"]}
            print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1
        report = {"ok": True, **semantic_diff(before["scene"], after["scene"])}
        encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0

    source_path = Path(args.source)
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        return 2

    if args.command == "render":
        try:
            report = render_source(source, args.out, blender_bin=args.blender,
                                   resolution=args.resolution, samples=args.samples,
                                   engine=args.engine, timeout_seconds=args.timeout)
            print(json.dumps({"ok": True, **report}, indent=2))
            return 0
        except BlenderUnavailableError as exc:
            print(json.dumps({"ok": False, "code": "BLENDER_UNAVAILABLE", "error": str(exc)}), file=sys.stderr)
            return 2
        except M3LRenderError as exc:
            print(json.dumps({"ok": False, "code": exc.code, "error": str(exc), "details": exc.details}, indent=2), file=sys.stderr)
            return 1
    result = compile_source(source)
    if args.command in ("export-obj", "export-stl", "export-usd"):
        if not result["valid"] or result["scene"] is None:
            print(json.dumps({"valid": False, "summary": result["summary"],
                              "diagnostics": result["diagnostics"]}, indent=2), file=sys.stderr)
            return 1
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if args.command == "export-obj":
            out_path.write_text(export_obj(result["scene"]), encoding="utf-8")
        elif args.command == "export-stl":
            out_path.write_bytes(export_stl(result["scene"], binary=not args.ascii))
        elif args.command == "export-usd":
            out_path.write_text(export_usd(result["scene"]), encoding="utf-8")
        print(json.dumps({"valid": True, "file": str(out_path), "bytes": out_path.stat().st_size,
                          "format": args.command.replace("export-", ""), "summary": result["summary"]}, indent=2))
        return 0

    if args.command == "export-step":
        if not result["valid"] or result["scene"] is None:
            print(json.dumps({"valid": False, "summary": result["summary"],
                              "diagnostics": result["diagnostics"]}, indent=2), file=sys.stderr)
            return 1
        try:
            report = export_step(result["scene"], args.out, output_unit=args.unit)
            print(json.dumps({"ok": True, **report, "summary": result["summary"]}, indent=2))
            return 0
        except CadQueryUnavailableError as exc:
            print(json.dumps({"ok": False, "code": "CAD_BACKEND_UNAVAILABLE", "error": str(exc)}, indent=2), file=sys.stderr)
            return 2
        except CadQueryExportError as exc:
            print(json.dumps({"ok": False, "code": "CAD_EXPORT_FAILED", "error": str(exc)}, indent=2), file=sys.stderr)
            return 1
    if args.command == "validate":
        print(json.dumps({"valid": result["valid"], "summary": result["summary"],
                          "diagnostics": result["diagnostics"]}, indent=2))
    elif args.command == "judge":
        print(json.dumps(judge_result(result, require_camera=args.require_camera), indent=2))
    elif args.command == "inspect":
        output = result["scene"] if args.pretty else {"valid": result["valid"], "summary": result["summary"],
                                                        "diagnostics": result["diagnostics"]}
        print(json.dumps(output, indent=2))
    else:
        if not result["valid"] or result["scene"] is None:
            print(json.dumps({"valid": False, "summary": result["summary"],
                              "diagnostics": result["diagnostics"]}, indent=2), file=sys.stderr)
            return 1
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = getattr(args, "format", "glb")
        if fmt == "obj":
            out_path.write_text(export_obj(result["scene"]), encoding="utf-8")
        elif fmt == "stl":
            out_path.write_bytes(export_stl(result["scene"], binary=True))
        elif fmt == "usd":
            out_path.write_text(export_usd(result["scene"]), encoding="utf-8")
        else:
            try:
                output_glb = export_glb(result["scene"])
            except ProceduralMaterialsUnavailableError as exc:
                print(json.dumps({"valid": False, "code": "PROCEDURAL_MATERIALS_UNAVAILABLE", "error": str(exc)}, indent=2), file=sys.stderr)
                return 2
            out_path.write_bytes(output_glb)
        if args.json_out:
            json_path = Path(args.json_out)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(result["scene"], indent=2), encoding="utf-8")
        print(json.dumps({"valid": True, "glb": str(out_path), "bytes": out_path.stat().st_size,
                          "summary": result["summary"], "diagnostics": result["diagnostics"]}, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
