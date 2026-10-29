"""Slicer self-test: the navlib library loads and a connection with three getters can be opened and closed.

Uses the app name "3D Mouse Navigation (self-test)" so the user's real profile in the driver's settings is untouched.
"""
# Everything lives inside main(): Slicer's --python-script namespace does not make module-level imports visible to
# functions, and a NameError in the finally block would skip slicer.util.exit and hang the process.


def main():
    import os
    import sys
    import traceback

    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_navlib_connect.log")
    lines = []

    def check(name, ok):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}")
        return bool(ok)

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        from MouseNav3DLib import navlib_ctypes as nl

        lib = nl.load_library()
        ok = check("load_library() is not None", lib is not None)
        if lib is None:
            return False
        identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        getters = {
            nl.VIEW_AFFINE: (nl.MATRIX, lambda: identity),
            nl.MODEL_EXTENTS: (nl.BOX, lambda: ((-100.0, -100.0, -100.0), (100.0, 100.0, 100.0))),
            nl.VIEW_PERSPECTIVE: (nl.BOOL, lambda: True),
        }
        conn = nl.Connection("3D Mouse Navigation (self-test)", getters, {}, lib)
        try:
            lines.append(f"INFO: NlCreate result = {conn.create_result}, handle = {conn.handle}")
            ok &= check("handle is not 0", conn.handle != 0)
            for _ in range(5):  # let the driver's queued callbacks run on this thread
                slicer.app.processEvents()
            try:  # what the panel's driver status uses; information only (a device may or may not be attached)
                lines.append(f"INFO: device.present = {conn.read(nl.DEVICE_PRESENT, nl.BOOL)!r}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"INFO: device.present could not be read: {exc!r}")
        finally:
            conn.close()
        ok &= check("close() returned without error and cleared the handle", conn.handle == 0)
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
