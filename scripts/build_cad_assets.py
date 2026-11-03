"""Build STEP/B-rep deliverables for every valid example (requires optional CadQuery)."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from m3l import __version__, compile_source  # noqa: E402
from m3l.cadquery_backend import CadQueryUnavailableError, export_step, discover_cadquery  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not discover_cadquery():
        print("CadQuery/OpenCascade is not installed. Install with: pip install -e '.[cad]'", file=sys.stderr)
        return 2
    out_dir = ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets, skipped = [], []
    for source_path in sorted((ROOT / "examples").glob("*.m3l")):
        result = compile_source(source_path.read_text(encoding="utf-8"))
        if not result["valid"] or result["scene"] is None:
            skipped.append({"source": source_path.name, "diagnostics": result["diagnostics"]})
            continue
        step_path = out_dir / f"{source_path.stem}.step"
        report = export_step(result["scene"], step_path, output_unit="MM")
        assets.append({"source": source_path.name, "scene_name": result["scene"]["name"],
                       "step": step_path.name, "sha256": sha256(step_path),
                       "bytes": step_path.stat().st_size, "units": "MM",
                       "object_count": report["object_count"],
                       "body_audits": report["objects"], "kernel": report["kernel"]})
    manifest = {"m3l_version": __version__, "backend": "CadQuery/OpenCascade",
                "format": "STEP", "output_unit": "MM", "build_script": "scripts/build_cad_assets.py",
                "valid_examples": assets, "skipped_invalid_examples": skipped}
    target = out_dir / "CAD_MANIFEST.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(target), "built": len(assets), "skipped": len(skipped),
                      "assets": [{"step": x["step"], "bytes": x["bytes"], "objects": x["object_count"]}
                                 for x in assets]}, indent=2))
    return 0 if assets and not [item for item in skipped if item["source"] != "invalid.m3l"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
