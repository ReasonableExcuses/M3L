---
name: m3l-authoring
description: Authoritative guide and best practices for authoring high-precision, visually photorealistic 3D models in M3L (Model 3D Language). Covers coordinate standards, compound 3D trigonometry, parametric hierarchy, material selection, and topology hygiene to eliminate floating joints, warped fillets, or distorted geometry.
---

# M3L Authoring Master Guide for AI Agents & Humans

## 1. Executive Rules of Spatial Geometry

M3L is a deterministic mathematical compiler. Unlike text or freeform meshes, it compiles exact IEEE 754 float values into watertight glTF 2.0 geometry.
When an LLM agent drafts an M3L scene, spatial errors (floating struts, tilted blades, dislocated joints) occur when the agent **approximates** compound 3D angles in text rather than calculating the exact trigonometry.

Follow these inviolable rules:

### Coordinate Conventions
* **$X$ (Lateral / Pitch axis):** Left ($-X$) to Right ($+X$).
* **$Y$ (Vertical / Altitude):** Down ($-Y$) to Up ($+Y$). Ground plane is strictly **$Y = 0.0$**.
* **$Z$ (Longitudinal / Roll axis):** Rear ($-Z$) to Nose/Front ($+Z$).

### Ground Contact Rule ($Y = 0.0$)
Any object intended to rest on the ground (skids, tires, rubber pads, feet, table legs) **must** mathematically terminate with its bottom surface at $Y = 0.0$:
$$\text{center}_Y = \frac{\text{height}}{2} \quad \implies \quad \text{bottom}_Y = 0.0$$

---

## 2. Compound 3D Angle Calculations

When angling a strut, arm, or leg of length $L$ by angle $\theta$ around the $Z$-axis (canting outward/inward in the $XY$ plane):

### Exact Trigonometric Formulas
Given an upper attachment pivot point $(X_p, Y_p, Z_p)$:
1. If the strut center is at distance $L/2$ along angle $\theta$ from vertical:
   $$\text{offset}_X = \frac{L}{2} \sin(\theta), \quad \text{offset}_Y = -\frac{L}{2} \cos(\theta)$$
   $$\text{center}_X = X_p + \text{offset}_X, \quad \text{center}_Y = Y_p + \text{offset}_Y$$
2. The bottom foot location will be at:
   $$\text{foot}_X = X_p + L \sin(\theta), \quad \text{foot}_Y = Y_p - L \cos(\theta)$$
3. **Always compute $\theta$ to hit the target ground $Y=0.0$ exactly:**
   $$\cos(\theta) = \frac{Y_p - \text{pad\_radius}}{L}$$
   $$\theta = \arccos\left(\frac{Y_p - \text{pad\_radius}}{L}\right)$$

> [!WARNING]
> Never guess decimal coordinates for angled parts. Use the formula above or use `param` expressions directly in M3L!

---

## 3. Fillet and Chamfer Rules

The M3L fillet builder constructs exact spherical corners and cylindrical edges.
* **Invariant:** Fillet radius $r$ must satisfy $r < 0.5 \times \min(\text{width}, \text{height}, \text{depth})$.
* **Thin Plate Rule:** For thin plates or aerodynamic hulls (e.g., thickness $H = 0.02$), **never** use a large fillet (e.g., $0.04$). Use an analytical fillet of $r \le 0.004$ to maintain crisp, professional mechanical edges without lozenge deformation.

---

## 4. Radial and Mirror Symmetry Patterns

### Radial Quadrotor / Multirotor
For an $N$-rotor platform with arm radius $R$:
For rotor $k \in \{0, 1, \dots, N-1\}$ where angle $\phi_k = \frac{\pi}{4} + k \frac{\pi}{2}$:
$$X_k = R \cos(\phi_k), \quad Z_k = R \sin(\phi_k)$$
Rotors in the horizontal disk plane must have pitch and roll equal to $0^\circ$ (`rotate: [0, 0, 0]` or pure yaw `rotate: [0, yaw, 0]`).

### Bilateral Mirroring
When instancing symmetric sub-assemblies (e.g. left and right wings, landing gear):
* Right side: `at: [X, Y, Z]`, `rotate: [rx, ry, rz]`
* Left side: `at: [-X, Y, Z]`, `rotate: [rx, -ry, -rz]`
* Set `double_sided: true` on thin sheets to prevent normal culling.

---

## 5. Material and Lighting Presets

Always assign physically calibrated PBR presets:
* Structural Airframe: `preset: carbon_fiber`, `roughness: 0.35`
* CNC Motor Mounts & Brackets: `preset: aluminum` or `preset: titanium`, `metallic: 0.95`, `roughness: 0.25`
* Optical Lenses & Visors: `preset: glass`, `roughness: 0.05`
* Landing Skids & Vibration Dampers: `preset: rubber`, `roughness: 0.85`
* Forward Navigation / Sensor Beacons: `preset: plastic_glossy`, `emissive: [0.0, 0.8, 1.0]`, `emissive_factor: 2.5`

---

## 6. Verification and Self-Inspection Loop

Before delivering any 3D asset:
1. **Syntax & Topology Check:** Run `m3l validate <file>` and ensure 0 errors.
2. **Preflight Audit:** Run `m3l compile <file> -o <file>.glb` to verify watertightness and signed volume.
3. **Headless Blender Multi-Angle Render:**
   Run `m3l render <file> --view isometric` and inspect the generated image in `<dist>/` to visually confirm:
   - Ground contact at $Y=0.0$ (no floating).
   - Rotor blades lie flat in the horizontal plane.
   - Clean, purposeful silhouettes without bloated fillets.

