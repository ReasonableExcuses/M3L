use std::collections::HashMap;

/// Calculates per-vertex smooth normals for a triangular mesh.
pub fn compute_normals(vertices: &[[f32; 3]], indices: &[[u32; 3]]) -> Vec<[f32; 3]> {
    let mut normals = vec![[0.0f32; 3]; vertices.len()];

    for tri in indices {
        let i0 = tri[0] as usize;
        let i1 = tri[1] as usize;
        let i2 = tri[2] as usize;

        if i0 >= vertices.len() || i1 >= vertices.len() || i2 >= vertices.len() {
            continue;
        }

        let p0 = vertices[i0];
        let p1 = vertices[i1];
        let p2 = vertices[i2];

        let u = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
        let v = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];

        let nx = u[1] * v[2] - u[2] * v[1];
        let ny = u[2] * v[0] - u[0] * v[2];
        let nz = u[0] * v[1] - u[1] * v[0];

        normals[i0][0] += nx;
        normals[i0][1] += ny;
        normals[i0][2] += nz;

        normals[i1][0] += nx;
        normals[i1][1] += ny;
        normals[i1][2] += nz;

        normals[i2][0] += nx;
        normals[i2][1] += ny;
        normals[i2][2] += nz;
    }

    for n in &mut normals {
        let len_sq = n[0] * n[0] + n[1] * n[1] + n[2] * n[2];
        if len_sq > 1e-12 {
            let inv_len = 1.0 / len_sq.sqrt();
            n[0] *= inv_len;
            n[1] *= inv_len;
            n[2] *= inv_len;
        } else {
            *n = [0.0, 1.0, 0.0];
        }
    }

    normals
}

/// Evaluates axis-aligned bounding box: [min_x, min_y, min_z, max_x, max_y, max_z]
pub fn compute_bounds(vertices: &[[f32; 3]]) -> [f32; 6] {
    if vertices.is_empty() {
        return [0.0; 6];
    }

    let mut min_x = vertices[0][0];
    let mut min_y = vertices[0][1];
    let mut min_z = vertices[0][2];
    let mut max_x = vertices[0][0];
    let mut max_y = vertices[0][1];
    let mut max_z = vertices[0][2];

    for v in &vertices[1..] {
        if v[0] < min_x { min_x = v[0]; }
        if v[1] < min_y { min_y = v[1]; }
        if v[2] < min_z { min_z = v[2]; }
        if v[0] > max_x { max_x = v[0]; }
        if v[1] > max_y { max_y = v[1]; }
        if v[2] > max_z { max_z = v[2]; }
    }

    [min_x, min_y, min_z, max_x, max_y, max_z]
}

/// Helper key for undirected edges
#[derive(Hash, Eq, PartialEq, Copy, Clone, Debug)]
struct Edge(u32, u32);

impl Edge {
    fn new(a: u32, b: u32) -> Self {
        if a < b { Edge(a, b) } else { Edge(b, a) }
    }
}

