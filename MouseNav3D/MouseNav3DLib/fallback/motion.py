"""Fallback motion: per-axis settings and report-time integration. Pure Python (no slicer, qt, vtk, numpy).

Axes are the 3D mouse's own frame, each -1..1 of full deflection: tx right, ty up (lift the cap), tz toward you (pull
the cap), rx tilt back (about right), ry spin (about up, anticlockwise seen from above), rz roll (about toward you).

`apply_settings` turns raw deflections into velocities (dead zone, per-axis reverse and sensitivity, overall speed;
linear, no response curve). `Integrator` turns the stream of timestamped device reports into displacement: the view
code calls `take(now)` once per frame and gets the integral of velocity since the last call.

Design of the Integrator (why the motion is even and stops at once):
  * Each report's velocity is held from the report's own timestamp to the next report's timestamp (or to `now` for the
    newest one), never from the moment a timer happened to run. A late or uneven frame therefore moves the view by the
    time that really elapsed at the velocity that really applied, and several reports inside one frame are each
    integrated over their own interval.
  * Velocity goes through a first-order filter (time constant SMOOTH_S) that softens report-to-report jitter. The
    filtered velocity is integrated in closed form over every interval, so the total does not depend on where the
    `take` calls fall.
  * A report that is inside the dead zone on every axis ends the motion at that report's time: the filter is reset to
    zero, so nothing is carried past a release. A cap that sends nothing for STALE_S counts as released at
    (last report + STALE_S).
  * Onset: when the cap leaves rest the filter starts at the first velocity instead of climbing from zero, so a steady
    push is integrated without losing the filter's time constant (the cap's own spring already ramps the reports).
"""
import threading
from collections import deque
from dataclasses import dataclass, field
from math import exp

AXES = ("tx", "ty", "tz", "rx", "ry", "rz")
SMOOTH_S = 0.03       # time constant of the velocity filter
STALE_S = 0.25        # no report for this long: the cap counts as released (a lost Bluetooth packet)
DEAD_ZONE = 0.04      # of full deflection: the cap at rest reads a few counts


@dataclass
class AxisSettings:
    reverse: dict = field(default_factory=dict)        # axis -> True to flip its sign
    sensitivity: dict = field(default_factory=dict)    # axis -> factor (default 1.0)
    speed: float = 1.0
    dead_zone: float = DEAD_ZONE


def apply_settings(raw, s):
    """{axis: velocity} for all six axes from raw deflections (missing axes are at rest). An axis whose |deflection| is
    inside the dead zone (edge included) is zero; otherwise deflection x sign x sensitivity x speed."""
    out = {}
    for k in AXES:
        v = float(raw.get(k, 0.0))
        if abs(v) <= s.dead_zone:
            out[k] = 0.0
            continue
        sign = -1.0 if s.reverse.get(k, False) else 1.0
        out[k] = v * sign * float(s.sensitivity.get(k, 1.0)) * s.speed
    return out


class Integrator:
    """feed(t, axes) from the reader thread, take(now) from the frame timer. Thread-safe. Times are one monotonic
    clock in seconds (time.monotonic())."""

    def __init__(self, settings=None):
        self.settings = settings if settings is not None else AxisSettings()
        self._lock = threading.Lock()
        self._queue = deque()          # (t, velocity tuple, moving) not yet reached by the cursor
        self._cursor = None            # time integrated up to
        self._smooth = (0.0,) * 6      # filtered velocity at the cursor
        self._target = (0.0,) * 6      # velocity of the newest applied report
        self._target_t = 0.0           # timestamp of that report (for the stale rule)
        self._moving = False

    # --- input ------------------------------------------------------------------------------------------------
    def feed(self, t, axes):
        """One device report: raw deflections {axis: -1..1} stamped with its arrival time."""
        vel = apply_settings(axes, self.settings)
        vec = tuple(vel[k] for k in AXES)
        moving = any(vec)
        with self._lock:
            self._queue.append((float(t), vec, moving))

    def reset(self):
        """Forget everything (motion that happened while nobody was listening)."""
        with self._lock:
            self._queue.clear()
            self._cursor = None
            self._smooth = self._target = (0.0,) * 6
            self._moving = False

    @property
    def idle(self):
        """True when nothing is moving and no report is waiting."""
        with self._lock:
            return not self._moving and not self._queue

    # --- output -----------------------------------------------------------------------------------------------
    def take(self, now):
        """{axis: integral of velocity} from the previous take (or the first report) to `now`."""
        out = [0.0] * 6
        with self._lock:
            now = float(now)
            if self._cursor is None:
                self._cursor = min(self._queue[0][0], now) if self._queue else now
            if now < self._cursor:
                return dict(zip(AXES, out))
            while True:
                nxt = self._queue[0][0] if self._queue and self._queue[0][0] <= now else None
                self._advance(now if nxt is None else max(nxt, self._cursor), out)
                if nxt is None:
                    break
                _t, vec, moving = self._queue.popleft()
                if moving and not self._moving:
                    self._smooth = vec                     # onset: start at the first velocity
                elif not moving:
                    self._smooth = (0.0,) * 6              # release: instant stop
                self._target, self._moving, self._target_t = vec, moving, self._cursor
        return dict(zip(AXES, out))

    def _advance(self, end, out):
        """Integrate the held velocity from the cursor to `end`, applying the stale rule on the way."""
        c = self._cursor
        while c < end:
            seg_end = end
            stale = False
            if self._moving:
                stale_at = self._target_t + STALE_S
                if stale_at <= end:
                    seg_end, stale = max(stale_at, c), True
            dt = seg_end - c
            if dt > 0.0 and self._moving:
                e = exp(-dt / SMOOTH_S)
                s0, v = self._smooth, self._target
                for i in range(6):
                    out[i] += v[i] * dt + (s0[i] - v[i]) * SMOOTH_S * (1.0 - e)
                self._smooth = tuple(v[i] + (s0[i] - v[i]) * e for i in range(6))
            c = seg_end
            if stale:
                self._target = self._smooth = (0.0,) * 6
                self._moving = False
        self._cursor = max(c, end)
