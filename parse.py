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

            seen_ids = set()
            parsed_objects = []

            for name, value in locals.items():
                if name.startswith("_"):
                    continue
                if not isinstance(value, ParametricObject):
                    continue

                instance_id = id(value)
                if instance_id in seen_ids:
                    continue

                seen_ids.add(instance_id)
                parsed_objects.append(parse_parametric_object(value, name, None))

            return parsed_objects

        def parse_parametric_object(
            obj: ParametricObject,
            name: str,
            material: Union[str, None],
        ) -> ParametricObjectNode:
            name = obj.name if (hasattr(obj, "name") and obj.name) else name
            material = (
                obj.material if (hasattr(obj, "material") and obj.material) else material
            )

            if isinstance(obj, cadquery.Assembly):
                return ParametricObjectNode(
                    name=name,
                    material=material,
                    children=[
                        parse_parametric_object(child, name, material)
                        for child in obj.shapes + obj.children
                    ],
                )

            if isinstance(obj, ParametricShape):
                shape = obj
            elif isinstance(obj, cadquery.Workplane):
                vals = obj.vals()
                if not vals:
                    raise BlendQueryBuildException("Workplane produced no solids.")
                shape = cadquery.Shape(vals[0].wrapped)
            else:
                raise BlendQueryBuildException(
                    "Failed to parse parametric object; Unsupported object type ("
                    + str(type(obj))
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