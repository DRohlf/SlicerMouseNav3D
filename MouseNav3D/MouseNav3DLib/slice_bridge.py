"""Describes one Slicer slice view to the navlib: property getters/setters, no navlib connection of its own.

Same shape as `View3DBridge` (getters/setters/widget/render/set_motion/release_motion). slicer is imported inside
functions only; the widget, node and logic are fetched on every call and never kept.

A slice view is reported as a perspective camera (the driver turns push/pull of an orthographic view into zoom and
never moves the camera along the normal): it sits CAMERA_DISTANCE mm in front of the slice on the +normal side and
looks at the slice centre; `view.fov` matches the slice's field-of-view height at that distance. The driver's pan in
the slice plane moves the slice centre in-plane; its camera motion along the normal accumulates and pages through
whole planes of the volume's slice spacing. `view.extents` is readable but writes are ignored: zoom stays on Slicer's
own mouse. Rotation in a written affine is ignored. Only slice position and field of view
change: never layers, visibility or other scene content.
"""
import math

import numpy as np

from . import camera_math as cm
from . import navlib_ctypes as nl

# mm from the slice plane to the reported camera and to the pivot (the slice centre). In a perspective view the driver
# scales its translation speed with the distance to the pivot, so this sets how fast a push pages and how fast a pan
# moves. 100 mm is a default that felt right on hardware; it is not a proven equivalence between pan speed and
# paging speed. Adjust the feel with the speed setting in 3Dconnexion's own app.
CAMERA_DISTANCE = 100.0
DEPTH = 1e8  # depth half-extent reported to the driver
DEFAULT_SPACING = 1.0  # mm per plane when no volume is shown


def step_planes(carry, spacing):
    """(planes, remainder): the whole planes of `spacing` contained in `carry` (toward zero) and what is left."""
    try:
        spacing = float(spacing)
    except (TypeError, ValueError):
        spacing = DEFAULT_SPACING
    if not (math.isfinite(spacing) and spacing > 0.0):
        spacing = DEFAULT_SPACING
    n = int(math.floor(abs(carry) / spacing + 1e-6))
    planes = n if carry >= 0 else -n
    return planes, carry - planes * spacing


