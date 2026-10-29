"""Slicer self-test: View3DBridge accessors on the first 3D view (no navlib connection is made)."""
# Everything lives inside main(): Slicer's --python-script namespace does not make module-level imports visible to
# functions, and a NameError in the finally block would skip slicer.util.exit and hang the process.


def main():
    import math
    import os
    import sys
    import time
    import traceback

    import numpy as np
    import slicer
    import vtk

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    log_path = os.path.join(here, "out", "selftest_view3d_bridge.log")
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
        from MouseNav3DLib import navlib_ctypes as nl
        from MouseNav3DLib import camera_math as cm
        from MouseNav3DLib.view3d_bridge import View3DBridge

        slicer.mrmlScene.Clear(0)
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        slicer.app.processEvents()

        bridge = View3DBridge(0)
        get = {k: v[1] for k, v in bridge.getters().items()}
        put = bridge.setters()
        widget = bridge.widget()
        ok = check("widget() found", widget is not None)
        if widget is None:
            return False
        view = widget.threeDView()
        window = view.renderWindow()
        ok &= check("widget(99) is None", View3DBridge(99).widget() is None)
        ok &= check("getter on missing view raises NoData", raises(nl.NoData, View3DBridge(99).getters()[nl.VIEW_AFFINE][1]))

        ends = [0]
        window.AddObserver(vtk.vtkCommand.EndEvent, lambda *_: ends.__setitem__(0, ends[0] + 1))

        def cam():
            return window.GetRenderers().GetFirstRenderer().GetActiveCamera()

        def pose():
            c = cam()
            return np.array(c.GetPosition()), np.array(c.GetFocalPoint()), np.array(c.GetViewUp())

        # test_affine_roundtrip
        view.resetCamera()
        slicer.app.processEvents()
        before = pose()
        put[nl.VIEW_AFFINE](get[nl.VIEW_AFFINE]())
        after = pose()
        ok &= check("affine roundtrip", all(np.allclose(a, b, atol=1e-6) for a, b in zip(before, after)),
                    f"max diff {max(np.abs(a - b).max() for a, b in zip(before, after)):.2e}")
        a16 = get[nl.VIEW_AFFINE]()
        ok &= check("affine getter is a finite 16-tuple", len(a16) == 16 and np.all(np.isfinite(a16)))

        # test_set_affine_moves_camera
        m = cm.from_navlib(a16)
        dist0 = cam().GetDistance()
        m[0, 3] += 10.0
        ends[0] = 0
        put[nl.TRANSACTION](1)
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        renders_during = ends[0]
        after = pose()
        ok &= check("affine write moves position by 10 mm in x", np.allclose(after[0] - before[0], [10, 0, 0], atol=1e-6))
        ok &= check("affine write moves focal point by 10 mm in x", np.allclose(after[1] - before[1], [10, 0, 0], atol=1e-6))
        ok &= check("focal distance kept", abs(cam().GetDistance() - dist0) < 1e-6)
        ok &= check("no render before transaction 0", renders_during == 0, f"EndEvents {renders_during}")
        put[nl.TRANSACTION](0)
        sync_renders = ends[0]
        ok &= check("transaction 0 renders exactly once (synchronously)", sync_renders == 1, f"EndEvents {sync_renders}")
        slicer.app.processEvents()
        lines.append(f"INFO: first frame: synchronous EndEvents = {sync_renders}; after processEvents = {ends[0]} "
                     f"(extra scheduled renders = {ends[0] - sync_renders})")
        # again after a settle, to separate startup renders from per-frame ones
        for _ in range(3):
            slicer.app.processEvents()
        ends[0] = 0
        m[0, 3] += 1.0
        put[nl.TRANSACTION](1)
        put[nl.VIEW_AFFINE](cm.to_navlib(m))
        put[nl.TRANSACTION](0)
        s2 = ends[0]
        for _ in range(3):
            slicer.app.processEvents()
        lines.append(f"INFO: settled frame: synchronous EndEvents = {s2}; after processEvents = {ends[0]} "
                     f"(extra scheduled renders = {ends[0] - s2})")

        # degenerate camera never gives a NaN affine
        c = cam()
        c.SetFocalPoint(*c.GetPosition())
        ok &= check("view.affine finite when position == focal point", np.all(np.isfinite(get[nl.VIEW_AFFINE]())))
        view.resetCamera()

        # test_front_and_coordinate_system
        ok &= check("views.front", tuple(get[nl.VIEWS_FRONT]()) == tuple(cm.FRONT_VIEW))
        ok &= check("coordinateSystem", tuple(get[nl.COORDINATE_SYSTEM]()) == tuple(cm.COORDINATE_SYSTEM))
        ok &= check("unitsToMeters 0.001", get[nl.MODEL_UNITS_TO_METERS]() == 0.001)
        ok &= check("rotatable / pivot.user / timingSource", get[nl.VIEW_ROTATABLE]() is True
                    and get[nl.PIVOT_USER]() is False and get[nl.FRAME_TIMING_SOURCE]() == 0)
        ok &= check("perspective by default, fov in radians",
                    get[nl.VIEW_PERSPECTIVE]() is True
                    and abs(get[nl.VIEW_FOV]() - math.radians(cam().GetViewAngle())) < 1e-9)
        ok &= check("view.target is not published", nl.VIEW_TARGET not in bridge.getters())
        ok &= check("focusDistance", abs(get[nl.VIEW_FOCUS_DISTANCE]() - cam().GetDistance()) < 1e-9)
        put[nl.VIEW_FOV](math.radians(40.0))
        ok &= check("fov set", abs(cam().GetViewAngle() - 40.0) < 1e-9)
        cam().SetViewAngle(30.0)

        # test_empty_scene_extents: Slicer's bounding box and axis labels are NOT data. They stay visible here (the
        # default); no data -> the unit box.
        view_node = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLViewNode")
        ok &= check("box and axis labels are visible for these checks",
                    bool(view_node.GetBoxVisible()) and bool(view_node.GetAxisLabelsVisible()))
        lo, hi = get[nl.MODEL_EXTENTS]()
        ok &= check("empty scene (box and labels shown): unit box",
                    np.all(np.isfinite(lo + hi)) and np.allclose(np.subtract(hi, lo), 1.0)
                    and np.allclose(0.5 * (np.add(lo, hi)), 0.0), f"{lo} {hi}")
        ok &= check("empty scene: pivot finite", np.all(np.isfinite(get[nl.PIVOT_POSITION]())))

        # test_parallel_projection_zoom
        ok &= check("extents raise NoData in perspective", raises(nl.NoData, get[nl.VIEW_EXTENTS]))
        cam().SetParallelProjection(True)
        cam().SetParallelScale(100.0)
        lo, hi = get[nl.VIEW_EXTENTS]()
        ok &= check("parallel extents: half-height = ParallelScale, depth +-1e8",
                    abs(hi[1] - 100.0) < 1e-9 and abs(lo[1] + 100.0) < 1e-9 and hi[2] == 1e8 and lo[2] == -1e8
                    and get[nl.VIEW_PERSPECTIVE]() is False)
        put[nl.VIEW_EXTENTS](((lo[0] / 2, lo[1] / 2, lo[2]), (hi[0] / 2, hi[1] / 2, hi[2])))
        ok &= check("extents set at half size halves ParallelScale", abs(cam().GetParallelScale() - 50.0) < 1e-9,
                    f"{cam().GetParallelScale()}")
        cam().SetParallelProjection(False)

        # test_motion_rate
        interactor = view.interactor()
        put[nl.MOTION](True)
        ok &= check("motion True: interactive rate", window.GetDesiredUpdateRate() == interactor.GetDesiredUpdateRate(),
                    f"{window.GetDesiredUpdateRate()} vs {interactor.GetDesiredUpdateRate()}")
        ends[0] = 0
        put[nl.MOTION](False)
        ok &= check("motion False: still rate", window.GetDesiredUpdateRate() == interactor.GetStillUpdateRate(),
                    f"{window.GetDesiredUpdateRate()} vs {interactor.GetStillUpdateRate()}")
        ok &= check("motion False: one final render", ends[0] == 1, f"EndEvents {ends[0]}")

        # test_hit_lookat
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(10.0)
        sphere.SetThetaResolution(48)
        sphere.SetPhiResolution(48)
        sphere.Update()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "bridgeTestSphere")
        node.SetAndObservePolyData(sphere.GetOutput())
        node.CreateDefaultDisplayNodes()
        slicer.app.processEvents()
        view.forceRender()
        put[nl.HIT_LOOKFROM]((0.0, -100.0, 0.0))
        put[nl.HIT_DIRECTION]((0.0, 1.0, 0.0))
        put[nl.HIT_APERTURE](0.0)
        put[nl.HIT_SELECTION_ONLY](False)
        hit = get[nl.HIT_LOOKAT]()
        ok &= check("hit.lookat on sphere", np.allclose(hit, (0, -10, 0), atol=0.5), f"{hit}")
        put[nl.HIT_APERTURE](2.0)
        hit = get[nl.HIT_LOOKAT]()
        ok &= check("hit.lookat with aperture", np.allclose(hit, (0, -10, 0), atol=0.5), f"{hit}")
        put[nl.HIT_DIRECTION]((0.0, -1.0, 0.0))
        ok &= check("pointing away raises NoData", raises(nl.NoData, get[nl.HIT_LOOKAT]))
        put[nl.HIT_DIRECTION]((1.0, 0.0, 0.0))
        put[nl.HIT_LOOKFROM]((-100.0, 0.0, 0.0))
        hit = get[nl.HIT_LOOKAT]()
        ok &= check("hit.lookat along +x", np.allclose(hit, (-10, 0, 0), atol=0.5), f"{hit}")
        lo, hi = get[nl.MODEL_EXTENTS]()
        ok &= check("model.extents covers the sphere", np.allclose(lo, (-10, -10, -10), atol=0.5)
                    and np.allclose(hi, (10, 10, 10), atol=0.5), f"{lo} {hi}")
        ok &= check("pivot defaults to visible-data centre", np.allclose(get[nl.PIVOT_POSITION](), (0, 0, 0), atol=0.5))
        ok &= check("box and axis labels still visible", bool(view_node.GetBoxVisible())
                    and bool(view_node.GetAxisLabelsVisible()))

        # rays through empty space that would hit an axis label if decorations counted -> NoData. The labels face
        # the camera, so the rays run along the viewing direction, over a grid covering the +x label.
        view.resetCamera()
        view.forceRender()
        renderer = window.GetRenderers().GetFirstRenderer()
        view_dir = np.array(cam().GetDirectionOfProjection())
        helper = np.array([0.0, 0.0, 1.0]) if abs(view_dir[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        au = np.cross(view_dir, helper)
        au /= np.linalg.norm(au)
        av = np.cross(view_dir, au)
        label_rays = []
        label_hits = 0
        props = renderer.GetViewProps()
        props.InitTraversal()
        for _ in range(props.GetNumberOfItems()):
            p = props.GetNextProp()
            if not (isinstance(p, vtk.vtkFollower) and p.GetVisibility() and p.GetMapper() is not None):
                continue
            b = p.GetBounds()
            centre = np.array([0.5 * (b[0] + b[1]), 0.5 * (b[2] + b[3]), 0.5 * (b[4] + b[5])])
            if np.linalg.norm(centre - (115.0, 0.0, 0.0)) > 2.0:  # not the +x label
                continue
            p.GetMapper().Update()
            moved = vtk.vtkTransformPolyDataFilter()
            tr = vtk.vtkTransform()
            tr.SetMatrix(p.GetMatrix())
            moved.SetTransform(tr)
            moved.SetInputData(p.GetMapper().GetInput())
            moved.Update()
            loc = vtk.vtkStaticCellLocator()
            loc.SetDataSet(moved.GetOutput())
            loc.BuildLocator()
            lines.append(f"INFO: +x label: bounds {tuple(round(x, 1) for x in b)}, view_dir {view_dir.round(3)}, "
                         f"world bounds {tuple(round(x, 1) for x in moved.GetOutput().GetBounds())}")
            for du in np.linspace(-5.0, 5.0, 11):
                for dv in np.linspace(-5.0, 5.0, 11):
                    start = centre + du * au + dv * av - 300.0 * view_dir
                    label_rays.append(start)
                    label_hits += int(loc.IntersectWithLine(start, start + 600.0 * view_dir, 0.0,
                                                            vtk.vtkPoints(), vtk.vtkIdList()))
        ok &= check("control: the +x axis label is a surface a decoration-blind ray would hit", label_hits > 0,
                    f"{label_hits} of {len(label_rays)} rays")
        put[nl.HIT_APERTURE](0.0)
        put[nl.HIT_DIRECTION](tuple(view_dir))
        misses = 0
        for start in label_rays:
            put[nl.HIT_LOOKFROM](tuple(start))
            misses += int(raises(nl.NoData, get[nl.HIT_LOOKAT]))
        ok &= check("rays through the axis label hit nothing (decorations never hit)",
                    len(label_rays) > 0 and misses == len(label_rays), f"{misses} of {len(label_rays)}")
        for origin in ((100.0, -300.0, 100.0), (-100.0, -300.0, 100.0), (100.0, -300.0, -100.0)):  # box edges
            put[nl.HIT_DIRECTION]((0.0, 1.0, 0.0))
            put[nl.HIT_LOOKFROM](origin)
            ok &= check(f"ray along a box edge from {origin} hits nothing", raises(nl.NoData, get[nl.HIT_LOOKAT]))

        # a segmentation (closed surface shown in 3D) is hit
        seg_sphere = vtk.vtkSphereSource()
        seg_sphere.SetRadius(8.0)
        seg_sphere.SetCenter(50.0, 0.0, 0.0)
        seg_sphere.SetThetaResolution(48)
        seg_sphere.SetPhiResolution(48)
        seg_sphere.Update()
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "bridgeTestSegmentation")
        seg.CreateDefaultDisplayNodes()
        seg.GetSegmentation().SetMasterRepresentationName("Closed surface")
        seg.AddSegmentFromClosedSurfaceRepresentation(seg_sphere.GetOutput(), "sphere")
        seg.GetDisplayNode().SetVisibility3D(True)
        slicer.app.processEvents()
        view.forceRender()
        put[nl.HIT_LOOKFROM]((50.0, -100.0, 0.0))
        put[nl.HIT_DIRECTION]((0.0, 1.0, 0.0))
        try:
            hit = get[nl.HIT_LOOKAT]()
        except nl.NoData:
            hit = None
        ok &= check("segmentation closed surface is hit through its centre",
                    hit is not None and np.allclose(hit, (50, -8, 0), atol=0.5), f"{hit}")
        lo, hi = get[nl.MODEL_EXTENTS]()
        ok &= check("model.extents covers model and segmentation, not the box",
                    np.allclose(lo, (-10, -10, -10), atol=0.5) and np.allclose(hi, (58, 10, 10), atol=0.5), f"{lo} {hi}")
        ok &= check("pivot defaults to the centre of both", np.allclose(get[nl.PIVOT_POSITION](), (24, 0, 0), atol=0.5))
        # toggling the decorations changes nothing
        try:
            view_node.SetBoxVisible(False)
            view_node.SetAxisLabelsVisible(False)
            slicer.app.processEvents()
            lo2, hi2 = get[nl.MODEL_EXTENTS]()
            ok &= check("extents identical with box and labels hidden", np.allclose(lo, lo2) and np.allclose(hi, hi2))
        finally:
            view_node.SetBoxVisible(True)
            view_node.SetAxisLabelsVisible(True)
            slicer.app.processEvents()
        # a volume rendering counts for the extents (not for hits)
        vol = slicer.util.addVolumeFromArray(np.zeros((10, 10, 10), dtype=np.float32))
        vol.SetOrigin(300.0, 0.0, 0.0)
        display = slicer.modules.volumerendering.logic().CreateDefaultVolumeRenderingNodes(vol)
        display.SetVisibility(True)
        slicer.app.processEvents()
        view.forceRender()
        lo, hi = get[nl.MODEL_EXTENTS]()
        ok &= check("volume rendering counts for model.extents", hi[0] > 305.0, f"{lo} {hi}")
        slicer.mrmlScene.RemoveNode(display)
        slicer.mrmlScene.RemoveNode(vol)
        slicer.mrmlScene.RemoveNode(seg)
        slicer.app.processEvents()
        # locators are cached per actor: a heavy scene (20 models of ~50k triangles) is only slow the first time
        heavy = []
        for k in range(20):
            src = vtk.vtkSphereSource()
            src.SetRadius(4.0)
            src.SetCenter(-300.0 + 12.0 * k, 400.0, 0.0)
            src.SetThetaResolution(160)
            src.SetPhiResolution(160)
            src.Update()
            hn = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f"bridgeHeavy{k}")
            hn.SetAndObservePolyData(src.GetOutput())
            hn.CreateDefaultDisplayNodes()
            heavy.append(hn)
        slicer.app.processEvents()
        view.forceRender()
        put[nl.HIT_LOOKFROM]((-300.0 + 12.0 * 7, 100.0, 0.0))
        put[nl.HIT_DIRECTION]((0.0, 1.0, 0.0))
        put[nl.HIT_APERTURE](0.0)
        t0 = time.perf_counter()
        hit1 = get[nl.HIT_LOOKAT]()
        t_first = time.perf_counter() - t0
        t0 = time.perf_counter()
        hit2 = get[nl.HIT_LOOKAT]()
        t_second = time.perf_counter() - t0
        tris = sum(h.GetPolyData().GetNumberOfCells() for h in heavy)
        lines.append(f"INFO: hit.lookat timing, 20 models / {tris} triangles: first {t_first * 1000:.1f} ms, "
                     f"second (unchanged) {t_second * 1000:.1f} ms, ratio {t_first / max(t_second, 1e-9):.1f}")
        ok &= check("heavy scene hit lands on the model", np.allclose(hit1, (-216, 396, 0), atol=0.5)
                    and np.allclose(hit1, hit2), f"{hit1} {hit2}")
        ok &= check("second unchanged hit.lookat is at least 5x faster than the first", t_second * 5 <= t_first,
                    f"{t_first * 1000:.1f} ms vs {t_second * 1000:.1f} ms")
        heavy[7].GetPolyData().GetPoints().SetPoint(0, 0.0, 0.0, 0.0)  # changed data must rebuild, not serve a stale locator
        heavy[7].GetPolyData().Modified()
        hit3 = get[nl.HIT_LOOKAT]()
        ok &= check("changed polydata still hit after cache invalidation", hit3 is not None)
        for hn in heavy:
            slicer.mrmlScene.RemoveNode(hn)
        slicer.app.processEvents()
        put[nl.PIVOT_POSITION]((1.0, 2.0, 3.0))
        ok &= check("pivot stored", tuple(get[nl.PIVOT_POSITION]()) == (1.0, 2.0, 3.0))

        # the tables are accepted by a Connection (no driver, no navlib connection)
        conn = nl.Connection("(self-test, no driver)", bridge.getters(), bridge.setters(), None)
        ok &= check("Connection builds from the bridge tables", conn.accessors is not None)
        conn.close()

        # layout without a 3D view: Slicer keeps the hidden widget alive, so the bridge either still answers or
        # raises NoData; it never raises anything else (the controller decides by visibility)
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        slicer.app.processEvents()
        try:
            get[nl.VIEW_AFFINE]()
            outcome = True
        except nl.NoData:
            outcome = True
        except Exception:
            outcome = False
        ok &= check("layout without 3D view: getter answers or raises NoData", outcome,
                    f"widget() is {'None' if bridge.widget() is None else 'kept (hidden)'}")
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        slicer.app.processEvents()
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
