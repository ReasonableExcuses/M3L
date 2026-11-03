"""Deterministic, bounded procedural PBR texture generation for M3L.

Textures are deliberately generated as ordinary PNG images embedded in GLB. This
keeps the output portable to glTF viewers and avoids runtime shader dependencies.
The presets are useful starting materials, not a substitute for scanned references.
"""
from __future__ import annotations

import io
import math
from typing import Any

class ProceduralMaterialsUnavailableError(RuntimeError):
    """Raised only when an authored texture material needs missing optional packages."""


SURFACE_PRESETS = {
    # roughness and metallic channels are *multipliers* for the material's
    # authored glTF scalar factors. This preserves source editability while maps
    # add bounded per-pixel variation rather than overriding the material class.
    "brushed_metal": {"seed": 11, "height": 0.035, "roughness": 0.92, "metallic": 0.96, "ao": 0.98},
    "anodized_metal": {"seed": 23, "height": 0.025, "roughness": 0.90, "metallic": 0.94, "ao": 0.99},
    "rubber": {"seed": 37, "height": 0.075, "roughness": 0.96, "metallic": 1.00, "ao": 0.94},
    "ceramic_glaze": {"seed": 41, "height": 0.012, "roughness": 0.96, "metallic": 1.00, "ao": 0.99},
    "carbon_fiber": {"seed": 53, "height": 0.070, "roughness": 0.88, "metallic": 0.88, "ao": 0.93},
    "leather_grain": {"seed": 67, "height": 0.085, "roughness": 0.97, "metallic": 1.00, "ao": 0.91},
    "wood_grain": {"seed": 79, "height": 0.045, "roughness": 0.94, "metallic": 1.00, "ao": 0.97},
    "fabric_weave": {"seed": 89, "height": 0.065, "roughness": 0.98, "metallic": 1.00, "ao": 0.92},
}


def _png(array) -> bytes:
    from PIL import Image
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG", optimize=True)
    return stream.getvalue()


