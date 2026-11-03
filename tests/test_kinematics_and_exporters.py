import struct
import pytest
from m3l.compiler import compile_source
from m3l.exporters import export_obj, export_stl, export_usd


def _errors(res):
    return [d for d in res["diagnostics"] if d["severity"] == "error"]


def test_snap_to_ground_rotated_box():
    src = """scene "snap_test" {
  units = "m"
  box angled_foot {
    size = [0.1, 0.4, 0.1]
    at = [0.2, 0.5, 0.0]
    rotate = [0, 0, 30]
    snap_to_ground = true
  }
}"""
    res = compile_source(src)
    assert not _errors(res), f"Errors: {_errors(res)}"
    objs = res["scene"]["objects"]
    assert len(objs) == 1
    # Check that after snap_to_ground, the lowest point of this object is 0.0
    from m3l.compiler import object_bounds
    b = object_bounds(objs[0])
    assert pytest.approx(b["min"][1], abs=1e-5) == 0.0


def test_align_bottom_height():
    src = """scene "align_test" {
  units = "m"
  box shelf {
    size = [0.5, 0.05, 0.3]
    at = [0, 0, 0]
    align_bottom = 0.75
  }
}"""
    res = compile_source(src)
    assert not _errors(res)
    from m3l.compiler import object_bounds
    b = object_bounds(res["scene"]["objects"][0])
    assert pytest.approx(b["min"][1], abs=1e-5) == 0.75


def test_mirror_copy():
    src = """scene "mirror_test" {
  units = "m"
  box wing_right {
    size = [0.4, 0.02, 0.1]
    at = [0.5, 0.2, 0.0]
    rotate = [5, 10, -15]
    mirror_copy = "x"
  }
}"""
    res = compile_source(src)
    assert not _errors(res)
    objs = res["scene"]["objects"]
    assert len(objs) == 2
    names = {o["name"] for o in objs}
    assert names == {"wing_right", "wing_right_mirrored"}

    left = [o for o in objs if o["name"] == "wing_right_mirrored"][0]
    t = left["transform"]
    assert pytest.approx(t["translation"][0], abs=1e-5) == -0.5
    assert pytest.approx(t["translation"][1], abs=1e-5) == 0.2
    assert pytest.approx(t["rotation_euler_degrees"][0], abs=1e-5) == 5.0
    assert pytest.approx(t["rotation_euler_degrees"][1], abs=1e-5) == -10.0
    assert pytest.approx(t["rotation_euler_degrees"][2], abs=1e-5) == 15.0


def test_attach_to_anchor():
    src = """scene "attach_test" {
  units = "m"
  box table {
    size = [1.0, 0.1, 0.8]
    at = [0, 0.8, 0]
  }
  box lamp {
    size = [0.1, 0.2, 0.1]
    attach_to = "table.top"
    at = [0, 0.1, 0]  # lamp center 0.1 above table top (Y=0.85)
  }
}"""
    res = compile_source(src)
    assert not _errors(res)
    objs = {o["name"]: o for o in res["scene"]["objects"]}
    lamp = objs["lamp"]
    # Table top is Y = 0.8 + 0.05 = 0.85
    # Lamp at is anchor + [0, 0.1, 0] = 0.85 + 0.1 = 0.95
    assert pytest.approx(lamp["transform"]["translation"][1], abs=1e-5) == 0.95


def test_exporters():
    src = """scene "export_test" {
  units = "m"
  box cube {
    size = [1.0, 1.0, 1.0]
    at = [0, 0.5, 0]
  }
}"""
    res = compile_source(src)
    assert not _errors(res)
    scene = res["scene"]

    # Test OBJ
    obj_str = export_obj(scene)
    assert "o cube" in obj_str
    assert "v " in obj_str
    assert "vn " in obj_str
    assert "f " in obj_str

    # Test STL
    stl_bytes = export_stl(scene, binary=True)
    assert len(stl_bytes) >= 84
    tri_count = struct.unpack_from("<I", stl_bytes, 80)[0]
    assert tri_count == 12  # Cube has 12 triangles

    # Test USD
    usd_str = export_usd(scene)
    assert "#usda 1.0" in usd_str
    assert 'def Mesh "cube"' in usd_str
    assert "point3f[] points =" in usd_str
    assert "int[] faceVertexIndices =" in usd_str
