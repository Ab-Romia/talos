import functools
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.routing import APIRoute


def openapi_doc(responses: dict[int | str, dict[str, Any]]):
    """ Binds OpenAPI response documentation directly to a dependency function. """

    def decorator(func: Callable[..., Any]):
        # Store metadata on a custom attribute of the function object
        setattr(func, "__openapi_responses__", responses)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_all_dependants(dependant) -> list[Any]:
    """
    Recursively unrolls nested dependencies within FastAPI's Dependant tree.
    """
    flat_dependants = []
    for sub_dep in dependant.dependencies:
        flat_dependants.append(sub_dep)
        flat_dependants.extend(get_all_dependants(sub_dep))
    return flat_dependants


def propagate_dependency_responses(app: FastAPI) -> None:
    """
    Iterates through all routes, inspects their compiled dependencies,
    and automatically merges dependency-level errors into the route schemas.
    """
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        # Traverse both top-level and sub-dependencies for this specific route
        all_sub_deps = get_all_dependants(route.dependant)
        responses_to_add = {}

        for dep in all_sub_deps:
            # Check if the callable dependency has documented error attributes
            if dep.call and hasattr(dep.call, "__openapi_responses__"):
                dep_metadata = getattr(dep.call, "__openapi_responses__")
                for status_code, schema in dep_metadata.items():
                    if route.responses is None:
                        route.responses = {}
                    # Route-level declarations take precedence to avoid collisions
                    if status_code not in route.responses:
                        responses_to_add[status_code] = schema

        if responses_to_add:
            if route.responses is None:
                route.responses = {}
            route.responses.update(responses_to_add)
