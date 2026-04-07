from typing import Union, List, Tuple
from dataclasses import dataclass, field

import bpy
import cadquery

ParametricShape = cadquery.Shape
ParametricObject = Union[
    ParametricShape,
    cadquery.Workplane,
    cadquery.Assembly,
]

BLENDQUERY_INSTANCE_MARKER = "is_blendquery_instance"
BLENDQUERY_OUTPUT_COLLECTION_KEY = "blendquery_output_collection"


@dataclass
class ParametricObjectNode:
    name: str
    material: Union[str, None] = None
    children: List["ParametricObjectNode"] = field(default_factory=list)
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    faces: List[Tuple[int, int, int]] = field(default_factory=list)


class BlendQueryBuildException(Exception):
    def __init__(self, message):
        super().__init__(message)


def is_blendquery_instance_root(blender_object: bpy.types.Object) -> bool:
    if blender_object is None:
        return False
    try:
        return bool(blender_object.get(BLENDQUERY_INSTANCE_MARKER, False))
    except Exception:
        return False


def ensure_blendquery_instance_root(
    blender_object: bpy.types.Object,
) -> bpy.types.Object:
    if blender_object is None:
        raise BlendQueryBuildException("No BlendQuery instance root was provided.")

    instance_root = find_blendquery_instance_root(blender_object)
    if instance_root is None:
        raise BlendQueryBuildException(
            f"Object '{blender_object.name}' is not inside a BlendQuery instance."
        )

    return instance_root

def get_blendquery_output_collection(
    instance_root: bpy.types.Object,
) -> bpy.types.Collection:
    if instance_root is None:
        raise BlendQueryBuildException("BlendQuery instance root is missing.")

    stored_name = instance_root.get(BLENDQUERY_OUTPUT_COLLECTION_KEY, None)
    if stored_name:
        output_collection = bpy.data.collections.get(stored_name)
        if output_collection is not None:
            return output_collection

    # Fallback: reacquire from current linked collections
    for collection in instance_root.users_collection:
        if collection is not None:
            instance_root[BLENDQUERY_OUTPUT_COLLECTION_KEY] = collection.name
            return collection

    raise BlendQueryBuildException(
        f"BlendQuery instance '{instance_root.name}' is not linked to any live output collection."
    )

def regenerate_blendquery_object(
    parametric_objects: List[ParametricObject],
    root_blender_object: bpy.types.Object,
    old_blender_objects,
):
    instance_root = ensure_blendquery_instance_root(root_blender_object)
    output_collection = get_blendquery_output_collection(instance_root)

    active = bpy.context.view_layer.objects.active
    selected_objects = bpy.context.selected_objects.copy()

    clear_output_collection(instance_root, output_collection, old_blender_objects)

    new_blender_objects = []
    print("BLENDQUERY TOP LEVEL COUNT:", len(parametric_objects))
    print(
        "BLENDQUERY TOP LEVEL NAMES:",
        [getattr(obj, "name", "<unnamed>") for obj in parametric_objects],
    )

    for parametric_object in parametric_objects:
        new_blender_objects.append(
            build_blender_object(parametric_object, instance_root)
        )

    new_blender_objects = flatten_list(new_blender_objects)

    for blender_object in new_blender_objects:
        if output_collection.objects.get(blender_object.name) is None:
            output_collection.objects.link(blender_object)

        property_group = old_blender_objects.add()
        property_group.object = blender_object

    for selected_object in bpy.context.selected_objects:
        selected_object.select_set(False)

    try:
        for selected_object in selected_objects:
            if selected_object and bpy.data.objects.get(selected_object.name) is not None:
                selected_object.select_set(True)

        if active and bpy.data.objects.get(active.name) is not None:
            bpy.context.view_layer.objects.active = active
    except Exception:
        pass


def find_blendquery_instance_root(
    blender_object: bpy.types.Object,
) -> Union[bpy.types.Object, None]:
    current = blender_object

    while current is not None:
        if is_blendquery_instance_root(current):
            return current
        current = current.parent

    return None


