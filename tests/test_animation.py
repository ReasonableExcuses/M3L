"""Tests for M3L Declarative Joints and Animation Engine (Tier 7)."""
import json
import pytest
from m3l.compiler import compile_source
from m3l.glb import export_glb


def test_joint_compilation():
    src = """
scene "robotic_arm" {
  cylinder base_stand {
    radius = 0.2
    height = 0.4
  }
  cylinder upper_arm {
    radius = 0.05
    height = 0.8
    at = [0, 0.6, 0]
  }
  cylinder forearm {
    radius = 0.04
    height = 0.7
    at = [0, 1.35, 0]
  }
  joint shoulder {
    type = revolute
    parent = base_stand
    child = upper_arm
    anchor = [0, 0.2, 0]
    axis = [0, 0, 1]
    limits = [-45, 90]
  }
  joint elbow {
    type = revolute
    parent = upper_arm
    child = forearm
    anchor = [0, 0.4, 0]
    axis = [0, 0, 1]
    limits = [0, 150]
  }
}
"""
    res = compile_source(src)
    assert res["valid"], [d["message"] for d in res["diagnostics"] if d["severity"] == "error"]
    scene = res["scene"]
    assert len(scene["joints"]) == 2
    j0 = scene["joints"][0]
    assert j0["name"] == "shoulder"
    assert j0["type"] == "revolute"
    assert j0["parent"] == "base_stand"
    assert j0["child"] == "upper_arm"
    assert j0["limits"] == [-45.0, 90.0]
    assert j0["axis"] == [0.0, 0.0, 1.0]


def test_joint_diagnostics():
    src_invalid_type = """
scene "bad_joint" {
  box b1 {
    size = [1, 1, 1]
  }
  box b2 {
    size = [1, 1, 1]
  }
  joint j1 {
    type = warp_drive
    child = b2
  }
}
"""
    res = compile_source(src_invalid_type)
    assert any(d["code"] == "E210" for d in res["diagnostics"])

    src_missing_target = """
scene "bad_target" {
  box b1 {
    size = [1, 1, 1]
  }
  joint j1 {
    child = non_existent_obj
  }
}
"""
    res = compile_source(src_missing_target)
    assert any(d["code"] == "E211" for d in res["diagnostics"])

    src_bad_limits = """
scene "bad_limits" {
  box b1 {
    size = [1, 1, 1]
  }
  box b2 {
    size = [1, 1, 1]
  }
  joint j1 {
    parent = b1
    child = b2
    limits = [90, -90]
  }
}
"""
    res = compile_source(src_bad_limits)
    assert any(d["code"] == "E212" for d in res["diagnostics"])


def test_animation_compilation_and_glb():
    src = """
scene "animated_radar" {
  cylinder mast {
    radius = 0.05
    height = 1.0
  }
  box radar_dish {
    size = [0.8, 0.2, 0.05]
    at = [0, 0.6, 0]
  }
  animation spin {
    target = radar_dish
    channel = rotation_y
    keyframes = [
      {time: 0.0, value: 0.0},
      {time: 1.0, value: 180.0},
      {time: 2.0, value: 360.0}
    ]
  }
  animation pulse {
    target = radar_dish
    channel = scale
    keyframes = [
      {time: 0.0, value: 1.0},
      {time: 0.5, value: 1.2},
      {time: 1.0, value: 1.0}
    ]
  }
}
"""
    res = compile_source(src)
    assert res["valid"], [d["message"] for d in res["diagnostics"] if d["severity"] == "error"]
    scene = res["scene"]
    assert len(scene["animations"]) == 2
    assert scene["stats"]["animation_count"] == 2

    glb_bytes = export_glb(scene)
    assert len(glb_bytes) > 20
    assert glb_bytes[:4] == b"glTF"

    # Extract JSON header
    json_len = int.from_bytes(glb_bytes[12:16], "little")
    gltf = json.loads(glb_bytes[20:20+json_len].decode("utf-8"))

    assert "animations" in gltf
    assert len(gltf["animations"]) == 2

    spin_anim = gltf["animations"][0]
    assert spin_anim["name"] == "spin"
    assert len(spin_anim["channels"]) == 1
    assert spin_anim["channels"][0]["target"]["path"] == "rotation"

    pulse_anim = gltf["animations"][1]
    assert pulse_anim["name"] == "pulse"
    assert len(pulse_anim["channels"]) == 1
    assert pulse_anim["channels"][0]["target"]["path"] == "scale"


def test_animation_diagnostics():
    src_bad_target = """
scene "bad_anim" {
  box b1 {
    size = [1, 1, 1]
  }
  animation a1 {
    target = ghost_object
    keyframes = [{time: 0.0, value: 0}]
  }
}
"""
    res = compile_source(src_bad_target)
    assert any(d["code"] == "E220" for d in res["diagnostics"])

    src_bad_channel = """
scene "bad_anim_channel" {
  box b1 {
    size = [1, 1, 1]
  }
  animation a1 {
    target = b1
    channel = teleportation
    keyframes = [{time: 0.0, value: 0}]
  }
}
"""
    res = compile_source(src_bad_channel)
    assert any(d["code"] == "E221" for d in res["diagnostics"])

    src_non_monotonic_time = """
scene "bad_time" {
  box b1 {
    size = [1, 1, 1]
  }
  animation a1 {
    target = b1
    channel = rotation_y
    keyframes = [
      {time: 2.0, value: 180},
      {time: 1.0, value: 360}
    ]
  }
}
"""
    res = compile_source(src_non_monotonic_time)
    assert any(d["code"] == "E223" for d in res["diagnostics"])
