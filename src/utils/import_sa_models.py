import importlib
import os
import pkgutil


def import_sa_models():
    """Import every top-level package's ``.model`` module so all SQLAlchemy
    models are registered on ``Base`` (required before ``create_all`` or the
    first mapper use in processes that don't import the full app).

    Uses iter_modules + targeted imports (rather than walk_packages) so whole
    packages — and their heavy import chains — aren't imported as a side
    effect.
    """
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for _importer, name, ispkg in pkgutil.iter_modules([src_dir]):
        if not ispkg:
            continue
        try:
            importlib.import_module(f"{name}.model")
        except ModuleNotFoundError as e:
            # Packages without a model module are fine; real import errors
            # inside an existing model module must not be swallowed.
            if e.name != f"{name}.model":
                raise
