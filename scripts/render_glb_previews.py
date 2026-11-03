#!/usr/bin/env python3
"""Render quick diagnostic PNGs from generated GLB assets using optional VTK.

This is not a replacement for Blender's production render path. It is a cheap,
reproducible geometry preview tool for CI/development machines without Blender.
Requires optional `vtk` only; the core M3L package remains standard-library-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def linear_to_srgb(value: float) -> float:
    value = max(0.0, min(1.0, float(value)))
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def render_one(vtk, glb_path: Path, scene_json_path: Path, output_path: Path, size: int) -> dict:
    scene_doc = json.loads(scene_json_path.read_text(encoding="utf-8"))
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.075, 0.09, 0.12)
    renderer.SetBackground2(0.20, 0.23, 0.28)
    renderer.GradientBackgroundOn()

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(size, size)
    window.AddRenderer(renderer)

    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(glb_path))
    importer.SetRenderWindow(window)
    importer.Update()

    # Use simple fixed studio lighting for comparable diagnostic previews.
    renderer.RemoveAllLights()
    for position, intensity in (((3, 4, 5), 0.9), ((-4, 2, 1), 0.55), ((0, 3, -5), 0.35)):
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*position)
        light.SetFocalPoint(0, 0, 0)
        light.SetIntensity(intensity)
        light.SetPositional(False)
        renderer.AddLight(light)

    actors = renderer.GetActors()
    actors.InitTraversal()
    for _ in range(actors.GetNumberOfItems()):
        actor = actors.GetNextActor()
        prop = actor.GetProperty()
        # GLTF PBR base-color factors are linear. Phong preview shading expects
        # display-space color here, so convert only for this diagnostic viewer.
        color = prop.GetColor()
        prop.SetColor(*(linear_to_srgb(channel) for channel in color))
        prop.SetInterpolationToPhong()
        prop.SetAmbient(0.20)
        prop.SetDiffuse(0.78)
        prop.SetSpecular(0.10)
        prop.SetSpecularPower(24)

    camera_spec = scene_doc.get("camera")
    camera = renderer.GetActiveCamera()
    if isinstance(camera_spec, dict) and isinstance(camera_spec.get("position"), list):
        camera.SetPosition(*camera_spec["position"])
        camera.SetFocalPoint(*(camera_spec.get("target") or [0, 0, 0]))
        camera.SetViewUp(0, 1, 0)
        camera.SetViewAngle(float(camera_spec.get("fov", 45)))
    else:
        renderer.ResetCamera()
    renderer.ResetCameraClippingRange()
    window.Render()

    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(output_path))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    if not output_path.is_file() or output_path.stat().st_size < 100:
        window.Finalize()
        raise RuntimeError(f"Preview writer did not create a usable image: {output_path}")
    bounds = renderer.ComputeVisiblePropBounds()
    window.Finalize()
    return {
        "asset": glb_path.name,
        "preview": output_path.name,
        "bytes": output_path.stat().st_size,
        "resolution": [size, size],
        "bounds": [round(float(v), 6) for v in bounds],
        "renderer": f"VTK {vtk.vtkVersion.GetVTKVersion()} diagnostic preview",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="dist", help="Directory containing built GLBs and scene JSON files")
    parser.add_argument("--size", type=int, default=800, help="Square preview dimension (128..2048)")
    parser.add_argument("--assets", nargs="*", help="Optional asset basenames, e.g. vase bracket; default all manifest assets")
    args = parser.parse_args(argv)
    if not 128 <= args.size <= 2048:
        parser.error("--size must be between 128 and 2048")
    try:
        import vtk
    except ImportError:
        print("Optional dependency missing: install vtk to render diagnostic previews.", file=sys.stderr)
        return 2

    dist = Path(args.dist)
    manifest_path = dist / "manifest.json"
    if args.assets:
        names = args.assets
    elif manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        names = [Path(item["source"]).stem for item in manifest.get("valid_examples", [])]
    else:
        names = [p.stem for p in dist.glob("*.glb")]

    results = []
    failures = []
    for name in names:
        glb = dist / f"{name}.glb"
        scene_json = dist / f"{name}.scene.json"
        if not glb.is_file() or not scene_json.is_file():
            failures.append({"asset": name, "error": "missing GLB or scene JSON"})
            continue
        try:
            results.append(render_one(vtk, glb, scene_json, dist / f"{name}_preview.png", args.size))
        except Exception as exc:  # keep processing other previews; report each error
            failures.append({"asset": name, "error": f"{type(exc).__name__}: {exc}"})
    report = {"renderer": "VTK diagnostic preview; not production rendering", "built": len(results), "failed": failures, "previews": results}
    report_path = dist / "PREVIEWS.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report}, indent=2))
    return 0 if results and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
