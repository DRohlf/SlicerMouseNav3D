"""Slicer self-test: the module panel.

Checks: enabling starts the controller and disabling stops it (setting `enabled` follows); the limb side persists and
reaches the running controller; the built-in reader group is hidden in driver mode and shown in fallback mode, and its
controls reach the running reader and the settings; the panel's status equals Controller.status(); the settings button
shows the note in driver mode; the refresh timer runs only while the panel is shown; cleanup (module Reload / exit)
stops the controller; the startup hook stays off in scripted runs.

No real navlib connection or device reader is started: navlib's loader is replaced by one that finds no driver, the
fallback reader is a fake, and the controller's name is "3D Mouse Navigation (self-test)", so a driver's real profile is never touched. Every QSettings
key touched is put back.
"""


def main():
    import os
    import sys
    import time
    import traceback

    import qt
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_panel.log")
    lines = []
    AXES = ("tx", "ty", "tz", "rx", "ry", "rz")
    KEYS = (["MouseNav3D/enabled", "MouseNav3D/limb_side", "MouseNav3D/fallback/speed", "MouseNav3D/fallback/dead_zone",
             "MouseNav3D/fallback/rotation_lock"]
            + [f"MouseNav3D/fallback/{p}_{a}" for p in ("reverse", "sensitivity") for a in AXES])

    def check(name, ok, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
        return bool(ok)

    class FakeReader:
        def __init__(self):
            self.on_report = None
            self.devices = ["Test mouse"]
            self.battery = 77
            self.error = ""
            self.started = self.stopped = 0

        def start(self):
            self.started += 1

        def stop(self, wait=2.0):
            self.stopped += 1
            return True

        @property
        def running(self):
            return self.started > self.stopped

    class StubDriverController:
        mode = "driver"
        navigator = None
        limb_side = "right"

        def status(self):
            return "Connected to the 3Dconnexion driver."

        def stop(self):
            self.mode = None

    def run():
        settings = qt.QSettings()
        saved = {k: (settings.value(k) if settings.contains(k) else None) for k in KEYS}
        saved_paths = None
        user_settings = slicer.app.revisionUserSettings() if hasattr(slicer.app, "revisionUserSettings") else settings
        saved_paths = user_settings.value("Modules/AdditionalPaths")
        nl = None
        real_load = None
        try:
            sys.path.insert(0, os.path.join(root, "MouseNav3D"))
            for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
                del sys.modules[m]
            p = os.path.join(root, "tools", "install_dev.py")
            ok = True
            if getattr(slicer, "_mousenav3d_controller", None) is not None:
                ok &= check("no controller before the test", False, "another controller is installed")
                return ok
            settings.setValue("MouseNav3D/enabled", False)  # the widget must not start anything while it is built
            settings.sync()
            exec(open(p).read(), {"__file__": p})
            slicer.app.processEvents()
            from MouseNav3DLib import controller as ctlmod
            from MouseNav3DLib import navlib_ctypes as nl
            real_load = nl.load_library
            nl.load_library = lambda: None  # no driver: no real navlib connection under the user's profile

            widget_rep = slicer.modules.mousenav3d.widgetRepresentation()
            w = widget_rep.self() if hasattr(widget_rep, "self") else slicer.modules.MouseNav3DWidget
            mod = sys.modules[type(w).__module__]
            ok &= check("widget builds; enabled off builds without a controller",
                        getattr(slicer, "_mousenav3d_controller", None) is None and not w.enableCheckBox.checked,
                        f"status '{w.statusLabel.text}'")
            ok &= check("status reads Off when disabled", w.statusLabel.text == "Off.")
            ok &= check("fallback group hidden when nothing runs", w.fallbackGroup.isHidden())

            readers = []

            def factory():
                c = ctlmod.Controller(app_name="3D Mouse Navigation (self-test)")
                r = FakeReader()
                readers.append(r)
                c._reader_factory = lambda: r
                return c

            w.controllerFactory = factory

            # --- enabling starts the controller ---------------------------------------------------------------------
            w.enableCheckBox.checked = True
            slicer.app.processEvents()
            ctl = getattr(slicer, "_mousenav3d_controller", None)
            ok &= check("enabling starts the controller (fallback mode, fake reader)",
                        ctl is not None and ctl.mode == "fallback" and readers and readers[0].started == 1,
                        f"mode {getattr(ctl, 'mode', None)}")
            ok &= check("the enabled setting follows", settings.value("MouseNav3D/enabled") in (True, "true"),
                        str(settings.value("MouseNav3D/enabled")))
            ok &= check("panel status equals Controller.status()", ctl is not None and w.statusLabel.text == ctl.status(),
                        w.statusLabel.text)
            ok &= check("status names the device and battery", "Test mouse" in w.statusLabel.text and "77" in w.statusLabel.text)
            first = ctl
            w.onEnableToggled(True)
            ok &= check("enabling again keeps the one controller", slicer._mousenav3d_controller is first and len(readers) == 1)

            # --- fallback group ---------------------------------------------------------------------------------------
            ok &= check("fallback group shown in fallback mode", not w.fallbackGroup.isHidden())
            ok &= check("the driver settings button is replaced by the group in fallback mode", w.settingsButton.isHidden())
            nav = ctl.navigator
            w.reverseBoxes["tx"].checked = True
            w.sensitivitySliders["ry"].value = 2.0
            w.speedSlider.value = 1.5
            w.deadZoneSlider.value = 0.1
            slicer.app.processEvents()
            s = nav.settings
            ok &= check("reverse, sensitivity, speed and dead zone reach the running reader",
                        s.reverse.get("tx") is True and abs(s.sensitivity.get("ry") - 2.0) < 1e-9
                        and abs(s.speed - 1.5) < 1e-9 and abs(s.dead_zone - 0.1) < 1e-9,
                        f"{s.reverse.get('tx')} {s.sensitivity.get('ry')} {s.speed} {s.dead_zone}")
            from MouseNav3DLib import settings as mn_settings
            persisted = mn_settings.fallback_axis_settings()
            ok &= check("and persist", persisted.reverse["tx"] is True and abs(persisted.sensitivity["ry"] - 2.0) < 1e-9
                        and abs(persisted.speed - 1.5) < 1e-9 and abs(persisted.dead_zone - 0.1) < 1e-9)
            w.rotationLockBox.checked = True
            ok &= check("rotation lock reaches the navigator and persists",
                        nav.rotation_lock is True and mn_settings.fallback_rotation_lock() is True)
            nav.handle_report(time.monotonic(), {"tx": 0.5, "rz": -0.25}, None)
            w.refresh()
            ok &= check("live axes line shows the newest deflections",
                        "tx +0.50" in w.axesLabel.text and "rz -0.25" in w.axesLabel.text, w.axesLabel.text)
            ok &= check("slider ranges: sensitivity and speed 0.1-3",
                        abs(w.sensitivitySliders["tx"].minimum - 0.1) < 1e-9 and abs(w.sensitivitySliders["tx"].maximum - 3.0) < 1e-9
                        and abs(w.speedSlider.minimum - 0.1) < 1e-9 and abs(w.speedSlider.maximum - 3.0) < 1e-9)

            # --- limb side --------------------------------------------------------------------------------------------
            w.limbComboBox.currentText = "Left"
            slicer.app.processEvents()
            ok &= check("limb side persists and reaches the controller",
                        str(settings.value("MouseNav3D/limb_side")) == "left" and ctl.limb_side == "left",
                        f"{settings.value('MouseNav3D/limb_side')} / {ctl.limb_side}")
            w.limbComboBox.currentText = "Right"

            # --- timer only while shown ---------------------------------------------------------------------------------
            w.enter()
            ok &= check("refresh timer runs while the panel is shown", w._timer.isActive())
            w.exit()
            ok &= check("refresh timer stops when the panel is hidden", not w._timer.isActive())

            # --- disabling stops it -------------------------------------------------------------------------------------
            w.enableCheckBox.checked = False
            slicer.app.processEvents()
            ok &= check("disabling stops the controller",
                        getattr(slicer, "_mousenav3d_controller", None) is None and ctl.mode is None and readers[0].stopped == 1
                        and ctl.connection is None and ctl.navigator is None)
            ok &= check("the enabled setting follows (off)", settings.value("MouseNav3D/enabled") in (False, "false"))
            ok &= check("panel reads Off and hides the group", w.statusLabel.text == "Off." and w.fallbackGroup.isHidden())
            w.enableCheckBox.checked = True
            slicer.app.processEvents()
            ok &= check("enabling again starts a new controller",
                        slicer._mousenav3d_controller is not first and slicer._mousenav3d_controller.mode == "fallback"
                        and len(readers) == 2)
            w.enableCheckBox.checked = False

            # --- driver mode ----------------------------------------------------------------------------------------------
            stub = StubDriverController()
            slicer._mousenav3d_controller = stub
            w.refresh()
            ok &= check("fallback group hidden in driver mode", w.fallbackGroup.isHidden())
            ok &= check("driver status shown as the controller reports it", w.statusLabel.text == stub.status(), w.statusLabel.text)
            ok &= check("settings button visible in driver mode", not w.settingsButton.isHidden())
            w.settingsButton.click()
            ok &= check("settings button shows the note (no navlib call opens the driver's settings)",
                        w.settingsNote.text == mod.SETTINGS_NOTE and not w.settingsNote.isHidden(), w.settingsNote.text)
            w.limbComboBox.currentText = "Left"
            ok &= check("limb side reaches a driver-mode controller", stub.limb_side == "left")
            w.limbComboBox.currentText = "Right"
            mod.stop_controller()
            ok &= check("stop_controller clears the installed controller and stops it",
                        getattr(slicer, "_mousenav3d_controller", None) is None and stub.mode is None)

            # --- "no device": retried from the refresh, at most every RETRY_S, only while the panel is shown ----------
            made = []

            def no_device_factory():
                c = ctlmod.Controller(app_name="3D Mouse Navigation (self-test)")
                c._reader_factory = lambda: None
                made.append(c)
                return c

            w.controllerFactory = no_device_factory
            w.enableCheckBox.checked = True
            slicer.app.processEvents()
            first_nd = slicer._mousenav3d_controller
            ok &= check("no driver and no reader: mode no device", first_nd is not None and first_nd.mode == "no device"
                        and len(made) == 1, f"{getattr(first_nd, 'mode', None)}, {len(made)} made")
            w._last_start -= w.RETRY_S + 1.0
            w.refresh()
            ok &= check("no retry while the panel is hidden", len(made) == 1, f"{len(made)} made")
            w.enter()
            w.refresh()
            ok &= check("panel shown and RETRY_S passed: one retry", len(made) == 2
                        and slicer._mousenav3d_controller is made[1] and first_nd.mode is None, f"{len(made)} made")
            w.refresh()
            ok &= check("no second retry within RETRY_S", len(made) == 2, f"{len(made)} made")
            w.exit()
            w.enableCheckBox.checked = False
            slicer.app.processEvents()
            w.controllerFactory = factory

            # --- startup hook / cleanup -----------------------------------------------------------------------------------
            os.environ.pop("MOUSENAV3D_NO_AUTOSTART", None)
            ok &= check("no autostart hook in a scripted run", mod._autostart_allowed() is False)
            mod._on_startup_completed()  # enabled is off: nothing starts
            ok &= check("startup hook starts nothing while disabled", getattr(slicer, "_mousenav3d_controller", None) is None)
            w.enableCheckBox.checked = True
            slicer.app.processEvents()
            running = slicer._mousenav3d_controller
            w.cleanup()
            ok &= check("cleanup (Reload / exit) stops the controller and the timer",
                        getattr(slicer, "_mousenav3d_controller", None) is None and running.mode is None and w._timer is None)
            w.cleanup()
            ok &= check("cleanup twice is harmless", True)
            return ok
        finally:
            if nl is not None and real_load is not None:
                nl.load_library = real_load
            try:
                ctl_left = getattr(slicer, "_mousenav3d_controller", None)
                slicer._mousenav3d_controller = None
                if ctl_left is not None:
                    ctl_left.stop()
            except Exception:
                pass
            for k, v in saved.items():
                if v is None:
                    settings.remove(k)
                else:
                    settings.setValue(k, v)
            settings.sync()
            if saved_paths is None:
                user_settings.remove("Modules/AdditionalPaths")
            else:
                user_settings.setValue("Modules/AdditionalPaths", saved_paths)
            user_settings.sync()

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
