"""Applies the fallback integrator's motion to the view under the mouse. Needs Slicer; slicer and qt are imported inside
functions only.

An 8 ms precise `QTimer` calls `tick()`: it takes the integrator's displacement since the last tick (one report-time
integral, see motion.py) and moves the target view by exactly that, so the motion follows the device's own clock rather
than the timer's. The 3D view renders once per tick (scheduleRender coalesces); while the cap moves the render window
is on its interactive update rate (reported through `on_motion`), and back to still quality after the release.

  3D view     object mode, the scene moves as the cap: pan (tx, ty), dolly (tz: pull = closer), turn about the
              camera's focal point (rx, ry, rz; driver mode turns about the centre of the visible data instead);
              rotation lock leaves only pan and dolly.
  slice view  as in driver mode: push/pull (tz) pages through whole image planes, faster the further you push (push
              = toward -normal, pull = toward +normal); pan (tx, ty: the picture moves with the cap); and, unlike
              driver mode, zoom by twist (ry: anticlockwise seen from above = in).
  buttons     1 = fit the view under the mouse; 2 = rotation lock (3D), press again to free.

Nothing moves while Slicer is not the active application: ticks then discard the motion and the button presses.
The speeds (full deflection, speed 1) are ported from the author's earlier reader.
"""
import logging
import math
import threading
import time

import numpy as np

from .. import slice_bridge

_log = logging.getLogger("MouseNav3D")

ROT_DEG_S = 120.0                   # full deflection, speed 1
PAN_FRAC_S = 0.8                    # of the view's width (3D: of the focal distance) per second
DOLLY_E_S = 1.2                     # zoom factor e^(1.2 s^-1) at full deflection
LEVEL_PLANES_S = 30.0               # image planes per second at full push or pull
ZOOM_E_S = 1.2
TICK_MS = 8


def _rotate(v, axis, ang):
    """Rodrigues: v turned by ang (radians) about the unit axis."""
    k = axis / (np.linalg.norm(axis) or 1.0)
    return v * math.cos(ang) + np.cross(k, v) * math.sin(ang) + k * np.dot(k, v) * (1 - math.cos(ang))