def gather_object_subtree(
    root_object: bpy.types.Object,
) -> List[bpy.types.Object]:
    if root_object is None:
        return []

    gathered_names: List[str] = []

    def _walk(obj: bpy.types.Object):
        gathered_names.append(obj.name)
        for child in list(obj.children):
            _walk(child)

    _walk(root_object)

    gathered_objects: List[bpy.types.Object] = []
    for name in gathered_names:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            gathered_objects.append(obj)

    return gathered_objects


def delete_object_subtree(root_object: bpy.types.Object):
    if root_object is None:
        return

    subtree_names = [obj.name for obj in gather_object_subtree(root_object)]
    subtree_names = sorted(
        subtree_names,
        key=lambda name: object_parent_depth(bpy.data.objects[name]) if bpy.data.objects.get(name) else -1,
        reverse=True,
    )

    meshes_to_cleanup = []

    for name in subtree_names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue

        try:
            if obj.type == "MESH" and obj.data is not None:
                meshes_to_cleanup.append(obj.data)

            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            continue

    for mesh in meshes_to_cleanup:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except Exception:
            continue

def object_parent_depth(blender_object: bpy.types.Object) -> int:
    depth = 0
    current = blender_object

    while current is not None and current.parent is not None:
        depth += 1
        current = current.parent

    return depth
 

def delete_blendquery_instance_from_object(
    blender_object: bpy.types.Object,
    tracked_blender_objects=None,
):
    if blender_object is None:
        raise BlendQueryBuildException("No object was provided for deletion.")

    delete_object_subtree(blender_object)

    if tracked_blender_objects is not None:
        try:
            stale_indexes = []
            for index, pointer in enumerate(tracked_blender_objects):
                try:
                    obj = pointer.object
                except Exception:
                    obj = None

                if obj is None:
                    stale_indexes.append(index)

            for index in reversed(stale_indexes):
                tracked_blender_objects.remove(index)
        except Exception:
            pass

    try:
        bpy.context.view_layer.objects.active = None
    except Exception:
        pass

def clear_output_collection(
    instance_root: bpy.types.Object,
    output_collection: bpy.types.Collection,
    blender_objects,
):
    to_delete = [obj for obj in list(output_collection.objects) if obj != instance_root]

    meshes_to_cleanup = []

    for obj in to_delete:
        try:
            if obj.type == "MESH" and obj.data is not None:
                meshes_to_cleanup.append(obj.data)

            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            continue

    for mesh in meshes_to_cleanup:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except Exception:
            continue

    blender_objects.clear()


def delete_blender_objects(blender_objects):
    for pointer in blender_objects:
        try:
            obj = pointer.object
            if obj is None:
                continue

            mesh = obj.data if obj.type == "MESH" else None

            bpy.data.objects.remove(obj, do_unlink=True)

            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except Exception:
            continue

    blender_objects.clear()


def build_blender_object(
    parametric_object: ParametricObjectNode,
    parent: bpy.types.Object,
):
    mesh = None

    if len(parametric_object.vertices) > 0:
        mesh = bpy.data.meshes.new(parametric_object.name)
        mesh.from_pydata(parametric_object.vertices, [], parametric_object.faces)
        mesh.update()

    blender_object = bpy.data.objects.new(
        parametric_object.name,
        mesh,
    )

    if mesh is not None and parametric_object.material is not None:
        try:
            material = bpy.data.materials[parametric_object.material]
            blender_object.data.materials.append(material)
        except Exception:
            pass

    blender_object.parent = parent

    blender_objects = [blender_object]

    for child in parametric_object.children:
        blender_objects.append(build_blender_object(child, blender_object))

    return blender_objects


def flatten_list(nested_list):
    flattened_list = []

    for item in nested_list:
        if isinstance(item, list):
            flattened_list.extend(flatten_list(item))
        else:
            flattened_list.append(item)

    return flattened_list