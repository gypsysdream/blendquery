import sys
import pickle
from typing import Union

from interop_types import ParametricObjectNode, BlendQueryBuildException


def main():
    try:
        from setup_venv import setup_venv
        setup_venv()

        import cadquery

        ParametricShape = cadquery.Shape
        ParametricObject = Union[
            ParametricShape,
            cadquery.Workplane,
            cadquery.Assembly,
        ]

        payload = pickle.loads(sys.stdin.buffer.read())
        parametric_script = payload["script"]
        tolerance = payload["tolerance"]
        angular_tolerance = payload["angular_tolerance"]

        def parse_parametric_script(script: str):
            locals = {}
            globals = {
                "cadquery": cadquery,
                "cq": cadquery,
            }
            exec(script, globals, locals)

            return [
                parse_parametric_object(value, name, None)
                for name, value in locals.items()
                if isinstance(value, ParametricObject) and not name.startswith("_")
            ]

        def parse_parametric_object(
            object: ParametricObject,
            name: str,
            material: Union[str, None],
        ) -> ParametricObjectNode:
            name = object.name if (hasattr(object, "name") and object.name) else name
            material = (
                object.material if (hasattr(object, "material") and object.material) else material
            )

            if isinstance(object, cadquery.Assembly):
                return ParametricObjectNode(
                    name=name,
                    material=material,
                    children=[
                        parse_parametric_object(child, name, material)
                        for child in object.shapes + object.children
                    ],
                )

            if isinstance(object, ParametricShape):
                shape = object
            elif isinstance(object, cadquery.Workplane):
                vals = object.vals()
                if not vals:
                    raise BlendQueryBuildException("Workplane produced no solids.")
                shape = cadquery.Shape(vals[0].wrapped)
            else:
                raise BlendQueryBuildException(
                    "Failed to parse parametric object; Unsupported object type ("
                    + str(type(object))
                    + ")."
                )

            vertices, faces = shape.tessellate(tolerance, angular_tolerance)
            vertices = [
                vertex.toTuple() if hasattr(vertex, "toTuple") else vertex.to_tuple()
                for vertex in vertices
            ]

            return ParametricObjectNode(
                name=name,
                material=material,
                vertices=vertices,
                faces=faces,
            )

        parametric_objects = parse_parametric_script(parametric_script)
        sys.stdout.buffer.write(pickle.dumps(parametric_objects))
        sys.stdout.buffer.flush()
        sys.exit(0)

    except Exception as exception:
        sys.stdout.buffer.write(pickle.dumps(exception))
        sys.stdout.buffer.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()