#[cfg(feature = "wasm")]
use wasm_bindgen::prelude::*;

#[cfg(feature = "wasm")]
use crate::geometry;

#[cfg(feature = "wasm")]
#[wasm_bindgen]
pub fn wasm_version() -> String {
    "0.1.0-wasm".to_string()
}

#[cfg(feature = "wasm")]
#[wasm_bindgen]
pub fn wasm_subdivide_mesh_json(verts_json: &str, indices_json: &str, levels: u32) -> Result<String, JsValue> {
    let verts: Vec<[f32; 3]> = serde_json::from_str(verts_json)
        .map_err(|e| JsValue::from_str(&format!("Invalid vertices JSON: {}", e)))?;
    let indices: Vec<[u32; 3]> = serde_json::from_str(indices_json)
        .map_err(|e| JsValue::from_str(&format!("Invalid indices JSON: {}", e)))?;

    let (new_verts, new_indices) = geometry::loop_subdivision(verts, indices, levels);
    let normals = geometry::compute_normals(&new_verts, &new_indices);

    let output = serde_json::json!({
        "vertices": new_verts,
        "indices": new_indices,
        "normals": normals,
    });

    serde_json::to_string(&output)
        .map_err(|e| JsValue::from_str(&format!("Failed to serialize result: {}", e)))
}

#[cfg(feature = "wasm")]
#[wasm_bindgen]
pub fn wasm_compute_normals_json(verts_json: &str, indices_json: &str) -> Result<String, JsValue> {
    let verts: Vec<[f32; 3]> = serde_json::from_str(verts_json)
        .map_err(|e| JsValue::from_str(&format!("Invalid vertices JSON: {}", e)))?;
    let indices: Vec<[u32; 3]> = serde_json::from_str(indices_json)
        .map_err(|e| JsValue::from_str(&format!("Invalid indices JSON: {}", e)))?;

    let normals = geometry::compute_normals(&verts, &indices);
    serde_json::to_string(&normals)
        .map_err(|e| JsValue::from_str(&format!("Failed to serialize normals: {}", e)))
}

