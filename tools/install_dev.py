r"""Development install of the 3D Mouse Navigation module into 3D Slicer. In Slicer's Python console:

    p = r"<path to>\tools\install_dev.py"
    exec(open(p).read(), {"__file__": p})

(tools/package_test_build.py prints this line with the real absolute path of the package it builds.)

Adds the MouseNav3D folder of this repository to Slicer's additional module paths (kept for future sessions), in place
of any other MouseNav3D folder, and loads the module now without a restart.
"""
import os

import qt
import slicer

MODULE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "MouseNav3D"))


def install(module_dir=MODULE_DIR, select=True):
    module_dir = os.path.normpath(module_dir)
    settings = slicer.app.revisionUserSettings() if hasattr(slicer.app, "revisionUserSettings") else qt.QSettings()
    paths = settings.value("Modules/AdditionalPaths") or []
    if isinstance(paths, str):
        paths = [paths]
    paths = [os.path.normpath(p) for p in paths]
    keep = [p for p in paths if os.path.basename(p) != "MouseNav3D"] + [module_dir]
    if keep != paths:
        settings.setValue("Modules/AdditionalPaths", keep)
    moved = [p for p in paths if os.path.basename(p) == "MouseNav3D" and p != module_dir]
    if not hasattr(slicer.modules, "mousenav3d"):
        fm = slicer.app.moduleManager().factoryManager()
        fm.registerModule(qt.QFileInfo(os.path.join(module_dir, "MouseNav3D.py")))
        fm.loadModules(["MouseNav3D"])
        moved = []
    if select:
        slicer.util.selectModule("MouseNav3D")
    print(f"3D Mouse Navigation installed from {module_dir}: Modules menu > Utilities > 3D Mouse Navigation"
          + (f". It was loaded from {moved[0]} in this session: restart Slicer to use the new place." if moved else ""))


install()
