import json
import struct
import tempfile
import unittest
from pathlib import Path

from m3l import compile_source, export_glb
from m3l.blender_backend import BlenderUnavailableError, blender_render_script, discover_blender, render_source
from m3l.geometry import audit_mesh
from m3l.judge import judge_result
from m3l.api import Handler

ROOT = Path(__file__).resolve().parents[1]


class GeometryV03Tests(unittest.TestCase):
    def test_scene_name_is_not_overwritten_by_last_object_bound(self):
        source = '''scene "scene_name_must_survive" {
  box first {
    size = [1, 1, 1]
  }
  box last {
    size = [1, 1, 1]
    at = [2, 0, 0]
  }
}
'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["scene"]["name"], "scene_name_must_survive")

    def source(self, name):
        return (ROOT / "examples" / name).read_text(encoding="utf-8")

    def parse_glb(self, blob):
        magic, version, length = struct.unpack("<4sII", blob[:12])
        self.assertEqual(magic, b"glTF")
        self.assertEqual(version, 2)
        self.assertEqual(length, len(blob))
        json_len, json_type = struct.unpack("<I4s", blob[12:20])
        self.assertEqual(json_type, b"JSON")
        return json.loads(blob[20:20 + json_len].decode("utf-8"))

    def test_bracket_extrusion_is_closed_solid(self):
        result = compile_source(self.source("bracket.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        obj = next(o for o in result["scene"]["objects"] if o["name"] == "bracket_body")
        audit = audit_mesh(obj["geometry"]["mesh"])
        self.assertTrue(audit["valid"], audit)
        self.assertTrue(audit["watertight"], audit)
        self.assertGreater(audit["absolute_volume"], 0)

    def test_vase_revolve_is_closed_solid(self):
        result = compile_source(self.source("vase.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        obj = next(o for o in result["scene"]["objects"] if o["name"] == "vase_body")
        audit = audit_mesh(obj["geometry"]["mesh"])
        self.assertTrue(audit["valid"], audit)
        self.assertTrue(audit["watertight"], audit)
        self.assertGreater(audit["triangle_count"], 1000)
        self.assertEqual(obj["geometry"]["mesh"]["shading"], "smooth")

    def test_mixed_scene_compiles_with_all_three_geometry_families(self):
        result = compile_source(self.source("design_study.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual({o["type"] for o in result["scene"]["objects"]}, {"box", "extrude", "revolve"})
        report = judge_result(result, require_camera=True)
        topology = next(c for c in report["checks"] if c["name"] == "custom_mesh_topology")
        self.assertEqual(topology["status"], "pass", topology)

    def test_tube_sweep_is_closed_and_glb_exportable(self):
        result = compile_source(self.source("handle.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        obj = next(o for o in result["scene"]["objects"] if o["name"] == "handle_tube")
        audit = audit_mesh(obj["geometry"]["mesh"])
        self.assertTrue(audit["valid"], audit)
        self.assertTrue(audit["watertight"], audit)
        self.assertEqual(obj["geometry"]["mesh"]["shading"], "smooth")
        self.assertTrue(export_glb(result["scene"]).startswith(b"glTF"))

    def test_custom_mesh_glb_contains_valid_accessors_and_nodes(self):
        result = compile_source(self.source("vase.m3l"))
        blob = export_glb(result["scene"])
        doc = self.parse_glb(blob)
        self.assertEqual(doc["asset"]["generator"], "M3L compiler 0.5")
        self.assertTrue(doc["accessors"])
        self.assertTrue(doc["bufferViews"])
        self.assertGreaterEqual(len(doc["meshes"]), 2)
        vase = next(node for node in doc["nodes"] if node.get("name") == "vase_body")
        self.assertIn("mesh", vase)

    def test_custom_mesh_units_convert_in_node_transform(self):
        source = '''scene "cm_profile" {
  units = cm
  extrude plate {
    profile = [[0, 0], [10, 0], [10, 8], [0, 8]]
    depth = 2
    at = [100, 5, 0]
  }
}'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        doc = self.parse_glb(export_glb(result["scene"]))
        node = next(n for n in doc["nodes"] if n.get("name") == "plate")
        self.assertEqual(node["translation"], [1.0, 0.05, 0.0])
        self.assertEqual(node["scale"], [0.01, 0.01, 0.01])

    def test_self_intersecting_profile_is_rejected(self):
        source = '''scene "bad_profile" {
  extrude x {
    profile = [[0, 0], [2, 2], [0, 2], [2, 0], [3, 0]]
    depth = 0.2
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E180", {d["code"] for d in result["diagnostics"]})

    def test_negative_revolve_radius_is_rejected(self):
        source = '''scene "negative_radius" {
  revolve x {
    profile = [[-0.2, 0], [0.5, 0], [0.4, 1], [0, 1]]
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E180", {d["code"] for d in result["diagnostics"]})

    def test_render_script_is_valid_python_without_blender_runtime(self):
        script = blender_render_script()
        self.assertIn("bpy.ops.import_scene.gltf", script)
        self.assertIn("M3L Preview Floor", script)
        compile(script, "render_m3l.py", "exec")

    def test_explicit_missing_blender_binary_is_reported(self):
        self.assertIsNone(discover_blender("/definitely/not/a/blender/executable"))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BlenderUnavailableError):
                render_source(self.source("vase.m3l"), Path(tmp) / "preview.png",
                              blender_bin="/definitely/not/a/blender/executable")

    def test_malformed_box_size_vector_returns_diagnostic(self):
        source = '''scene "bad_box" {
  box block {
    size = [1, 2]
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E122", {d["code"] for d in result["diagnostics"]})

    def test_grid_array_rejects_custom_geometry_types(self):
        source = '''scene "bad_array" {
  array shapes {
    shape = extrude
    counts = [2, 1, 1]
    step = [1, 0, 0]
    at = [0, 0, 0]
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E170", {d["code"] for d in result["diagnostics"]})

    def test_supported_by_checks_every_array_instance_on_concave_extrusion(self):
        source = '''scene "support_check" {
  extrude bracket {
    profile = [[0, 0], [0.48, 0], [0.48, 0.18], [0.19, 0.18], [0.19, 0.72], [0, 0.72]]
    depth = 0.12
    at = [-0.24, 0.09, -0.36]
  }
  array heads {
    shape = cylinder
    counts = [2, 1, 2]
    step = [0.27, 0, 0.41]
    at = [-0.105, 0.16, -0.255]
    radius = 0.035
    height = 0.025
  }
  constraint heads_supported {
    kind = supported_by
    object = heads
    target = bracket
    tolerance = 0.01
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        support_errors = [d for d in result["diagnostics"] if d["code"] == "E164"]
        self.assertTrue(support_errors)
        self.assertIn("not wholly supported", support_errors[0]["message"])

    def test_supported_by_does_not_crash_when_target_profile_is_invalid(self):
        source = '''scene "invalid_support" {
  extrude bracket {
    profile = [[0, 0], [1, 0], [0, 1], [1, 1]]
    depth = 0.1
  }
  box foot {
    size = [0.1, 0.1, 0.1]
    at = [0, 0.1, 0]
  }
  constraint foot_supported {
    kind = supported_by
    object = foot
    target = bracket
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertTrue({d["code"] for d in result["diagnostics"]} & {"E180", "E164"})

    def test_bracket_example_passes_array_support_constraints(self):
        result = compile_source(self.source("bracket.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["summary"]["constraint_count"], 2)
        report = judge_result(result)
        constraint_check = next(c for c in report["checks"] if c["name"] == "constraints")
        self.assertEqual(constraint_check["status"], "pass", constraint_check)

    def test_api_schema_and_capabilities_announce_platform_v05_and_scene_v03(self):
        class FakeHandler:
            def __init__(self, path):
                self.path = path
                self.payload = None
            def _send(self, status, payload, content_type="application/json"):
                self.payload = (status, payload)
        schema_handler = FakeHandler("/v1/schema")
        Handler.do_GET(schema_handler)
        self.assertEqual(schema_handler.payload[0], 200)
        self.assertEqual(schema_handler.payload[1]["version"], "0.3")
        self.assertIn("revolve", schema_handler.payload[1]["primitives"])
        self.assertIn("sweep", schema_handler.payload[1]["primitives"])
        self.assertIn("supported_by", schema_handler.payload[1]["constraint_kinds"])
        caps_handler = FakeHandler("/v1/capabilities")
        Handler.do_GET(caps_handler)
        self.assertEqual(caps_handler.payload[1]["version"], "0.5.0")
        self.assertIn("rendering", caps_handler.payload[1])
        self.assertIn("cad_export", caps_handler.payload[1])
        schema = schema_handler.payload[1]
        self.assertEqual(schema["cad_export"]["format"], "STEP")
        self.assertIn("POST /v1/export/step", schema["endpoints"])


if __name__ == "__main__":
    unittest.main()
