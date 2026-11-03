#!/usr/bin/env python3
"""Benchmark M3L's deterministic GLB audit/package/restore path on local assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m3l.quality import audit_glb
from m3l.reverse import compile_asset_projection, decompile_glb, pack_glb, restore_package


def non_json_chunks(blob):
    chunks = []
    offset = 12
    while offset < len(blob):
        length, kind = struct.unpack_from("<II", blob, offset)
        payload = blob[offset + 8:offset + 8 + length]
        if kind != 0x4E4F534A:
            chunks.append((kind, hashlib.sha256(payload).hexdigest(), len(payload)))
        offset += 8 + length
    return chunks


def run_one(path: Path, out_dir: Path):
    original = path.read_bytes()
    t0 = time.perf_counter()
    audit = audit_glb(original)
    audit_seconds = time.perf_counter() - t0
    if not audit["valid"]:
        raise RuntimeError(f"Structural audit failed: {audit['errors'][:5]}")

    t0 = time.perf_counter()
    projection = decompile_glb(original)
    decompile_seconds = time.perf_counter() - t0
    t0 = time.perf_counter()
    compiled = compile_asset_projection(original, projection)
    compile_noop_seconds = time.perf_counter() - t0
    if compiled != original:
        raise RuntimeError("No-op reverse-compile was not byte-identical.")

    t0 = time.perf_counter()
    package = pack_glb(original)
    pack_seconds = time.perf_counter() - t0
    t0 = time.perf_counter()
    restored = restore_package(package)
    restore_seconds = time.perf_counter() - t0
    if restored != original:
        raise RuntimeError("Lossless package did not restore exact bytes.")
    if non_json_chunks(original) != non_json_chunks(compiled):
        raise RuntimeError("Non-JSON chunks changed during no-op reverse compile.")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{path.stem}.m3la").write_text(json.dumps(projection, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"{path.stem}.m3lp").write_bytes(package)
    (out_dir / f"{path.stem}.quality.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    return {
        "asset": path.name, "sha256": hashlib.sha256(original).hexdigest(), "source_bytes": len(original),
        "package_bytes": len(package), "package_overhead_percent": round((len(package) / max(1, len(original)) - 1) * 100, 3),
        "counts": audit["counts"], "scores": audit["scores"], "warnings": len(audit["warnings"]),
        "audit_seconds": round(audit_seconds, 6), "decompile_seconds": round(decompile_seconds, 6),
        "no_op_compile_seconds": round(compile_noop_seconds, 6), "pack_seconds": round(pack_seconds, 6),
        "restore_seconds": round(restore_seconds, 6), "exact_restore": restored == original,
        "non_json_chunks_preserved": True,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", default="dist", help="Directory containing .glb assets")
    ap.add_argument("--out", default="dist/QUALITY_BENCHMARKS.json", help="Benchmark JSON output")
    ap.add_argument("--work-dir", default="dist/quality_packages", help="Directory for .m3la/.m3lp/report files")
    args = ap.parse_args(argv)
    asset_dir = Path(args.assets)
    paths = sorted(p for p in asset_dir.glob("*.glb") if p.is_file())
    if not paths:
        ap.error(f"No .glb assets found in {asset_dir}")
    results, failures = [], []
    for path in paths:
        try:
            results.append(run_one(path, Path(args.work_dir)))
        except Exception as exc:
            failures.append({"asset": path.name, "error": f"{type(exc).__name__}: {exc}"})
    report = {"schema": "m3l.quality_benchmark.v1", "note": "Local microbenchmark, not an end-to-end LLM or visual-quality benchmark.",
              "assets_tested": len(paths), "passed": len(results), "failed": failures, "results": results}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out), **report}, indent=2))
    return 0 if results and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
