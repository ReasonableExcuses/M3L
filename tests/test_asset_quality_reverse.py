from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from m3l import compile_source, export_glb
from m3l.api import Handler
from m3l.quality import GLBFormatError, audit_glb, parse_glb
from m3l.reverse import (PROJECTION_SCHEMA, compile_asset_projection, decompile_glb,
                         pack_glb, restore_package)

ROOT = Path(__file__).resolve().parents[1]


class GLBQualityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "examples" / "vase.m3l").read_text(encoding="utf-8")
        result = compile_source(source)
        if not result["valid"]:
            raise AssertionError(result["diagnostics"])
        cls.glb = export_glb(result["scene"])

    def test_audit_reports_counts_and_scoped_score_meaning(self):
        report = audit_glb(self.glb)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["counts"]["meshes"] > 0, True)
        self.assertGreater(report["counts"]["triangles"], 500)
        self.assertIn("not a visual or artistic quality score", report["scores"]["interpretation"])
        self.assertEqual(len(report["asset"]["sha256"]), 64)

    def test_corrupt_declared_length_is_rejected(self):
        damaged = bytearray(self.glb)
        struct.pack_into("<I", damaged, 8, len(damaged) + 4)
        with self.assertRaises(GLBFormatError):
            audit_glb(bytes(damaged))

    def test_corrupt_accessor_index_is_reported_without_crash(self):
        doc, _bin, _chunks = parse_glb(self.glb)
        doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"] = 999999
        encoded = json.dumps(doc, separators=(",", ":")).encode()
        encoded += b" " * ((4 - len(encoded) % 4) % 4)
        chunks = []
        pos = 12
        while pos < len(self.glb):
            length, kind = struct.unpack_from("<II", self.glb, pos)
            chunk = self.glb[pos + 8:pos + 8 + length]
            chunks.append((kind, chunk))
            pos += 8 + length
        out_chunks = [(kind, encoded if kind == 0x4E4F534A else chunk) for kind, chunk in chunks]
        total = 12 + sum(8 + len(chunk) for _, chunk in out_chunks)
        out = bytearray(struct.pack("<4sII", b"glTF", 2, total))
        for kind, chunk in out_chunks:
            out.extend(struct.pack("<II", len(chunk), kind))
            out.extend(chunk)
        report = audit_glb(bytes(out))
        self.assertFalse(report["valid"])
        self.assertIn("POSITION_ACCESSOR_INVALID", {e["code"] for e in report["errors"]})


class ReverseCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "examples" / "robot.m3l").read_text(encoding="utf-8")
        result = compile_source(source)
        if not result["valid"]:
            raise AssertionError(result["diagnostics"])
        cls.glb = export_glb(result["scene"])

    def chunk_payloads(self, data):
        records = []
        offset = 12
        while offset < len(data):
            length, chunk_type = struct.unpack_from("<II", data, offset)
            payload = data[offset + 8:offset + 8 + length]
            records.append((chunk_type, payload))
            offset += 8 + length
        return records

    def test_decompile_noop_compile_is_byte_identical(self):
        projection = decompile_glb(self.glb)
        self.assertEqual(projection["schema"], PROJECTION_SCHEMA)
        self.assertEqual(compile_asset_projection(self.glb, projection), self.glb)

    def test_lossless_package_restores_exact_source(self):
        package = pack_glb(self.glb)
        restored = restore_package(package)
        self.assertEqual(restored, self.glb)
        self.assertEqual(hashlib.sha256(restored).digest(), hashlib.sha256(self.glb).digest())

    def test_transform_edit_preserves_all_non_json_chunk_payloads(self):
        projection = decompile_glb(self.glb)
        projection["nodes"][-1]["translation"] = [1.25, 2.0, -0.75]
        edited = compile_asset_projection(self.glb, projection)
        before = self.chunk_payloads(self.glb)
        after = self.chunk_payloads(edited)
        self.assertEqual([x for x in before if x[0] != 0x4E4F534A], [x for x in after if x[0] != 0x4E4F534A])
        old_doc = parse_glb(self.glb)[0]
        new_doc = parse_glb(edited)[0]
        self.assertEqual(new_doc["nodes"][-1]["translation"], [1.25, 2.0, -0.75])
        self.assertEqual(old_doc["buffers"][0]["byteLength"], new_doc["buffers"][0]["byteLength"])

    def test_material_edit_preserves_mesh_bin_chunk(self):
        projection = decompile_glb(self.glb)
        if not projection["materials"]:
            self.skipTest("fixture has no materials")
        projection["materials"][0]["roughness_factor"] = 0.37
        edited = compile_asset_projection(self.glb, projection)
        old_doc = parse_glb(self.glb)[0]
        new_doc = parse_glb(edited)[0]
        self.assertEqual(new_doc["materials"][0]["pbrMetallicRoughness"]["roughnessFactor"], 0.37)
        self.assertEqual([x for x in self.chunk_payloads(self.glb) if x[0] != 0x4E4F534A],
                         [x for x in self.chunk_payloads(edited) if x[0] != 0x4E4F534A])

    def test_projection_hash_must_match_exact_original(self):
        projection = decompile_glb(self.glb)
        projection["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            compile_asset_projection(self.glb, projection)

    def test_structural_node_edits_are_rejected(self):
        projection = decompile_glb(self.glb)
        projection["nodes"][0]["mesh"] = 999
        with self.assertRaisesRegex(ValueError, "hierarchy are read-only"):
            compile_asset_projection(self.glb, projection)

    def test_invalid_transform_is_rejected(self):
        projection = decompile_glb(self.glb)
        projection["nodes"][0]["scale"] = [0.0, 1.0, 1.0]
        with self.assertRaisesRegex(ValueError, "non-zero"):
            compile_asset_projection(self.glb, projection)

    def test_invalid_material_factor_is_rejected(self):
        projection = decompile_glb(self.glb)
        if not projection["materials"]:
            self.skipTest("fixture has no materials")
        projection["materials"][0]["roughness_factor"] = 1.5
        with self.assertRaisesRegex(ValueError, "in \[0,1\]"):
            compile_asset_projection(self.glb, projection)

    def test_tampered_package_is_rejected(self):
        package = bytearray(pack_glb(self.glb))
        package[-8] ^= 0xFF
        with self.assertRaises(ValueError):
            restore_package(bytes(package))


class QualityAPIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "examples" / "vase.m3l").read_text(encoding="utf-8")
        cls.glb = export_glb(compile_source(source)["scene"])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def post(self, route, payload):
        data = json.dumps(payload).encode()
        req = Request(self.base + route, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as res:
            return json.loads(res.read())

    def test_audit_api_returns_structural_report(self):
        result = self.post("/v1/quality/audit", {"glb_base64": base64.b64encode(self.glb).decode()})
        self.assertTrue(result["ok"])
        self.assertGreater(result["quality"]["counts"]["triangles"], 100)

    def test_decompile_and_compile_noop_via_api(self):
        result = self.post("/v1/glb/decompile", {"glb_base64": base64.b64encode(self.glb).decode()})
        projection = result["source_projection"]
        compiled = self.post("/v1/glb/compile-source", {
            "glb_base64": base64.b64encode(self.glb).decode(), "source_projection": projection})
        self.assertTrue(compiled["exact_restore"])
        self.assertEqual(base64.b64decode(compiled["glb_base64"]), self.glb)

    def test_package_restore_via_api(self):
        packed = self.post("/v1/glb/pack", {"glb_base64": base64.b64encode(self.glb).decode()})
        restored = self.post("/v1/glb/restore", {"package_base64": packed["package_base64"]})
        self.assertEqual(base64.b64decode(restored["glb_base64"]), self.glb)


if __name__ == "__main__":
    unittest.main()
