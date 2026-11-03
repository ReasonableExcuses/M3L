#!/usr/bin/env python3
"""Build an inspection gallery for M3L procedural surface texture maps."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from m3l.procedural_materials import SURFACE_PRESETS, generate_surface_maps  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def main() -> int:
    output = ROOT / "dist" / "quality_study" / "material_maps"
    output.mkdir(parents=True, exist_ok=True)
    names = list(SURFACE_PRESETS)
    fields = ["baseColor modulation", "tangent normal", "AO (R)", "roughness (G)", "metallic (B)"]
    cell = 164
    left = 176
    top = 66
    sheet = Image.new("RGB", (left + len(fields) * cell, top + len(names) * cell), (28, 31, 37))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 18), "M3L procedural PBR map study · 128 px samples", fill=(245, 247, 250))
    for col, title in enumerate(fields):
        draw.text((left + col * cell + 8, 43), title, fill=(230, 233, 240))
    records = []
    for row, name in enumerate(names):
        maps = generate_surface_maps(name, 512)
        for key, payload in maps.items():
            if key.endswith("_png"):
                filename = f"{name}_{key.removesuffix('_png')}.png"
                (output / filename).write_bytes(payload)
        base = load(maps["base_color_png"]).resize((144, 144), Image.Resampling.LANCZOS)
        normal = load(maps["normal_png"]).resize((144, 144), Image.Resampling.LANCZOS)
        orm = load(maps["orm_png"]).resize((144, 144), Image.Resampling.LANCZOS)
        ao = Image.merge("RGB", (orm.getchannel("R"),) * 3)
        rough = Image.merge("RGB", (orm.getchannel("G"),) * 3)
        metal = Image.merge("RGB", (orm.getchannel("B"),) * 3)
        tiles = [base, normal, ao, rough, metal]
        draw.text((12, top + row * cell + 65), name.replace("_", " "), fill=(245, 247, 250))
        for col, tile in enumerate(tiles):
            x = left + col * cell + 10
            y = top + row * cell + 10
            sheet.paste(tile, (x, y))
            draw.rectangle((x - 1, y - 1, x + 144, y + 144), outline=(105, 112, 125), width=1)
        records.append({"surface": name, "resolution": maps["resolution"],
                        "map_bytes": maps["bytes"],
                        "map_sha256": {key: sha256(maps[key]) for key in ("base_color_png", "normal_png", "orm_png")},
                        "scalar_texture_multipliers": {"roughness": SURFACE_PRESETS[name]["roughness"],
                                                       "metallic": SURFACE_PRESETS[name]["metallic"],
                                                       "occlusion": SURFACE_PRESETS[name]["ao"]}})
    gallery = output / "material_preset_gallery.png"
    sheet.save(gallery, optimize=True)
    report = {"schema": "m3l.material_gallery.v1", "meaning": "packed ORM channels are texture multipliers; material scalar factors remain authored separately", "gallery": gallery.name, "gallery_sha256": sha256(gallery.read_bytes()), "gallery_bytes": gallery.stat().st_size, "surfaces": records}
    (output / "material_gallery.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gallery": str(gallery), "bytes": gallery.stat().st_size, "surfaces": len(records), "records": records}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