class Navigator:
    def __init__(self, integrator, settings=None, target=None, on_motion=None, on_change=None, is_active=None):
        """`target()` returns the bridge to move (View3DBridge or SliceBridge) or None; `on_motion(bool)` is told when
        motion starts and ends; `on_change()` after a button changed something (rotation lock); `is_active()` says
        whether Slicer is the active application (default: controller.app_is_active, the check the controller uses)."""
        self.integrator = integrator
        self.settings = settings if settings is not None else integrator.settings
        self.rotation_lock = False
        self.target = target or (lambda: None)
        self.on_motion = on_motion
        self.on_change = on_change
        self.is_active = is_active or self._app_active
        self.moving = False
        self.timer = None
        self._tick_slot = None
        self._buttons = set()
        self._presses = []
        self._lock = threading.Lock()
        self._carry_mm = 0.0                       # push/pull not yet worth a whole image plane
        self._carry_view = None
        self.last_axes = {}                        # newest raw deflections, for the panel's live line
        self._tick_error_logged = False

    # --- lifecycle --------------------------------------------------------------------------------------------
    def start(self):
        import qt
        if self.timer is None:
            self.timer = qt.QTimer()
            self.timer.setTimerType(qt.Qt.PreciseTimer)
            self.timer.setInterval(TICK_MS)
            self._tick_slot = self.tick
            self.timer.connect("timeout()", self._tick_slot)
        self.integrator.reset()
        self.timer.start()

    def stop(self):
        timer, self.timer = self.timer, None
        if timer is not None:
            try:
                timer.stop()
                timer.disconnect("timeout()", self._tick_slot)
            except Exception:  # noqa: BLE001
                pass
        self._tick_slot = None
        self._set_moving(False)
        self.integrator.reset()

    @staticmethod
    def _app_active():
        """The controller's shared activity check (controller.app_is_active), False if it fails."""
        try:
            from ..controller import app_is_active
            return app_is_active()
        except Exception:  # noqa: BLE001
            return False

    # --- from the reader thread ---------------------------------------------------------------------------------
    def handle_report(self, t, axes, buttons):
        """The readers' on_report: axes go to the integrator, button changes are queued for the next tick."""
        if axes:
            self.last_axes = dict(axes)
            self.integrator.feed(t, axes)
        if buttons is not None:
            new = set(buttons)
            with self._lock:
                self._presses += sorted(new - self._buttons)
                self._buttons = new

    def _take_presses(self):
        with self._lock:
            presses, self._presses = self._presses, []
        return presses

    # --- one frame ----------------------------------------------------------------------------------------------
    def tick(self, now=None):
        """One frame (the 8 ms timer's slot). Never raises: the first failure is logged, later ones are not, and the
        timer keeps running (the next frame may well work, e.g. once a deleted view is retargeted)."""
        try:
            self._frame(now)
        except Exception:  # noqa: BLE001 - a timer callback must not spam
            if not self._tick_error_logged:
                self._tick_error_logged = True
                _log.exception("fallback frame failed")

    def _frame(self, now=None):
        now = time.monotonic() if now is None else now
        presses = self._take_presses()
        d = self.integrator.take(now)
        if not self.is_active():
            self._set_moving(False)                # another program is in front: nothing moves, nothing is saved up
            return
        for b in presses:
            self.button(b)
        if any(d.values()):
            self._set_moving(True)
            self.apply(d)
        if self.moving and self.integrator.idle:       # released: the last displacement is in, back to still quality
            self._set_moving(False)

    def _set_moving(self, moving):
        if moving == self.moving:
            return
        self.moving = moving
        if self.on_motion is not None:
            try:
                self.on_motion(moving)
            except Exception:  # noqa: BLE001 - the view may be gone
                pass

    # --- motion -------------------------------------------------------------------------------------------------
    def apply(self, d, bridge=None):
        """Move the view (the target unless given) by the integrated displacement d ({axis: deflection-seconds})."""
        bridge = bridge if bridge is not None else self.target()
        if bridge is None:
            return None
        if hasattr(bridge, "view_index"):
            self._move3d(bridge, d)
        else:
            self._move_slice(bridge, d)
        return bridge

    def _move3d(self, bridge, d):
        w = bridge.widget()
        if w is None:
            return
        view = w.threeDView()
        ren = view.renderWindow().GetRenderers().GetFirstRenderer()
        cam = ren.GetActiveCamera()
        pos, foc, up = (np.array(cam.GetPosition()), np.array(cam.GetFocalPoint()), np.array(cam.GetViewUp()))
        dop = foc - pos
        dist = float(np.linalg.norm(dop)) or 1.0
        dop /= dist
        right = np.cross(dop, up)
        right /= np.linalg.norm(right) or 1.0
        up = np.cross(right, dop)
        toward = -dop
        # pan: the scene moves with the cap, so the camera moves the other way
        shift = -(d["tx"] * right + d["ty"] * up) * (PAN_FRAC_S * dist)
        pos, foc = pos + shift, foc + shift
        # dolly: pulling the cap toward you brings the scene closer
        pos = foc - (foc - pos) / math.exp(DOLLY_E_S * d["tz"])
        if not self.rotation_lock:
            w_ = d["rx"] * right + d["ry"] * up + d["rz"] * toward
            n = float(np.linalg.norm(w_))
            if n > 0.0:
                ang = math.radians(ROT_DEG_S) * n
                axis = w_ / n
                pos = foc + _rotate(pos - foc, axis, -ang)           # the scene turns as the cap: camera the other way
                up = _rotate(up, axis, -ang)
        cam.SetFocalPoint(*foc)
        cam.SetPosition(*pos)
        cam.SetViewUp(*up)
        cam.OrthogonalizeViewUp()
        ren.ResetCameraClippingRange()
        view.scheduleRender()

    def _move_slice(self, bridge, d):
        w = bridge.widget()
        if w is None:
            return
        node, logic = w.mrmlSliceNode(), w.sliceLogic()
        if self._carry_view != bridge.name:
            self._carry_view, self._carry_mm = bridge.name, 0.0
        fov = np.array(node.GetFieldOfView())
        # pan: the picture moves with the cap (slide right = right, lift = up), as in driver mode
        dx = PAN_FRAC_S * np.array([d["tx"] * fov[0], d["ty"] * fov[1]])
        if np.any(dx):
            x, y, _n = bridge._basis(node)
            bridge._shift(node, -(dx[0] * x + dx[1] * y))
        # zoom: twist anticlockwise (seen from above) zooms in
        if d["ry"]:
            f = math.exp(-ZOOM_E_S * d["ry"])
            node.SetFieldOfView(fov[0] * f, fov[1] * f, fov[2])
        # page: push/pull through whole image planes, faster the further you push, in driver mode's direction
        # (slice_bridge: the camera sits on the +normal side, so pushing into the screen moves toward -normal and
        # pulling toward +normal; tz is "toward you", so the offset changes with +tz)
        if d["tz"]:
            spacing = bridge._spacing(logic)
            self._carry_mm += LEVEL_PLANES_S * d["tz"] * spacing
            planes, self._carry_mm = slice_bridge.step_planes(self._carry_mm, spacing)
            if planes:
                logic.SetSliceOffset(logic.GetSliceOffset() + planes * spacing)
                if bridge._volume_shown(logic):
                    logic.SnapSliceOffsetToIJK()           # on an image plane, as the arrow keys leave it
        else:
            self._carry_mm = 0.0

    # --- buttons ------------------------------------------------------------------------------------------------
    def button(self, b):
        bridge = self.target()
        if b == 1 and bridge is not None:
            w = bridge.widget()
            if w is not None:
                if hasattr(bridge, "view_index"):
                    w.threeDView().resetFocalPoint()
                    w.threeDView().resetCamera()
                else:
                    w.sliceLogic().FitSliceToAll()
        elif b == 2:
            self.rotation_lock = not self.rotation_lock
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                pass
