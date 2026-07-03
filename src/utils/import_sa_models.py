import importlib
import os
import pkgutil


def import_sa_models():
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for importer, modname, ispkg in pkgutil.walk_packages(
            path=[src_dir],
            onerror=lambda x: None
    ):
        if modname.endswith(".model"):
            importlib.import_module(modname)
