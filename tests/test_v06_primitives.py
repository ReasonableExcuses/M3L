"""Unit tests for M3L v0.6 foundational primitives: loft, cone, torus, group, param, and material presets."""
import math
import pytest

from m3l.parser import parse, M3LParseError
from m3l.compiler import compile_source
from m3l.judge import judge_result
from m3l.glb import export_glb
from m3l.geometry import build_loft, build_cone, build_torus, audit_mesh


def test_param_expressions_and_math():
    source = """
    scene "test_params" {
      param base_radius = 0.5
      param height_factor = 2.5
      param total_height = base_radius * height_factor
      param x_offset = min(1.0, 2.0) + sqrt(4.0)

      cylinder col {
        radius = base_radius
        height = total_height
        at = [x_offset, total_height / 2, 0]
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    scene = res["scene"]
    assert scene["params"]["base_radius"] == 0.5
    assert scene["params"]["height_factor"] == 2.5
    assert scene["params"]["total_height"] == 1.25
    assert scene["params"]["x_offset"] == 3.0

    col = scene["objects"][0]
    assert col["geometry"]["radius"] == 0.5
    assert col["geometry"]["height"] == 1.25
    assert col["transform"]["translation"] == [3.0, 0.625, 0.0]


def test_param_undefined_raises_parse_error():
    source = """
    scene "test_bad_param" {
      param foo = undefined_var * 2
    }
    """
    with pytest.raises(M3LParseError, match="Undefined parameter"):
        parse(source)


def test_cone_primitive_watertight():
    # Frustum
    mesh_frustum = build_cone(radius_bottom=0.8, radius_top=0.3, height=1.5, segments=24)
    audit_f = audit_mesh(mesh_frustum)
    assert audit_f["valid"]
    assert audit_f["watertight"]
    assert audit_f["boundary_edges"] == 0
    assert audit_f["edges_not_used_twice"] == 0
    assert audit_f["inconsistent_winding_edges"] == 0
    assert audit_f["signed_volume"] > 0

    # Pointed cone
    mesh_pointed = build_cone(radius_bottom=1.0, radius_top=0.0, height=2.0, segments=32)
    audit_p = audit_mesh(mesh_pointed)
    assert audit_p["valid"]
    assert audit_p["watertight"]
    assert audit_p["boundary_edges"] == 0
    assert audit_p["signed_volume"] > 0

    # Compile scene with cone
    source = """
    scene "cone_scene" {
      cone tip {
        radius_bottom = 0.5
        radius_top = 0.1
        height = 1.2
        segments = 24
        at = [0, 0.6, 0]
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    glb_bytes = export_glb(res["scene"])
    assert len(glb_bytes) > 500
    assert glb_bytes[:4] == b"glTF"


def test_torus_primitive_watertight():
    mesh_torus = build_torus(major_radius=1.0, minor_radius=0.25, segments=32, rings=16)
    audit_t = audit_mesh(mesh_torus)
    assert audit_t["valid"]
    assert audit_t["watertight"]
    assert audit_t["boundary_edges"] == 0
    assert audit_t["edges_not_used_twice"] == 0
    assert audit_t["inconsistent_winding_edges"] == 0
    assert audit_t["signed_volume"] > 0

    # Expected analytical torus volume = 2 * pi^2 * R * r^2
    expected_vol = 2 * (math.pi ** 2) * 1.0 * (0.25 ** 2)
    assert abs(audit_t["signed_volume"] - expected_vol) < 0.15

    # Compile scene with torus
    source = """
    scene "torus_scene" {
      torus ring {
        major_radius = 0.6
        minor_radius = 0.08
        segments = 32
        rings = 16
        at = [0, 0.5, 0]
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    glb_bytes = export_glb(res["scene"])
    assert len(glb_bytes) > 500
    assert glb_bytes[:4] == b"glTF"


def test_loft_primitive_watertight():
    # 3 circular stations at x = -1, 0, 1
    sections = []
    for x in (-1.0, 0.0, 1.0):
        r = 0.5 if x == 0.0 else 0.2
        ring = []
        for i in range(12):
            ang = 2 * math.pi * i / 12
            ring.append([x, r * math.cos(ang), r * math.sin(ang)])
        sections.append(ring)

    mesh_loft = build_loft(sections, subdivisions=2)
    audit_l = audit_mesh(mesh_loft)
    assert audit_l["valid"]
    assert audit_l["watertight"]
    assert audit_l["boundary_edges"] == 0
    assert audit_l["edges_not_used_twice"] == 0
    assert audit_l["inconsistent_winding_edges"] == 0
    assert audit_l["signed_volume"] > 0

    source = f"""
    scene "loft_scene" {{
      loft pod {{
        sections = {sections}
        subdivisions = 4
      }}
    }}
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    glb_bytes = export_glb(res["scene"])
    assert len(glb_bytes) > 500


def test_group_hierarchy_and_bounds():
    source = """
    scene "group_scene" {
      group sub_assembly {
        at = [10.0, 0.0, 0.0]
        rotate = [0.0, 90.0, 0.0]

        box part_a {
          size = [2.0, 1.0, 1.0]
          at = [0.0, 0.5, 0.0]
        }
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    scene = res["scene"]
    assert len(scene["groups"]) == 1
    assert scene["groups"][0]["name"] == "sub_assembly"
    assert len(scene["objects"]) == 1
    obj = scene["objects"][0]
    assert obj["group"] == "sub_assembly"

    # World bounds of part_a should take into account group at = [10, 0, 0]
    bounds = scene["bounds"]["part_a"]
    # Rotated 90 deg around Y: size [2, 1, 1] becomes extents along Z
    assert bounds["min"][0] >= 9.0 and bounds["max"][0] <= 11.0
    assert bounds["min"][1] >= 0.0 and bounds["max"][1] <= 1.0

    # GLB export should build hierarchical nodes
    glb_bytes = export_glb(scene)
    assert len(glb_bytes) > 500


def test_material_presets_and_overrides():
    source = """
    scene "presets_scene" {
      material m_gold {
        preset = gold
      }
      material m_custom_gold {
        preset = gold
        roughness = 0.45
        tint = "#eecc22"
      }
      material m_chrome {
        preset = chrome
      }
      material m_glass {
        preset = glass
      }

      box b1 {
        size = [1, 1, 1]
        material = m_gold
      }
      box b2 {
        size = [1, 1, 1]
        material = m_custom_gold
        at = [2, 0, 0]
      }
      box b3 {
        size = [1, 1, 1]
        material = m_chrome
        at = [4, 0, 0]
      }
      box b4 {
        size = [1, 1, 1]
        material = m_glass
        at = [6, 0, 0]
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    mats = res["scene"]["materials"]

    assert mats["m_gold"]["metallic"] == 1.0
    assert mats["m_gold"]["source_color"] == "#ffd700"

    assert mats["m_custom_gold"]["roughness"] == 0.45
    assert mats["m_custom_gold"]["source_color"] == "#eecc22"

    assert mats["m_chrome"]["metallic"] == 1.0
    assert mats["m_chrome"]["roughness"] == 0.08

    assert mats["m_glass"]["transmission"] == 0.95
    assert mats["m_glass"]["ior"] == 1.52

    glb_bytes = export_glb(res["scene"])
    assert len(glb_bytes) > 1000


def test_unknown_preset_produces_diagnostic():
    source = """
    scene "bad_preset" {
      material bad {
        preset = unobtainium
      }
    }
    """
    res = compile_source(source)
    assert not res["valid"]
    assert any(d["code"] == "E115" for d in res["diagnostics"])


def test_spline_path_sweep_watertight():
    source = """
    scene "spline_sweep_scene" {
      sweep wire {
        path_type = catmull_rom
        control_points = [
          [0.0, 0.0, 0.0],
          [0.5, 0.3, 0.2],
          [1.0, 0.1, -0.2],
          [1.5, 0.4, 0.1]
        ]
        path_segments = 32
        radius = 0.04
        segments = 16
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    obj = res["scene"]["objects"][0]
    mesh = obj["geometry"]["mesh"]
    audit = audit_mesh(mesh)
    assert audit["valid"]
    assert audit["watertight"]
    assert audit["boundary_edges"] == 0
    assert audit["signed_volume"] > 0

    glb_bytes = export_glb(res["scene"])
    assert len(glb_bytes) > 500


def test_filleted_box_primitive():
    source = """
    scene "filleted_box_scene" {
      box enclosure {
        size = [1.0, 0.6, 0.4]
        fillet = 0.05
        fillet_segments = 4
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    obj = res["scene"]["objects"][0]
    mesh = obj["geometry"]["mesh"]
    audit = audit_mesh(mesh)
    assert audit["valid"]
    assert audit["watertight"]
    assert audit["boundary_edges"] == 0
    assert audit["signed_volume"] > 0

    judge = judge_result(res)
    assert judge["verdict"] in ("approved", "ready_for_visual_review")
    glb_bytes = export_glb(res["scene"])
    assert len(glb_bytes) > 500


def test_prototype_and_instances():
    source = """
    scene "instancing_scene" {
      material rubber {
        base = "#222222"
        roughness = 0.8
        metallic = 0.0
      }
      material chrome {
        preset = chrome
      }

      prototype wheel_subassembly {
        cylinder tire {
          radius = 0.35
          height = 0.25
          material = rubber
        }
        cylinder rim {
          radius = 0.25
          height = 0.26
          material = chrome
        }
      }

      instance wheel_front_left {
        prototype = wheel_subassembly
        at = [0.85, 0.35, 1.3]
      }

      instance wheel_front_right {
        prototype = wheel_subassembly
        at = [-0.85, 0.35, 1.3]
        mirror = x
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    scene = res["scene"]

    # 2 groups should be created for the two instances
    group_names = [g["name"] for g in scene["groups"]]
    assert "wheel_front_left" in group_names
    assert "wheel_front_right" in group_names

    # 4 objects total: 2 parts for each instance
    obj_names = [o["name"] for o in scene["objects"]]
    assert "wheel_front_left_tire" in obj_names
    assert "wheel_front_left_rim" in obj_names
    assert "wheel_front_right_tire" in obj_names
    assert "wheel_front_right_rim" in obj_names

    # GLB export should share mesh indices for corresponding parts
    glb_bytes = export_glb(scene)
    assert len(glb_bytes) > 500


def test_csg_boolean_difference_watertight():
    source = """
    scene "csg_scene" {
      box block {
        size = [1.0, 1.0, 1.0]
      }
      cylinder cutter {
        radius = 0.3
        height = 1.5
      }
      boolean carved_block {
        op = difference
        base = block
        tools = [cutter]
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    scene = res["scene"]

    # Original operands should be hidden (consumed by boolean)
    obj_names = [o["name"] for o in scene["objects"]]
    assert "carved_block" in obj_names
    assert "block" not in obj_names
    assert "cutter" not in obj_names

    bool_obj = scene["objects"][0]
    mesh = bool_obj["geometry"]["mesh"]
    audit = audit_mesh(mesh)
    assert audit["valid"]
    assert audit["watertight"]
    assert audit["boundary_edges"] == 0
    assert audit["signed_volume"] > 0

    judge = judge_result(res)
    assert judge["verdict"] in ("approved", "ready_for_visual_review")
    glb_bytes = export_glb(scene)
    assert len(glb_bytes) > 500



def test_subdivision_primitive_watertight():
    source = """
    scene "test_subdivision" {
      box rough_cube {
        size = [1.0, 1.0, 1.0]
      }
      subdivision smooth_sphere_like {
        base = rough_cube
        levels = 2
      }
    }
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    scene = res["scene"]

    # Base cube should be hidden by default
    names = [o["name"] for o in scene["objects"]]
    assert "smooth_sphere_like" in names
    assert "rough_cube" not in names

    subd_obj = scene["objects"][0]
    mesh = subd_obj["geometry"]["mesh"]
    audit = audit_mesh(mesh)
    assert audit["valid"]
    assert audit["watertight"]
    assert audit["boundary_edges"] == 0
    assert audit["triangle_count"] == 192
    assert audit["signed_volume"] > 0

    judge = judge_result(res)
    assert judge["verdict"] in ("approved", "ready_for_visual_review")
    glb_bytes = export_glb(scene)
    assert len(glb_bytes) > 1000


def test_material_texture_import(tmp_path):
    from PIL import Image
    import os

    tex_path = str(tmp_path / "diffuse.png")
    img = Image.new("RGBA", (32, 32), color=(200, 100, 50, 255))
    img.save(tex_path)

    # Use forward slashes for cross-platform M3L path
    m3l_path = tex_path.replace("\\", "/")
    source = f"""
    scene "test_textures" {{
      material textured_mat {{
        base = "#ffffff"
        base_texture = "{m3l_path}"
      }}
      box cube {{
        size = [1, 1, 1]
        material = textured_mat
      }}
    }}
    """
    res = compile_source(source)
    assert res["valid"], res["diagnostics"]
    scene = res["scene"]

    glb_bytes = export_glb(scene)
    assert len(glb_bytes) > len(open(tex_path, "rb").read())
