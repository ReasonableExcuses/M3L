import base64
import json
import unittest
from pathlib import Path

from m3l import compile_source, export_glb
from m3l.procedural_materials import SURFACE_PRESETS, generate_surface_maps
from m3l.quality import audit_glb, parse_glb

ROOT = Path(__file__).resolve().parents[1]


class ProceduralMaterialTests(unittest.TestCase):
    def source(self, surface="brushed_metal", resolution=128):
        return f'''scene "textured_part" {{
  units = m
  material finish {{
    base = "#8c9aa8"
    roughness = 0.28
    metallic = 0.85
    surface = {surface}
    texture_resolution = {resolution}
  }}
  revolve ring {{
    profile = [[0.18, -0.025], [0.24, -0.025], [0.24, 0.025], [0.18, 0.025]]
    segments = 48
    at = [0, 0.2, 0]
    material = finish
  }}
  camera {{
    at = [0.8, 0.7, 1.0]
    target = [0, 0.2, 0]
  }}
}}'''

    def test_surface_material_emits_uvs_tangents_and_embedded_pbr_maps(self):
        result = compile_source(self.source())
        self.assertTrue(result["valid"], result["diagnostics"])
        glb = export_glb(result["scene"])
        doc, _, _ = parse_glb(glb)
        self.assertEqual(len(doc["images"]), 3)
        self.assertEqual(len(doc["textures"]), 3)
        material = next(m for m in doc["materials"] if m["name"] == "finish")
        self.assertIn("baseColorTexture", material["pbrMetallicRoughness"])
        self.assertIn("metallicRoughnessTexture", material["pbrMetallicRoughness"])
        self.assertIn("normalTexture", material)
        self.assertIn("occlusionTexture", material)
        attrs = doc["meshes"][0]["primitives"][0]["attributes"]
        self.assertTrue({"POSITION", "NORMAL", "TEXCOORD_0", "TANGENT"}.issubset(attrs))
        report = audit_glb(glb)
        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(any(w["code"] == "NORMAL_MAP_WITHOUT_TANGENTS" for w in report["warnings"]))
        self.assertEqual(sum(1 for img in report["materials"]["images"] if img.get("decodes")), 3)

    def test_packed_orm_channels_follow_surface_multipliers(self):
        import io
        import numpy as np
        from PIL import Image
        from m3l.procedural_materials import SURFACE_PRESETS, generate_surface_maps

        for surface, preset in SURFACE_PRESETS.items():
            with self.subTest(surface=surface):
                maps = generate_surface_maps(surface, 128)
                orm = np.asarray(Image.open(io.BytesIO(maps["orm_png"])).convert("RGB"), dtype=np.float32) / 255.0
                # Roughness/metallic are glTF texture multipliers; scalar material
                # factors authored in M3L remain responsible for the overall response.
                self.assertAlmostEqual(float(orm[..., 1].mean()), preset["roughness"], delta=0.06)
                self.assertAlmostEqual(float(orm[..., 2].mean()), preset["metallic"], delta=0.01)
                self.assertGreater(float(orm[..., 0].mean()), 0.85)

    def test_all_surface_presets_are_deterministic(self):
        self.assertEqual(len(SURFACE_PRESETS), 8)
        for surface in SURFACE_PRESETS:
            first = generate_surface_maps(surface, 128)
            second = generate_surface_maps(surface, 128)
            self.assertEqual(first["base_color_png"], second["base_color_png"], surface)
            self.assertEqual(first["normal_png"], second["normal_png"], surface)
            self.assertEqual(first["orm_png"], second["orm_png"], surface)
            self.assertEqual(first["resolution"], 128)

    def test_unknown_surface_is_actionable_compile_diagnostic(self):
        result = compile_source(self.source(surface="platinum_unicorn"))
        self.assertFalse(result["valid"])
        self.assertIn("E112", {d["code"] for d in result["diagnostics"]})

    def test_texture_resolution_is_bounded(self):
        result = compile_source(self.source(resolution=8192))
        self.assertFalse(result["valid"])
        self.assertIn("E113", {d["code"] for d in result["diagnostics"]})

    def test_precision_lens_example_delivers_pbr_maps_without_technical_warnings(self):
        source = (ROOT / "examples" / "precision_lens.m3l").read_text(encoding="utf-8")
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["summary"]["object_count"], 38)
        blob = export_glb(result["scene"])
        report = audit_glb(blob)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["counts"]["textures"], 18)
        self.assertEqual(report["counts"]["images"], 18)
        self.assertEqual(report["geometry"]["textured_primitive_uv0_coverage"], 1.0)
        self.assertEqual(report["geometry"]["normal_mapped_primitive_tangent_coverage"], 1.0)
        self.assertEqual(report["scores"]["geometry_integrity_score"], 100.0)
        self.assertEqual(report["scores"]["material_delivery_score"], 100.0)
        self.assertEqual(report["warnings"], [])
        self.assertTrue({"KHR_materials_transmission", "KHR_materials_ior", "KHR_materials_clearcoat"}.issubset(report["materials"]["extensions_used"]))
        self.assertEqual(len(report["materials"]["extensions_used"]), len(set(report["materials"]["extensions_used"])))
        self.assertTrue(any(m["has_transmission"] for m in report["materials"]["reports"]))
        self.assertTrue(any(m["has_ior"] for m in report["materials"]["reports"]))
        self.assertTrue(any(m["has_clearcoat"] for m in report["materials"]["reports"]))

    def test_transmission_ior_and_clearcoat_emit_standard_gltf_extensions(self):
        source = self.source().replace(
            '    metallic = 0.85',
            '    metallic = 0.02\n    transmission = 0.94\n    ior = 1.52\n    clearcoat = 0.72\n    clearcoat_roughness = 0.08')
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        doc, _, _ = parse_glb(export_glb(result["scene"]))
        self.assertTrue({"KHR_materials_transmission", "KHR_materials_ior", "KHR_materials_clearcoat"}.issubset(doc["extensionsUsed"]))
        material = next(m for m in doc["materials"] if m["name"] == "finish")
        self.assertAlmostEqual(material["extensions"]["KHR_materials_transmission"]["transmissionFactor"], 0.94)
        self.assertAlmostEqual(material["extensions"]["KHR_materials_ior"]["ior"], 1.52)
        self.assertAlmostEqual(material["extensions"]["KHR_materials_clearcoat"]["clearcoatFactor"], 0.72)
        audit = audit_glb(export_glb(result["scene"]))
        self.assertTrue(audit["valid"], audit["errors"])
        self.assertTrue(any(row["has_transmission"] and row["has_ior"] and row["has_clearcoat"] for row in audit["materials"]["reports"]))

    def test_invalid_ior_is_actionable(self):
        source = self.source().replace('    metallic = 0.85', '    metallic = 0.85\n    ior = 0.8')
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E114", {item["code"] for item in result["diagnostics"]})

    def test_texture_material_compiles_through_http_api(self):
        from http.server import ThreadingHTTPServer
        from m3l.api import Handler
        import threading
        import urllib.request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"source": self.source(), "format": "glb"}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/compile", data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())
            self.assertTrue(data["valid"], data.get("diagnostics"))
            out = base64.b64decode(data["glb_base64"])
            doc, _, _ = parse_glb(out)
            self.assertEqual(len(doc.get("images", [])), 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
