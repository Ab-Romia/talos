import importlib
import pkgutil


def import_sa_models():
    import src
    src_path = src.__path__
    for importer, modname, ispkg in pkgutil.walk_packages(
            path=[str(src_path)],
            onerror=lambda x: None
    ):
        print(f"Importing module: {modname}")
        if modname.endswith(".model"):
            importlib.import_module(modname)
