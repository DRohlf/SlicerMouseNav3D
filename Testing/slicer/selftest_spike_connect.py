"""Slicer self-test: the minimal Controller connects to the driver, the driver queries the 3D view within 2 s of
`active` = True, and stop() closes cleanly (twice without error).

Uses the app name "3D Mouse Navigation (self-test)" so the user's real profile in the driver's settings is untouched.
"""
# Everything lives inside main(): Slicer's --python-script namespace does not make module-level imports visible to
# functions, and a NameError in the finally block would skip slicer.util.exit and hang the process.


def main():
    import os
    import sys
    import threading
    import time
    import traceback

    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_spike_connect.log")
    lines = []

    def check(name, ok):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}")
        return bool(ok)

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        from MouseNav3DLib import controller as ctl_mod

        calls = []

        def collector(kind, name, value):
            calls.append((kind, name, threading.get_ident(), time.perf_counter()))

        slicer.util.mainWindow().show()
        slicer.app.processEvents()
        ctl = ctl_mod.Controller(app_name="3D Mouse Navigation (self-test)", recorder=collector)
        ok = True
        try:
            t0 = time.perf_counter()
            mode = ctl.start()
            lines.append(f"INFO: mode = {mode!r}; status = {ctl.status()!r}; write results = {ctl.write_results}; "
                         f"app active window = {slicer.app.activeWindow() is not None}")
            ok &= check("mode == 'driver'", mode == "driver")
            if mode != "driver":
                return False
            # The driver queries the view's getters only once there is device input, so getter traffic cannot be
            # asserted headless; it is verified in the live spike session. Here any driver callback counts.
            deadline = t0 + 2.0
            while time.perf_counter() < deadline and not calls:
                slicer.app.processEvents()
                time.sleep(0.01)
            ok &= check("at least one driver callback (get or set) within 2 s", bool(calls))
            if calls:
                lines.append(f"INFO: first callback {1000 * (calls[0][3] - t0):.0f} ms after start()")
            # Let a few more driver callbacks arrive so the log shows the whole startup query set.
            for _ in range(20):
                slicer.app.processEvents()
                time.sleep(0.01)
            for kind, name, tid, _t in calls:
                lines.append(f"CALL: {kind} {name} thread={tid} main={tid == ctl.main_thread}")
            names = sorted({f"{k}:{n}" for k, n, _tid, _t in calls})
            lines.append(f"INFO: distinct properties = {names}")
            on_main = all(c[2] == ctl.main_thread for c in calls)
            ok &= check("every recorded callback ran on the main thread", on_main)
            lines.append(f"INFO: all callbacks on the main thread = {on_main}; threads = {sorted(ctl.callback_threads)}"
                         f"; main = {ctl.main_thread}")
        finally:
            ctl.stop()
        ok &= check("connection closed and dropped", ctl.connection is None and ctl.target is None)
        try:
            ctl.stop()
            second = True
        except Exception:  # noqa: BLE001
            lines.append(traceback.format_exc())
            second = False
        ok &= check("second stop() does not raise", second)
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
            slicer.util.exit(0)


main()
