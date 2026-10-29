"""Slicer self-test: install_dev.py registers and loads the module, its widget builds, and the module's own
MouseNav3DTest passes. "Enable 3D mouse" is kept off meanwhile (and put back), so no driver connection or device
reader is started."""
# Everything lives inside main(): Slicer's --python-script namespace does not make module-level imports visible to
# functions, and a NameError in the finally block would skip slicer.util.exit and hang the process.


def main():
    import os
    import traceback

    import qt
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_load.log")
    lines = []

    def check(name, ok):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}")
        return bool(ok)

    def run():
        settings = slicer.app.revisionUserSettings() if hasattr(slicer.app, "revisionUserSettings") else qt.QSettings()
        saved = settings.value("Modules/AdditionalPaths")
        # the panel starts a controller when "enabled" is on; keep it off so this test never connects to the driver
        # (under the real app name) or starts a device reader
        app_settings = qt.QSettings()
        had_enabled = app_settings.contains("MouseNav3D/enabled")
        saved_enabled = app_settings.value("MouseNav3D/enabled")
        app_settings.setValue("MouseNav3D/enabled", False)
        app_settings.sync()
        try:
            p = os.path.join(root, "tools", "install_dev.py")
            exec(open(p).read(), {"__file__": p})
            ok = check("slicer.modules.mousenav3d exists", hasattr(slicer.modules, "mousenav3d"))
            slicer.util.selectModule("MouseNav3D")
            slicer.app.processEvents()
            widget = slicer.modules.mousenav3d.widgetRepresentation()
            ok &= check("widget representation builds", widget is not None)
            ok &= check("module title", slicer.modules.mousenav3d.title == "3D Mouse Navigation")
            ok &= check("enabled off: the panel started no controller",
                        getattr(slicer, "_mousenav3d_controller", None) is None)
            # the module's own test (what the Extensions Index CI runs): no driver, no device, must not raise
            import sys
            before = getattr(slicer, "_mousenav3d_controller", None)
            try:
                sys.modules["MouseNav3D"].MouseNav3DTest().runTest()
                ok &= check("MouseNav3DTest.runTest passes", True)
            except Exception as exc:  # noqa: BLE001
                ok &= check(f"MouseNav3DTest.runTest passes ({exc!r})", False)
            ok &= check("runTest leaves the session's controller alone",
                        getattr(slicer, "_mousenav3d_controller", None) is before)
            return ok
        finally:
            if saved is None:
                settings.remove("Modules/AdditionalPaths")
            else:
                settings.setValue("Modules/AdditionalPaths", saved)
            settings.sync()
            if had_enabled:
                app_settings.setValue("MouseNav3D/enabled", saved_enabled)
            else:
                app_settings.remove("MouseNav3D/enabled")
            app_settings.sync()

    ok = False
    try:
        ok = run()
    except Exception:
        lines.append(traceback.format_exc())
    finally:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            lines.append("OVERALL: PASS" if ok else "OVERALL: FAIL")
            with open(log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        finally:
            slicer.util.exit(0)


main()
