import importlib
import pkgutil


def import_sa_models():
    """Import every top-level package's ``.model`` module so all SQLAlchemy
    models are registered on ``Base`` (required before ``create_all`` or the
    first mapper use in processes that don't import the full app).
    """
    import src

    for _importer, name, ispkg in pkgutil.iter_modules(src.__path__):
        if not ispkg:
            continue
        try:
            importlib.import_module(f"{name}.model")
        except ModuleNotFoundError as e:
            # Packages without a model module are fine; real import errors
            # inside an existing model module must not be swallowed.
            if e.name != f"{name}.model":
                raise
