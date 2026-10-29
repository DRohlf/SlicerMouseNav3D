r"""Not a self-test (no OVERALL line): takes the README's screenshots into docs/images with a synthetic scene.

  panel_fallback.png  the module panel in fallback mode (a fake device stands in; the built-in reader group is shown)
  panel_driver.png    the module panel in driver mode (status text as the controller reports it; no real connection)
  layout.png          Slicer's main window: 3D view and slice views with the module panel

Run: "<Slicer 5.12.4>\Slicer.exe" --no-splash --python-script Testing\slicer\shots_panel.py
No navlib connection or device reader is started; QSettings keys it touches are restored.
"""


def main():
    import os
    import sys
    import traceback

    import numpy as np
    import qt
    import slicer
    import vtk

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    out = os.path.join(root, "docs", "images")
    os.makedirs(out, exist_ok=True)
    log = []
    KEYS = ["MouseNav3D/enabled", "MouseNav3D/limb_side"]

    class FakeReader:
        on_report = None
        devices = ["SpaceMouse Wireless"]
        battery = 86
        error = ""

        def start(self):
            pass

        def stop(self, wait=2.0):
            return True

    class DriverStub:
        mode = "driver"
        navigator = None
        limb_side = "right"

        def status(self):
            return "Connected to the 3Dconnexion driver."

        def stop(self):
            pass

    def save(widget, name, width=None):
        slicer.app.processEvents()
        pix = widget.grab()
        if width and pix.width() > width:
            pix = pix.scaledToWidth(width, qt.Qt.SmoothTransformation)
        path = os.path.join(out, name)
        log.append(f"{name}: {pix.width()}x{pix.height()} saved={pix.save(path)}")

    def run():
        settings = qt.QSettings()
        saved = {k: (settings.value(k) if settings.contains(k) else None) for k in KEYS}
        user_settings = slicer.app.revisionUserSettings() if hasattr(slicer.app, "revisionUserSettings") else settings
        saved_paths = user_settings.value("Modules/AdditionalPaths")
        real_load = None
        nl = None
        try:
            sys.path.insert(0, os.path.join(root, "MouseNav3D"))
            for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
                del sys.modules[m]
            settings.setValue("MouseNav3D/enabled", False)
            settings.setValue("MouseNav3D/limb_side", "right")
            p = os.path.join(root, "tools", "install_dev.py")
            exec(open(p).read(), {"__file__": p})
            from MouseNav3DLib import controller as ctlmod
            from MouseNav3DLib import navlib_ctypes as nl
            real_load, nl.load_library = nl.load_library, (lambda: None)

            # synthetic scene: a ball-and-shell volume and a model
            z, y, x = np.mgrid[-50:50, -50:50, -50:50].astype(float)
            r = np.sqrt(x * x + y * y + z * z)
            arr = (np.exp(-((r - 30) / 6.0) ** 2) * 900 + np.exp(-((np.sqrt((x - 15) ** 2 + y * y + (z + 10) ** 2)) / 12.0) ** 2) * 500)
            volume = slicer.util.addVolumeFromArray(arr.astype(np.int16), name="Synthetic volume")
            volume.SetSpacing(1.0, 1.0, 1.0)
            volume.SetOrigin(-50, -50, -50)
            sphere = vtk.vtkSphereSource()
            sphere.SetRadius(22)
            sphere.SetThetaResolution(48)
            sphere.SetPhiResolution(48)
            sphere.Update()
            model = slicer.modules.models.logic().AddModel(sphere.GetOutput())
            model.GetDisplayNode().SetColor(0.85, 0.35, 0.3)
            model.GetDisplayNode().SetOpacity(0.7)
            model.GetDisplayNode().SetVisibility2D(True)
            slicer.util.setSliceViewerLayers(background=volume, fit=True)
            manager = slicer.app.layoutManager()
            manager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
            slicer.app.processEvents()
            manager.threeDWidget(0).threeDView().resetFocalPoint()
            manager.threeDWidget(0).threeDView().resetCamera()

            slicer.util.selectModule("MouseNav3D")
            slicer.app.processEvents()
            rep = slicer.modules.mousenav3d.widgetRepresentation()
            w = rep.self()
            w.reloadCollapsibleButton.visible = False  # developer buttons are not part of the module
            dock = slicer.util.mainWindow().findChild("QDockWidget", "PythonConsoleDockWidget")
            if dock is not None:
                dock.hide()

            def factory():
                c = ctlmod.Controller(app_name="3D Mouse Navigation (self-test)")
                c._reader_factory = lambda: FakeReader()
                return c

            w.controllerFactory = factory
            w.enableCheckBox.checked = True
            slicer.app.processEvents()
            w.refresh()
            w.fallbackGroup.collapsed = False
            slicer.app.processEvents()
            save(rep, "panel_fallback.png")
            save(slicer.util.mainWindow(), "layout.png", width=1800)

            w.enableCheckBox.checked = False
            slicer._mousenav3d_controller = DriverStub()
            w.enableCheckBox.blockSignals(True)
            w.enableCheckBox.checked = True
            w.enableCheckBox.blockSignals(False)
            w.refresh()
            slicer.app.processEvents()
            save(rep, "panel_driver.png")
            slicer._mousenav3d_controller = None
        finally:
            if nl is not None and real_load is not None:
                nl.load_library = real_load
            c = getattr(slicer, "_mousenav3d_controller", None)
            slicer._mousenav3d_controller = None
            if c is not None:
                try:
                    c.stop()
                except Exception:
                    pass
            for k, v in saved.items():
                settings.remove(k) if v is None else settings.setValue(k, v)
            settings.sync()
            if saved_paths is None:
                user_settings.remove("Modules/AdditionalPaths")
            else:
                user_settings.setValue("Modules/AdditionalPaths", saved_paths)
            user_settings.sync()

    try:
        run()
    except Exception:
        log.append(traceback.format_exc())
    finally:
        try:
            with open(os.path.join(here, "out", "shots_panel.log"), "w") as f:
                f.write("\n".join(log) + "\n")
        finally:
            slicer.util.exit(0)


main()
