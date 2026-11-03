"""Rebuild all valid example GLBs, scene IR files, and an integrity manifest."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from m3l import __version__, compile_source, export_glb  # noqa: E402
from m3l.geometry import audit_mesh  # noqa: E402
from m3l.judge import judge_result  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    examples_dir = ROOT / "examples"
    dist_dir = ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    failed = []
    skipped_experimental = []
    for source_path in sorted(examples_dir.glob("*.m3l")):
        source_bytes = source_path.read_bytes()
        source = source_bytes.decode("utf-8")
        result = compile_source(source)
        if not result["valid"] or result["scene"] is None:
            # The v0.6 vehicle source is bundled as an artifact/source reference,
            # but this packaged executable CLI is v0.5.0 and has no `loft` type.
            # Preserve it in the archive while keeping v0.5 example rebuilds usable.
            if source_path.name == "lamborghini_revuelto_outer.m3l":
                skipped_experimental.append({"source": source_path.name,
                                             "reason": "requires v0.6 loft compiler; bundled runtime is v0.5.0"})
            else:
                failed.append({"source": source_path.name, "diagnostics": result["diagnostics"]})
            continue
        name = source_path.stem
        glb_path = dist_dir / f"{name}.glb"
        json_path = dist_dir / f"{name}.scene.json"
        glb_bytes = export_glb(result["scene"])
        scene_json = json.dumps(result["scene"], indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        glb_path.write_bytes(glb_bytes)
        json_path.write_bytes(scene_json)
        objects = result["scene"].get("objects", [])
        audits = []
        triangles = 0
        for obj in objects:
            mesh = obj.get("geometry", {}).get("mesh")
            if mesh:
                audits.append({"object": obj["name"], **audit_mesh(mesh)})
                triangles += len(mesh.get("triangles", []))
        entries.append({
            "source": source_path.name, "source_sha256": sha256(source_bytes),
            "glb": glb_path.name, "glb_sha256": sha256(glb_bytes), "glb_bytes": len(glb_bytes),
            "scene_ir": json_path.name, "scene_ir_sha256": sha256(scene_json), "scene_ir_bytes": len(scene_json),
            "valid": True, "summary": result["summary"],
            "object_types": {kind: sum(o["type"] == kind for o in objects)
                             for kind in sorted({o["type"] for o in objects})},
            "custom_mesh_audits": audits,
            "judge": judge_result(result, require_camera=False)["verdict"],
        })
    manifest = {"m3l_version": __version__, "ir_schema": "m3l.scene.v0.3",
                "build_script": "scripts/build_examples.py", "valid_examples": entries,
                "skipped_invalid_examples": failed,
                "skipped_experimental_incompatible_examples": skipped_experimental}
    manifest_path = dist_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"built": len(entries), "skipped_invalid": len(failed),
                      "skipped_experimental_incompatible": len(skipped_experimental),
                      "manifest": str(manifest_path),
                      "assets": [{"source": e["source"], "glb_bytes": e["glb_bytes"],
                                  "objects": e["summary"]["object_count"]} for e in entries]}, indent=2))
    return 1 if any(item["source"] != "invalid.m3l" for item in failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
