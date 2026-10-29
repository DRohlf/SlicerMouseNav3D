"""Describes one Slicer 3D view to the navlib: property getters/setters, no navlib connection of its own.

slicer, qt and vtk are imported inside functions only, so the module imports under plain Python. The widget,
renderer and camera are fetched on every call and never kept, so a layout change cannot leave a dangling reference.
Cameras are modified without rendering; one render happens when the driver ends a frame (`transaction` 0).
"""
import math

import numpy as np

from . import camera_math as cm
from . import navlib_ctypes as nl

DEFAULT_INTERACTIVE_RATE = 15.0
DEFAULT_STILL_RATE = 0.0001
DEPTH = 1e8  # parallel projection: depth half-extent reported to the driver


class View3DBridge:
    def __init__(self, view_index):
        self.view_index = int(view_index)
        self._pivot = None
        self._pivot_visible = False
        self._lookfrom = None
        self._direction = None
        self._aperture = 0.0
        self._selection_only = False
        self._moving = False
        self._classified = {}  # id(prop) -> (prop, pickable flag, is decoration); prop is held so the id stays valid
        self._locators = {}  # id(prop) -> (prop, polydata, polydata MTime, matrix values, matrix, inverse, locator)

    # --- access to the live view -----------------------------------------------------------------------------
    def widget(self):
        """The qMRMLThreeDWidget at this layout index, or None if it no longer exists."""
        try:
            import slicer
            manager = slicer.app.layoutManager()
            if manager is None:
                return None
            w = manager.threeDWidget(self.view_index)
            if w is None:
                return None
            w.threeDView()  # raises RuntimeError if the C++ object has been deleted
            return w
        except (RuntimeError, ValueError, AttributeError, IndexError):
            return None

    def _view(self):
        w = self.widget()
        if w is None:
            raise nl.NoData("3D view is gone")
        return w.threeDView()

    def _renderer(self):
        r = self._view().renderWindow().GetRenderers().GetFirstRenderer()
        if r is None:
            raise nl.NoData("no renderer")
        return r

    def _camera(self):
        return self._renderer().GetActiveCamera()

    def render(self):
        w = self.widget()
        if w is not None:
            w.threeDView().forceRender()

    # --- helpers ---------------------------------------------------------------------------------------------
    def _aspect(self):
        w, h = self._view().renderWindow().GetSize()
        return w / h if w > 0 and h > 0 else 1.0

    def _is_decoration(self, prop):
        """Cached `_classify`: recomputed only when the prop's Pickable flag changes (no pipeline Update per call)."""
        entry = self._classified.get(id(prop))
        pickable = bool(prop.GetPickable())
        if entry is None or entry[0] is not prop or entry[1] != pickable:
            entry = (prop, pickable, self._classify(prop))
            self._classified[id(prop)] = entry
        return entry[2]

    @staticmethod
    def _classify(prop):
        """True for Slicer's own view decorations: the 3D bounding box outline and the axis labels (and any
        orientation-marker or ruler prop that shares the renderer).

        Slicer's vtkMRMLThreeDViewDisplayableManager creates them non-pickable: the labels as vtkFollower text,
        the box as a line-only (outline) vtkActor. Scene content (models, segmentations, volume renderings) is
        pickable and never a follower or an outline. Tested against Slicer 5.12.4; it holds whether the user shows
        or hides the box and labels, because hidden props are skipped for being invisible anyway.
        """
        import vtk
        if isinstance(prop, (vtk.vtkAnnotatedCubeActor, vtk.vtkAxesActor, vtk.vtkCubeAxesActor, vtk.vtkCaptionActor2D)):
            return True
        if prop.GetPickable():
            return False
        if isinstance(prop, vtk.vtkFollower):
            return True
        if isinstance(prop, vtk.vtkActor):
            mapper = prop.GetMapper()
            if mapper is not None and mapper.GetInputAlgorithm() is not None:
                mapper.GetInputAlgorithm().Update()
                poly = mapper.GetInput()
                if isinstance(poly, vtk.vtkPolyData):
                    return (poly.GetLines().GetNumberOfCells() > 0 and poly.GetPolys().GetNumberOfCells() == 0
                            and poly.GetStrips().GetNumberOfCells() == 0)
        return False

    def _data_props(self):
        """The visible props that show scene content: everything in the main renderer that has bounds, is visible
        and is not a Slicer view decoration. The one rule behind model.extents, the default pivot and hit tests."""
        found = []
        props = self._renderer().GetViewProps()
        props.InitTraversal()
        seen = set()
        for _ in range(props.GetNumberOfItems()):
            prop = props.GetNextProp()
            seen.add(id(prop))
            if not prop.GetVisibility() or self._is_decoration(prop):
                continue
            b = prop.GetBounds()
            if b is None or not all(math.isfinite(c) for c in b) or b[0] > b[1] or b[2] > b[3] or b[4] > b[5]:
                continue
            found.append(prop)
        for key in [k for k in self._classified if k not in seen]:
            del self._classified[key]  # props that left the renderer
        return found

    def _model_bounds(self):
        """Union of the bounds of the visible data props; invalid (so the unit box) when there are none."""
        boxes = [prop.GetBounds() for prop in self._data_props()]
        if not boxes:
            return np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        b = np.array(boxes, dtype=float)
        return np.array([b[:, 0].min(), b[:, 1].max(), b[:, 2].min(), b[:, 3].max(), b[:, 4].min(), b[:, 5].max()])

    def _model_extents(self):
        lo, hi = cm.safe_extents(self._model_bounds())
        return lo, hi

    # --- getters ---------------------------------------------------------------------------------------------
    def _get_affine(self):
        cam = self._camera()
        return cm.to_navlib(cm.camera_to_affine(cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp()))

    def _get_extents(self):
        cam = self._camera()
        if not cam.GetParallelProjection():
            raise nl.NoData("perspective projection")
        half_h = cam.GetParallelScale()
        half_w = half_h * self._aspect()
        return ((-half_w, -half_h, -DEPTH), (half_w, half_h, DEPTH))

    def _get_fov(self):
        return math.radians(self._camera().GetViewAngle())

    def _get_perspective(self):
        return not self._camera().GetParallelProjection()

    def _get_focus_distance(self):
        return self._camera().GetDistance()

    def _get_model_extents(self):
        lo, hi = self._model_extents()
        return (tuple(float(c) for c in lo), tuple(float(c) for c in hi))

    def _get_pivot(self):
        if self._pivot is not None:
            return self._pivot
        lo, hi = self._model_extents()
        return tuple(float(c) for c in 0.5 * (lo + hi))

    def _get_lookat(self):
        if self._lookfrom is None or self._direction is None:
            raise nl.NoData("no hit-test ray")
        hit = self._pick(self._lookfrom, self._direction, self._aperture)
        if hit is None:
            raise nl.NoData("nothing hit")
        return hit

    def _pick(self, origin, direction, aperture):
        """Nearest hit of a visible data prop along the ray (a ring of rays covers the aperture), or None."""
        d = np.asarray(direction, dtype=float)
        n = np.linalg.norm(d)
        if n < 1e-12:
            return None
        d /= n
        o = np.asarray(origin, dtype=float)
        helper = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(d, helper)
        u /= np.linalg.norm(u)
        v = np.cross(d, u)
        r = 0.5 * float(aperture)
        offsets = [np.zeros(3)]
        if r > 0:
            offsets += [r * (math.cos(a) * u + math.sin(a) * v) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
        props = self._polydata_locators()
        best, best_t = None, None
        for off in offsets:
            start = o + off
            for matrix, inverse, locator in props:
                hit = self._intersect(start, d, matrix, inverse, locator)
                if hit is not None:
                    t = float(np.dot(hit - start, d))
                    if t >= 0 and (best_t is None or t < best_t):
                        best, best_t = hit, t
        return None if best is None else tuple(float(c) for c in best)

    def _polydata_locators(self):
        """(matrix, inverse matrix, cell locator) for each visible data actor with polygonal input, whether or not
        its Pickable flag is set (decorations are excluded by `_data_props`).

        Own ray casting instead of vtkPicker.Pick3DRay: that clips the ray to the camera's clipping range, which
        depends on where the camera currently is.
        """
        import vtk
        found, kept = [], {}
        for prop in self._data_props():
            if not isinstance(prop, vtk.vtkActor):
                continue
            mapper = prop.GetMapper()
            if mapper is None or mapper.GetInputAlgorithm() is None:
                continue
            mapper.GetInputAlgorithm().Update()  # a no-op when the pipeline is current
            poly = mapper.GetInput()
            if not isinstance(poly, vtk.vtkPolyData) or poly.GetNumberOfCells() == 0:
                continue
            values = tuple(prop.GetMatrix().GetElement(i, j) for i in range(4) for j in range(4))
            entry = self._locators.get(id(prop))
            if (entry is None or entry[0] is not prop or entry[1] is not poly or entry[2] != poly.GetMTime()
                    or entry[3] != values):
                matrix = vtk.vtkMatrix4x4()
                matrix.DeepCopy(prop.GetMatrix())
                inverse = vtk.vtkMatrix4x4()
                vtk.vtkMatrix4x4.Invert(matrix, inverse)
                locator = vtk.vtkStaticCellLocator()
                locator.SetDataSet(poly)
                locator.BuildLocator()
                entry = (prop, poly, poly.GetMTime(), values, matrix, inverse, locator)
            kept[id(prop)] = entry
            found.append((entry[4], entry[5], entry[6]))
        self._locators = kept  # actors no longer present are dropped
        return found

    @staticmethod
    def _intersect(start, direction, matrix, inverse, locator):
        """Nearest intersection (world coordinates) of the ray with one actor's locator, or None."""
        import vtk
        far = 1e7
        p1 = inverse.MultiplyPoint([*start, 1.0])[:3]
        p2 = inverse.MultiplyPoint([*(start + far * direction), 1.0])[:3]
        points, cells = vtk.vtkPoints(), vtk.vtkIdList()
        if not locator.IntersectWithLine(p1, p2, 0.0, points, cells) or points.GetNumberOfPoints() == 0:
            return None
        best, best_t = None, None
        for i in range(points.GetNumberOfPoints()):
            world = np.array(matrix.MultiplyPoint([*points.GetPoint(i), 1.0])[:3])
            t = float(np.dot(world - start, direction))
            if best_t is None or t < best_t:
                best, best_t = world, t
        return best

    def getters(self):
        return {
            nl.VIEW_AFFINE: (nl.MATRIX, self._get_affine),
            nl.VIEW_EXTENTS: (nl.BOX, self._get_extents),
            nl.VIEW_FOV: (nl.FLOAT, self._get_fov),
            nl.VIEW_PERSPECTIVE: (nl.BOOL, self._get_perspective),
            nl.VIEW_ROTATABLE: (nl.BOOL, lambda: True),
            nl.VIEW_FOCUS_DISTANCE: (nl.FLOAT, self._get_focus_distance),
            nl.MODEL_EXTENTS: (nl.BOX, self._get_model_extents),
            nl.COORDINATE_SYSTEM: (nl.MATRIX, lambda: cm.COORDINATE_SYSTEM),
            nl.VIEWS_FRONT: (nl.MATRIX, lambda: cm.FRONT_VIEW),
            nl.MODEL_UNITS_TO_METERS: (nl.FLOAT, lambda: 0.001),
            nl.PIVOT_POSITION: (nl.POINT, self._get_pivot),
            nl.PIVOT_USER: (nl.BOOL, lambda: False),
            nl.HIT_LOOKAT: (nl.POINT, self._get_lookat),
            nl.FRAME_TIMING_SOURCE: (nl.LONG, lambda: 0),
        }

    # --- setters ---------------------------------------------------------------------------------------------
    def _set_affine(self, m16):
        cam = self._camera()
        distance = cam.GetDistance()
        position, focal, up = cm.affine_to_camera(cm.from_navlib(m16), distance)
        cam.SetPosition(*position)
        cam.SetFocalPoint(*focal)
        cam.SetViewUp(*up)
        cam.OrthogonalizeViewUp()
        self._renderer().ResetCameraClippingRange()

    def _set_extents(self, box):
        cam = self._camera()
        if not cam.GetParallelProjection():
            return
        lo, hi = box
        half_h = 0.5 * (hi[1] - lo[1])
        if half_h > 0 and math.isfinite(half_h):
            cam.SetParallelScale(half_h)
            self._renderer().ResetCameraClippingRange()

    def _set_fov(self, radians):
        deg = math.degrees(radians)
        if 0.0 < deg < 180.0:
            self._camera().SetViewAngle(deg)

    def _set_pivot(self, p):
        self._pivot = tuple(float(c) for c in p)

    def _set_pivot_visible(self, v):
        self._pivot_visible = bool(v)

    def _set_lookfrom(self, p):
        self._lookfrom = tuple(float(c) for c in p)

    def _set_direction(self, v):
        self._direction = tuple(float(c) for c in v)

    def _set_aperture(self, a):
        self._aperture = float(a)

    def _set_selection_only(self, v):
        self._selection_only = bool(v)

    def _set_motion(self, moving):
        view = self._view()
        window = view.renderWindow()
        interactor = view.interactor()
        self._moving = bool(moving)
        if moving:
            window.SetDesiredUpdateRate(interactor.GetDesiredUpdateRate() if interactor else DEFAULT_INTERACTIVE_RATE)
        else:
            window.SetDesiredUpdateRate(interactor.GetStillUpdateRate() if interactor else DEFAULT_STILL_RATE)
            self.render()

    def set_motion(self, moving):
        """Interactive (True) or still (False) update rate; the controller uses it when the target changes mid-motion."""
        self._set_motion(moving)

    def release_motion(self):
        """Restore the still update rate if this bridge raised it. Safe when the view is gone; never raises."""
        if not self._moving:
            return
        try:
            self._set_motion(False)
        except Exception:  # noqa: BLE001 - view deleted or Slicer closing
            pass
        self._moving = False

    def _set_transaction(self, value):
        if int(value) == 0:
            self.render()

    def setters(self):
        return {
            nl.VIEW_AFFINE: self._set_affine,
            nl.VIEW_EXTENTS: self._set_extents,
            nl.VIEW_FOV: self._set_fov,
            nl.PIVOT_POSITION: self._set_pivot,
            nl.PIVOT_VISIBLE: self._set_pivot_visible,
            nl.HIT_LOOKFROM: self._set_lookfrom,
            nl.HIT_DIRECTION: self._set_direction,
            nl.HIT_APERTURE: self._set_aperture,
            nl.HIT_SELECTION_ONLY: self._set_selection_only,
            nl.MOTION: self._set_motion,
            nl.TRANSACTION: self._set_transaction,
        }
