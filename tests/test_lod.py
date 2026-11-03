"""Tests for M3L Automated Mesh Decimation and LOD Generation (Tier 6)."""
import os
import tempfile
from pathlib import Path
import pytest
from m3l.compiler import compile_source
from m3l.geometry import build_sphere, decimate_mesh, generate_lods
from m3l.exporters import export_lods
from m3l.cli import main


def test_decimate_mesh_sphere():
    # Sphere with high subdivision
    sphere = build_sphere(radius=1.0, segments=32, rings=24)
    orig_tris = len(sphere["triangles"])
    assert orig_tris >= 1000

    # Decimate to 50%
    lod1 = decimate_mesh(sphere, target_fraction=0.5)
    assert len(lod1["triangles"]) < orig_tris
    assert len(lod1["triangles"]) <= int(orig_tris * 0.75)
    assert len(lod1["vertices"]) < len(sphere["vertices"])

    # Decimate to 25%
    lod2 = decimate_mesh(sphere, target_fraction=0.25)
    assert len(lod2["triangles"]) < len(lod1["triangles"])
    assert len(lod2["triangles"]) <= int(orig_tris * 0.45)


def test_generate_lods():
    sphere = build_sphere(radius=0.5, segments=24, rings=16)
    lods = generate_lods(sphere, levels=[1.0, 0.5, 0.25])
    assert len(lods) == 3
    assert len(lods[0]["triangles"]) > len(lods[1]["triangles"])
    assert len(lods[1]["triangles"]) > len(lods[2]["triangles"])


def test_export_lods_cli():
    src = """
scene "lod_test" {
  sphere orb {
    radius = 0.5
    segments = 24
    rings = 16
  }
}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "test.m3l"
        src_path.write_text(src, encoding="utf-8")
        out_base = Path(tmpdir) / "test.glb"

        # Test CLI compile with --lod
        ret = main(["compile", str(src_path), "--out", str(out_base), "--lod"])
        assert ret == 0

        lod0 = Path(tmpdir) / "test_lod0.glb"
        lod1 = Path(tmpdir) / "test_lod1.glb"
        lod2 = Path(tmpdir) / "test_lod2.glb"

        assert lod0.is_file()
        assert lod1.is_file()
        assert lod2.is_file()
        assert lod0.stat().st_size > 0
        assert lod1.stat().st_size > 0
        assert lod2.stat().st_size > 0
