"""Optional machine-local venue extensions; no site configuration ships in Git."""
from functools import lru_cache
import importlib.util
from pathlib import Path
import sys


@lru_cache
def extensions():
    root = Path(__file__).resolve().parents[3] / '.local'
    loaded = []
    for entry in sorted(root.glob('*/__init__.py')):
        name = '_shuttleup_local_' + entry.parent.name
        spec = importlib.util.spec_from_file_location(name, entry, submodule_search_locations=[str(entry.parent)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded


def extension_for(key):
    return next((ext for ext in extensions() if key in ext.providers), None)
