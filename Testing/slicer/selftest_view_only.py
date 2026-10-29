"""Slicer self-test: view only. Around a 3D move through the driver's accessors, a slice move (pan and paging) through
the driver's accessors and a fallback apply on both kinds of view, no MRML node other than the camera and slice
nodes changes its MTime, and the scene's node count stays the same.

No navlib connection or device reader is started: the bridges and the Navigator are called directly.
"""


def main():
    import os
    import sys
    import traceback

    import numpy as np
    import slicer
    import vtk

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_view_only.log")
    lines = []
    VIEW_CLASSES = ("vtkMRMLCameraNode", "vtkMRMLSliceNode")

    def check(name, ok, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
        return bool(ok)

    def snapshot():
        scene = slicer.mrmlScene
        nodes = {}
        for i in range(scene.GetNumberOfNodes()):
            n = scene.GetNthNode(i)
            nodes[n.GetID()] = (n.GetClassName(), n.GetMTime())
        return scene.GetNumberOfNodes(), nodes

    def settle():
        slicer.app.processEvents()
        lm = slicer.app.layoutManager()
        for i in range(lm.threeDViewCount):
            lm.threeDWidget(i).threeDView().forceRender()
        for name in lm.sliceViewNames():
            lm.sliceWidget(name).sliceView().forceRender()
        slicer.app.processEvents()

    def compare(label, before, after):
        n0, a = before
        n1, b = after
        changed = sorted(f"{a[k][0]} {k}" for k in a if k in b and b[k][1] != a[k][1] and a[k][0] not in VIEW_CLASSES)
        moved = sorted(f"{a[k][0]}" for k in a if k in b and b[k][1] != a[k][1] and a[k][0] in VIEW_CLASSES)
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        return check(f"{label}: only camera and slice nodes changed, node count unchanged",
                     not changed and not added and not removed and n0 == n1 and moved,
                     f"view nodes modified: {moved}; other nodes modified: {changed}; added {added}; removed {removed};"
                     f" count {n0} -> {n1}")

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
            del sys.modules[m]
        from MouseNav3DLib import camera_math as cm
        from MouseNav3DLib import navlib_ctypes as nl
        from MouseNav3DLib.fallback import motion
        from MouseNav3DLib.fallback import navigator as navmod
        from MouseNav3DLib.slice_bridge import SliceBridge
        from MouseNav3DLib.view3d_bridge import View3DBridge

        ok = True
        manager = slicer.app.layoutManager()
        slicer.mrmlScene.Clear(0)
        manager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        # a scene worth protecting: a volume in the slice views, a model in the 3D view
        arr = np.random.RandomState(3).randint(0, 100, size=(30, 40, 50)).astype(np.int16)
        vol = slicer.util.addVolumeFromArray(arr, name="selftest_view_only_volume")
        vol.SetSpacing(1.0, 1.0, 2.0)
        slicer.util.setSliceViewerLayers(background=vol, fit=True)
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(20.0, 20.0, 30.0)
        sphere.SetRadius(15.0)
        sphere.Update()
        model = slicer.modules.models.logic().AddModel(sphere.GetOutput())
        model.SetName("selftest_view_only_model")
        tdv = manager.threeDWidget(0).threeDView()
        tdv.resetFocalPoint()
        tdv.resetCamera()
        settle()

        # --- 3D view through the driver's accessors -----------------------------------------------------------------
        b3 = View3DBridge(0)
        g, s = b3.getters(), b3.setters()
        before = snapshot()
        for name, (_t, fn) in g.items():          # every read the driver may make
            try:
                fn()
            except nl.NoData:
                pass
        s[nl.MOTION](True)
        affine = cm.from_navlib(g[nl.VIEW_AFFINE][1]())
        for k in range(5):
            affine[:3, 3] += np.array([3.0, -2.0, 1.0])
            s[nl.VIEW_AFFINE](cm.to_navlib(affine))
            s[nl.TRANSACTION](0)
        s[nl.MOTION](False)
        settle()
        ok &= compare("3D move (driver accessors)", before, snapshot())

        # --- slice view through the driver's accessors: pan and paging ------------------------------------------------
        bs = SliceBridge("Red")
        g, s = bs.getters(), bs.setters()
        before = snapshot()
        for name, (_t, fn) in g.items():
            try:
                fn()
            except nl.NoData:
                pass
        s[nl.MOTION](True)
        affine = cm.from_navlib(g[nl.VIEW_AFFINE][1]())
        normal = affine[:3, 2].copy()
        for k in range(5):
            affine[:3, 3] += np.array([2.0, 1.0, 0.0]) - 2.5 * normal   # pan, and more than one plane of paging
            s[nl.VIEW_AFFINE](cm.to_navlib(affine))
            s[nl.TRANSACTION](0)
        s[nl.MOTION](False)
        settle()
        ok &= compare("slice move (driver accessors)", before, snapshot())

        # --- fallback apply on both views ------------------------------------------------------------------------------
        st = motion.AxisSettings()
        nav = navmod.Navigator(motion.Integrator(st), st, target=lambda: None)
        nav.is_active = lambda: True
        d = {"tx": 0.05, "ty": -0.04, "tz": 0.3, "rx": 0.02, "ry": 0.05, "rz": -0.03}
        before = snapshot()
        nav.apply(d, View3DBridge(0))
        settle()
        ok &= compare("fallback apply, 3D view", before, snapshot())
        before = snapshot()
        nav.apply(d, SliceBridge("Yellow"))
        settle()
        ok &= compare("fallback apply, slice view (pan, zoom, paging)", before, snapshot())
        return ok

    ok = False
    try:
        ok = run()
    except Exception:
        lines.append(traceback.format_exc())
    finally:
        try:
            try:
                slicer.mrmlScene.Clear(0)
            except Exception:  # noqa: BLE001
                pass
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            lines.append("OVERALL: PASS" if ok else "OVERALL: FAIL")
            with open(log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        finally:
            slicer.util.exit(0 if ok else 1)


main()
