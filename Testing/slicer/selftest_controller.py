"""Slicer self-test: controller lifecycle, retarget, focus, reload during motion, no driver.

No real navlib connection is opened: the connection is replaced by a recording fake (Connection API: write/close).
"""


def main():
    import importlib
    import os
    import sys
    import traceback

    import qt
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_controller.log")
    lines = []

    def check(name, ok, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
        return bool(ok)

    class FakeConnection:
        handle = 1

        def __init__(self):
            self.writes = []
            self.closed = False

        def write(self, name, type_id, value):
            self.writes.append((name, value))
            return 0

        def close(self):
            self.closed = True
            self.handle = 0

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
            del sys.modules[m]
        from MouseNav3DLib import controller as ctlmod
        from MouseNav3DLib import navlib_ctypes as nl
        from MouseNav3DLib.slice_bridge import SliceBridge
        from MouseNav3DLib.view3d_bridge import View3DBridge

        ok = True
        manager = slicer.app.layoutManager()
        L = slicer.vtkMRMLLayoutNode
        slicer.mrmlScene.Clear(0)
        manager.setLayout(L.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        slicer._mousenav3d_controller = None

        def fresh(**kw):
            c = ctlmod.Controller(**kw)
            c.connection = FakeConnection()
            c._init_target()
            return c

        # --- no driver ------------------------------------------------------------------------------------
        class IdleReader:
            """A reader that never touches a device: only the lifecycle is under test."""
            running = False
            devices = []
            battery = None
            error = ""
            on_report = None

            def start(self):
                self.running = True

            def stop(self):
                self.running = False
                return True

        real_load = nl.load_library
        nl.load_library = lambda: None
        try:
            c = ctlmod.Controller()
            c._reader_factory = lambda: None
            mode0 = c.start()
            ok &= check("no driver, no reader on this platform: mode no device", mode0 == "no device"
                        and c.navigator is None and "not found" in c.status(), f"{mode0}: {c.status()}")
            c.stop()
            c = ctlmod.Controller()
            reader = IdleReader()
            c._reader_factory = lambda: reader
            mode = c.start()
        finally:
            nl.load_library = real_load
        ok &= check("no driver: mode fallback", mode == "fallback", mode)
        ok &= check("no driver: status text set", isinstance(c.status(), str) and "looking for" in c.status(), c.status())
        ok &= check("no driver: no connection; reader, navigator and retarget timer running",
                    c.connection is None and c._timer is not None and reader.running and c.navigator is not None
                    and c.target is not None)
        reader.devices, reader.battery = ["Test mouse"], 77
        ok &= check("fallback status shows device and battery", "Test mouse" in c.status() and "77 %" in c.status(),
                    c.status())
        c.stop()
        c.stop()
        ok &= check("stop idempotent", c.mode is None and not reader.running and c.navigator is None
                    and c._timer is None)

        # --- MOUSENAV3D_FORCE_FALLBACK=1: the driver is never tried ------------------------------------------------
        loads = []
        old_env = os.environ.get("MOUSENAV3D_FORCE_FALLBACK")
        nl.load_library = lambda: loads.append(1)
        os.environ["MOUSENAV3D_FORCE_FALLBACK"] = "1"
        try:
            c = ctlmod.Controller()
            reader = IdleReader()
            c._reader_factory = lambda: reader
            mode = c.start()
            ok &= check("FORCE_FALLBACK=1: fallback mode without loading the driver",
                        mode == "fallback" and not loads and c.connection is None and reader.running
                        and "MOUSENAV3D_FORCE_FALLBACK" in c.status(), f"{mode}: {c.status()}")
            c.stop()
        finally:
            nl.load_library = real_load
            if old_env is None:
                os.environ.pop("MOUSENAV3D_FORCE_FALLBACK", None)
            else:
                os.environ["MOUSENAV3D_FORCE_FALLBACK"] = old_env

        # --- driver status without device.present (a connection that cannot read it): the plain text ----------------
        c = fresh()
        c.mode = ctlmod.MODE_DRIVER
        c._status = "Connected to the 3Dconnexion driver."
        ok &= check("driver status falls back to the plain text when device.present cannot be read",
                    c.status() == "Connected to the 3Dconnexion driver.", c.status())
        c.stop()

        # --- retarget ---------------------------------------------------------------------------------------
        c = fresh()
        ok &= check("initial target is 3D view 0", c.target is not None and c.target.view_index == 0)
        getters, setters = c.build_accessors()
        over = {"w": None}
        c._pointer_over = lambda w: over["w"] is not None and w is over["w"]

        def all_getters_bad():
            bad = []
            for name, (_t, fn) in getters.items():
                try:
                    fn()
                except nl.NoData:
                    pass
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{name}: {exc!r}")
            return bad

        bad = all_getters_bad()
        ok &= check("getters ok, conventional", not bad, str(bad))
        manager.setLayout(L.SlicerLayoutOneUpRedSliceView)
        slicer.app.processEvents()
        over["w"] = manager.sliceWidget("Red")
        c.connection.writes.clear()
        c._retarget()
        ok &= check("one-up red slice: target is a SliceBridge for Red",
                    isinstance(c.target, SliceBridge) and c.target.name == "Red")
        bad = all_getters_bad()
        ok &= check("one-up red slice: getters raise nothing but NoData", not bad, str(bad))
        written = [n for n, _v in c.connection.writes]
        ok &= check("slice retarget writes model.extents and view.affine",
                    nl.MODEL_EXTENTS in written and nl.VIEW_AFFINE in written, str(written))
        red = c.target
        ok &= check("slice view reports a perspective, non-rotatable view",
                    getters[nl.VIEW_PERSPECTIVE][1]() is True and getters[nl.VIEW_ROTATABLE][1]() is False)
        setters[nl.VIEW_AFFINE](getters[nl.VIEW_AFFINE][1]())  # the accessors reach the slice bridge
        manager.setLayout(L.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        over["w"] = manager.sliceWidget("Yellow")
        c._retarget()
        ok &= check("over Yellow: a different SliceBridge", isinstance(c.target, SliceBridge) and c.target.name == "Yellow")
        over["w"] = manager.sliceWidget("Red")
        c._retarget()
        ok &= check("slice bridges are cached per view", c.target is red and sorted(c._slice_bridges) == ["Red", "Yellow"],
                    str(sorted(c._slice_bridges)))
        over["w"] = manager.threeDWidget(0)
        c._retarget()
        ok &= check("back over 3D: the 3D bridge", isinstance(c.target, View3DBridge) and c.target.view_index == 0)
        ghost = c._bridge_for_slice("NoSuchSlice")
        c._retarget()
        ok &= check("a slice bridge whose view is gone is pruned", "NoSuchSlice" not in c._slice_bridges and ghost is not None)
        manager.setLayout(L.SlicerLayoutOneUpRedSliceView)
        slicer.app.processEvents()
        over["w"] = manager.sliceWidget("Red")
        c._retarget()
        manager.setLayout(L.SlicerLayoutDual3DView)
        slicer.app.processEvents()
        over["w"] = manager.threeDWidget(1)
        c._retarget()
        ok &= check("dual 3D: target follows view 1", c.target is not None and c.target.view_index == 1)
        written = [n for n, _v in c.connection.writes]
        ok &= check("retarget tells the driver the view changed",
                    nl.MODEL_EXTENTS in written and nl.VIEW_AFFINE in written, str(written))
        bad = all_getters_bad()
        ok &= check("dual 3D, view 1: getters ok", not bad, str(bad))
        over["w"] = manager.threeDWidget(0)
        c._retarget()
        ok &= check("dual 3D: target follows view 0", c.target.view_index == 0)
        over["w"] = manager.threeDWidget(1)
        c._retarget()
        ok &= check("bridges kept per view", len(c._bridges) == 2, str(sorted(c._bridges)))
        over["w"] = None
        c._retarget()
        ok &= check("pointer over nothing keeps target", c.target.view_index == 1)
        manager.setLayout(L.SlicerLayoutOneUpRedSliceView)
        slicer.app.processEvents()
        manager.setLayout(L.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        c._retarget()
        ok &= check("layout back to conventional: target alive or None",
                    c.target is None or c.target.widget() is not None)
        bad = all_getters_bad()
        ok &= check("after layout change getters ok", not bad, str(bad))
        # dead target widget: fall back to view 0
        c._set_target(c._bridge3d(5))
        c._retarget()
        ok &= check("dead target falls back to 3D view 0", c.target is not None and c.target.view_index == 0)
        c._bridges.clear()
        c._set_target(None)
        try:
            getters[nl.VIEW_AFFINE][1]()
            ok &= check("no target: getter raises NoData", False)
        except nl.NoData:
            ok &= check("no target: getter raises NoData", True)
        setters[nl.VIEW_AFFINE]((1.0,) * 16)  # no target: silently ignored
        ok &= check("no target: setter ignored", True)
        c.stop()

        # --- focus --------------------------------------------------------------------------------------------
        c = fresh()
        c._on_app_state(qt.Qt.ApplicationInactive)
        ok &= check("focus False written on deactivate", (nl.FOCUS, False) in c.connection.writes,
                    str(c.connection.writes))
        c._on_app_state(qt.Qt.ApplicationActive)
        ok &= check("focus True written on activate", c.connection.writes[-1] == (nl.FOCUS, True))
        c.stop()

        # --- focus: robust state argument, failures contained ----------------------------------------------------
        c = fresh()
        c._on_app_state(int(qt.Qt.ApplicationInactive))
        ok &= check("focus False from an int state", c.connection.writes[-1] == (nl.FOCUS, False))
        c._on_app_state(int(qt.Qt.ApplicationActive))
        ok &= check("focus True from an int state", c.connection.writes[-1] == (nl.FOCUS, True))
        c._on_app_state(qt.Qt.ApplicationSuspended)
        ok &= check("focus False from a suspended state", c.connection.writes[-1] == (nl.FOCUS, False))

        class Exploding(FakeConnection):
            def write(self, name, type_id, value):
                raise OSError("driver gone")

        c.connection = Exploding()
        try:
            c._on_app_state(int(qt.Qt.ApplicationActive))
            c._on_app_state(int(qt.Qt.ApplicationInactive))
            c._on_app_state("not a state")
            ok &= check("focus write failure and bad state never raise", True)
        except Exception as exc:  # noqa: BLE001
            ok &= check("focus write failure and bad state never raise", False, repr(exc))
        ok &= check("first focus failure logged once", c._focus_error_logged)
        c.connection = FakeConnection()
        c.stop()

        # --- stop: a failing bridge never keeps the connection open ----------------------------------------------
        class BadBridge:
            def release_motion(self):
                raise RuntimeError("old bridge")

            def widget(self):
                return object()

        c = fresh()
        conn = c.connection
        c._bridges[7] = BadBridge()
        c._slice_bridges["Bad"] = BadBridge()
        try:
            c.stop()
            ok &= check("stop with failing bridges does not raise", True)
        except Exception as exc:  # noqa: BLE001
            ok &= check("stop with failing bridges does not raise", False, repr(exc))
        ok &= check("stop still deactivates and closes the connection", (nl.ACTIVE, False) in conn.writes and conn.closed,
                    str(conn.writes))

        # --- limb side from settings is validated -------------------------------------------------------------
        from MouseNav3DLib import settings as mnsettings
        key = mnsettings.PREFIX + "limb_side"
        store = qt.QSettings()
        had = store.contains(key)
        old_side = store.value(key) if had else None
        nl.load_library = lambda: None
        try:
            for stored, expected in (("banana", "right"), ("left", "left"), ("LEFT", "left"), ("", "right")):
                mnsettings.set("limb_side", stored)
                c = ctlmod.Controller()
                c._reader_factory = lambda: None  # never start the real device reader
                c.start()
                ok &= check(f"limb_side {stored!r} -> {expected!r}", c.limb_side == expected, c.limb_side)
                c.stop()
        finally:
            nl.load_library = real_load
            if had:
                store.setValue(key, old_side)
            else:
                store.remove(key)

        # --- hooks leave nothing behind ------------------------------------------------------------------------
        c = fresh()
        c._install_hooks()
        ok &= check("timer running, interval 50",
                    c._timer is not None and c._timer.isActive() and c._timer.interval == 50)
        c.stop()
        ok &= check("stop clears the timer and hooks", c._timer is None and not c._hooks_installed)

        # --- reload during motion -----------------------------------------------------------------------------
        manager.setLayout(L.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        window = manager.threeDWidget(0).threeDView().renderWindow()
        still = window.GetDesiredUpdateRate()
        old = fresh()
        ctlmod.install(old)
        old.build_accessors()[1][nl.MOTION](True)
        ok &= check("motion raises update rate", window.GetDesiredUpdateRate() > still + 1e-9,
                    f"{window.GetDesiredUpdateRate()} vs {still}")
        old_conn = old.connection
        importlib.reload(ctlmod)
        new = ctlmod.Controller()
        new.connection = FakeConnection()
        ctlmod.install(new)
        ok &= check("reload: old connection closed", old_conn.closed and old.connection is None)
        ok &= check("reload: still update rate restored", abs(window.GetDesiredUpdateRate() - still) < 1e-9,
                    f"{window.GetDesiredUpdateRate()} vs {still}")
        ok &= check("reload: exactly one controller", slicer._mousenav3d_controller is new)
        new.stop()
        slicer._mousenav3d_controller = None
        return ok

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
            slicer.util.exit(0 if ok else 1)


main()
