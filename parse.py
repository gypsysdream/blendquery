import sys
import pickle

from interop_types import ParametricObjectNode, BlendQueryBuildException


def main():
    try:
        from setup_venv import setup_venv

        setup_venv()

        import cadquery

        payload = pickle.loads(sys.stdin.buffer.read())
        parametric_script = payload["script"]
        tolerance = payload["tolerance"]
        angular_tolerance = payload["angular_tolerance"]
        enable_build123d = payload.get("enable_build123d", False)

        build123d = None
        if enable_build123d:
            try:
                import build123d as _build123d

                build123d = _build123d
            except Exception:
                build123d = None

        cadquery_types = (
            cadquery.Shape,
            cadquery.Workplane,
            cadquery.Assembly,
        )

        build123d_shape_types = ()
        if build123d is not None:
            build123d_shape_types = (build123d.Shape,)

        parseable_types = cadquery_types + build123d_shape_types

        def parse_parametric_script(script: str):
            locals_dict = {}
            globals_dict = {
                "cadquery": cadquery,
                "cq": cadquery,
            }

            if build123d is not None:
                globals_dict["build123d"] = build123d
                globals_dict["b3d"] = build123d

            exec(script, globals_dict, locals_dict)

            seen_ids = set()
            parsed_objects = []

            for name, value in locals_dict.items():
                if name.startswith("_"):
                    continue
                if not isinstance(value, parseable_types):
                    continue

                instance_id = id(value)
                if instance_id in seen_ids:
                    continue

                seen_ids.add(instance_id)
                parsed_objects.append(parse_parametric_object(value, name, None))

            return parsed_objects

        def parse_parametric_object(obj, name: str, material):
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

            if isinstance(obj, cadquery.Shape):
                shape = obj

            elif isinstance(obj, cadquery.Workplane):
                vals = obj.vals()
                if not vals:
                    raise BlendQueryBuildException("Workplane produced no solids.")
                shape = cadquery.Shape(vals[0].wrapped)

            elif build123d is not None and isinstance(obj, build123d.Shape):
                wrapped = getattr(obj, "wrapped", None)
                if wrapped is None:
                    raise BlendQueryBuildException(
                        "build123d shape did not expose a wrapped OCC shape."
                    )
                shape = cadquery.Shape(wrapped)

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