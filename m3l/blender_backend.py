"""Optional Blender bridge for production-quality offline rendering.

M3L remains useful without Blender. When Blender is installed, this adapter imports the
compiled glTF and renders a deterministic studio preview in a clean background process.
It never executes Python emitted by an LLM: only the fixed script embedded here runs.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

from .compiler import compile_source
from .glb import export_glb


class BlenderUnavailableError(RuntimeError):
    pass


class M3LRenderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "RENDER_FAILED", details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def discover_blender(explicit: str | None = None) -> str | None:
    """Return a valid Blender executable path, or None when unavailable."""
    candidate = explicit or os.environ.get("M3L_BLENDER") or shutil.which("blender")
    if not candidate:
        standard_paths = [
            r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        ]
        for sp in standard_paths:
            if Path(sp).is_file():
                candidate = sp
                break
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if path.is_file() and os.access(path, os.X_OK):
        return str(path.resolve())
    discovered = shutil.which(str(candidate))
    return str(Path(discovered).resolve()) if discovered else None


def blender_render_script() -> str:
    """Return fixed Blender-side code. Args are passed as data after `--`."""
    return textwrap.dedent(r'''
        import bpy
        import math
        import mathutils
        import os
        import sys

        def args_after_separator():
            if "--" not in sys.argv:
                raise RuntimeError("Expected arguments after --: input.glb output.png resolution samples engine")
            args = sys.argv[sys.argv.index("--") + 1:]
            if len(args) != 5:
                raise RuntimeError("Expected exactly five render arguments")
            return args

        def aim(obj, point):
            direction = mathutils.Vector(point) - obj.location
            obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

        def material_for_floor():
            mat = bpy.data.materials.new("M3L Studio Floor")
            mat.diffuse_color = (0.19, 0.205, 0.22, 1.0)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (0.19, 0.205, 0.22, 1.0)
                bsdf.inputs["Roughness"].default_value = 0.82
            return mat

        def add_area_light(name, location, target, energy, size, color):
            data = bpy.data.lights.new(name=name, type="AREA")
            data.energy = energy
            data.shape = "DISK"
            data.size = size
            data.color = color
            obj = bpy.data.objects.new(name, data)
            bpy.context.collection.objects.link(obj)
            obj.location = location
            aim(obj, target)
            return obj

        def main():
            import mathutils
            input_glb, output_png, resolution_raw, samples_raw, engine = args_after_separator()
            resolution = int(resolution_raw)
            samples = int(samples_raw)
            if resolution < 64 or resolution > 4096:
                raise RuntimeError("resolution must be between 64 and 4096")
            if samples < 1 or samples > 1024:
                raise RuntimeError("samples must be between 1 and 1024")

            # --factory-startup includes a cube, camera, and light. Remove them so
            # the imported GLB alone determines bounds and the active camera.
            bpy.ops.object.select_all(action="SELECT")
            bpy.ops.object.delete(use_global=False)
            bpy.ops.import_scene.gltf(filepath=input_glb)
            scene = bpy.context.scene
            meshes = [o for o in scene.objects if o.type == "MESH"]
            if not meshes:
                raise RuntimeError("Imported scene contains no mesh objects")

            # Derive a stable framing volume from evaluated object bounds.
            world_points = []
            for obj in meshes:
                for corner in obj.bound_box:
                    world_points.append(obj.matrix_world @ mathutils.Vector(corner))
            mins = [min(float(v[i]) for v in world_points) for i in range(3)]
            maxs = [max(float(v[i]) for v in world_points) for i in range(3)]
            center = [(mins[i] + maxs[i]) * 0.5 for i in range(3)]
            extent = max(maxs[i] - mins[i] for i in range(3))
            extent = max(extent, 0.25)
            # glTF's Y-up coordinates are converted to Blender's Z-up on import.
            floor_z = mins[2] - extent * 0.035

            # The glTF importer creates authored cameras but does not always
            # assign one as the active Blender scene camera.
            imported_cameras = [obj for obj in scene.objects if obj.type == "CAMERA"]
            existing_camera = scene.camera or (imported_cameras[0] if imported_cameras else None)
            if existing_camera is None:
                camera_data = bpy.data.cameras.new("M3L Preview Camera")
                existing_camera = bpy.data.objects.new("M3L Preview Camera", camera_data)
                bpy.context.collection.objects.link(existing_camera)
                existing_camera.location = (center[0] + extent * 1.8,
                                            center[1] + extent * 1.25,
                                            center[2] + extent * 2.0)
                aim(existing_camera, center)
                camera_data.lens = 48
                scene.camera = existing_camera
            else:
                scene.camera = existing_camera

            # Add a neutral studio floor to the preview only, not to the exported asset.
            bpy.ops.mesh.primitive_plane_add(size=extent * 8.0,
                location=(center[0], center[1], floor_z))
            floor = bpy.context.object
            floor.name = "M3L Preview Floor (render-only)"
            floor.data.materials.append(material_for_floor())

            # Soft key/fill/rim setup helps reveal curvature and silhouette even when
            # authored lights are missing or inadequate. These objects are render-only.
            add_area_light("M3L Studio Key",
                (center[0] + extent * 1.4, center[1] + extent * 2.2, center[2] + extent * 1.5),
                center, 900 * extent * extent, extent * 1.2, (1.0, 0.88, 0.74))
            add_area_light("M3L Studio Fill",
                (center[0] - extent * 1.8, center[1] + extent * 0.9, center[2] + extent * 0.7),
                center, 450 * extent * extent, extent * 1.6, (0.70, 0.82, 1.0))
            add_area_light("M3L Studio Rim",
                (center[0] + extent * 0.3, center[1] + extent * 1.5, center[2] - extent * 2.0),
                center, 700 * extent * extent, extent * 1.0, (0.84, 0.9, 1.0))

            scene.render.engine = ("CYCLES" if engine == "cycles" else
                ("BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
                 else "BLENDER_EEVEE"))
            if scene.render.engine == "CYCLES":
                scene.cycles.samples = samples
                scene.cycles.use_denoising = True
            scene.render.resolution_x = resolution
            scene.render.resolution_y = resolution
            scene.render.resolution_percentage = 100
            scene.render.image_settings.file_format = "PNG"
            scene.render.film_transparent = False
            scene.render.filepath = os.path.abspath(output_png)
            scene.render.use_file_extension = False
            scene.render.image_settings.color_mode = "RGBA"
            if scene.world is None:
                scene.world = bpy.data.worlds.new("M3L Studio World")
            scene.world.use_nodes = True
            bg = scene.world.node_tree.nodes.get("Background")
            if bg:
                bg.inputs["Color"].default_value = (0.22, 0.24, 0.28, 1.0)
                bg.inputs["Strength"].default_value = 0.45
            try:
                scene.view_settings.view_transform = "AgX"
            except Exception:
                pass
            # Slightly wider transparent margins are preferable to clipping parts.
            existing_camera.data.dof.use_dof = False
            bpy.ops.render.render(write_still=True)
            if not os.path.isfile(output_png) or os.path.getsize(output_png) < 128:
                raise RuntimeError("Blender completed without producing a non-empty PNG")

        main()
    ''').lstrip()


def render_source(source: str, output_path: str | Path, *, blender_bin: str | None = None,
                  resolution: int = 1024, samples: int = 32, engine: str = "eevee",
                  timeout_seconds: int = 240) -> dict[str, Any]:
    """Compile M3L, render with Blender in a clean subprocess, and write a PNG preview."""
    binary = discover_blender(blender_bin)
    if not binary:
        raise BlenderUnavailableError(
            "Blender was not found. Install Blender or set M3L_BLENDER to its executable path to enable rendering.")
    if isinstance(resolution, bool) or not isinstance(resolution, int) or not 64 <= resolution <= 4096:
        raise M3LRenderError("resolution must be an integer from 64 to 4096", code="INVALID_RENDER_SETTINGS")
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 1024:
        raise M3LRenderError("samples must be an integer from 1 to 1024", code="INVALID_RENDER_SETTINGS")
    if engine not in ("eevee", "cycles"):
        raise M3LRenderError("engine must be 'eevee' or 'cycles'", code="INVALID_RENDER_SETTINGS")

    result = compile_source(source)
    if not result["valid"] or result["scene"] is None:
        raise M3LRenderError("M3L source failed compilation; render was not started.",
                             code="SCENE_INVALID", details={"diagnostics": result["diagnostics"], "summary": result["summary"]})
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="m3l-blender-") as temp_dir:
        temp = Path(temp_dir)
        glb_path = temp / "scene.glb"
        script_path = temp / "render_m3l.py"
        png_path = temp / "preview.png"
        glb_path.write_bytes(export_glb(result["scene"]))
        script_path.write_text(blender_render_script(), encoding="utf-8")
        cmd = [binary, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", str(script_path), "--", str(glb_path), str(png_path),
               str(resolution), str(samples), engine]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise M3LRenderError(f"Blender render timed out after {timeout_seconds} seconds.", code="RENDER_TIMEOUT") from exc
        if proc.returncode != 0 or not png_path.is_file():
            tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-6000:]
            raise M3LRenderError("Blender failed to render the compiled scene.", code="BLENDER_RENDER_FAILED",
                                 details={"returncode": proc.returncode, "log_tail": tail})
        image_bytes = png_path.read_bytes()
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise M3LRenderError("Blender output did not have a valid PNG signature.", code="INVALID_RENDER_OUTPUT")
        destination.write_bytes(image_bytes)
        elapsed = time.perf_counter() - started
    return {"path": str(destination), "format": "png", "mime_type": "image/png",
            "bytes": len(image_bytes), "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "resolution": [resolution, resolution], "engine": engine, "samples": samples,
            "elapsed_seconds": round(elapsed, 3), "blender_binary": binary,
            "scene_summary": result["summary"]}
