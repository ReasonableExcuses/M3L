"""Tests for M3L Model Context Protocol (MCP) server."""
import json
from m3l.mcp_server import handle_tool_call, TOOLS


def test_mcp_tools_list():
    tool_names = [t["name"] for t in TOOLS]
    assert "m3l_validate" in tool_names
    assert "m3l_compile" in tool_names
    assert "m3l_judge" in tool_names
    assert "m3l_diff" in tool_names
    assert "m3l_patch" in tool_names
    assert "m3l_capabilities" in tool_names
    assert "m3l_schema" in tool_names


def test_mcp_capabilities():
    res = handle_tool_call("m3l_capabilities", {})
    assert "boolean" in res["primitives"]
    assert "subdivision" in res["primitives"]
    assert "loft" in res["primitives"]
    assert "catmull_rom" in res["splines"]
    assert "carbon_fiber" in res["procedural_surfaces"]


def test_mcp_validate_valid():
    src = """scene "test_valid" {
  box b {
    size = [1, 1, 1]
  }
}"""
    res = handle_tool_call("m3l_validate", {"source": src})
    assert res["valid"] is True
    assert res["errors"] == 0


def test_mcp_validate_invalid():
    src = """scene "test_invalid" {
  box b {
    unknown_prop = 123
  }
}"""
    res = handle_tool_call("m3l_validate", {"source": src})
    assert res["valid"] is False
    assert res["errors"] > 0
    assert any(d["code"] == "E101" for d in res["diagnostics"])


def test_mcp_compile():
    src = """scene "test_compile" {
  box b {
    size = [1, 1, 1]
  }
}"""
    res = handle_tool_call("m3l_compile", {"source": src})
    assert res["valid"] is True
    assert res["glb_bytes"] > 500
    assert "glb_base64" in res


def test_mcp_judge():
    src = """scene "test_judge" {
  camera {
    at = [2, 2, 2]
    target = [0, 0, 0]
  }
  light l {
    type = directional
    at = [5, 5, 5]
  }
  box b {
    size = [1, 1, 1]
  }
}"""
    res = handle_tool_call("m3l_judge", {"source": src, "require_camera": True})
    assert res["verdict"] in ("approved", "ready_for_visual_review")
    assert res["ready_for_visual_review"] is True


def test_mcp_diff():
    src_a = """scene "diff" {
  box a {
    size = [1, 1, 1]
  }
}"""
    src_b = """scene "diff" {
  box a {
    size = [2, 2, 2]
  }
}"""
    res = handle_tool_call("m3l_diff", {"source_a": src_a, "source_b": src_b})
    assert res["change_count"] > 0
    assert len(res["changes"]) > 0


def test_mcp_export():
    src = """scene "export_mcp" {
  box b {
    size = [1, 1, 1]
  }
}"""
    res_obj = handle_tool_call("m3l_export", {"source": src, "format": "obj"})
    assert res_obj["ok"] is True
    assert "o b" in res_obj["content"]

    res_stl = handle_tool_call("m3l_export", {"source": src, "format": "stl"})
    assert res_stl["ok"] is True
    assert res_stl["bytes"] > 0
    assert "base64" in res_stl

    res_usd = handle_tool_call("m3l_export", {"source": src, "format": "usd"})
    assert res_usd["ok"] is True
    assert 'def Mesh "b"' in res_usd["content"]
