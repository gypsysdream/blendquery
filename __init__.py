bl_info = {
    "name": "BlendQuery",
    "blender": (3, 0, 0),
    "category": "Parametric",
}

import os
import re
import sys
import traceback
import importlib
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from setup_venv import setup_venv

venv_dir = setup_venv()

numpy = None
cadquery = None
build123d = None

numpy_version = None
cadquery_version = None
build123d_version = None

BLENDQUERY_INSTANCE_MARKER = "is_blendquery_instance"
BLENDQUERY_INSTANCE_ID_KEY = "blendquery_instance_id"
BLENDQUERY_OUTPUT_COLLECTION_KEY = "blendquery_output_collection"

SOURCE_MODE_ITEMS = [
    ("MASOCHIST", "Masochist Mode", "Run the in-Blender text datablock"),
    ("SADIST", "Sadist Mode", "Run the physical file from disk"),
]

# TODO: Find a better way to store/reset
are_dependencies_installed = False
dependency_status_message = "Dependency status has not been checked yet."

dependency_status_level = "INFO"


def set_dependency_status(message: str, level: str = "INFO"):
    global dependency_status_message, dependency_status_level
    dependency_status_message = message
    dependency_status_level = level

def get_blendquery_module():
    return importlib.import_module(f"{__package__}.blendquery")


def get_addon_preferences(context=None):
    if context is None:
        context = bpy.context

    addons = context.preferences.addons
    addon = addons.get(__package__)
    if addon is None:
        return None
    return addon.preferences


def is_build123d_enabled(context=None):
    preferences = get_addon_preferences(context)
    if preferences is None:
        return False
    return preferences.enable_build123d

def get_module_version(module):
    if module is None:
        return None

    version = getattr(module, "__version__", None)
    if version:
        return str(version)

    try:
        from importlib.metadata import version as dist_version
        package_name = getattr(module, "__name__", None)
        if package_name:
            return dist_version(package_name)
    except Exception:
        pass

    return "unknown"

def set_dependency_versions(numpy_ver=None, cadquery_ver=None, build123d_ver=None):
    global numpy_version, cadquery_version, build123d_version
    numpy_version = numpy_ver
    cadquery_version = cadquery_ver
    build123d_version = build123d_ver


def probe_venv_dependencies(enable_build123d: bool):
    import subprocess
    import json

    python_executable = os.path.join(
        venv_dir,
        "Scripts" if os.name == "nt" else "bin",
        "python.exe" if os.name == "nt" else "python",
    )
    probe_script = f"""
import json

result = {{}}

try:
    import numpy
    result["numpy_ok"] = True
    result["numpy_version"] = getattr(numpy, "__version__", "unknown")
except Exception as exc:
    result["numpy_ok"] = False
    result["numpy_error"] = str(exc)

try:
    import cadquery
    result["cadquery_ok"] = True
    result["cadquery_version"] = getattr(cadquery, "__version__", "unknown")
except Exception as exc:
    result["cadquery_ok"] = False
    result["cadquery_error"] = str(exc)

enable_build123d = {repr(enable_build123d)}
if enable_build123d:
    try:
        import build123d
        result["build123d_ok"] = True
        result["build123d_version"] = getattr(build123d, "__version__", "unknown")
    except Exception as exc:
        result["build123d_ok"] = False
        result["build123d_error"] = str(exc)
else:
    result["build123d_ok"] = False
    result["build123d_disabled"] = True

print(json.dumps(result))
"""

    completed = subprocess.run(
        [python_executable, "-c", probe_script],
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip() or "Dependency probe subprocess failed."
        )

    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError("Dependency probe subprocess returned no output.")

    return json.loads(stdout)

def statusbar_progress_bar(self, context):
    if bpy.context.window_manager.blendquery.is_regenerating:
        layout = self.layout
        row = layout.row()
        row.progress(
            text="Regenerating BlendQuery Objects",
            factor=bpy.context.window_manager.blendquery.regeneration_progress,
            type="BAR",
        )
        row.scale_x = 4


class BlendQueryAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    enable_build123d: bpy.props.BoolProperty(
        name="Enable build123d backend",
        description="Allow BlendQuery to import and use build123d when available",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        column = layout.column(align=True)

        column.label(text="Optional Backends")
        column.prop(self, "enable_build123d")

        status_box = layout.box()
        status_box.label(text="Dependency Status")

        resolved_cadquery_version = cadquery_version
        resolved_build123d_version = build123d_version
        resolved_numpy_version = numpy_version

        if cadquery is None:
            status_box.label(text="CadQuery: not imported")
        else:
            status_box.label(text=f"CadQuery: available ({resolved_cadquery_version or 'unknown'})")

        if self.enable_build123d:
            if build123d is None:
                status_box.label(text="build123d: enabled but not available")
            else:
                status_box.label(
                    text=f"build123d: enabled and available ({resolved_build123d_version or 'unknown'})"
                )
        else:
            status_box.label(text="build123d: disabled")

        if numpy is None:
            status_box.label(text="NumPy: not imported")
        else:
            status_box.label(text=f"NumPy: available ({resolved_numpy_version or 'unknown'})")

        icon = "ERROR" if dependency_status_level == "ERROR" else "INFO"
        status_box.separator()
        status_box.label(text=dependency_status_message, icon=icon)

        layout.separator()
        layout.operator("blendquery.import_dependencies", icon="FILE_REFRESH")

class BlendQueryAddInstanceOperator(bpy.types.Operator):
    bl_idname = "blendquery.add_instance"
    bl_label = "BlendQuery Instance"
    bl_description = "Create a new BlendQuery instance empty and owned collection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        import uuid

        scene_collection = context.scene.collection

        instance_name = "BlendQuery"
        output_collection_name = f"{instance_name}__bq"

        output_collection = bpy.data.collections.new(output_collection_name)
        scene_collection.children.link(output_collection)

        instance_object = bpy.data.objects.new(instance_name, None)
        instance_object.empty_display_type = "PLAIN_AXES"
        instance_object.empty_display_size = 0.5

        instance_object[BLENDQUERY_INSTANCE_MARKER] = True
        instance_object[BLENDQUERY_INSTANCE_ID_KEY] = str(uuid.uuid4())
        instance_object[BLENDQUERY_OUTPUT_COLLECTION_KEY] = output_collection.name

        output_collection.objects.link(instance_object)

        for obj in context.selected_objects:
            obj.select_set(False)

        instance_object.select_set(True)
        context.view_layer.objects.active = instance_object

        return {"FINISHED"}


class BlendQueryDeleteSubtreeOperator(bpy.types.Operator):
    bl_idname = "blendquery.delete_subtree"
    bl_label = "Delete BlendQuery Subtree"
    bl_description = "Delete the selected object and all of its children"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({"WARNING"}, "No active object selected.")
            return {"CANCELLED"}

        try:
            blendquery_module = get_blendquery_module()
            blendquery_module.delete_object_subtree(obj)
        except Exception as exc:
            self.report({"WARNING"}, f"Failed to delete subtree: {exc}")
            return {"CANCELLED"}

        return {"FINISHED"}


class BlendQueryPickScriptFileOperator(bpy.types.Operator):
    bl_idname = "blendquery.pick_script_file"
    bl_label = "Pick BlendQuery Script File"
    bl_description = "Choose a physical Python file for Sadist Mode"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            current_path = obj.blendquery.script_path
            if current_path:
                self.filepath = bpy.path.abspath(current_path)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({"WARNING"}, "No active object selected.")
            return {"CANCELLED"}

        obj.blendquery.script_path = self.filepath
        self.report({"INFO"}, f"Set script path to: {self.filepath}")
        return {"FINISHED"}


def register():
    bpy.utils.register_class(ObjectPropertyGroup)
    bpy.utils.register_class(BlendQueryPropertyGroup)
    bpy.utils.register_class(BlendQueryImportDependenciesOperator)
    bpy.utils.register_class(BlendQueryInstallOperator)
    bpy.utils.register_class(BlendQueryRegenerateOperator)
    bpy.utils.register_class(BlendQueryPanel)
    bpy.utils.register_class(BlendQueryWindowPropertyGroup)
    bpy.utils.register_class(BlendQueryAddonPreferences)
    bpy.utils.register_class(BlendQueryAddInstanceOperator)
    bpy.utils.register_class(BlendQueryDeleteSubtreeOperator)
    bpy.utils.register_class(BlendQueryPickScriptFileOperator)
    bpy.types.VIEW3D_MT_add.append(menu_add_blendquery)

    bpy.types.WindowManager.blendquery = bpy.props.PointerProperty(
        type=BlendQueryWindowPropertyGroup
    )
    bpy.types.Object.blendquery = bpy.props.PointerProperty(
        type=BlendQueryPropertyGroup
    )

    bpy.app.handlers.load_post.append(initialise)
    bpy.types.STATUSBAR_HT_header.append(statusbar_progress_bar)


def unregister():
    try:
        bpy.types.STATUSBAR_HT_header.remove(statusbar_progress_bar)
        bpy.app.handlers.load_post.remove(initialise)
    except Exception:
        pass

    del bpy.types.Object.blendquery
    del bpy.types.WindowManager.blendquery

    bpy.utils.unregister_class(BlendQueryPanel)
    bpy.utils.unregister_class(BlendQueryWindowPropertyGroup)
    bpy.utils.unregister_class(BlendQueryRegenerateOperator)
    bpy.utils.unregister_class(BlendQueryInstallOperator)
    bpy.utils.unregister_class(BlendQueryImportDependenciesOperator)
    bpy.utils.unregister_class(BlendQueryPropertyGroup)
    bpy.utils.unregister_class(ObjectPropertyGroup)
    try:
        bpy.types.VIEW3D_MT_add.remove(menu_add_blendquery)
    except Exception:
        pass
    bpy.utils.unregister_class(BlendQueryPickScriptFileOperator)
    bpy.utils.unregister_class(BlendQueryDeleteSubtreeOperator)
    bpy.utils.unregister_class(BlendQueryAddInstanceOperator)
    bpy.utils.unregister_class(BlendQueryAddonPreferences)


@persistent
def initialise(_=None):
    bpy.ops.blendquery.import_dependencies()
    if not are_dependencies_installed:
        return


def menu_add_blendquery(self, context):
    self.layout.operator(
        BlendQueryAddInstanceOperator.bl_idname,
        icon="EMPTY_AXIS",
        text="BlendQuery Instance",
    )


def update(_object):
    # Auto-regeneration intentionally disabled for stability.
    return


class ObjectPropertyGroup(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object)


class BlendQueryPropertyGroup(bpy.types.PropertyGroup):
    def _update(self, _context):
        update(self.id_data)

    source_mode: bpy.props.EnumProperty(
        name="Source Mode",
        items=SOURCE_MODE_ITEMS,
        default="MASOCHIST",
        update=_update,
    )

    script: bpy.props.PointerProperty(
        name="Script",
        type=bpy.types.Text,
        update=_update,
    )

    script_path: bpy.props.StringProperty(
        name="Script Path",
        subtype="FILE_PATH",
        update=_update,
    )

    object_pointers: bpy.props.CollectionProperty(type=ObjectPropertyGroup)

    tessellation_tolerance: bpy.props.FloatProperty(
        name="Tess Tol",
        default=1.1,
        min=0.001,
        soft_max=5.0,
        update=_update,
    )

    tessellation_angular_tolerance: bpy.props.FloatProperty(
        name="Angle Tol",
        default=1.1,
        min=0.001,
        soft_max=5.0,
        update=_update,
    )


def ui_update(self, context):
    if context.area:
        for region in context.area.regions:
            if region.type == "UI":
                region.tag_redraw()
    return None


class BlendQueryWindowPropertyGroup(bpy.types.PropertyGroup):
    installing_dependencies: bpy.props.BoolProperty(
        name="Installing",
        default=False,
        description="Whether BlendQuery is installing dependencies",
    )

    is_regenerating: bpy.props.BoolProperty(update=ui_update)
    regeneration_progress: bpy.props.FloatProperty(update=ui_update)


class BlendQueryImportDependenciesOperator(bpy.types.Operator):
    bl_idname = "blendquery.import_dependencies"
    bl_label = "BlendQuery Import Dependencies"

    import_error = None

    def execute(self, context):
        global are_dependencies_installed
        global cadquery, build123d, numpy

        self.import_error = None

        try:
            enable_build123d = is_build123d_enabled(context)
            result = probe_venv_dependencies(enable_build123d)

            numpy = object() if result.get("numpy_ok") else None
            cadquery = object() if result.get("cadquery_ok") else None
            build123d = object() if result.get("build123d_ok") else None

            set_dependency_versions(
                numpy_ver=result.get("numpy_version"),
                cadquery_ver=result.get("cadquery_version"),
                build123d_ver=result.get("build123d_version"),
            )

            if not result.get("cadquery_ok"):
                are_dependencies_installed = False
                set_dependency_status(
                    "CadQuery import failed in BlendQuery venv: "
                    + result.get("cadquery_error", "unknown error"),
                    "ERROR",
                )
            elif enable_build123d:
                if result.get("build123d_ok"):
                    are_dependencies_installed = True
                    set_dependency_status(
                        "CadQuery available. build123d enabled and available.",
                        "INFO",
                    )
                else:
                    are_dependencies_installed = True
                    set_dependency_status(
                        "CadQuery available. build123d is enabled but could not be imported: "
                        + result.get("build123d_error", "unknown error"),
                        "ERROR",
                    )
            else:
                are_dependencies_installed = True
                set_dependency_status(
                    "CadQuery available. build123d is disabled in add-on preferences.",
                    "INFO",
                )

        except Exception:
            numpy = None
            cadquery = None
            build123d = None
            are_dependencies_installed = False
            set_dependency_versions(None, None, None)

            exception_trace = traceback.format_exc()
            self.import_error = (
                f"Failed to probe BlendQuery dependencies: {exception_trace}"
            )
            set_dependency_status(
                "Dependency probe failed. See warning/details for traceback.",
                "ERROR",
            )

        context.window_manager.modal_handler_add(self)
        redraw_ui()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self.import_error is not None:
            self.report({"WARNING"}, self.import_error)
            redraw_info_area()
        return {"FINISHED"}


def create_parse_parametric_script_thread(payload):
    import threading
    import subprocess
    import queue
    import pickle

    response = queue.Queue()

    def process():
        cwd = os.path.dirname(os.path.abspath(__file__))
        parent_directory = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        env = os.environ.copy()
        env["PATH"] = parent_directory

        python_executable = os.path.join(
            venv_dir,
            "Scripts" if os.name == "nt" else "bin",
            "python.exe" if os.name == "nt" else "python",
        )

        python_executable = os.path.join(
            venv_dir,
            "Scripts" if os.name == "nt" else "bin",
            "python.exe" if os.name == "nt" else "python",
        )
        
        proc = subprocess.Popen(
            [python_executable, "parse.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout_data, stderr_data = proc.communicate(
                input=pickle.dumps(payload),
                timeout=10,
            )
            if not stdout_data:
                stderr_text = (
                    stderr_data.decode("utf-8", errors="replace")
                    if stderr_data
                    else "No stdout returned from parse.py"
                )
                response.put(RuntimeError(stderr_text))
                return

            response.put(pickle.loads(stdout_data))
        except subprocess.TimeoutExpired:
            proc.kill()
            response.put(RuntimeError("BlendQuery parse timed out."))
        except Exception as exception:
            response.put(exception)

    thread = threading.Thread(target=process)
    thread.start()
    return thread, response


regenerate_operators = []


def update_regeneration_progress():
    bpy.context.window_manager.blendquery.is_regenerating = (
        len(regenerate_operators) > 0
    )
    bpy.context.window_manager.blendquery.regeneration_progress = 1 / (
        len(regenerate_operators) + 1
    )


class BlendQueryRegenerateOperator(bpy.types.Operator):
    bl_idname = "blendquery.regenerate"
    bl_label = "BlendQuery Regenerate"

    def execute(self, context):
        self.object = context.active_object

        if not self.object:
            self.report({"WARNING"}, "No active object selected.")
            return {"CANCELLED"}

        source_mode = self.object.blendquery.source_mode

        if source_mode == "MASOCHIST":
            if not self.object.blendquery.script:
                self.report({"WARNING"}, "No BlendQuery text script assigned.")
                return {"CANCELLED"}

            script_text = self.object.blendquery.script.as_string()

        elif source_mode == "SADIST":
            script_path = self.object.blendquery.script_path
            if not script_path:
                self.report({"WARNING"}, "No BlendQuery script path assigned.")
                return {"CANCELLED"}

            resolved_path = Path(bpy.path.abspath(script_path))
            if not resolved_path.exists():
                self.report(
                    {"WARNING"},
                    f"BlendQuery script file was not found: {resolved_path}",
                )
                return {"CANCELLED"}

            try:
                script_text = resolved_path.read_text(encoding="utf-8")
            except Exception as exc:
                self.report(
                    {"WARNING"},
                    f"Failed to read BlendQuery script file: {exc}",
                )
                return {"CANCELLED"}

            print("BLENDQUERY SADIST MODE PATH:", str(resolved_path))

        else:
            self.report({"WARNING"}, f"Unknown source mode: {source_mode}")
            return {"CANCELLED"}

        payload = {
            "script": script_text,
            "tolerance": self.object.blendquery.tessellation_tolerance,
            "angular_tolerance": self.object.blendquery.tessellation_angular_tolerance,
            "enable_build123d": is_build123d_enabled(context),
        }

        self.thread, self.response = create_parse_parametric_script_thread(payload)

        regenerate_operators.append(self)
        update_regeneration_progress()

        self.timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self.thread.is_alive():
            return {"PASS_THROUGH"}

        response = self.response.get()
        if isinstance(response, Exception):
            self.report_exception(response)
        else:
            blendquery_module = get_blendquery_module()
            blendquery_module.regenerate_blendquery_object(
                response,
                self.object,
                self.object.blendquery.object_pointers,
            )

        regenerate_operators.remove(self)
        update_regeneration_progress()
        context.window_manager.event_timer_remove(self.timer)

        return {"FINISHED"}

    def report_exception(self, exception):
        stack_trace = "".join(
            traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
            )
        )
        script_error = re.search(
            r'File "<string>",\s*(.*(?:\n.*)*)',
            stack_trace,
            re.MULTILINE | re.DOTALL,
        )
        self.report(
            {"WARNING"},
            f"Failed to regenerate BlendQuery object: "
            f"{script_error and script_error.group(1) or stack_trace}",
        )
        redraw_info_area()


class BlendQueryInstallOperator(bpy.types.Operator):
    bl_idname = "blendquery.install"
    bl_label = "Install"
    bl_description = "Installs BlendQuery required dependencies."

    exception = None

    def invoke(self, context, event):
        from install import install_dependencies, BlendQueryInstallException

        def callback(result):
            if isinstance(result, BlendQueryInstallException):
                self.exception = result

        pip_executable = os.path.join(
            venv_dir, "Scripts" if os.name == "nt" else "bin", "pip"
        )
        self.thread = install_dependencies(pip_executable, callback)

        self.timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.window_manager.blendquery.installing_dependencies = True
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not self.thread.is_alive():
            if self.exception:
                self.report(
                    {"WARNING"},
                    f"Failed to install BlendQuery dependencies: {self.exception}",
                )
                redraw_info_area()
            else:
                initialise()

            context.window_manager.blendquery.installing_dependencies = False
            context.window_manager.event_timer_remove(self.timer)
            redraw_ui()
            return {"FINISHED"}

        return {"PASS_THROUGH"}


class BlendQueryPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_BLENDQUERY_PANEL"
    bl_label = bl_info["name"]
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    def draw(self, context):
        layout = self.layout
        if are_dependencies_installed:
            self.installed(layout, context)
        else:
            self.not_installed(layout, context)

    def installed(self, layout, context):
        if context.active_object:
            obj = context.active_object
            column = layout.column()

            column.prop(obj.blendquery, "source_mode")

            if obj.blendquery.source_mode == "MASOCHIST":
                column.prop(obj.blendquery, "script")
            elif obj.blendquery.source_mode == "SADIST":
                row = column.row(align=True)
                row.prop(obj.blendquery, "script_path", text="Script Path")
                row.operator("blendquery.pick_script_file", text="", icon="FILE_FOLDER")

            column.prop(obj.blendquery, "tessellation_tolerance")
            column.prop(obj.blendquery, "tessellation_angular_tolerance")
            column.separator(factor=0.5)

            row = column.row()
            row.operator("blendquery.regenerate", text="Regenerate")

            row = column.row()
            row.operator("blendquery.delete_subtree", text="Delete Subtree")

    def not_installed(self, layout, context):
        box = layout.box()
        box.label(
            icon="INFO",
            text="BlendQuery requires the following dependencies to be installed:",
        )
        box.label(text="    • CadQuery")
        column = box.column()
        if context.window_manager.blendquery.installing_dependencies:
            column.enabled = False
            column.operator(
                "blendquery.install",
                icon="PACKAGE",
                text="Installing dependencies...",
            )
        else:
            column.operator(
                "blendquery.install",
                icon="PACKAGE",
                text="Install dependencies",
            )


def redraw_ui():
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)


def redraw_info_area():
    for area in bpy.context.screen.areas:
        if area.type == "INFO":
            area.tag_redraw()