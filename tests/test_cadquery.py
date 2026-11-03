"""Optional integration tests for the CadQuery/OpenCascade B-rep backend."""
import tempfile
import unittest
import base64
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from m3l import compile_source
from m3l.cadquery_backend import discover_cadquery, export_step
from m3l.api import Handler

try:
    import cadquery as cq
except Exception:  # pragma: no cover - exercised when CAD optional extra is absent
    cq = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(discover_cadquery(), "CadQuery optional dependency is not installed")
class CadQueryBackendTests(unittest.TestCase):
    def source(self, name):
        return (ROOT / "examples" / name).read_text(encoding="utf-8")

    def test_all_valid_examples_export_and_round_trip_as_brep_solids(self):
        for source_path in sorted((ROOT / "examples").glob("*.m3l")):
            # This later experimental car scene uses v0.6 `loft`, while this
            # executable source tree is the v0.5.0 core. Do not misclassify that
            # documented version mismatch as a CAD-backend regression.
            if source_path.name == "lamborghini_revuelto_outer.m3l":
                continue
            with self.subTest(source=source_path.name):
                result = compile_source(source_path.read_text(encoding="utf-8"))
                if not result["valid"]:
                    self.assertEqual(source_path.name, "invalid.m3l")
                    continue
                with tempfile.TemporaryDirectory(prefix="m3l-step-test-") as tmp:
                    step_path = Path(tmp) / f"{source_path.stem}.step"
                    report = export_step(result["scene"], step_path, output_unit="MM")
                    self.assertGreater(report["bytes"], 256)
                    self.assertEqual(report["format"], "STEP")
                    self.assertEqual(report["object_count"], result["summary"]["object_count"])
                    loaded = cq.importers.importStep(str(step_path)).val()
                    self.assertTrue(loaded.isValid(), source_path.name)
                    self.assertEqual(len(loaded.Solids()), result["summary"]["object_count"])
                    self.assertGreater(loaded.Volume(), 0)


    def test_http_step_endpoint_returns_round_trippable_base64(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            source = self.source("bracket.m3l")
            data = json.dumps({"source": source, "unit": "MM"}).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/export/step",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["step"]["format"], "STEP")
            self.assertEqual(payload["step"]["object_count"], 5)
            step_bytes = base64.b64decode(payload["step_base64"])
            with tempfile.TemporaryDirectory(prefix="m3l-api-step-test-") as tmp:
                path = Path(tmp) / "api.step"
                path.write_bytes(step_bytes)
                loaded = cq.importers.importStep(str(path)).val()
                self.assertTrue(loaded.isValid())
                self.assertEqual(len(loaded.Solids()), 5)
        finally:
            server.shutdown()
            server.server_close()

    def test_step_export_converts_declared_meters_to_millimeters(self):
        source = '''scene "unit_test" {
  units = m
  box body {
    size = [1, 2, 3]
  }
}
'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        with tempfile.TemporaryDirectory(prefix="m3l-step-units-") as tmp:
            path = Path(tmp) / "unit_test.step"
            report = export_step(result["scene"], path, output_unit="MM")
            loaded = cq.importers.importStep(str(path)).val()
            bounds = loaded.BoundingBox()
            self.assertEqual(report["source_unit"], "M")
            self.assertEqual(report["output_unit"], "MM")
            self.assertAlmostEqual(bounds.xlen, 1000, delta=0.05)
            self.assertAlmostEqual(bounds.ylen, 2000, delta=0.05)
            self.assertAlmostEqual(bounds.zlen, 3000, delta=0.05)

    def test_nonuniform_scale_and_rotation_preserve_validity(self):
        source = '''scene "transformed" {
  box body {
    size = [1, 2, 3]
    at = [4, 5, 6]
    rotate = [12, 20, 33]
    scale = [1.5, 0.75, 2]
  }
}
'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        with tempfile.TemporaryDirectory(prefix="m3l-step-transform-") as tmp:
            path = Path(tmp) / "transformed.step"
            export_step(result["scene"], path, output_unit="MM")
            loaded = cq.importers.importStep(str(path)).val()
            self.assertTrue(loaded.isValid())
            self.assertEqual(len(loaded.Solids()), 1)
            self.assertGreater(loaded.Volume(), 0)


if __name__ == "__main__":
    unittest.main()
