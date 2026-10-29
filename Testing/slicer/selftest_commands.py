"""Slicer self-test: anatomical view commands and the controller's commands.activeCommand setter (no navlib connection)."""


def main():
    import os
    import sys
    import traceback

    import numpy as np
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_commands.log")
    lines = []

    def check(name, ok, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
        return bool(ok)

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
            del sys.modules[m]
        from MouseNav3DLib import commands
        from MouseNav3DLib import navlib_ctypes as nl
        from MouseNav3DLib.controller import Controller

        slicer.mrmlScene.Clear(0)
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        slicer.app.processEvents()
        widget = slicer.app.layoutManager().threeDWidget(0)
        view = widget.threeDView()
        cam = view.renderWindow().GetRenderers().GetFirstRenderer().GetActiveCamera()

        def reposition():
            cam.SetFocalPoint(10.0, 20.0, 30.0)
            cam.SetPosition(10.0 + 120.0, 20.0 + 50.0, 30.0 + 80.0)
            cam.SetViewUp(0, 0, 1)

        def dop():
            return np.array(cam.GetDirectionOfProjection())

        def dist():
            return float(cam.GetDistance())

        ok = True
        cases = [("mn3d.anterior", (0, -1, 0)), ("mn3d.posterior", (0, 1, 0)),
                 ("mn3d.right", (-1, 0, 0)), ("mn3d.left", (1, 0, 0)),
                 ("mn3d.superior", (0, 0, -1)), ("mn3d.inferior", (0, 0, 1))]
        for cid, expect in cases:
            reposition()
            d0 = dist()
            commands.run(cid, 0, "right")
            ok &= check(f"{cid} direction", np.allclose(dop(), expect, atol=1e-6), str(dop()))
            ok &= check(f"{cid} distance kept", abs(dist() - d0) < 1e-6, f"{dist()} vs {d0}")
            ok &= check(f"{cid} focal point kept", np.allclose(cam.GetFocalPoint(), (10, 20, 30), atol=1e-6))
        for limb, lat, med in (("right", (-1, 0, 0), (1, 0, 0)), ("left", (1, 0, 0), (-1, 0, 0))):
            for cid, expect in (("mn3d.lateral", lat), ("mn3d.medial", med)):
                reposition()
                commands.run(cid, 0, limb)
                ok &= check(f"{cid} limb {limb}", np.allclose(dop(), expect, atol=1e-6), str(dop()))
        # reset
        reposition()
        commands.run("mn3d.reset", 0, "right")
        ok &= check("reset runs", True)
        # unknown view / unknown id: no-ops
        reposition()
        before = np.array(cam.GetPosition())
        commands.run("mn3d.right", 99, "right")
        commands.run("mn3d.nonsense", 0, "right")
        ok &= check("unknown view/id no-op", np.allclose(cam.GetPosition(), before))

        # controller setter, no connection
        ctl = Controller(0)
        ok &= check("limb_side default", ctl.limb_side == "right")
        setters = ctl.build_setters()
        setter = setters[nl.COMMANDS_ACTIVE_COMMAND]
        reposition()
        setter("mn3d.right")
        ok &= check("activeCommand runs right", np.allclose(dop(), (-1, 0, 0), atol=1e-6), str(dop()))
        reposition()
        before = np.array(cam.GetPosition())
        setter("")
        setter("mn3d.bogus")
        ok &= check("empty / unknown id ignored", np.allclose(cam.GetPosition(), before))
        ok &= check("bridge setters still present", nl.VIEW_AFFINE in setters)
        orig = commands.run
        commands.run = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            setter("mn3d.right")
            setter("mn3d.left")
            ok &= check("exception in run does not escape", True)
        finally:
            commands.run = orig
        return ok

    ok = False
    try:
        try:
            ok = run()
        except Exception:
            lines.append("EXCEPTION:\n" + traceback.format_exc())
            ok = False
        lines.append("OVERALL: " + ("PASS" if ok else "FAIL"))
    finally:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        finally:
            slicer.util.exit(0 if ok else 1)


main()
