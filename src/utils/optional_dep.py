from functools import wraps


def optional_dep(dep_fn):
    @wraps(dep_fn)
    def wrapper(*args, **kwargs):
        try:
            return dep_fn(*args, **kwargs)
        except:  # noqa
            return None

    return wrapper
