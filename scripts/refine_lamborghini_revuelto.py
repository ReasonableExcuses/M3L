"""Refine the bundled Revuelto concept GLB into a Blender studio asset.

Example:
  blender --background --factory-startup --python scripts/refine_lamborghini_revuelto.py -- \
    dist/lamborghini_revuelto_outer.glb dist/lamborghini_revuelto_refined.blend \
    dist/lamborghini_revuelto_refined.glb dist/lamborghini_revuelto_hero.png
"""
import bpy
import math
import os
import re
import sys
from mathutils import Vector


def args():
    if "--" not in sys.argv:
        raise RuntimeError("Pass source GLB, output blend, and hero PNG after --")
    values = sys.argv[sys.argv.index("--") + 1:]
    if len(values) != 4:
        raise RuntimeError("Expected input.glb output.blend output.glb hero.png")
    return values


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def set_input(node, names, value):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return


def tune_materials():
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            continue
        name = material.name.lower()
        if "arancio_paint" in name:
            set_input(principled, ["Base Color"], (0.78, 0.065, 0.003, 1.0))
            set_input(principled, ["Metallic"], 0.42)
            set_input(principled, ["Roughness"], 0.26)
            set_input(principled, ["Coat Weight", "Clearcoat"], 0.42)
            set_input(principled, ["Coat Roughness", "Clearcoat Roughness"], 0.11)
            set_input(principled, ["IOR"], 1.48)
        elif "tinted_glass" in name:
            set_input(principled, ["Roughness"], 0.075)
            set_input(principled, ["Metallic"], 0.0)
            set_input(principled, ["Transmission Weight", "Transmission"], 0.34)
            set_input(principled, ["IOR"], 1.48)
            set_input(principled, ["Coat Weight", "Clearcoat"], 0.14)
        elif "tire_rubber" in name:
            set_input(principled, ["Roughness"], 0.74)
            set_input(principled, ["Metallic"], 0.0)
        elif "wheel_alloy" in name:
            set_input(principled, ["Roughness"], 0.2)
            set_input(principled, ["Metallic"], 0.92)
            set_input(principled, ["Anisotropic IOR Level", "Anisotropic"], 0.28)
        elif "wheel_dark" in name or "black_carbon" in name:
            set_input(principled, ["Roughness"], 0.27 if "wheel" in name else 0.31)
            set_input(principled, ["Metallic"], 0.72 if "wheel" in name else 0.34)
        elif "panel_black" in name:
            set_input(principled, ["Roughness"], 0.34)
            set_input(principled, ["Metallic"], 0.18)
        elif "led_white" in name or "led_red" in name:
            set_input(principled, ["Emission Strength"], 0.45)


def make_principled(name, color, metallic, roughness):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return material


