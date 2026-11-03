use pyo3::prelude::*;

pub mod geometry;
pub mod wasm;

#[pyfunction]
fn version() -> &'static str {
    "0.1.0-rust"
}

#[pyfunction]
fn is_available() -> bool {
    true
}

/// Computes vertex normals for a triangle mesh.
/// Returns a list of [nx, ny, nz] unit vectors.
#[pyfunction]
fn compute_normals(
    vertices: Vec<[f32; 3]>,
    indices: Vec<[u32; 3]>,
) -> PyResult<Vec<[f32; 3]>> {
    Ok(geometry::compute_normals(&vertices, &indices))
}

/// Evaluates axis-aligned bounding box [min_x, min_y, min_z, max_x, max_y, max_z]
#[pyfunction]
fn compute_bounds(vertices: Vec<[f32; 3]>) -> PyResult<[f32; 6]> {
    Ok(geometry::compute_bounds(&vertices))
}

/// Performs Loop subdivision on a triangle mesh.
/// Returns (new_vertices, new_indices).
#[pyfunction]
fn subdivide_loop(
    vertices: Vec<[f32; 3]>,
    indices: Vec<[u32; 3]>,
    levels: u32,
) -> PyResult<(Vec<[f32; 3]>, Vec<[u32; 3]>)> {
    Ok(geometry::loop_subdivision(vertices, indices, levels))
}

/// Ear-clipping 2D polygon triangulation.
/// Returns a list of triangle index triples [i0, i1, i2].
#[pyfunction]
fn triangulate_polygon_2d(pts: Vec<[f32; 2]>) -> PyResult<Vec<[u32; 3]>> {
    Ok(geometry::triangulate_polygon_2d(&pts))
}

#[pymodule]
fn m3l_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(is_available, m)?)?;
    m.add_function(wrap_pyfunction!(compute_normals, m)?)?;
    m.add_function(wrap_pyfunction!(compute_bounds, m)?)?;
    m.add_function(wrap_pyfunction!(subdivide_loop, m)?)?;
    m.add_function(wrap_pyfunction!(triangulate_polygon_2d, m)?)?;
    Ok(())
}
