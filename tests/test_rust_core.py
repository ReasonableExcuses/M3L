import time
import pytest
from m3l.geometry import HAS_M3L_CORE, build_subdivision, _smooth_normals, build_box

try:
    import m3l_core
except ImportError:
    m3l_core = None


def test_rust_core_loaded():
    assert HAS_M3L_CORE is True, "m3l_core Rust extension should be compiled and imported"
    assert m3l_core is not None
    assert m3l_core.is_available() is True
    assert "rust" in m3l_core.version()


def test_rust_bounding_box():
    verts = [[-2.5, 1.0, 3.0], [4.0, -10.0, 0.0], [1.0, 5.0, -8.0]]
    bounds = m3l_core.compute_bounds(verts)
    assert bounds == [-2.5, -10.0, -8.0, 4.0, 5.0, 3.0]


def test_rust_normals():
    # Triangle lying on XY plane facing +Z
    verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    tris = [[0, 1, 2]]
    normals = m3l_core.compute_normals(verts, tris)
    assert len(normals) == 3
    for n in normals:
        assert pytest.approx(n[0], abs=1e-5) == 0.0
        assert pytest.approx(n[1], abs=1e-5) == 0.0
        assert pytest.approx(n[2], abs=1e-5) == 1.0


def test_rust_loop_subdivision():
    # Tetrahedral mesh
    verts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    tris = [[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]]

    # 1 level of subdivision on 4 triangles -> 16 triangles
    sub_v, sub_t = m3l_core.subdivide_loop(verts, tris, 1)
    assert len(sub_t) == 16
    assert len(sub_v) == 10

    # 2 levels -> 64 triangles
    sub_v2, sub_t2 = m3l_core.subdivide_loop(verts, tris, 2)
    assert len(sub_t2) == 64


def test_subdivision_performance_speedup():
    cube = build_box([1.0, 1.0, 1.0])
    
    # Subdivide level 3 (12 * 4^3 = 768 triangles)
    t0 = time.perf_counter()
    res = build_subdivision(cube, levels=3)
    t_rust = time.perf_counter() - t0
    
    assert len(res["triangles"]) == 12 * (4 ** 3)
    assert len(res["render_normals"]) == len(res["vertices"])
    # In Rust, 768 triangles takes under 10ms
    assert t_rust < 0.1, f"Rust subdivision took {t_rust*1000:.2f} ms"
