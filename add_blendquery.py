import uuid
import bpy
from .blendquery import (
    delete_blendquery_instance_from_object,
    BlendQueryBuildException,
)

BLENDQUERY_INSTANCE_MARKER = "is_blendquery_instance"
BLENDQUERY_INSTANCE_ID_KEY = "blendquery_instance_id"
BLENDQUERY_OUTPUT_COLLECTION_KEY = "blendquery_output_collection"
BLENDQUERY_SCRIPT_KEY = "blendquery_script"
BLENDQUERY_TESSELLATION_TOLERANCE_KEY = "blendquery_tess_tol"
BLENDQUERY_ANGULAR_TOLERANCE_KEY = "blendquery_ang_tol"


def make_default_instance_name() -> str:
    return "BlendQuery"


def make_default_output_collection_name(instance_name: str) -> str:
    return f"{instance_name}__bq"


class OBJECT_OT_add_blendquery_instance(bpy.types.Operator):
    bl_idname = "object.add_blendquery_instance"
    bl_label = "Add BlendQuery Instance"
    bl_description = "Create a new BlendQuery instance empty and owned output collection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        scene_collection = context.scene.collection

        instance_name = make_default_instance_name()
        output_collection_name = make_default_output_collection_name(instance_name)

        instance_object = bpy.data.objects.new(instance_name, None)
        instance_object.empty_display_type = "PLAIN_AXES"
        instance_object.empty_display_size = 0.5

        instance_object[BLENDQUERY_INSTANCE_MARKER] = True
        instance_object[BLENDQUERY_INSTANCE_ID_KEY] = str(uuid.uuid4())
        instance_object[BLENDQUERY_SCRIPT_KEY] = ""
        instance_object[BLENDQUERY_TESSELLATION_TOLERANCE_KEY] = 0.1
        instance_object[BLENDQUERY_ANGULAR_TOLERANCE_KEY] = 0.1

        output_collection = bpy.data.collections.new(output_collection_name)
        scene_collection.children.link(output_collection)

        instance_object[BLENDQUERY_OUTPUT_COLLECTION_KEY] = output_collection.name
        output_collection.objects.link(instance_object)

        for obj in context.selected_objects:
            obj.select_set(False)

        instance_object.select_set(True)
        context.view_layer.objects.active = instance_object

        self.report({"INFO"}, f"Created BlendQuery instance '{instance_object.name}'")
        return {"FINISHED"}


class OBJECT_OT_delete_blendquery_subtree(bpy.types.Operator):
    bl_idname = "object.delete_blendquery_subtree"
    bl_label = "Delete BlendQuery Subtree"
    bl_description = "Delete the clicked object and all of its children"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.view_layer.objects.active is not None

    def execute(self, context: bpy.types.Context):
        active_object = context.view_layer.objects.active

        if active_object is None:
            self.report({"ERROR"}, "No active object selected.")
            return {"CANCELLED"}

        try:
            delete_blendquery_instance_from_object(active_object)
        except BlendQueryBuildException as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to delete subtree: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Deleted subtree.")
        return {"FINISHED"}


def menu_func(self, context):
    self.layout.operator(
        OBJECT_OT_add_blendquery_instance.bl_idname,
        icon="EMPTY_AXIS",
    )


classes = (
    OBJECT_OT_add_blendquery_instance,
    OBJECT_OT_delete_blendquery_subtree,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.VIEW3D_MT_add.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(menu_func)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)