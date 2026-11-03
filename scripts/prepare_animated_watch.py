"""Run inside Blender to add watch labels, a looping movement rig, and exports.

Example:
  blender --background --factory-startup --python scripts/prepare_animated_watch.py -- \
    dist/abyss_300_chronograph/abyss_300_chronograph.glb \
    dist/abyss_300_chronograph/abyss_300_chronograph_animated.glb \
    dist/abyss_300_chronograph/abyss_300_chronograph.blend \
    dist/abyss_300_chronograph/animation.json \
    dist/abyss_300_chronograph/studio.png
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector


FPS = 24
LOOP_SECONDS = 10
FRAME_START = 1
FRAME_END = FRAME_START + FPS * LOOP_SECONDS
CLIP_NAME = "Abyss_Chronograph_10s"


def arguments():
    if "--" not in sys.argv:
        raise RuntimeError("Pass input GLB, output animated GLB, blend, report, and preview after --.")
    values = sys.argv[sys.argv.index("--") + 1:]
    if len(values) != 5:
        raise RuntimeError("Expected five paths: input.glb output.glb scene.blend report.json preview.png")
    return values


def clear_startup_objects():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def add_dial_label(name, body, size, location, material):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.extrude = 0.000025
    curve.bevel_depth = 0.000012
    curve.bevel_resolution = 2
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(material)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")
    obj = bpy.context.view_layer.objects.active
    obj["m3l_role"] = "dial_engraving"
    return obj


def add_studio(scene, meshes):
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    mins = [min(float(point[i]) for point in points) for i in range(3)]
    maxs = [max(float(point[i]) for point in points) for i in range(3)]
    center = [(mins[i] + maxs[i]) * 0.5 for i in range(3)]
    extent = max(maxs[i] - mins[i] for i in range(3))
    floor_z = mins[2] - extent * 0.035
    bpy.ops.mesh.primitive_plane_add(size=extent * 8.0, location=(center[0], center[1], floor_z))
    floor = bpy.context.object
    floor.name = "M3L Render Only Floor"
    floor["m3l_render_only"] = True
    floor_mat = bpy.data.materials.new("M3L Render Only Slate")
    floor_mat.diffuse_color = (0.018, 0.027, 0.042, 1.0)
    floor_mat.use_nodes = True
    bsdf = floor_mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.018, 0.027, 0.042, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.82
    floor.data.materials.append(floor_mat)

    def area(name, offset, energy, size, color):
        data = bpy.data.lights.new(name=name, type="AREA")
        data.energy = energy * extent * extent
        data.shape = "DISK"
        data.size = size * extent
        data.color = color
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = (center[0] + offset[0] * extent,
                        center[1] + offset[1] * extent,
                        center[2] + offset[2] * extent)
        direction = Vector(center) - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        obj["m3l_render_only"] = True

    area("M3L Product Key", (1.4, -0.6, 2.2), 180, 1.0, (1.0, 0.87, 0.72))
    area("M3L Product Fill", (-1.4, 1.0, 1.2), 70, 1.4, (0.68, 0.8, 1.0))
    area("M3L Product Rim", (0.0, 1.8, 1.6), 110, 0.8, (0.78, 0.87, 1.0))
    return center, extent


def rig_turning_part(obj, pivot_name, pivot_location, seconds_per_revolution):
    world = obj.matrix_world.copy()
    pivot = bpy.data.objects.new(pivot_name, None)
    bpy.context.collection.objects.link(pivot)
    pivot.location = pivot_location
    pivot.empty_display_type = "CIRCLE"
    pivot.empty_display_size = 0.004
    pivot["m3l_role"] = "animation_pivot"
    obj.parent = pivot
    obj.matrix_parent_inverse = pivot.matrix_world.inverted()
    obj.matrix_world = world
    obj["m3l_role"] = "animated_component"

    pivot.rotation_mode = "XYZ"
    scene = bpy.context.scene
    scene.frame_set(FRAME_START)
    pivot.rotation_euler.z = 0.0
    pivot.keyframe_insert(data_path="rotation_euler", index=2, frame=FRAME_START, group="Timekeeping")
    scene.frame_set(FRAME_END)
    revolutions = LOOP_SECONDS / seconds_per_revolution
    pivot.rotation_euler.z = math.tau * revolutions
    pivot.keyframe_insert(data_path="rotation_euler", index=2, frame=FRAME_END, group="Timekeeping")

    action = pivot.animation_data.action
    action.name = CLIP_NAME
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "LINEAR"
        cycles = fcurve.modifiers.new("CYCLES")
        cycles.mode_before = "REPEAT"
        cycles.mode_after = "REPEAT"
    pivot.animation_data.action = None
    track = pivot.animation_data.nla_tracks.new()
    track.name = CLIP_NAME
    strip = track.strips.new(CLIP_NAME, FRAME_START, action)
    strip.blend_type = "REPLACE"
    strip.extrapolation = "NOTHING"
    strip.action_frame_start = FRAME_START
    strip.action_frame_end = FRAME_END
    return pivot


def export_animated_glb(path):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        if not obj.get("m3l_render_only"):
            obj.select_set(True)
    bpy.context.view_layer.objects.active = next(
        (obj for obj in bpy.context.scene.objects if obj.select_get() and obj.type == "MESH"), None)
    available = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    options = {
        "filepath": os.path.abspath(path),
        "export_format": "GLB",
        "use_selection": True,
        "export_animations": True,
        "export_nla_strips": True,
        "export_merge_animation": "NLA_TRACK",
        "export_nla_strips_merged_animation_name": CLIP_NAME,
        "export_extras": True,
        "export_cameras": True,
        "export_lights": False,
        "export_yup": True,
    }
    bpy.ops.export_scene.gltf(**{key: value for key, value in options.items() if key in available})


def main():
    source_glb, output_glb, output_blend, report_path, preview_path = arguments()
    clear_startup_objects()
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(source_glb))
    scene = bpy.context.scene
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("Input GLB contains no mesh objects.")

    cameras = [obj for obj in scene.objects if obj.type == "CAMERA"]
    if cameras:
        scene.camera = next((obj for obj in cameras if obj.name == "M3L_Camera"), cameras[0])
    champagne = bpy.data.materials.get("champagne_steel")
    if champagne is None:
        champagne = bpy.data.materials.get("luminous")
    if champagne is not None:
        add_dial_label("Abyss Dial Brand", "ABYSS", 0.0025, (0.0, -0.011, 0.00545), champagne)
        add_dial_label("Abyss Dial Depth Rating", "300 M", 0.00135, (0.0, 0.012, 0.00545), champagne)

    center, extent = add_studio(scene, meshes)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Abyss Product Studio")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.09, 0.11, 0.14, 1.0)
        background.inputs["Strength"].default_value = 0.18

    # The scene uses glTF Y-up converted to Blender Z-up; all dials are XY planes.
    rig_specs = [
        ("chronograph_seconds_hand", "RIG_Chronograph_Seconds", (0.0, 0.0, 0.0067), 60.0),
        ("minute_hand", "RIG_Main_Minute", (0.0, 0.0, 0.0067), 3600.0),
        ("hour_hand", "RIG_Main_Hour", (0.0, 0.0, 0.0067), 43200.0),
        ("seconds_counter_hand", "RIG_Subdial_Seconds", (-0.009, 0.0, 0.0062), 60.0),
        ("minute_counter_hand", "RIG_Subdial_Minutes", (0.009, 0.0, 0.0062), 1800.0),
        ("hours_counter_hand", "RIG_Subdial_Hours", (0.0, 0.0093, 0.0062), 43200.0),
        ("movement_rotor", "RIG_Automatic_Rotor", (0.0, 0.0, -0.0081), 4.0),
    ]
    rigs = []
    missing = []
    for obj_name, pivot_name, pivot_location, period in rig_specs:
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            missing.append(obj_name)
            continue
        rig_turning_part(obj, pivot_name, pivot_location, period)
        rigs.append({"object": obj_name, "pivot": pivot_name,
                     "seconds_per_revolution": period})
    if missing:
        raise RuntimeError("Expected moving components were not found: " + ", ".join(missing))

    scene.render.filepath = os.path.abspath(preview_path)
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
    scene.frame_set(FRAME_START)
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(output_blend))
    export_animated_glb(output_glb)

    report = {
        "schema": "m3l.watch_animation.v1",
        "asset": "Abyss 300 Automatic Chronograph",
        "clip": {"name": CLIP_NAME, "start_frame": FRAME_START, "end_frame": FRAME_END,
                 "fps": FPS, "duration_seconds": LOOP_SECONDS, "loop": True},
        "rigged_components": rigs,
        "geometry": {"named_mesh_objects": len([o for o in bpy.context.scene.objects if o.type == "MESH"]),
                     "asset_extent_m": extent, "center_blender_xyz": [float(v) for v in center]},
        "outputs": {"animated_glb": os.path.basename(output_glb),
                    "blend_scene": os.path.basename(output_blend),
                    "preview": os.path.basename(preview_path)},
        "notes": ["Rigid object animation; no skinned/deformation rig is required for a mechanical watch.",
                  "The dial labels are Blender-generated mesh engravings because M3L has no text primitive yet."],
    }
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