class SliceBridge:
    def __init__(self, name):
        self.name = str(name)
        self._carry = 0.0  # motion along the normal not yet worth a whole plane (mm)
        self._moving = False

    # --- access to the live view -----------------------------------------------------------------------------
    def widget(self):
        """The qMRMLSliceWidget with this name, or None if it no longer exists."""
        try:
            import slicer
            manager = slicer.app.layoutManager()
            if manager is None:
                return None
            w = manager.sliceWidget(self.name)
            if w is None:
                return None
            w.sliceView()  # raises RuntimeError if the C++ object has been deleted
            return w
        except (RuntimeError, ValueError, AttributeError, IndexError):
            return None

    def _widget(self):
        w = self.widget()
        if w is None:
            raise nl.NoData("slice view is gone")
        return w

    def _node(self):
        node = self._widget().mrmlSliceNode()
        if node is None:
            raise nl.NoData("no slice node")
        return node

    def _logic(self):
        logic = self._widget().sliceLogic()
        if logic is None:
            raise nl.NoData("no slice logic")
        return logic

    def render(self):
        w = self.widget()
        if w is not None:
            w.sliceView().forceRender()

    # --- geometry --------------------------------------------------------------------------------------------
    @staticmethod
    def _basis(node):
        """Unit slice x, y and normal (RAS) from SliceToRAS."""
        m = node.GetSliceToRAS()
        cols = []
        for c in range(3):
            v = np.array([m.GetElement(i, c) for i in range(3)], dtype=float)
            length = np.linalg.norm(v)
            cols.append(v / length if length > 1e-12 else np.eye(3)[c])
        return cols[0], cols[1], cols[2]

    @staticmethod
    def _centre(node):
        """RAS position of the middle of the view, on the slice plane."""
        dims = node.GetDimensions()
        p = node.GetXYToRAS().MultiplyPoint([dims[0] / 2.0, dims[1] / 2.0, 0.0, 1.0])
        return np.array(p[:3], dtype=float)

    @staticmethod
    def _shift(node, delta):
        """Translate the slice in RAS by `delta` (in-plane only, by the caller's construction): the plane and the
        orientation stay, only SliceToRAS' translation changes."""
        m = node.GetSliceToRAS()
        for i in range(3):
            m.SetElement(i, 3, m.GetElement(i, 3) + float(delta[i]))
        node.UpdateMatrices()

    @staticmethod
    def _volume_shown(logic):
        composite = logic.GetSliceCompositeNode()
        return composite is not None and any(
            i for i in (composite.GetBackgroundVolumeID(), composite.GetForegroundVolumeID(),
                        composite.GetLabelVolumeID()))

    def _spacing(self, logic):
        """Slice spacing along the normal of the lowest-spacing shown volume; DEFAULT_SPACING when none is shown."""
        try:
            if self._volume_shown(logic):
                value = float(logic.GetLowestVolumeSliceSpacing()[2])
                if math.isfinite(value) and value > 0.0:
                    return value
        except (TypeError, ValueError, IndexError, AttributeError, RuntimeError):
            pass
        return DEFAULT_SPACING

    def _model_bounds(self):
        """Union of the RAS bounds of the volumes shown in this view; an invalid box (so the unit box) when none."""
        node = self._node()
        scene = node.GetScene()
        composite = self._logic().GetSliceCompositeNode()
        boxes, seen = [], set()
        if scene is not None and composite is not None:
            for volume_id in (composite.GetBackgroundVolumeID(), composite.GetForegroundVolumeID(),
                              composite.GetLabelVolumeID()):
                if not volume_id or volume_id in seen:
                    continue
                seen.add(volume_id)
                volume = scene.GetNodeByID(volume_id)
                if volume is None or not hasattr(volume, "GetRASBounds"):
                    continue
                b = [0.0] * 6
                volume.GetRASBounds(b)
                if all(math.isfinite(c) for c in b) and b[0] <= b[1] and b[2] <= b[3] and b[4] <= b[5]:
                    boxes.append(b)
        if not boxes:
            return np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        a = np.array(boxes, dtype=float)
        return np.array([a[:, 0].min(), a[:, 1].max(), a[:, 2].min(), a[:, 3].max(), a[:, 4].min(), a[:, 5].max()])

    # --- getters ---------------------------------------------------------------------------------------------
    def _get_affine(self):
        node = self._node()
        x, y, n = self._basis(node)
        affine = np.eye(4)
        affine[:3, 0], affine[:3, 1], affine[:3, 2] = x, y, n
        affine[:3, 3] = self._centre(node) + CAMERA_DISTANCE * n
        return cm.to_navlib(affine)

    def _get_extents(self):
        fov = self._node().GetFieldOfView()
        return ((-0.5 * fov[0], -0.5 * fov[1], -DEPTH), (0.5 * fov[0], 0.5 * fov[1], DEPTH))

    def _get_fov(self):
        """Vertical field of view of a perspective camera CAMERA_DISTANCE from the slice that sees the whole view."""
        half_h = 0.5 * float(self._node().GetFieldOfView()[1])
        return 2.0 * math.atan2(half_h, CAMERA_DISTANCE)

    def _get_model_extents(self):
        lo, hi = cm.safe_extents(self._model_bounds())
        return (tuple(float(c) for c in lo), tuple(float(c) for c in hi))

    def _get_pivot(self):
        return tuple(float(c) for c in self._centre(self._node()))

    @staticmethod
    def _get_lookat():
        raise nl.NoData("hit testing is not supported on slice views")

    def getters(self):
        return {
            nl.VIEW_AFFINE: (nl.MATRIX, self._get_affine),
            nl.VIEW_EXTENTS: (nl.BOX, self._get_extents),
            nl.VIEW_FOV: (nl.FLOAT, self._get_fov),
            nl.VIEW_PERSPECTIVE: (nl.BOOL, lambda: True),
            nl.VIEW_ROTATABLE: (nl.BOOL, lambda: False),
            nl.VIEW_FOCUS_DISTANCE: (nl.FLOAT, lambda: CAMERA_DISTANCE),
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
        """Pan and page from the written affine's translation relative to the current one; rotation is ignored."""
        node = self._node()
        logic = self._logic()
        new = cm.from_navlib(m16)[:3, 3]
        if not np.all(np.isfinite(new)):
            return
        x, y, n = self._basis(node)
        delta = new - (self._centre(node) + CAMERA_DISTANCE * n)
        dx, dy, dn = float(np.dot(delta, x)), float(np.dot(delta, y)), float(np.dot(delta, n))
        planes, self._carry = step_planes(self._carry + dn, self._spacing(logic))
        was = node.StartModify()
        try:
            if dx or dy:
                self._shift(node, dx * x + dy * y)
            if planes:
                logic.SetSliceOffset(logic.GetSliceOffset() + planes * self._spacing(logic))
                if self._volume_shown(logic):  # without a volume the snap would jump to an arbitrary grid
                    logic.SnapSliceOffsetToIJK()
        finally:
            node.EndModify(was)

    def _ignored(self, _value):
        """Pivot, hit-test and extents setters: accepted, no effect on a slice view."""

    def _set_motion(self, moving):
        self._moving = bool(moving)
        if not moving:
            self._carry = 0.0
            self.render()

    def set_motion(self, moving):
        """Start or end a motion (the controller uses it when the target changes mid-motion)."""
        self._set_motion(moving)

    def release_motion(self):
        """End a motion this bridge started. Safe when the view is gone; never raises."""
        self._carry = 0.0
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
            nl.VIEW_EXTENTS: self._ignored,  # zoom stays on Slicer's mouse
            nl.PIVOT_POSITION: self._ignored,
            nl.PIVOT_VISIBLE: self._ignored,
            nl.HIT_LOOKFROM: self._ignored,
            nl.HIT_DIRECTION: self._ignored,
            nl.HIT_APERTURE: self._ignored,
            nl.HIT_SELECTION_ONLY: self._ignored,
            nl.MOTION: self._set_motion,
            nl.TRANSACTION: self._set_transaction,
        }
