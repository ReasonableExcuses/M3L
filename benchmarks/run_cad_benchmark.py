"""Small STEP backend benchmark; reports local timings, not comparative performance."""
from __future__ import annotations
import argparse
import json
import math
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from m3l import __version__, compile_source  # noqa: E402
from m3l.cadquery_backend import CadQueryUnavailableError, discover_cadquery, export_step  # noqa: E402


def percentile(values, p):
    vals = sorted(values)
    return vals[max(0, min(len(vals) - 1, math.ceil(p * len(vals)) - 1))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 20:
        parser.error("--iterations must be between 1 and 20")
    if not discover_cadquery():
        print("CadQuery/OpenCascade optional dependency missing; install with pip install -e '.[cad]'", file=sys.stderr)
        return 2
    import cadquery as cq
    records = []
    with tempfile.TemporaryDirectory(prefix="m3l-cad-bench-") as tmp:
        tmp = Path(tmp)
        for source_path in sorted((ROOT / "examples").glob("*.m3l")):
            source = source_path.read_text(encoding="utf-8")
            compile_start = time.perf_counter()
            result = compile_source(source)
            compile_ms = (time.perf_counter() - compile_start) * 1000
            if not result["valid"] or result["scene"] is None:
                records.append({"source": source_path.name, "status": "invalid_example",
                                "diagnostics": result["diagnostics"]})
                continue
            timings, sizes = [], []
            for idx in range(args.iterations):
                path = tmp / f"{source_path.stem}-{idx}.step"
                start = time.perf_counter()
                report = export_step(result["scene"], path, output_unit="MM")
                timings.append((time.perf_counter() - start) * 1000)
                sizes.append(path.stat().st_size)
            records.append({"source": source_path.name, "status": "ok", "objects": report["object_count"],
                            "scene_compile_ms": round(compile_ms, 4),
                            "step_export_ms_median": round(statistics.median(timings), 4),
                            "step_export_ms_p95": round(percentile(timings, 0.95), 4),
                            "step_bytes": int(statistics.median(sizes)),
                            "solid_count": sum(row["solid_count"] for row in report["objects"]),
                            "kernel": report["kernel"]})
    result_doc = {"m3l_version": __version__, "python": platform.python_version(),
                  "platform": platform.platform(), "cadquery_version": cq.__version__,
                  "iterations": args.iterations,
                  "scope": "M3L compile and CadQuery/OpenCascade B-rep + STEP export; excludes LLM, network, rendering and external baselines",
                  "results": records}
    out = ROOT / "dist" / "CAD_BENCHMARKS.json"
    out.write_text(json.dumps(result_doc, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "ok": sum(r["status"] == "ok" for r in records),
                      "iterations": args.iterations}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