def generate_surface_maps(surface: str, resolution: int = 256) -> dict[str, Any]:
    """Generate baseColor, tangent-space normal, and packed occlusion/roughness/metallic maps.

    Requires optional ``numpy`` and ``Pillow`` packages. Resolution is intentionally
    restricted to 128/256/512/1024 by the compiler to bound LLM-generated workloads.
    Repeated calls for one preset/resolution are deterministic.
    """
    if surface not in SURFACE_PRESETS:
        raise ValueError(f"Unsupported procedural surface {surface!r}.")
    if resolution not in (128, 256, 512, 1024):
        raise ValueError("Texture resolution must be 128, 256, 512 or 1024.")
    try:
        import numpy as np
        from PIL import Image  # noqa: F401 - validates optional dependency at point of use
    except ImportError as exc:
        raise ProceduralMaterialsUnavailableError(
            "Procedural PBR textures require numpy and Pillow; install with `pip install -e '.[materials]'`."
        ) from exc

    preset = SURFACE_PRESETS[surface]
    n = resolution
    rng = np.random.default_rng(int(preset["seed"]) + n)
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    u, v = x / n, y / n
    noise = rng.normal(0.0, 1.0, (n, n)).astype(np.float32)
    # Cheap deterministic multiscale grain. Rolled/shifted versions provide structure
    # without requiring a large convolution dependency.
    noise_coarse = (noise + np.roll(noise, n // 17 or 1, 0) + np.roll(noise, n // 23 or 1, 1)) / 3.0
    noise_fine = (noise + np.roll(noise, 1, 0) + np.roll(noise, 1, 1)) / 3.0

    if surface == "brushed_metal":
        streak = np.sin(u * n * 1.7 + noise_coarse * 1.9) * 0.055
        streak += np.sin(u * n * 0.19 + noise_coarse * 2.5) * 0.035
        height = streak + noise_fine * 0.055
        shade = 0.89 + np.sin(u * n * 1.8 + noise_coarse) * 0.07 + noise_fine * 0.075
        rough_detail = preset["roughness"] + np.abs(noise_fine) * 0.08 - 0.04
    elif surface == "anodized_metal":
        grain = np.sin(u * n * 0.42 + noise_coarse * 2.0) * 0.025
        shade = 0.94 + grain + noise_fine * 0.035
        height = grain + noise_fine * 0.035
        rough_detail = preset["roughness"] + np.abs(noise_fine) * 0.05 - 0.025
    elif surface == "rubber":
        pitch = max(5.0, n / 32.0)
        dx = np.mod(x, pitch) - pitch / 2
        dy = np.mod(y, pitch) - pitch / 2
        dot = np.exp(-(dx * dx + dy * dy) / max(1.0, pitch * pitch * 0.20))
        height = dot * 0.35 + noise_coarse * 0.045
        shade = 0.77 + dot * 0.12 + noise_fine * 0.055
        rough_detail = preset["roughness"] + np.abs(noise_fine) * 0.09 - 0.035
    elif surface == "ceramic_glaze":
        cloud = noise_coarse * 0.55 + np.sin(u * 7.1 + v * 3.7) * 0.14
        shade = 0.97 + cloud * 0.035
        height = cloud * 0.045 + noise_fine * 0.01
        rough_detail = preset["roughness"] + np.abs(cloud) * 0.04 - 0.02
    elif surface == "carbon_fiber":
        cell = max(6.0, n / 24.0)
        sx = np.mod(x + np.floor(y / cell) * (cell * 0.5), cell) / cell
        sy = np.mod(y, cell) / cell
        weave = (np.sin(sx * math.pi) ** 6) * (0.65 + 0.35 * np.sin(sy * math.pi) ** 4)
        checker = np.where((np.floor(x / cell) + np.floor(y / cell)).astype(int) % 2 == 0, 1.0, 0.78)
        shade = 0.63 + weave * 0.28 * checker + noise_fine * 0.025
        height = weave * 0.22 + noise_fine * 0.035
        rough_detail = preset["roughness"] + weave * 0.09 + np.abs(noise_fine) * 0.04 - 0.035
    elif surface == "leather_grain":
        pores = (np.sin(x * 0.62 + noise_coarse * 2.2) * np.sin(y * 0.57 + noise_fine * 1.8))
        shade = 0.91 + noise_coarse * 0.09 + pores * 0.035
        height = noise_coarse * 0.11 + pores * 0.08 + noise_fine * 0.025
        rough_detail = preset["roughness"] + np.abs(pores) * 0.05 + np.abs(noise_fine) * 0.03 - 0.02
    elif surface == "wood_grain":
        bands = np.sin(v * n * 0.115 + np.sin(u * 15.0 + noise_coarse * 2.0) * 3.5)
        bands += 0.28 * np.sin(v * n * 0.26 + u * 7.0)
        shade = 0.82 + bands * 0.105 + noise_fine * 0.035
        height = bands * 0.07 + noise_fine * 0.02
        rough_detail = preset["roughness"] + np.abs(bands) * 0.055 - 0.025
    else:  # fabric_weave
        pitch = max(4.0, n / 28.0)
        warp = np.sin((x + 0.4 * np.sin(y / pitch)) * 2 * math.pi / pitch)
        weft = np.sin((y + 0.4 * np.sin(x / pitch)) * 2 * math.pi / pitch)
        shade = 0.84 + (warp + weft) * 0.065 + noise_fine * 0.025
        height = (np.abs(warp) + np.abs(weft)) * 0.055 + noise_fine * 0.02
        rough_detail = preset["roughness"] + (np.abs(warp) + np.abs(weft)) * 0.025 - 0.025

    shade = np.clip(shade, 0.38, 1.12)
    height = np.asarray(height, dtype=np.float32)
    dx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
    dy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
    strength = 2.6 + preset["height"] * 19.0
    nx, ny, nz = -dx * strength, -dy * strength, np.ones_like(height)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack(((nx / length + 1) * 127.5,
                       (ny / length + 1) * 127.5,
                       (nz / length + 1) * 127.5), axis=-1)
    normal_png = _png(np.clip(normal, 0, 255).astype(np.uint8))

    # R=occlusion, G=roughness, B=metallic per the glTF metallic-roughness convention.
    ao = np.clip(preset["ao"] - np.abs(height) * 0.08, 0.0, 1.0)
    rough = np.clip(rough_detail, 0.0, 1.0)
    metal = np.full((n, n), float(preset["metallic"]), dtype=np.float32)
    orm = np.stack((ao * 255, rough * 255, metal * 255), axis=-1).astype(np.uint8)
    orm_png = _png(orm)

    gray = np.repeat(np.clip(shade * 255, 0, 255).astype(np.uint8)[..., None], 3, axis=-1)
    base_png = _png(gray)
    return {"base_color_png": base_png, "normal_png": normal_png, "orm_png": orm_png,
            "resolution": resolution, "surface": surface,
            "bytes": {"base_color": len(base_png), "normal": len(normal_png), "orm": len(orm_png)}}
