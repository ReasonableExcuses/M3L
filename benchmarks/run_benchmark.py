"""Microbenchmark the deterministic M3L compile/export path.

This deliberately excludes LLM token/API time and rendering time. It is a reproducible
instrumentation baseline, not a performance comparison against Blender or other systems.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from m3l import __version__, compile_source, export_glb  # noqa: E402
from m3l.geometry import audit_mesh  # noqa: E402


def percentile(values, p):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * p
    lo, hi = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--out", default="dist/BENCHMARKS.json")
    args = parser.parse_args()
    if args.iterations < 3 or args.iterations > 1000:
        parser.error("--iterations must be between 3 and 1000")

    rows = []
    for source_path in sorted((ROOT / "examples").glob("*.m3l")):
        source = source_path.read_text(encoding="utf-8")
        first = compile_source(source)
        if not first["valid"] or first["scene"] is None:
            rows.append({"source": source_path.name, "status": "invalid_example",
                         "diagnostics": first["diagnostics"]})
            continue
        compile_ms, export_ms = [], []
        blob = b""
        compiled = first
        # One warmup run is discarded.
        export_glb(first["scene"])
        for _ in range(args.iterations):
            start = time.perf_counter()
            compiled = compile_source(source)
            compile_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            blob = export_glb(compiled["scene"])
            export_ms.append((time.perf_counter() - start) * 1000)
        objects = compiled["scene"]["objects"]
        custom = [o for o in objects if o.get("geometry", {}).get("mesh")]
        audits = [audit_mesh(o["geometry"]["mesh"]) for o in custom]
        rows.append({
            "source": source_path.name, "status": "ok", "iterations": args.iterations,
            "source_bytes": len(source.encode("utf-8")), "glb_bytes": len(blob),
            "objects": len(objects), "custom_mesh_objects": len(custom),
            "custom_mesh_triangles": sum(a.get("triangle_count", 0) for a in audits),
            "custom_meshes_watertight": sum(bool(a.get("watertight")) for a in audits),
            "compile_ms_median": round(statistics.median(compile_ms), 4),
            "compile_ms_p95": round(percentile(compile_ms, .95), 4),
            "export_ms_median": round(statistics.median(export_ms), 4),
            "export_ms_p95": round(percentile(export_ms, .95), 4),
        })
    report = {"m3l_version": __version__, "python": sys.version.split()[0],
              "platform": platform.platform(), "iterations": args.iterations,
              "scope": "compile/export only; excludes LLM inference, network, Blender rendering, and external baselines",
              "results": rows}
    out_path = (ROOT / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out_path), "rows": len(rows),
                      "ok": sum(r.get("status") == "ok" for r in rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
