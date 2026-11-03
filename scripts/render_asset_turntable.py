#!/usr/bin/env python3
"""Render a fixed multi-view diagnostic turntable for any GLB using optional VTK.

These views are designed for geometric inspection or a separate vision-model review.
They are not a substitute for a glTF-conformant production PBR renderer such as
Blender Eevee/Cycles, particularly for transmission, anisotropy, and other extensions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time


def _capture(vtk, window, output: Path):
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(output))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    payload = output.read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"Invalid or missing PNG output: {output}")
    return payload


def render_turntable(glb_path: Path, out_dir: Path, size=768, views=8, neutral_materials=False):
    try:
        import vtk
    except ImportError as exc:
        raise RuntimeError("Install optional dependency with: pip install -e '.[preview]'") from exc
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.055, 0.065, 0.085)
    renderer.SetBackground2(0.18, 0.21, 0.26)
    renderer.GradientBackgroundOn()
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(size, size)
    window.AddRenderer(renderer)
    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(glb_path.resolve()))
    importer.SetRenderWindow(window)
    importer.Update()
    actors = renderer.GetActors()
    actors.InitTraversal()
    actor_list = [actors.GetNextActor() for _ in range(actors.GetNumberOfItems())]
    # VTK is not a PBR reference renderer. Raise a modest ambient baseline to keep
    # dark metallic/almost-black assets diagnostically visible without pretending to
    # reproduce environment-map reflections or glTF's complete material model.
    for actor in actor_list:
        prop = actor.GetProperty()
        if neutral_materials:
            # Geometry-review mode intentionally removes authored textures and tints.
            # This is useful for silhouette/part-placement inspection, not material review.
            actor.SetTexture(None)
            prop.SetColor(0.66, 0.69, 0.73)
            prop.SetAmbient(0.30)
            prop.SetDiffuse(0.78)
            prop.SetSpecular(0.22)
            prop.SetSpecularPower(28.0)
            prop.SetInterpolationToPhong()
        else:
            prop.SetAmbient(0.28)
            prop.SetDiffuse(0.72)
            prop.SetSpecular(0.28)
            prop.SetSpecularPower(36.0)
    if not actor_list:
        window.Finalize()
        raise RuntimeError("GLB importer produced no mesh actors.")
    bounds = renderer.ComputeVisiblePropBounds()
    if not bounds or any(not math.isfinite(float(v)) for v in bounds):
        window.Finalize()
        raise RuntimeError("Could not compute finite asset bounds.")
    mins = [float(bounds[0]), float(bounds[2]), float(bounds[4])]
    maxs = [float(bounds[1]), float(bounds[3]), float(bounds[5])]
    center = [(mins[i] + maxs[i]) * 0.5 for i in range(3)]
    extent = max(maxs[i] - mins[i] for i in range(3))
    extent = max(extent, 1e-3)

    # Stable studio illumination: same setup across views so comparisons are meaningful.
    renderer.RemoveAllLights()
    for pos, intensity in (((1.8, 2.7, 2.0), 1.25), ((-2.0, 1.1, 0.8), 0.78), ((0.2, 1.9, -2.3), 0.68)):
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(center[0] + pos[0] * extent, center[1] + pos[1] * extent,
                          center[2] + pos[2] * extent)
        light.SetFocalPoint(*center)
        light.SetIntensity(intensity)
        light.SetPositional(False)
        renderer.AddLight(light)

    camera = renderer.GetActiveCamera()
    camera.SetViewUp(0, 1, 0)
    camera.SetFocalPoint(*center)
    camera.SetViewAngle(34)
    # Distance is chosen conservatively so the full bounds are visible in all views.
    distance = extent * 2.55
    rendered = []
    for i in range(views):
        angle = 2 * math.pi * i / views
        elevation = math.radians(18 if i % 2 == 0 else 10)
        horizontal = distance * math.cos(elevation)
        camera.SetPosition(center[0] + horizontal * math.cos(angle),
                           center[1] + distance * math.sin(elevation),
                           center[2] + horizontal * math.sin(angle))
        camera.SetFocalPoint(*center)
        camera.SetViewUp(0, 1, 0)
        renderer.ResetCameraClippingRange()
        window.Render()
        outfile = out_dir / f"view_{i:02d}.png"
        payload = _capture(vtk, window, outfile)
        rendered.append({"index": i, "angle_degrees": round(i * 360.0 / views, 3),
                         "path": outfile.name, "bytes": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()})
    window.Finalize()

    contact_sheet = None
    try:
        from PIL import Image, ImageDraw
        thumbs = []
        for item in rendered:
            im = Image.open(out_dir / item["path"]).convert("RGB")
            im.thumbnail((size // 2, size // 2))
            thumbs.append(im.copy())
        cols = 4 if views >= 4 else views
        rows = math.ceil(views / cols)
        sheet = Image.new("RGB", (cols * (size // 2), rows * (size // 2) + 44), (22, 25, 32))
        draw = ImageDraw.Draw(sheet)
        for i, im in enumerate(thumbs):
            sheet.paste(im, ((i % cols) * (size // 2), 44 + (i // cols) * (size // 2)))
        mode_label = "neutral geometry review" if neutral_materials else "authored-material diagnostic"
        draw.text((16, 14), f"M3L {mode_label} - {glb_path.name} - {views} views", fill=(240, 242, 248))
        path = out_dir / "contact_sheet.png"
        sheet.save(path)
        contact_sheet = {"path": path.name, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    except Exception as exc:
        contact_sheet = {"error": f"{type(exc).__name__}: {exc}"}

    report = {"schema": "m3l.turntable.v1", "asset": glb_path.name,
              "asset_sha256": hashlib.sha256(glb_path.read_bytes()).hexdigest(),
              "renderer": f"VTK {vtk.vtkVersion.GetVTKVersion()} diagnostic renderer",
              "mode": "neutral_geometry_review" if neutral_materials else "authored_material_diagnostic",
              "rendering_limitations": (["not a production PBR renderer", "authored material textures intentionally removed", "lighting is standardized for geometry comparison"] if neutral_materials else ["not a production PBR renderer", "advanced glTF material extension fidelity may differ", "lighting is standardized for diagnostic comparison"]),
              "size": [size, size], "views": rendered,
              "bounds": {"min": mins, "max": maxs, "center": center, "max_extent": extent},
              "contact_sheet": contact_sheet, "elapsed_seconds": round(time.perf_counter() - started, 3)}
    (out_dir / "turntable_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("asset", help="Input .glb")
    ap.add_argument("--out-dir", default="dist/turntable", help="Output directory")
    ap.add_argument("--size", type=int, default=768, help="Square output size 128..2048")
    ap.add_argument("--views", type=int, default=8, help="Number of azimuth views 4..16")
    ap.add_argument("--neutral-materials", action="store_true", help="Use neutral gray materials to review geometry without judging PBR appearance")
    args = ap.parse_args(argv)
    if not 128 <= args.size <= 2048 or not 4 <= args.views <= 16:
        ap.error("--size must be 128..2048 and --views must be 4..16")
    try:
        report = render_turntable(Path(args.asset), Path(args.out_dir), args.size, args.views, args.neutral_materials)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
