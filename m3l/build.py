"""Build a reviewable, provenance-carrying M3L asset bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import __version__
from .compiler import compile_source
from .glb import export_glb
from .judge import judge_result
from .quality import audit_glb


BUNDLE_SCHEMA = "m3l.asset_bundle.v1"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_asset(source_path: str | Path, output_dir: str | Path, *,
                require_camera: bool = False) -> dict[str, Any]:
    """Compile source and write source, scene IR, GLB, audits, and a manifest.

    Files are written only after compilation, GLB export, and structural audit
    have succeeded. The manifest records hashes for every other bundle file.
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    try:
        source_bytes = source_path.read_bytes()
        source = source_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "stage": "read_source", "error": str(exc)}

    result = compile_source(source)
    if not result.get("valid") or result.get("scene") is None:
        return {"ok": False, "stage": "compile", "summary": result.get("summary"),
                "diagnostics": result.get("diagnostics", [])}

    try:
        glb_bytes = export_glb(result["scene"])
        quality = audit_glb(glb_bytes)
    except Exception as exc:
        return {"ok": False, "stage": "export", "error": str(exc)}
    if not quality.get("valid"):
        return {"ok": False, "stage": "audit", "quality": quality}

    preflight = judge_result(result, require_camera=require_camera)
    source_name = source_path.name
    stem = source_path.stem
    files: dict[str, bytes] = {
        f"{stem}.m3l": source_bytes,
        f"{stem}.scene.json": _json_bytes(result["scene"]),
        f"{stem}.glb": glb_bytes,
        f"{stem}.quality.json": _json_bytes(quality),
        f"{stem}.preflight.json": _json_bytes(preflight),
    }
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "compiler_version": __version__,
        "scene_schema": result["scene"].get("schema"),
        "provenance": result["scene"].get("provenance", {}),
        "source": {"path": source_name, "sha256": _sha256(source_bytes), "bytes": len(source_bytes)},
        "build": {"valid": True, "summary": result.get("summary"),
                  "preflight_verdict": preflight["verdict"],
                  "ready_for_visual_review": preflight["ready_for_visual_review"],
                  "visual_review_required": preflight["visual_review_required"]},
        "artifacts": {
            name: {"sha256": _sha256(data), "bytes": len(data)}
            for name, data in files.items()
        },
        "quality_scope": "Structural GLB checks only; not an artistic-quality score.",
    }
    files["manifest.json"] = _json_bytes(manifest)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in files.items():
            (output_dir / name).write_bytes(payload)
    except OSError as exc:
        return {"ok": False, "stage": "write_bundle", "error": str(exc),
                "output_dir": str(output_dir)}

    return {"ok": True, "output_dir": str(output_dir),
            "source": source_name, "glb": f"{stem}.glb",
            "manifest": "manifest.json", "files": sorted(files),
            "glb_bytes": len(glb_bytes), "glb_sha256": _sha256(glb_bytes),
            "preflight_verdict": preflight["verdict"],
            "ready_for_visual_review": preflight["ready_for_visual_review"]}


def verify_asset_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Verify each bundled payload against its manifest hash and byte length."""
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"Cannot read bundle manifest: {exc}"}
    if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
        return {"ok": False, "error": f"Unsupported bundle schema; expected {BUNDLE_SCHEMA}."}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return {"ok": False, "error": "Bundle manifest has no artifact records."}

    checked = []
    errors = []
    for name, expected in sorted(artifacts.items()):
        if (not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}
                or not isinstance(expected, dict)):
            errors.append({"artifact": str(name), "error": "Invalid artifact record or path."})
            continue
        try:
            artifact_path = bundle_dir / name
            if artifact_path.resolve().parent != bundle_dir.resolve():
                raise OSError("Artifact path escapes the bundle directory.")
            payload = artifact_path.read_bytes()
        except OSError as exc:
            errors.append({"artifact": name, "error": str(exc)})
            continue
        actual_hash = _sha256(payload)
        actual_bytes = len(payload)
        hash_matches = actual_hash == expected.get("sha256")
        size_matches = actual_bytes == expected.get("bytes")
        checked.append({"artifact": name, "valid": hash_matches and size_matches,
                        "sha256": actual_hash, "bytes": actual_bytes})
        if not hash_matches or not size_matches:
            errors.append({"artifact": name, "error": "Hash or byte length does not match manifest.",
                           "hash_matches": hash_matches, "size_matches": size_matches})
    return {"ok": not errors, "bundle_dir": str(bundle_dir),
            "checked_count": len(checked), "checked": checked, "errors": errors}