/// Performs Loop subdivision on a 3D triangle mesh.
pub fn loop_subdivision(
    mut vertices: Vec<[f32; 3]>,
    mut triangles: Vec<[u32; 3]>,
    levels: u32,
) -> (Vec<[f32; 3]>, Vec<[u32; 3]>) {
    for _ in 0..levels {
        let n_orig_verts = vertices.len();

        // 1. Map edges to opposite vertices: Edge -> Vec<u32>
        let mut edge_opposites: HashMap<Edge, Vec<u32>> = HashMap::new();
        // 2. Map original vertices to neighbors: u32 -> Vec<u32>
        let mut vert_neighbors: Vec<Vec<u32>> = vec![Vec::new(); n_orig_verts];

        for tri in &triangles {
            let (a, b, c) = (tri[0], tri[1], tri[2]);
            let edges = [
                (Edge::new(a, b), c),
                (Edge::new(b, c), a),
                (Edge::new(c, a), b),
            ];
            for (e, opp) in edges {
                edge_opposites.entry(e).or_default().push(opp);
            }

            for &(u, v) in &[(a, b), (b, c), (c, a)] {
                let u_idx = u as usize;
                if !vert_neighbors[u_idx].contains(&v) {
                    vert_neighbors[u_idx].push(v);
                }
                let v_idx = v as usize;
                if !vert_neighbors[v_idx].contains(&u) {
                    vert_neighbors[v_idx].push(u);
                }
            }
        }

        // 3. Compute edge points (new vertices created along edges)
        let mut edge_point_map: HashMap<Edge, u32> = HashMap::new();
        let mut new_vertices = vertices.clone();

        for (&edge, opps) in &edge_opposites {
            let p_a = vertices[edge.0 as usize];
            let p_b = vertices[edge.1 as usize];

            let pt = if opps.len() == 2 {
                // Internal edge: 3/8*(A+B) + 1/8*(C+D)
                let p_c = vertices[opps[0] as usize];
                let p_d = vertices[opps[1] as usize];
                [
                    0.375 * (p_a[0] + p_b[0]) + 0.125 * (p_c[0] + p_d[0]),
                    0.375 * (p_a[1] + p_b[1]) + 0.125 * (p_c[1] + p_d[1]),
                    0.375 * (p_a[2] + p_b[2]) + 0.125 * (p_c[2] + p_d[2]),
                ]
            } else {
                // Boundary edge: 1/2*(A+B)
                [
                    0.5 * (p_a[0] + p_b[0]),
                    0.5 * (p_a[1] + p_b[1]),
                    0.5 * (p_a[2] + p_b[2]),
                ]
            };

            let new_idx = new_vertices.len() as u32;
            new_vertices.push(pt);
            edge_point_map.insert(edge, new_idx);
        }

        // 4. Update positions of original vertices
        for i in 0..n_orig_verts {
            let neighbors = &vert_neighbors[i];
            let n = neighbors.len() as f32;
            if n < 3.0 {
                continue;
            }

            // Beta weighting
            let beta = if n == 3.0 {
                3.0 / 16.0
            } else {
                let term = (3.0 / 8.0) + (0.25 * (2.0 * std::f32::consts::PI / n).cos());
                (1.0 / n) * (5.0 / 8.0 - term * term)
            };

            let orig = vertices[i];
            let mut sum_x = 0.0f32;
            let mut sum_y = 0.0f32;
            let mut sum_z = 0.0f32;

            for &nbr in neighbors {
                let p_nbr = vertices[nbr as usize];
                sum_x += p_nbr[0];
                sum_y += p_nbr[1];
                sum_z += p_nbr[2];
            }

            let weight_orig = 1.0 - n * beta;
            new_vertices[i] = [
                weight_orig * orig[0] + beta * sum_x,
                weight_orig * orig[1] + beta * sum_y,
                weight_orig * orig[2] + beta * sum_z,
            ];
        }

        // 5. Construct subdivided triangles (4 per parent triangle)
        let mut new_triangles = Vec::with_capacity(triangles.len() * 4);
        for tri in &triangles {
            let (a, b, c) = (tri[0], tri[1], tri[2]);
            let m_ab = edge_point_map[&Edge::new(a, b)];
            let m_bc = edge_point_map[&Edge::new(b, c)];
            let m_ca = edge_point_map[&Edge::new(c, a)];

            new_triangles.push([a, m_ab, m_ca]);
            new_triangles.push([b, m_bc, m_ab]);
            new_triangles.push([c, m_ca, m_bc]);
            new_triangles.push([m_ab, m_bc, m_ca]);
        }

        vertices = new_vertices;
        triangles = new_triangles;
    }

    (vertices, triangles)
}

/// Ear-clipping 2D polygon triangulation.
pub fn triangulate_polygon_2d(pts: &[[f32; 2]]) -> Vec<[u32; 3]> {
    let n = pts.len();
    if n < 3 {
        return Vec::new();
    }
    if n == 3 {
        return vec![[0, 1, 2]];
    }

    // Determine orientation (signed area)
    let mut area = 0.0f32;
    for i in 0..n {
        let j = (i + 1) % n;
        area += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1];
    }

    let mut indices: Vec<usize> = if area < 0.0 {
        (0..n).rev().collect() // ensure counter-clockwise
    } else {
        (0..n).collect()
    };

    let mut result = Vec::new();

    let is_convex = |prev: [f32; 2], curr: [f32; 2], next: [f32; 2]| -> bool {
        let cross = (curr[0] - prev[0]) * (next[1] - curr[1]) - (curr[1] - prev[1]) * (next[0] - curr[0]);
        cross >= 0.0
    };

    let point_in_triangle = |p: [f32; 2], a: [f32; 2], b: [f32; 2], c: [f32; 2]| -> bool {
        let sign = |p1: [f32; 2], p2: [f32; 2], p3: [f32; 2]| {
            (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        };
        let d1 = sign(p, a, b);
        let d2 = sign(p, b, c);
        let d3 = sign(p, c, a);

        let has_neg = (d1 < -1e-6) || (d2 < -1e-6) || (d3 < -1e-6);
        let has_pos = (d1 > 1e-6) || (d2 > 1e-6) || (d3 > 1e-6);

        !(has_neg && has_pos)
    };

    let mut count = 0;
    while indices.len() > 2 && count < n * 4 {
        count += 1;
        let mut ear_found = false;
        let m = indices.len();

        for i in 0..m {
            let prev_idx = indices[(i + m - 1) % m];
            let curr_idx = indices[i];
            let next_idx = indices[(i + 1) % m];

            let p_prev = pts[prev_idx];
            let p_curr = pts[curr_idx];
            let p_next = pts[next_idx];

            if !is_convex(p_prev, p_curr, p_next) {
                continue;
            }

            let mut has_point_inside = false;
            for j in 0..m {
                if j == (i + m - 1) % m || j == i || j == (i + 1) % m {
                    continue;
                }
                let test_pt = pts[indices[j]];
                if point_in_triangle(test_pt, p_prev, p_curr, p_next) {
                    has_point_inside = true;
                    break;
                }
            }

            if !has_point_inside {
                result.push([prev_idx as u32, curr_idx as u32, next_idx as u32]);
                indices.remove(i);
                ear_found = true;
                break;
            }
        }

        if !ear_found {
            // Degenerate fallback: fan triangulation
            for i in 1..indices.len() - 1 {
                result.push([indices[0] as u32, indices[i] as u32, indices[i + 1] as u32]);
            }
            break;
        }
    }

    result
}

