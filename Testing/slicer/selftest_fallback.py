"""Slicer self-test: fallback mode. Synthetic reports only; the real device is never read.

Checks: a synthetic HID report decodes through the real device descriptor (if a device is attached; its handle is
closed again), reports fed to the Navigator move the 3D camera and step the slice planes as stated, motion is
proportional to elapsed report time (evenly spaced steps at uneven ticks), nothing moves after a release or while the
application is inactive (and nothing is saved up for later), the buttons, the interactive update rate while moving,
the real 8 ms timer, the controller wiring, and that reader start/stop leaves no thread. QSettings keys it could touch
are put back.
"""


def main():
    import math
    import os
    import random
    import struct
    import sys
    import threading
    import time
    import traceback

    import numpy as np
    import qt
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_fallback.log")
    lines = []
    SETTING_KEYS = ["MouseNav3D/fallback/rotation_lock"]

    def check(name, ok, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
        return bool(ok)

    def cam3d():
        v = slicer.app.layoutManager().threeDWidget(0).threeDView()
        c = v.renderWindow().GetRenderers().GetFirstRenderer().GetActiveCamera()
        return np.array(c.GetPosition()), np.array(c.GetFocalPoint()), np.array(c.GetViewUp())

    def threads(name):
        return sum(t.name == name and t.is_alive() for t in threading.enumerate())

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
            del sys.modules[m]
        from MouseNav3DLib import controller as ctlmod
        from MouseNav3DLib import navlib_ctypes as nl
        from MouseNav3DLib.fallback import hid_windows as hid
        from MouseNav3DLib.fallback import motion
        from MouseNav3DLib.fallback import navigator as navmod
        from MouseNav3DLib.slice_bridge import SliceBridge
        from MouseNav3DLib.view3d_bridge import View3DBridge

        ok = True
        manager = slicer.app.layoutManager()
        L = slicer.vtkMRMLLayoutNode
        slicer.mrmlScene.Clear(0)
        manager.setLayout(L.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        slicer._mousenav3d_controller = None

        # --- the device's own descriptor decodes a synthetic report ----------------------------------------------
        devs = []
        try:
            devs = hid.find_devices() if sys.platform == "win32" else []
            if devs:
                d = devs[0]
                axes, btn, _bat = d.decode(bytes([1]) + struct.pack("<6h", 350, -175, 70, -350, 35, -105))
                _, btn2, _ = d.decode(bytes([3, 0b11]) + bytes(max(d.in_len - 2, 0)))
                want = {"tx": 1.0, "tz": -0.5, "ty": -0.2, "rx": -1.0, "rz": 0.1, "ry": 0.3}
                good = all(abs(axes[k] - v) < 1e-9 for k, v in want.items()) and btn is None and btn2 == [1, 2]
                ok &= check("decodes a synthetic report through the device descriptor", good,
                            f"{d.name} {d.vid:04X}:{d.pid:04X}: HID X 350, Y -175, Z 70, Rx -350, Ry 35, Rz -105 -> "
                            f"{axes} (ty = -Z, tz = Y, ry = -Rz, rz = Ry); buttons report -> {btn2}")
            else:
                ok &= check("decodes a synthetic report through the device descriptor", True,
                            "SKIPPED: no 3D mouse HID device found on this machine")
        finally:
            for d in devs:
                d.close()

        # --- a reader's report callback: merge, buttons, no axes ---------------------------------------------------
        got = []
        rd = hid.Reader()
        rd.on_report = lambda t, a, b: got.append((a, b))
        rd.feed({"tx": 0.5})
        rd.feed({"rx": -0.25})
        rd.feed(None, [1])
        ok &= check("reader merges split reports; a buttons-only report carries no axes",
                    got[0] == ({**dict.fromkeys(motion.AXES, 0.0), "tx": 0.5}, None)
                    and got[1][0]["tx"] == 0.5 and got[1][0]["rx"] == -0.25 and got[2] == ({}, [1]), str(got))

        # --- the Navigator on the real views -----------------------------------------------------------------------
        def new_nav(**kw):
            s = motion.AxisSettings()
            nav = navmod.Navigator(motion.Integrator(s), s, **kw)
            nav.is_active = lambda: True
            return nav

        bridge3d = View3DBridge(0)
        nav = new_nav(target=lambda: bridge3d)
        tdv = manager.threeDWidget(0).threeDView()
        tdv.resetFocalPoint()
        tdv.resetCamera()
        slicer.app.processEvents()
        T = 100.0

        def drive(nav, t0, t1, axes):
            """Hold `axes` from t0 to t1 (take at both ends), then release at t1."""
            nav.handle_report(t0, axes, None)
            nav.tick(t0)
            nav.tick(t1)
            nav.handle_report(t1, dict.fromkeys(motion.AXES, 0.0), None)
            nav.tick(t1)

        p0, f0, u0 = cam3d()
        dist = np.linalg.norm(p0 - f0)
        dop = (f0 - p0) / dist
        right = np.cross(dop, u0)
        right /= np.linalg.norm(right)
        drive(nav, T, T + 0.1, {"tx": 1.0})
        p1, f1, _ = cam3d()
        exp = -navmod.PAN_FRAC_S * dist * 0.1 * right
        ok &= check("3D pan: slide right 0.1 s", np.allclose(f1 - f0, exp, atol=1e-6) and np.allclose(p1 - p0, exp, atol=1e-6),
                    f"focal point moved {np.linalg.norm(f1 - f0):.3f} mm to the left (stated {np.linalg.norm(exp):.3f})")
        drive(nav, T + 1, T + 1.1, {"tz": 1.0})
        p2, f2, _ = cam3d()
        d2 = np.linalg.norm(p2 - f2)
        ok &= check("3D dolly: pull 0.1 s", abs(d2 - dist / math.exp(navmod.DOLLY_E_S * 0.1)) < 1e-6 and np.allclose(f2, f1),
                    f"distance {dist:.2f} -> {d2:.2f} mm, focal point fixed")
        drive(nav, T + 2, T + 2.1, {"ry": 0.5})
        p3, f3, u3 = cam3d()
        ang = math.degrees(math.acos(np.clip(np.dot(p2 - f2, p3 - f3) / d2 ** 2, -1, 1)))
        want = navmod.ROT_DEG_S * 0.1 * 0.5
        ok &= check("3D turn: half twist 0.1 s", abs(ang - want) < 1e-3 and abs(np.linalg.norm(p3 - f3) - d2) < 1e-6
                    and np.allclose(f3, f2) and abs(np.dot(u3, p3 - f3) / d2) < 1e-6,
                    f"turned {ang:.4f} deg about the focal point (stated {want:.4f}); distance kept; view-up square")
        nav.rotation_lock = True
        drive(nav, T + 3, T + 3.1, {"rx": 1.0, "ry": 1.0})
        p4, f4, _ = cam3d()
        nav.rotation_lock = False
        ok &= check("rotation lock: tilt and twist leave the 3D view still", np.allclose(p4, p3) and np.allclose(f4, f3))

        # even steps at uneven ticks, jittered reports
        rnd = random.Random(5)
        nav = new_nav(target=lambda: bridge3d)
        tdv.resetFocalPoint()
        tdv.resetCamera()
        slicer.app.processEvents()
        pa, fa, _ = cam3d()
        t = 300.0
        report_t, tick_t = [], [300.0]
        while t < 300.6:
            report_t.append(t)
            t += 1 / 60 + rnd.uniform(-0.004, 0.004)
        while tick_t[-1] < 300.5:
            tick_t.append(tick_t[-1] + rnd.uniform(0.005, 0.040))
        events = sorted([(x, 0) for x in report_t] + [(x, 1) for x in tick_t])
        steps, last, prev_f = [], tick_t[0], fa
        for x, kind in events:
            if kind == 0:
                nav.handle_report(x, {"tx": 0.5}, None)
            else:
                nav.tick(x)
                _, fn, _ = cam3d()
                steps.append((x - last, float(np.linalg.norm(fn - prev_f))))
                last, prev_f = x, fn
        per_s = navmod.PAN_FRAC_S * np.linalg.norm(fa - pa) * 0.5
        worst = max(abs(s / (dt * per_s) - 1.0) for dt, s in steps[1:] if dt > 0)
        total = np.linalg.norm(prev_f - fa)
        ok &= check("steady push: every step is speed x elapsed time", worst < 1e-6 and
                    abs(total - per_s * (tick_t[-1] - tick_t[0])) < 1e-6 * max(1.0, total),
                    f"{len(steps)} ticks of 5-40 ms, worst step {worst:.2e} off; total {total:.3f} mm")

        # release: no further motion
        nav = new_nav(target=lambda: bridge3d)
        nav.handle_report(400.0, {"tx": 1.0}, None)
        nav.tick(400.0)
        nav.tick(400.05)
        nav.handle_report(400.06, dict.fromkeys(motion.AXES, 0.0), None)
        nav.tick(400.08)
        _, fr, _ = cam3d()
        for k in range(1, 30):
            nav.tick(400.08 + 0.008 * k)
        _, fr2, _ = cam3d()
        ok &= check("after the release report the view does not move again", np.allclose(fr, fr2, atol=1e-9),
                    f"{np.linalg.norm(fr2 - fr):.2e} mm")

        # inactive application: nothing moves, nothing is saved up, presses dropped
        nav = new_nav(target=lambda: bridge3d)
        nav.handle_report(500.0, {"tx": 1.0}, None)
        nav.tick(500.0)
        _, fi0, _ = cam3d()
        nav.is_active = lambda: False
        nav.handle_report(500.05, {"tx": 1.0}, [2])
        nav.tick(500.1)
        _, fi1, _ = cam3d()
        lock_during = nav.rotation_lock
        nav.is_active = lambda: True
        nav.tick(500.2)
        _, fi2, _ = cam3d()
        per_s = navmod.PAN_FRAC_S * np.linalg.norm(fa - pa) * 1.0
        ok &= check("another program active: nothing moves, nothing is saved up, presses ignored",
                    np.allclose(fi1, fi0) and not lock_during and not nav.rotation_lock
                    and abs(np.linalg.norm(fi2 - fi1) - per_s * 0.1) < 0.01 * per_s,
                    f"inactive moved {np.linalg.norm(fi1 - fi0):.2e}; active again moved {np.linalg.norm(fi2 - fi1):.3f} "
                    f"(0.1 s = {per_s * 0.1:.3f})")
        # the one activity check, called for real (no wrapper that turns an exception into False)
        try:
            shared = ctlmod.app_is_active()
            direct = slicer.app.activeWindow() is not None
            ok &= check("the shared activity check runs against Slicer and agrees with activeWindow()",
                        isinstance(shared, bool) and shared == direct
                        and navmod.Navigator._app_active() == shared == ctlmod.Controller._app_is_active(),
                        f"active: {shared}")
        except Exception as exc:  # noqa: BLE001
            ok &= check("the shared activity check runs against Slicer and agrees with activeWindow()", False, repr(exc))

        # --- slice view ---------------------------------------------------------------------------------------------
        arr = np.random.RandomState(1).randint(0, 100, size=(40, 40, 40)).astype(np.int16)
        vol = slicer.util.addVolumeFromArray(arr, name="selftest_fallback_volume")
        vol.SetSpacing(1.0, 1.0, 2.0)
        slicer.util.setSliceViewerLayers(background=vol, fit=True)
        slicer.app.processEvents()
        red = slicer.util.getNode("vtkMRMLSliceNodeRed")
        rw = manager.sliceWidget("Red")
        logic = rw.sliceLogic()
        logic.SetSliceOffset(logic.GetSliceOffset())
        logic.SnapSliceOffsetToIJK()
        sbridge = SliceBridge("Red")
        nav = new_nav(target=lambda: sbridge)
        sp = sbridge._spacing(logic)
        o0 = logic.GetSliceOffset()
        drive(nav, 600.0, 600.1, {"tz": 1.0})
        o1 = logic.GetSliceOffset()
        n_exp = int(navmod.LEVEL_PLANES_S * 0.1)
        ok &= check("slice page: full pull 0.1 s steps whole planes toward +normal", abs(o1 - o0 - n_exp * sp) < 1e-6,
                    f"S{o0:.3f} -> S{o1:.3f} ({n_exp} planes of {sp:.3f} mm)")
        s = motion.AxisSettings()
        s.reverse["tz"] = True
        nav2 = navmod.Navigator(motion.Integrator(s), s, target=lambda: sbridge)
        nav2.is_active = lambda: True
        drive(nav2, 610.0, 610.1, {"tz": 1.0})
        o2 = logic.GetSliceOffset()
        ok &= check("slice paging reversed on the tz axis steps back", abs(o2 - o0) < 1e-6, f"S{o2:.3f}")
        # the same direction as driver mode: a driver camera move into the screen (toward -normal) and a fallback
        # push (tz < 0) both page toward -normal
        from MouseNav3DLib import camera_math as cm
        m = cm.from_navlib(sbridge._get_affine())
        m[:3, 3] -= 3.0 * sp * m[:3, 2]
        ob = logic.GetSliceOffset()
        sbridge._set_affine(cm.to_navlib(m))
        d_driver = logic.GetSliceOffset() - ob
        ob = logic.GetSliceOffset()
        drive(nav, 615.0, 615.1, {"tz": -1.0})
        d_push = logic.GetSliceOffset() - ob
        ok &= check("slice page: a push pages toward -normal, the direction slice_bridge pages a driver camera move "
                    "into the screen", d_driver < 0 and d_push < 0
                    and abs(d_push + n_exp * sp) < 1e-6, f"driver {d_driver:+.3f} mm, fallback push {d_push:+.3f} mm")
        nav3 = new_nav(target=lambda: sbridge)
        for k in range(10):                                # a light pull for 0.16 s: whole planes only
            nav3.handle_report(620.0 + 0.016 * k, {"tz": 0.2}, None)
        nav3.tick(620.0)
        o3a = logic.GetSliceOffset()
        for k in range(1, 11):
            nav3.tick(620.0 + 0.016 * k)
        o3 = logic.GetSliceOffset()
        n_slow = navmod.LEVEL_PLANES_S * 0.2 * 0.16
        ok &= check("slice page: light pull moves whole planes only", abs((o3 - o3a) / sp - int(n_slow)) < 1e-6,
                    f"{n_slow:.2f} planes of pull -> {(o3 - o3a) / sp:.0f} plane(s)")
        m0 = np.array([red.GetSliceToRAS().GetElement(i, 3) for i in range(3)])
        fov0 = np.array(red.GetFieldOfView())
        xs = np.array([[red.GetSliceToRAS().GetElement(i, j) for j in range(2)] for i in range(3)])
        xs = xs / np.linalg.norm(xs, axis=0)
        drive(nav, 630.0, 630.1, {"tx": 1.0, "ty": 0.5})
        m1 = np.array([red.GetSliceToRAS().GetElement(i, 3) for i in range(3)])
        exp = -navmod.PAN_FRAC_S * 0.1 * np.array([fov0[0], 0.5 * fov0[1]])   # the picture moves right and up
        ok &= check("slice pan: slide right + half lift (no paging)", np.allclose(m1 - m0, xs @ exp, atol=1e-6)
                    and abs(logic.GetSliceOffset() - o3) < 1e-6, f"centre moved {np.round(m1 - m0, 2)} mm")
        drive(nav, 640.0, 640.1, {"ry": 1.0})
        fov1 = np.array(red.GetFieldOfView())
        ok &= check("slice zoom by twist", abs(fov1[0] / fov0[0] - math.exp(-navmod.ZOOM_E_S * 0.1)) < 1e-6,
                    f"field of view {fov0[0]:.1f} -> {fov1[0]:.1f} mm")

        # --- buttons ------------------------------------------------------------------------------------------------
        changes = []
        nav = new_nav(target=lambda: sbridge, on_change=lambda: changes.append(1))
        nav.handle_report(700.0, {}, [1])
        nav.tick(700.0)
        fov2 = np.array(red.GetFieldOfView())
        nav.handle_report(700.1, {}, [])
        nav.handle_report(700.2, {}, [2])
        nav.tick(700.2)
        locked = nav.rotation_lock
        nav.handle_report(700.3, {}, [])
        nav.handle_report(700.4, {}, [2])
        nav.tick(700.4)
        ok &= check("buttons: 1 fits the slice view, 2 toggles the rotation lock",
                    not np.allclose(fov2, fov1) and locked and not nav.rotation_lock and len(changes) == 3,
                    f"field of view {fov1[0]:.1f} -> {fov2[0]:.1f} mm; lock on then off")
        bridge3d_fit = View3DBridge(0)
        nav = new_nav(target=lambda: bridge3d_fit)
        tdv.resetFocalPoint()
        tdv.resetCamera()
        slicer.app.processEvents()
        base_f = cam3d()[1]
        nav.apply({**dict.fromkeys(motion.AXES, 0.0), "tx": 0.3})
        moved = not np.allclose(cam3d()[1], base_f)
        nav.handle_report(710.0, {}, [1])
        nav.tick(710.0)
        ok &= check("button 1 in the 3D view fits it", moved and np.linalg.norm(cam3d()[1] - base_f) < 1.0,
                    f"focal point {np.linalg.norm(cam3d()[1] - base_f):.3f} mm from the fitted one (an empty scene's fit is only "
                    f"repeatable to ~0.1 mm; the pan was {0.3 * navmod.PAN_FRAC_S * dist:.0f} mm)")

        # --- controller wiring: interactive rate while moving, retarget without a navlib connection -----------------
        st = qt.QSettings()
        saved = {k: st.value(k) for k in SETTING_KEYS}
        try:
            class IdleReader:
                running = False
                devices = ["Test mouse"]
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
            reader = IdleReader()
            c = ctlmod.Controller()
            c._reader_factory = lambda: reader
            try:
                mode = c.start()
            finally:
                nl.load_library = real_load
            ok &= check("controller: no driver gives fallback mode with a connected device",
                        mode == "fallback" and "Test mouse connected" in c.status(), c.status())
            ok &= check("reader reports go to the navigator", reader.on_report == c.navigator.handle_report)
            ok &= check("the navigator timer is a precise 8 ms timer", c.navigator.timer.isActive()
                        and c.navigator.timer.interval == 8 and c.navigator.timer.timerType == qt.Qt.PreciseTimer,
                        f"{c.navigator.timer.interval} ms")
            c.navigator.is_active = lambda: True
            manager.setLayout(L.SlicerLayoutDual3DView)
            slicer.app.processEvents()

            def window():
                return manager.threeDWidget(0).threeDView().renderWindow()

            wi = manager.threeDWidget(0).threeDView().interactor()
            still, interactive = wi.GetStillUpdateRate(), wi.GetDesiredUpdateRate()
            window().SetDesiredUpdateRate(still)
            c._pointer_over = lambda w: w is manager.threeDWidget(1)
            c._retarget()
            ok &= check("retarget works in fallback mode (no navlib connection)",
                        isinstance(c.target, View3DBridge) and c.target.view_index == 1)
            c._pointer_over = lambda w: w is manager.threeDWidget(0)
            c._retarget()
            tnow = time.monotonic()
            reader.on_report(tnow, {"tx": 1.0}, None)
            f_before = cam3d()[1]
            c.navigator.tick(tnow + 0.05)
            rate_moving = window().GetDesiredUpdateRate()
            moved = not np.allclose(cam3d()[1], f_before)
            reader.on_report(tnow + 0.06, dict.fromkeys(motion.AXES, 0.0), None)
            c.navigator.tick(tnow + 0.07)
            rate_after = window().GetDesiredUpdateRate()
            ok &= check("interactive update rate while moving, still rate after the release",
                        moved and abs(rate_moving - interactive) < 1e-9
                        and abs(rate_after - still) < 1e-9, f"{rate_moving} while moving (interactive {interactive}), {rate_after} after (still {still}), "
                        f"camera moved: {moved}, target {c.target}")
            reader.on_report(time.monotonic(), {"tx": 1.0}, None)     # leave it moving, then stop
            c.navigator.tick(time.monotonic() + 0.02)
            c.stop()
            ok &= check("stop during motion: still rate back, reader and timer stopped",
                        abs(window().GetDesiredUpdateRate() - still) < 1e-9 and not reader.running
                        and c.navigator is None and c._timer is None)
            # a device button persists the rotation lock
            c = ctlmod.Controller()
            nl.load_library = lambda: None
            try:
                c._reader_factory = lambda: reader
                c.start()
            finally:
                nl.load_library = real_load
            c.navigator.is_active = lambda: True
            reader.on_report(time.monotonic(), {}, [2])
            c.navigator.tick(time.monotonic())
            from MouseNav3DLib import settings
            ok &= check("button 2 remembers the rotation lock", c.navigator.rotation_lock and settings.fallback_rotation_lock())
            c.stop()
        finally:
            for k, v in saved.items():
                if v is None:
                    st.remove(k)
                else:
                    st.setValue(k, v)
            manager.setLayout(L.SlicerLayoutConventionalView)

        # --- the real timer, with real time ---------------------------------------------------------------------------
        manager.setLayout(L.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        nav = new_nav(target=lambda: View3DBridge(0))
        tdv.resetFocalPoint()
        tdv.resetCamera()
        slicer.app.processEvents()
        pa, fa, _ = cam3d()
        nav.start()
        ticks = []
        orig = nav.tick
        nav.tick = lambda now=None: (ticks.append(1), orig(now))[1]
        nav.timer.disconnect("timeout()", nav._tick_slot)
        nav._tick_slot = nav.tick
        nav.timer.connect("timeout()", nav._tick_slot)
        nav.handle_report(time.monotonic(), {"tx": 1.0}, None)
        t0 = time.time()
        while time.time() - t0 < 0.3:
            slicer.app.processEvents()
            time.sleep(0.002)
        nav.stop()
        n = len(ticks)
        moved = np.linalg.norm(cam3d()[1] - fa)
        per_s = navmod.PAN_FRAC_S * np.linalg.norm(fa - pa)
        ok &= check("the 8 ms timer drives the motion in real time", n > 5 and 0 < moved <= per_s * (motion.STALE_S + 0.02),
                    f"{n} ticks in 0.3 s, moved {moved:.2f} mm (the 0.25 s of a held report = {per_s * 0.25:.2f})")
        ok &= check("stop leaves the timer off", nav.timer is None and nav.moving is False)

        # --- a failing frame: logged once, the real timer keeps running ------------------------------------------------
        import logging

        class Count(logging.Handler):
            def __init__(self):
                super().__init__(logging.ERROR)
                self.n = 0

            def emit(self, record):
                self.n += 1

        counter = Count()
        logging.getLogger("MouseNav3D").addHandler(counter)
        try:
            nav = new_nav(target=lambda: View3DBridge(0))
            calls = []

            def bad_apply(d, bridge=None):
                calls.append(1)
                raise RuntimeError("selftest: apply fails")

            nav.apply = bad_apply
            nav.start()
            t0 = time.time()
            while time.time() - t0 < 0.2:
                nav.handle_report(time.monotonic(), {"tx": 1.0}, None)
                slicer.app.processEvents()
                time.sleep(0.004)
            alive = nav.timer is not None and nav.timer.isActive()
            nav.stop()
        finally:
            logging.getLogger("MouseNav3D").removeHandler(counter)
        ok &= check("a raising apply is logged once and the 8 ms timer keeps running",
                    alive and len(calls) > 5 and counter.n == 1 and nav._tick_error_logged,
                    f"{len(calls)} failing frames, {counter.n} log record(s), timer active: {alive}")

        # --- readers start and stop without leaving a thread -------------------------------------------------------------
        real_find = hid.find_devices
        hid.find_devices = lambda: []                       # never touch the real device
        try:
            before = threading.active_count()
            r = hid.Reader()
            r.start()
            time.sleep(0.15)
            alive = threads(hid.THREAD_NAME)
            stopped = r.stop()
            ok &= check("HID reader: one thread while running, none after stop", alive == 1 and stopped
                        and threads(hid.THREAD_NAME) == 0 and threading.active_count() == before)
        finally:
            hid.find_devices = real_find
        if sys.platform == "win32":
            ok &= check("default reader on Windows is the HID reader (not started)",
                        isinstance(ctlmod.Controller()._make_reader(), hid.Reader))
        return ok

    ok = False
    try:
        ok = run()
    except Exception:
        lines.append(traceback.format_exc())
    finally:
        try:
            try:
                import slicer as _s
                _s.mrmlScene.Clear(0)
            except Exception:  # noqa: BLE001
                pass
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            lines.append("OVERALL: PASS" if ok else "OVERALL: FAIL")
            with open(log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        finally:
            slicer.util.exit(0 if ok else 1)


main()
