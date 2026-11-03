import json
import struct
import unittest
from pathlib import Path

from m3l import compile_source, export_glb, parse, apply_patches
from m3l.api import _serialize_ast
from m3l.geometry import beautify_mesh, mesh_quality_summary
from m3l.judge import judge_result

ROOT = Path(__file__).resolve().parents[1]


class M3LTests(unittest.TestCase):
    def source(self, name):
        return (ROOT / "examples" / name).read_text(encoding="utf-8")

    def test_stool_compiles(self):
        result = compile_source(self.source("stool.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["summary"]["object_count"], 6)
        self.assertEqual(result["summary"]["constraint_count"], 2)
        self.assertEqual(result["summary"]["array_count"], 1)
        generated_legs = [o for o in result["scene"]["objects"] if o.get("source_array") == "stool_legs"]
        self.assertEqual(len(generated_legs), 4)
        self.assertIn("stool_legs_1_0_1", {o["name"] for o in generated_legs})

    def test_robot_compiles(self):
        result = compile_source(self.source("robot.m3l"))
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertGreater(result["summary"]["object_count"], 8)

    def test_invalid_scene_returns_actionable_diagnostics(self):
        result = compile_source(self.source("invalid.m3l"))
        self.assertFalse(result["valid"])
        codes = {d["code"] for d in result["diagnostics"]}
        self.assertIn("E111", codes)
        self.assertIn("E122", codes)
        self.assertIn("E130", codes)
        self.assertIn("E101", codes)

    def test_glb_container_header_and_chunks(self):
        result = compile_source(self.source("stool.m3l"))
        blob = export_glb(result["scene"])
        magic, version, length = struct.unpack("<4sII", blob[:12])
        self.assertEqual(magic, b"glTF")
        self.assertEqual(version, 2)
        self.assertEqual(length, len(blob))
        json_len, json_type = struct.unpack("<I4s", blob[12:20])
        self.assertEqual(json_type, b"JSON")
        doc = json.loads(blob[20:20+json_len].decode("utf-8"))
        self.assertEqual(doc["asset"]["version"], "2.0")
        self.assertEqual(len(doc["meshes"]), 3)  # four legs share one instanced cylinder mesh
        self.assertEqual(len(doc["scenes"][0]["nodes"]), 9)  # 6 objects + camera + 2 lights
        self.assertIn("KHR_lights_punctual", doc["extensionsUsed"])

    def test_patch_round_trip(self):
        ast_scene = parse(self.source("stool.m3l"))
        applied = apply_patches(ast_scene, [{"op": "set", "target": "seat", "field": "at", "value": [0, 0.60, 0]}])
        self.assertEqual(len(applied), 1)
        recompiled = compile_source(_serialize_ast(ast_scene))
        self.assertTrue(recompiled["valid"], recompiled["diagnostics"])
        seat = next(o for o in recompiled["scene"]["objects"] if o["name"] == "seat")
        self.assertEqual(seat["transform"]["translation"], [0, 0.60, 0])

    def test_phase1_feature_graph_is_compiled(self):
        source = '''scene "feature_graph" {
  feature body {
    kind = "base_form"
    parent = "root"
    phase = "form"
    layer = "base_form"
    params = {"shape": "box", "size": [1, 1, 1]}
  }
  feature trim {
    kind = "detail"
    parent = "body"
    phase = "refinement"
    layer = "detail"
    params = {"width": 0.1, "count": 4}
  }
  box part {
    size = [1, 1, 1]
    at = [0, 0, 0]
  }
}'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        graph = result["scene"]["feature_graph"]
        self.assertEqual(graph["version"], "phase1")
        self.assertEqual(graph["node_count"], 2)
        self.assertEqual(graph["nodes"][0]["name"], "body")
        self.assertEqual(graph["layers"]["base_form"][0], "body")
        self.assertEqual(result["scene"]["features"][1]["params"]["width"], 0.1)

    def test_feature_patch_round_trip(self):
        source = '''scene "feature_patch" {
  feature body {
    kind = "base_form"
    parent = "root"
    params = {"shape": "box"}
  }
  feature trim {
    kind = "detail"
    parent = "body"
    params = {"width": 0.1}
  }
}'''
        ast_scene = parse(source)
        applied = apply_patches(ast_scene, [{"op": "set_feature", "target": "trim", "field": "params", "value": {"width": 0.2, "count": 6}}])
        self.assertEqual(applied[0]["target"], "trim")
        recompiled = compile_source(_serialize_ast(ast_scene))
        self.assertTrue(recompiled["valid"], recompiled["diagnostics"])
        self.assertEqual(recompiled["scene"]["features"][1]["params"]["width"], 0.2)

    def test_geometry_beauty_summary_is_stable(self):
        mesh = {"vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "triangles": [[0, 1, 2]]}
        summary = mesh_quality_summary(mesh)
        self.assertIn("quality_score", summary)
        self.assertIn("silhouette_score", summary)
        self.assertGreaterEqual(summary["quality_score"], 0.0)
        self.assertLessEqual(summary["quality_score"], 1.0)
        beautified = beautify_mesh(mesh, smoothness=0.8)
        self.assertEqual(beautified["shading"], "smooth")
        self.assertIn("render_normals", beautified)
        self.assertIn("quality", beautified)

    def test_parse_error_is_structured(self):
        result = compile_source('scene "broken" {\n box x {\n size = [1, 1, 1]\n')
        self.assertFalse(result["valid"])
        self.assertEqual(result["diagnostics"][0]["code"], "E001")

    def test_malformed_vector_is_diagnostic_not_crash(self):
        source = '''scene "bad_vector" {
  box b {
    size = [1, 1, 1]
    at = 7
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E121", {d["code"] for d in result["diagnostics"]})
        self.assertIsNotNone(result["scene"])

    def test_separated_constraint_rejects_overlap(self):
        source = '''scene "overlap" {
  box a {
    size = [1, 1, 1]
    at = [0, 0, 0]
  }
  box b {
    size = [1, 1, 1]
    at = [0.2, 0, 0]
  }
  constraint a_separate_from_b {
    kind = separated
    object = a
    target = b
    gap = 0
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E163", {d["code"] for d in result["diagnostics"]})

    def test_separated_constraint_allows_touching_boxes(self):
        source = '''scene "touching" {
  box a {
    size = [1, 1, 1]
    at = [0, 0, 0]
  }
  box b {
    size = [1, 1, 1]
    at = [1, 0, 0]
  }
  constraint a_separate_from_b {
    kind = separated
    object = a
    target = b
    gap = 0
    tolerance = 0.001
  }
}'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])

    def test_invalid_reference_value_does_not_crash(self):
        source = '''scene "bad_refs" {
  box a {
    size = [1, 1, 1]
    material = [1]
  }
  box b {
    size = [1, 1, 1]
    at = [0.2, 0, 0]
  }
  constraint broken {
    kind = [1]
    object = a
    target = b
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        codes = {d["code"] for d in result["diagnostics"]}
        self.assertIn("E130", codes)
        self.assertIn("E160", codes)

    def test_array_patch_updates_all_instances(self):
        ast_scene = parse(self.source("stool.m3l"))
        applied = apply_patches(ast_scene, [{"op": "set", "target": "stool_legs", "field": "step", "value": [0.4, 0, 0.4]}])
        self.assertEqual(applied[0]["target"], "stool_legs")
        result = compile_source(_serialize_ast(ast_scene))
        self.assertTrue(result["valid"], result["diagnostics"])
        leg = next(o for o in result["scene"]["objects"] if o["name"] == "stool_legs_1_0_1")
        self.assertEqual(leg["transform"]["translation"], [0.23, 0.25, 0.23])

    def test_array_expansion_is_bounded(self):
        source = '''scene "huge_array" {
  array too_many {
    shape = box
    counts = [100, 100, 100]
    step = [1, 1, 1]
    at = [0, 0, 0]
    size = [1, 1, 1]
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E172", {d["code"] for d in result["diagnostics"]})
        self.assertEqual(result["summary"]["object_count"], 0)

    def test_glb_converts_declared_units_to_meters(self):
        source = '''scene "centimeters" {
  units = cm
  box slab {
    size = [100, 20, 100]
    at = [0, 10, 0]
  }
}'''
        result = compile_source(source)
        self.assertTrue(result["valid"], result["diagnostics"])
        blob = export_glb(result["scene"])
        json_len = struct.unpack("<I", blob[12:16])[0]
        doc = json.loads(blob[20:20+json_len].decode("utf-8"))
        node = next(n for n in doc["nodes"] if n.get("name") == "slab")
        self.assertEqual(node["scale"], [1.0, 0.2, 1.0])
        self.assertEqual(node["translation"], [0.0, 0.1, 0.0])

    def test_judge_reports_preflight_without_claiming_visual_quality(self):
        result = compile_source(self.source("stool.m3l"))
        report = judge_result(result, require_camera=True)
        self.assertTrue(report["ready_for_visual_review"])
        self.assertTrue(report["visual_review_required"])
        self.assertIn("not an artistic-quality score", report["note"])
        self.assertEqual(next(c for c in report["checks"] if c["name"] == "mesh_reuse")["details"]["estimated_mesh_prototypes"], 3)

    def test_invalid_hex_color_is_rejected(self):
        source = '''scene "bad_color" {
  material bad {
    base = "blue-ish"
  }
  box b {
    size = [1, 1, 1]
    material = bad
  }
}'''
        result = compile_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("E110", {d["code"] for d in result["diagnostics"]})


if __name__ == "__main__":
    unittest.main()
