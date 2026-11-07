"""nextcloud-tools: Hermes Agent directory plugin — thin loader.

The plugin root is THIS directory (``cp -r <repo> ~/.hermes/plugins/nextcloud-tools``);
``plugin.yaml`` and this ``__init__.py`` stay at the root because that is what Hermes
discovers. All source files live in ``src/`` and are loaded here as the
``nextcloud_tools`` package, regardless of how Hermes imports this file.
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")

_spec = importlib.util.spec_from_file_location(
    "nextcloud_tools",
    os.path.join(_SRC, "__init__.py"),
    submodule_search_locations=[_SRC],
)
_pkg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("nextcloud_tools", _pkg)
_spec.loader.exec_module(_pkg)

register = _pkg.register
TOOLSET = _pkg.TOOLSET
