"""Slicer self-test: SliceBridge accessors on the Red slice view (no navlib connection is made)."""
# Everything lives inside main(): see selftest_view3d_bridge.py.


def main():
    import math
    import os
    import sys
    import traceback

    import numpy as np
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_slice_bridge.log")
    lines = []

    def check(name, ok, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))
        return bool(ok)

    def raises(exc, fn):
        try:
            fn()
        except exc:
            return True
        return False

    def run():
        sys.path.insert(0, os.path.join(root, "MouseNav3D"))
        for m in [m for m in sys.modules if m.startswith("MouseNav3DLib")]:
            del sys.modules[m]
        from MouseNav3DLib import camera_math as cm
        from MouseNav3DLib import navlib_ctypes as nl
        from MouseNav3DLib.slice_bridge import SliceBridge

        slicer.mrmlScene.Clear(0)
        manager = slicer.app.layoutManager()
        manager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        slicer.app.processEvents()

        # --- no volume ------------------------------------------------------------------------------------
        bridge = SliceBridge("Red")
        get = {k: v[1] for k, v in bridge.getters().items()}
        put = bridge.setters()
        ok = check("widget() found", bridge.widget() is not None)
        ok &= check("widget of a missing slice is None", SliceBridge("Nope").widget() is None)
        ok &= check("getter on a missing slice raises NoData",
                    raises(nl.NoData, SliceBridge("Nope").getters()[nl.VIEW_AFFINE][1]))
        lo, hi = get[nl.MODEL_EXTENTS]()
        ok &= check("no volume: model.extents is the unit box", np.allclose(lo, -0.5) and np.allclose(hi, 0.5),
                    f"{lo} {hi}")
        ok &= check("view.perspective True (push/pull arrives as camera z)", get[nl.VIEW_PERSPECTIVE]() is True)
        ok &= check("view.rotatable False", get[nl.VIEW_ROTATABLE]() is False)
        ok &= check("view.fov provided", nl.VIEW_FOV in bridge.getters())
        ok &= check("hit.lookat raises NoData", raises(nl.NoData, get[nl.HIT_LOOKAT]))
        ok &= check("units / coordinate system", get[nl.MODEL_UNITS_TO_METERS]() == 0.001
                    and tuple(get[nl.COORDINATE_SYSTEM]()) == tuple(cm.COORDINATE_SYSTEM))

        # --- with a volume of 0.333 mm slices ---------------------------------------------------------------
        spacing = 0.333
        vol = slicer.util.addVolumeFromArray(np.zeros((30, 40, 50), dtype=np.int16), name="slice-bridge-test")
        vol.SetSpacing(spacing, spacing, spacing)
        vol.SetOrigin(-10.0, -20.0, -5.0)
        slicer.util.setSliceViewerLayers(background=vol, fit=True)
        slicer.app.processEvents()
        node = manager.sliceWidget("Red").mrmlSliceNode()
        logic = manager.sliceWidget("Red").sliceLogic()
        composite = logic.GetSliceCompositeNode()
        layers0 = (composite.GetBackgroundVolumeID(), composite.GetForegroundVolumeID(), composite.GetLabelVolumeID())
        node.SetFieldOfView(100.0, 60.0, 0.5 * spacing)
        node.UpdateMatrices()
        logic.SnapSliceOffsetToIJK()
        slicer.app.processEvents()

        def basis():
            m = node.GetSliceToRAS()
            return tuple(np.array([m.GetElement(i, c) for i in range(3)]) for c in range(3))

        def centre():
            dims = node.GetDimensions()
            p = node.GetXYToRAS().MultiplyPoint([dims[0] / 2.0, dims[1] / 2.0, 0.0, 1.0])
            return np.array(p[:3])

        def rotation():
            return np.array([[node.GetSliceToRAS().GetElement(i, j) for j in range(3)] for i in range(3)])

        x, y, n = basis()
        c0 = centre()
        a = get[nl.VIEW_AFFINE]()
        am = cm.from_navlib(a)
        ok &= check("affine columns are slice x, y, normal", np.allclose(am[:3, 0], x) and np.allclose(am[:3, 1], y)
                    and np.allclose(am[:3, 2], n))
        ok &= check("affine translation = centre + 100 mm along the normal", np.allclose(am[:3, 3], c0 + 100.0 * n),
                    f"{am[:3, 3]} vs {c0 + 100.0 * n}")
        lo, hi = get[nl.MODEL_EXTENTS]()
        bounds = [0.0] * 6
        vol.GetRASBounds(bounds)
        ok &= check("model.extents = volume RAS bounds",
                    np.allclose(lo, bounds[0::2], atol=1e-6) and np.allclose(hi, bounds[1::2], atol=1e-6),
                    f"{lo} {hi} vs {bounds}")
        ok &= check("pivot.position is the slice centre", np.allclose(get[nl.PIVOT_POSITION](), c0, atol=1e-6))
        put[nl.PIVOT_POSITION]((1.0, 2.0, 3.0))
        put[nl.PIVOT_VISIBLE](True)
        ok &= check("pivot setters ignored", np.allclose(get[nl.PIVOT_POSITION](), c0, atol=1e-6))

        # roundtrip changes nothing
        rot0, off0 = rotation(), logic.GetSliceOffset()
        put[nl.VIEW_AFFINE](a)
        ok &= check("affine roundtrip changes nothing", np.allclose(centre(), c0, atol=1e-6)
                    and np.allclose(rotation(), rot0) and abs(logic.GetSliceOffset() - off0) < 1e-9)

        # pan by (5, 0) mm
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] += 5.0 * x
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        c1 = centre()
        ok &= check("pan (5,0) moves the centre 5 mm along slice x", np.allclose(c1 - c0, 5.0 * x, atol=1e-6),
                    f"{c1 - c0}")
        ok &= check("pan keeps the slice plane and orientation", abs(logic.GetSliceOffset() - off0) < 1e-9
                    and np.allclose(rotation(), rot0))
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] += -3.0 * y
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        ok &= check("pan along slice y", np.allclose(centre() - c1, -3.0 * y, atol=1e-6))
        c1 = centre()

        # normal: 1.0 mm with 0.333 spacing -> 3 planes
        off0 = logic.GetSliceOffset()
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] += 1.0 * n
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        d = logic.GetSliceOffset() - off0
        ok &= check("normal 1.0 mm steps 3 planes (0.999)", abs(d - 3 * spacing) < 1e-6, f"offset change {d}")
        moved = centre() - c1
        ok &= check("normal step keeps the in-plane centre", np.allclose(moved - n * np.dot(moved, n), 0.0, atol=1e-6))
        # 0.2 mm: nothing, carried; the same 0.2 mm again: one plane
        off0 = logic.GetSliceOffset()
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] += 0.2 * n
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        ok &= check("normal 0.2 mm steps no plane", abs(logic.GetSliceOffset() - off0) < 1e-9)
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        d = logic.GetSliceOffset() - off0
        ok &= check("the carried 0.2 mm plus another 0.2 mm steps one plane", abs(d - spacing) < 1e-6, f"{d}")
        # backwards (a fresh motion: the carry is dropped)
        bridge.release_motion()
        off0 = logic.GetSliceOffset()
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] -= 0.7 * n
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        d = logic.GetSliceOffset() - off0
        ok &= check("normal -0.7 mm steps -2 planes", abs(d + 2 * spacing) < 1e-6, f"{d}")

        # rotation in a written affine is ignored
        rot0, c2 = rotation(), centre()
        r = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, :3] = m[:3, :3] @ r
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        ok &= check("rotation in the written affine is ignored", np.allclose(rotation(), rot0)
                    and np.allclose(centre(), c2, atol=1e-6))

        # camera z: -1.0 mm pages 3 planes toward -normal
        bridge.release_motion()
        off0 = logic.GetSliceOffset()
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] += -1.0 * n
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        d = logic.GetSliceOffset() - off0
        ok &= check("camera z -1.0 mm steps 3 planes toward -normal (-0.999)", abs(d + 3 * spacing) < 1e-6, f"{d}")
        bridge.release_motion()

        # view.fov matches the field-of-view height at the camera distance
        from MouseNav3DLib import slice_bridge as sbmod
        fov_h = node.GetFieldOfView()[1]
        want = 2.0 * math.atan(0.5 * fov_h / sbmod.CAMERA_DISTANCE)
        ok &= check("view.fov = 2 atan(half height / distance)", abs(get[nl.VIEW_FOV]() - want) < 1e-9,
                    f"{get[nl.VIEW_FOV]()} vs {want}")
        ok &= check("view.focusDistance = camera distance", get[nl.VIEW_FOCUS_DISTANCE]() == sbmod.CAMERA_DISTANCE)

        # extents <-> field of view
        fov0 = list(node.GetFieldOfView())
        c3 = centre()
        e = get[nl.VIEW_EXTENTS]()
        ok &= check("view.extents are the half field of view",
                    np.allclose(e[1][:2], [fov0[0] / 2, fov0[1] / 2])
                    and np.allclose(e[0][:2], [-fov0[0] / 2, -fov0[1] / 2]) and e[1][2] > 1e3, str(e))
        put[nl.VIEW_EXTENTS](((e[0][0] / 2, e[0][1] / 2, e[0][2]), (e[1][0] / 2, e[1][1] / 2, e[1][2])))
        put[nl.VIEW_EXTENTS](((0, 0, 0), (0, 0, 0)))
        fov1 = list(node.GetFieldOfView())
        ok &= check("extents writes are ignored (field of view and centre unchanged)",
                    np.allclose(fov1, fov0) and np.allclose(centre(), c3, atol=1e-6), f"{fov0} -> {fov1}")

        # frame handling
        put[nl.MOTION](True)
        put[nl.TRANSACTION](1)
        put[nl.TRANSACTION](0)
        put[nl.MOTION](False)
        bridge.set_motion(True)
        bridge.release_motion()
        ok &= check("motion / transaction setters run", True)

        # view only
        layers1 = (composite.GetBackgroundVolumeID(), composite.GetForegroundVolumeID(), composite.GetLabelVolumeID())
        ok &= check("layers untouched", layers0 == layers1)
        ok &= check("view.affine finite", np.all(np.isfinite(get[nl.VIEW_AFFINE]())))

        # no volume at all: spacing 1.0
        slicer.mrmlScene.RemoveNode(vol)
        slicer.util.setSliceViewerLayers(background=None)
        slicer.app.processEvents()
        node.SetFieldOfView(100.0, 60.0, 1.0)
        node.UpdateMatrices()
        off0 = logic.GetSliceOffset()
        m = cm.from_navlib(get[nl.VIEW_AFFINE]())
        m[:3, 3] += 2.4 * basis()[2]
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        ok &= check("no volume: spacing 1.0 mm", abs(logic.GetSliceOffset() - off0 - 2.0) < 1e-6,
                    f"{logic.GetSliceOffset() - off0}")

        # slice view gone
        gone = SliceBridge("Nope")
        ok &= check("setter on a missing slice raises NoData",
                    raises(nl.NoData, lambda: gone.setters()[nl.VIEW_AFFINE]((1.0,) * 16)))
        gone.release_motion()
        gone.render()
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