def add_brake_and_wheel_detail():
    alloy = bpy.data.materials.get("wheel_alloy") or make_principled("Forged Titanium", (0.34, 0.4, 0.48), 0.92, 0.19)
    rotor_mat = make_principled("Carbon Ceramic Rotor", (0.12, 0.14, 0.16), 0.82, 0.28)
    hole_mat = make_principled("Rotor Drilling", (0.012, 0.016, 0.02), 0.18, 0.42)
    caliper_mat = make_principled("Carbon Ceramic Caliper Red", (0.55, 0.012, 0.018), 0.38, 0.24)
    cap_mat = make_principled("Machined Center Cap", (0.32, 0.36, 0.4), 0.94, 0.16)

    delete_names = [name for name in bpy.data.objects.keys()
                    if re.match(r"(?:front|rear)_(?:left|right)_(?:alloy_face|spoke_\d+|lug_\d+)$", name)]
    for name in delete_names:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    wheel_specs = [
        ("front_left_tire", -1.35), ("front_right_tire", -1.35),
        ("rear_left_tire", 1.32), ("rear_right_tire", 1.32),
    ]
    for tire_name, wheel_x in wheel_specs:
        tire = bpy.data.objects[tire_name]
        center = tire.matrix_world.translation.copy()
        side = -1 if center.y < 0 else 1
        radius = 0.31 if "front" in tire_name else 0.33
        outer_y = side * 1.174
        rotor_y = side * 1.125

        bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=radius * 0.88, depth=0.028,
                                           location=(wheel_x, rotor_y, center.z),
                                           rotation=(math.pi / 2, 0, 0))
        rotor = bpy.context.object
        rotor.name = tire_name.replace("_tire", "_carbon_ceramic_rotor")
        rotor.data.materials.append(rotor_mat)
        for poly in rotor.data.polygons:
            poly.use_smooth = True
        bevel = rotor.modifiers.new("Rotor Edge Bevel", "BEVEL")
        bevel.width = 0.003
        bevel.segments = 2

        bpy.ops.mesh.primitive_torus_add(major_segments=96, minor_segments=12,
                                        location=(wheel_x, outer_y, center.z),
                                        major_radius=radius * 0.94, minor_radius=0.012,
                                        rotation=(math.pi / 2, 0, 0))
        lip = bpy.context.object
        lip.name = tire_name.replace("_tire", "_forged_rim_lip")
        lip.data.materials.append(alloy)
        for poly in lip.data.polygons:
            poly.use_smooth = True

        # Ten pairs of tapered, forged spokes leave the drilled rotor and caliper visible.
        for spoke_index in range(10):
            base_angle = math.tau * spoke_index / 10
            for split in (-0.045, 0.045):
                angle = base_angle + split
                bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
                spoke = bpy.context.object
                spoke.name = f"{tire_name.replace('_tire','')}_forged_spoke_{spoke_index:02d}_{'a' if split < 0 else 'b'}"
                spoke.dimensions = (radius * 0.75, 0.042, 0.019)
                spoke.location = (wheel_x + math.cos(angle) * radius * 0.39,
                                  side * 1.181,
                                  center.z + math.sin(angle) * radius * 0.39)
                spoke.rotation_euler[1] = -angle
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                spoke.data.materials.append(alloy)
                bevel = spoke.modifiers.new("Spoke Edge Radius", "BEVEL")
                bevel.width = 0.006
                bevel.segments = 3
                for poly in spoke.data.polygons:
                    poly.use_smooth = True

        # Evenly spaced cross-drilling reads through the gaps between spokes.
        for hole_index in range(18):
            angle = math.tau * hole_index / 18
            bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.006, depth=0.002,
                                               location=(wheel_x + math.cos(angle) * radius * 0.73,
                                                         side * 1.146,
                                                         center.z + math.sin(angle) * radius * 0.73),
                                               rotation=(math.pi / 2, 0, 0))
            hole = bpy.context.object
            hole.name = f"{tire_name.replace('_tire','')}_rotor_hole_{hole_index:02d}"
            hole.data.materials.append(hole_mat)

        bpy.ops.mesh.primitive_cube_add(size=1, location=(wheel_x + radius * 0.56,
                                                         side * 1.14,
                                                         center.z + 0.015))
        caliper = bpy.context.object
        caliper.name = tire_name.replace("_tire", "_red_brake_caliper")
        caliper.dimensions = (0.09, 0.065, radius * 0.78)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        caliper.data.materials.append(caliper_mat)
        bevel = caliper.modifiers.new("Caliper Cast Edges", "BEVEL")
        bevel.width = 0.018
        bevel.segments = 4
        for poly in caliper.data.polygons:
            poly.use_smooth = True

        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.064, depth=0.045,
                                           location=(wheel_x, side * 1.198, center.z),
                                           rotation=(math.pi / 2, 0, 0))
        cap = bpy.context.object
        cap.name = tire_name.replace("_tire", "_machined_center_cap")
        cap.data.materials.append(cap_mat)
        for poly in cap.data.polygons:
            poly.use_smooth = True


def add_cabin_detail():
    leather = make_principled("Black Alcantara Interior", (0.012, 0.016, 0.022), 0.04, 0.52)
    trim = make_principled("Satin Interior Carbon", (0.024, 0.03, 0.04), 0.58, 0.3)
    screen = make_principled("Cockpit Display Glass", (0.006, 0.025, 0.04), 0.24, 0.13)

    def cabin_cube(name, location, dimensions, material, bevel=0.025, rotation=(0, 0, 0)):
        bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = dimensions
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.data.materials.append(material)
        if bevel:
            mod = obj.modifiers.new("Soft Upholstery Edges", "BEVEL")
            mod.width = bevel
            mod.segments = 4
        for poly in obj.data.polygons:
            poly.use_smooth = True
        return obj

    cabin_cube("Cabin Floor", (0.04, 0, 0.36), (1.28, 0.95, 0.08), trim, 0.03)
    cabin_cube("Instrument Panel", (-0.64, 0, 0.76), (0.22, 1.08, 0.17), leather, 0.045)
    cabin_cube("Center Console", (-0.05, 0, 0.63), (0.72, 0.18, 0.12), trim, 0.035)
    cabin_cube("Central Touch Display", (-0.57, 0, 0.865), (0.018, 0.34, 0.105), screen, 0.008)

    for side_name, y in (("Driver", -0.285), ("Passenger", 0.285)):
        cabin_cube(f"{side_name} Seat Base", (0.015, y, 0.49), (0.39, 0.31, 0.14), leather, 0.055)
        cabin_cube(f"{side_name} Bucket Back", (0.22, y, 0.68), (0.16, 0.31, 0.39), leather, 0.055,
                   rotation=(0, math.radians(-9), 0))
        for edge in (-1, 1):
            cabin_cube(f"{side_name} Seat Bolster {edge}", (0.22, y + edge * 0.13, 0.67),
                       (0.18, 0.055, 0.31), trim, 0.025, rotation=(0, math.radians(-9), 0))

    # Driver wheel and column, oriented toward the seat in the side-to-side cabin plane.
    bpy.ops.mesh.primitive_torus_add(major_segments=64, minor_segments=12,
                                    location=(-0.51, -0.29, 0.82), major_radius=0.12,
                                    minor_radius=0.012, rotation=(0, math.pi / 2, 0))
    steering = bpy.context.object
    steering.name = "Flat Bottom Steering Wheel"
    steering.data.materials.append(trim)
    cabin_cube("Steering Hub", (-0.51, -0.29, 0.82), (0.035, 0.07, 0.07), leather, 0.014)


def add_headlight_lenses():
    led = bpy.data.materials.get("led_white")
    if led and led.use_nodes:
        shader = led.node_tree.nodes.get("Principled BSDF")
        if shader:
            set_input(shader, ["Base Color"], (0.58, 0.7, 0.82, 1.0))
            set_input(shader, ["Emission Color", "Emission"], (0.12, 0.2, 0.32, 1.0))
            set_input(shader, ["Emission Strength"], 0.15)
            set_input(shader, ["Roughness"], 0.3)
    # Replace the thick lofted sweeps with a fine, surface-following Y LED trace.
    for name in ("front_headlight_signature_left", "front_headlight_signature_right"):
        obj = bpy.data.objects.get(name)
        if obj:
            obj.hide_render = True
    for side in (-1, 1):
        path = [(-2.34, side * 0.365, 0.612),
                (-2.292, side * 0.425, 0.644),
                (-2.222, side * 0.49, 0.671),
                (-2.145, side * 0.55, 0.689),
                (-2.205, side * 0.465, 0.642),
                (-2.295, side * 0.39, 0.621)]
        curve = bpy.data.curves.new("Thin Revuelto Y Light", "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = 0.006
        curve.bevel_resolution = 3
        spline = curve.splines.new("POLY")
        spline.points.add(len(path) - 1)
        for point, position in zip(spline.points, path):
            point.co = (*position, 1)
        line = bpy.data.objects.new(f"Thin Y LED {'L' if side < 0 else 'R'}", curve)
        bpy.context.collection.objects.link(line)
        curve.materials.append(led)
        bpy.context.view_layer.objects.active = line
        line.select_set(True)
        bpy.ops.object.convert(target="MESH")


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area(name, location, target, power, shape, size_x, size_y, color):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.shape = shape
    data.size = size_x
    if shape == "RECTANGLE":
        data.size_y = size_y
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    aim(obj, target)
    return obj


def add_studio(scene):
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0.015))
    floor = bpy.context.object
    floor.name = "Studio Cyclorama Floor"
    mat = bpy.data.materials.new("Studio Charcoal")
    mat.diffuse_color = (0.025, 0.034, 0.048, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (0.025, 0.034, 0.048, 1)
    shader.inputs["Roughness"].default_value = 0.32
    floor.data.materials.append(mat)

    center = (0, 0, 0.62)
    add_area("Key Softbox", (-3.8, -4.0, 6.2), center, 800, "RECTANGLE", 5.0, 2.4, (1.0, 0.84, 0.72))
    add_area("Front Fill", (-4.8, 2.8, 3.6), center, 420, "RECTANGLE", 4.0, 2.0, (0.72, 0.82, 1.0))
    add_area("Roof Strip", (0.4, -0.6, 6.8), center, 1150, "RECTANGLE", 6.0, 1.6, (1.0, 0.95, 0.88))
    add_area("Rear Rim", (3.8, 3.0, 4.4), center, 850, "RECTANGLE", 4.0, 1.4, (0.62, 0.76, 1.0))
    add_area("Side Strip", (0.3, -5.0, 2.2), center, 340, "RECTANGLE", 5.0, 1.2, (1.0, 0.52, 0.31))

    world = bpy.data.worlds.new("Automotive Studio World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.075, 0.09, 0.12, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.22
    scene.world = world

    camera_data = bpy.data.cameras.new("Hero Camera")
    camera = bpy.data.objects.new("Hero Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (-6.7, -6.2, 3.25)
    aim(camera, (0.0, 0.0, 0.62))
    camera_data.lens = 58
    scene.camera = camera


def smooth_meshes():
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        if obj.name in {"outer_body_shell", "tinted_greenhouse"}:
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()


def main():
    source, blend_path, glb_path, render_path = args()
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(source))
    scene = bpy.context.scene
    tune_materials()
    smooth_meshes()
    add_brake_and_wheel_detail()
    add_cabin_detail()
    add_headlight_lenses()
    add_studio(scene)

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 128
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.filepath = os.path.abspath(render_path)
    scene.camera.data.dof.use_dof = False
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(blend_path))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in scene.objects:
        if obj.type == "MESH" and obj.name != "Studio Cyclorama Floor":
            obj.select_set(True)
    mesh_active = next((obj for obj in scene.objects if obj.select_get() and obj.type == "MESH"), None)
    bpy.context.view_layer.objects.active = mesh_active
    export_options = {
        "filepath": os.path.abspath(glb_path),
        "export_format": "GLB",
        "use_selection": True,
        "export_apply": True,
        "export_materials": "EXPORT",
        "export_cameras": False,
        "export_lights": False,
        "export_extras": True,
    }
    available = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    bpy.ops.export_scene.gltf(**{key: value for key, value in export_options.items() if key in available})
    print("Saved refined scene:", os.path.abspath(blend_path))
    print("Saved refined GLB:", os.path.abspath(glb_path))
    print("Saved hero render:", os.path.abspath(render_path))


if __name__ == "__main__":
    main()
