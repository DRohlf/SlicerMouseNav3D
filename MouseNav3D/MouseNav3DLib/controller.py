"""One navlib connection per Slicer session: view under the mouse, focus, lifecycle, mode choice.

slicer, qt and vtk are imported inside functions only.

The connection is created once, with accessors that delegate to `self.target`, the bridge of the view the pointer was
last over; retargeting never reconnects. A 3D view gets a `View3DBridge`, a slice view a `SliceBridge`; both kinds
are cached per view and dropped when their view disappears.

`recorder(kind, name, value)` is called for every driver callback ("get" with the value returned, None if the getter
had no data; "set" with the value the driver wrote); `callback_threads` collects the thread ids the callbacks ran on.
"""
import logging
import os
import threading
import time

from . import commands
from . import navlib_ctypes as nl

_log = logging.getLogger("MouseNav3D")

MODE_DRIVER = "driver"
MODE_FALLBACK = "fallback"
MODE_NO_DEVICE = "no device"

RETARGET_INTERVAL_MS = 50


def app_is_active():
    """True while Slicer is the active application (one of its windows has the keyboard focus). The one activity
    check shared by the controller (driver focus) and the fallback navigator (nothing moves otherwise). It raises if
    Slicer's application object is not reachable; Controller._app_is_active and Navigator._app_active are the
    never-raising wrappers."""
    import slicer
    return slicer.app.activeWindow() is not None


def force_fallback():
    """True when the environment variable MOUSENAV3D_FORCE_FALLBACK is "1": start() skips the driver and uses the
    built-in reader, so fallback mode can be tried on a machine that has the driver."""
    return os.environ.get("MOUSENAV3D_FORCE_FALLBACK", "").strip() == "1"


def normalize_limb_side(value):
    """"right" or "left" (any case, surrounding blanks ignored); anything else is "right"."""
    if isinstance(value, str) and value.strip().lower() in ("right", "left"):
        return value.strip().lower()
    return "right"


class Controller:
    def __init__(self, view_index=0, app_name="3D Mouse Navigation", recorder=None):
        self.view_index = int(view_index)
        self.app_name = app_name
        self.recorder = recorder
        self.mode = None
        self._status = "not started"
        self.callback_threads = set()
        self.main_thread = threading.get_ident()
        self.connection = None
        self._target = None
        self._bridges = {}  # 3D view index -> View3DBridge, kept alive per view (they cache locators)
        self._slice_bridges = {}  # slice view name -> SliceBridge
        self._tree_keep = None
        self.write_results = {}  # property -> result code of the activation writes
        self.limb_side = "right"  # "right" or "left"; read from settings in start()
        self._command_error_logged = False
        self._focus_error_logged = False
        self._tick_error_logged = False
        self._thread_error_logged = False
        self._device_present = None  # (time read, True/False/None) of the last device.present read, driver mode
        self._moving = False
        self._timer = None
        self._hooks_installed = False
        self._tick_slot = None
        self._state_slot = None
        self._quit_slot = None
        self.navigator = None  # the fallback Navigator, in fallback mode
        self.reader = None  # the fallback device reader, in fallback mode
        self._reader_factory = None  # tests: callable returning a reader (or None); default per platform
        self._fallback_reason = ""

    # --- status / target ---------------------------------------------------------------------------------------
    def status(self):
        if self.mode == MODE_FALLBACK and self.reader is not None:
            return self._fallback_status()
        if self.mode == MODE_DRIVER and self.connection is not None:
            present = self._read_device_present()
            if present is True:
                return "Connected to the 3Dconnexion driver; a 3D mouse is connected."
            if present is False:
                return "Connected to the 3Dconnexion driver; no 3D mouse is connected."
        return self._status

    def _read_device_present(self, max_age_s=1.0):
        """The driver's device.present (True/False), read at most once per max_age_s; None if it cannot be read (a
        driver or binding without it), in which case the status stays "Connected to the 3Dconnexion driver."."""
        now = time.monotonic()
        cached = self._device_present
        if cached is not None and now - cached[0] < max_age_s:
            return cached[1]
        try:
            value = bool(self.connection.read(nl.DEVICE_PRESENT, nl.BOOL))
        except Exception:  # noqa: BLE001 - NavlibError, a fake connection without read(), ...
            value = None
        self._device_present = (now, value)
        return value

    def _fallback_status(self):
        """Fallback state: device name(s) and battery when the reader exposes them, rotation lock."""
        reader = self.reader
        base = f"{self._fallback_reason} Using the built-in reader: ".lstrip()
        devices = list(dict.fromkeys(getattr(reader, "devices", None) or []))
        if not devices:
            error = getattr(reader, "error", "")
            return base + "looking for a 3D mouse ..." + (f" ({error})" if error else "")
        battery = getattr(reader, "battery", None)
        text = f"{base}{', '.join(devices)} connected"
        if battery is not None:
            text += f", battery {battery} %"
        if self.navigator is not None and self.navigator.rotation_lock:
            text += ", rotation locked"
        return text

    @property
    def target(self):
        """The bridge the accessors currently delegate to, or None."""
        return self._target

    # --- bridges -----------------------------------------------------------------------------------------------
    def _bridge3d(self, index):
        bridge = self._bridges.get(index)
        if bridge is None:
            from .view3d_bridge import View3DBridge
            bridge = self._bridges[index] = View3DBridge(index)
        return bridge

    def _bridge_for_slice(self, name):
        bridge = self._slice_bridges.get(name)
        if bridge is None:
            from .slice_bridge import SliceBridge
            bridge = self._slice_bridges[name] = SliceBridge(name)
        return bridge

    @staticmethod
    def _alive(bridge):
        try:
            return bridge.widget() is not None
        except Exception:  # noqa: BLE001
            return False

    def _initial_target(self):
        for index in (self.view_index, 0):
            bridge = self._bridge3d(index)
            if self._alive(bridge):
                return bridge
        return None

    def _init_target(self):
        self._set_target(self._initial_target(), announce=False)

    # --- driver callbacks ----------------------------------------------------------------------------------------
    def _record(self, kind, name, value):
        self.callback_threads.add(threading.get_ident())
        rec = self.recorder
        if rec is not None:
            try:
                rec(kind, name, value)
            except Exception:  # noqa: BLE001 - a recorder must never break the driver callback
                _log.exception("recorder failed")

    def _dispatch_get(self, name):
        target = self._target
        if target is None:
            raise nl.NoData("no target view")
        entry = target.getters().get(name)
        if entry is None:
            raise nl.NoData(f"{name} not provided by the current view")
        return entry[1]()

    def _dispatch_set(self, name, value):
        if name == nl.MOTION:
            self._moving = bool(value)
        target = self._target
        if target is None:
            return
        fn = target.setters().get(name)
        if fn is not None:
            fn(value)

    def _off_main_thread(self, name):
        """True (and logged once) when a driver callback arrives on a thread other than the one start() ran on. Slicer,
        Qt and VTK must only be used from the main thread; the callbacks were measured on the main thread on Windows
        only, so any other thread is refused rather than trusted."""
        if threading.get_ident() == self.main_thread:
            return False
        if not self._thread_error_logged:
            self._thread_error_logged = True
            _log.warning("navlib called %s on thread %s, not on Slicer's main thread; refused (NoData)", name,
                         threading.get_ident())
        return True

    def _wrap_getter(self, name, fn):
        def getter():
            if self._off_main_thread(name):
                self._record("get", name, None)
                raise nl.NoData("called off the main thread")
            try:
                value = fn()
            except nl.NoData:
                self._record("get", name, None)
                raise
            self._record("get", name, value)
            return value
        return getter

    def _wrap_setter(self, name, fn):
        def setter(value):
            self._record("set", name, value)
            if self._off_main_thread(name):
                raise nl.NoData("called off the main thread")
            fn(value)
        return setter

    def _on_active_command(self, command_id):
        """commands.activeCommand: the id of a pressed command, "" on release. Never raises into the driver."""
        if not command_id or command_id not in commands.COMMAND_IDS:
            _log.debug("activeCommand %r ignored", command_id)
            return
        try:
            index = getattr(self._target, "view_index", self.view_index)
            commands.run(command_id, index, self.limb_side)
        except Exception:  # noqa: BLE001 - must never unwind into the driver callback
            if not self._command_error_logged:
                self._command_error_logged = True
                _log.exception("command %s failed", command_id)

    def build_accessors(self):
        """(getters, setters) for the Connection: wrapped accessors that delegate to the current target.

        The names and types come from a 3D bridge (a pure object); a bridge for another view type must provide a
        subset with the same types."""
        from .view3d_bridge import View3DBridge
        proto = View3DBridge(0)
        getters = {}
        for name, (type_id, _fn) in proto.getters().items():
            getters[name] = (type_id, self._wrap_getter(name, lambda n=name: self._dispatch_get(n)))
        setters = {}
        for name in proto.setters():
            setters[name] = self._wrap_setter(name, lambda v, n=name: self._dispatch_set(n, v))
        setters[nl.COMMANDS_ACTIVE_COMMAND] = self._wrap_setter(nl.COMMANDS_ACTIVE_COMMAND, self._on_active_command)
        return getters, setters

    def build_setters(self):
        """The wrapped property setters (target delegates plus commands.activeCommand), without connecting."""
        return self.build_accessors()[1]

    # --- retarget ------------------------------------------------------------------------------------------------
    def _pointer_over(self, widget):
        try:
            return bool(widget.isVisible() and widget.underMouse())
        except Exception:  # noqa: BLE001 - deleted widget
            return False

    def _view_under_mouse(self):
        """("slice", name), ("3d", index) or None. Only the layout manager's current, visible widgets count: a hidden
        3D widget survives layouts without a 3D view."""
        import slicer
        manager = slicer.app.layoutManager()
        if manager is None:
            return None
        for name in manager.sliceViewNames():
            if self._pointer_over(manager.sliceWidget(name)):
                return ("slice", name)
        for index in range(int(manager.threeDViewCount)):
            if self._pointer_over(manager.threeDWidget(index)):
                return ("3d", index)
        return None

    def _retarget(self):
        """Move the target to the view under the mouse; keep it when the pointer is over no view; fall back to 3D view 0, else no target, when the current target's widget is gone."""
        if self.connection is None and self.navigator is None:
            return
        hit = self._view_under_mouse()
        candidate = None
        if hit is not None:
            candidate = self._bridge3d(hit[1]) if hit[0] == "3d" else self._bridge_for_slice(hit[1])
            if candidate is not None and not self._alive(candidate):
                candidate = None
        if candidate is None:
            if self._target is not None and self._alive(self._target):
                return
            fallback = self._bridge3d(0)
            candidate = fallback if self._alive(fallback) else None
        if candidate is not self._target:
            self._set_target(candidate)
        self._prune_bridges()

    def _prune_bridges(self):
        for bridges in (self._bridges, self._slice_bridges):
            for key in [k for k, b in bridges.items() if b is not self._target and not self._alive(b)]:
                self._release(bridges[key])
                del bridges[key]

    @staticmethod
    def _release(bridge):
        """bridge.release_motion(), whatever happens (a bridge from an older class may lack it or fail)."""
        try:
            bridge.release_motion()
        except Exception:  # noqa: BLE001
            _log.debug("release_motion failed", exc_info=True)

    def _set_target(self, bridge, announce=True):
        old = self._target
        if bridge is old:
            return
        if old is not None and self._moving:
            self._release(old)
        self._target = bridge
        if bridge is not None and self._moving:
            try:
                bridge.set_motion(True)
            except Exception:  # noqa: BLE001
                _log.debug("could not raise the update rate on the new target", exc_info=True)
        if announce and bridge is not None:
            self._announce_view(bridge)

    def _announce_view(self, bridge):
        """Tell the driver the view changed, as FreeCAD's NavlibInterface::onViewChanged does: write the new view's
        model.extents and view.affine. Nothing is written to the scene."""
        conn = self.connection
        if conn is None:
            return
        getters = bridge.getters()
        for name, type_id in ((nl.MODEL_EXTENTS, nl.BOX), (nl.VIEW_AFFINE, nl.MATRIX)):
            try:
                conn.write(name, type_id, getters[name][1]())
            except nl.NoData:
                pass
            except Exception:  # noqa: BLE001
                _log.debug("announcing %s failed", name, exc_info=True)

    def _tick(self):
        try:
            self._retarget()
        except Exception:  # noqa: BLE001 - a timer callback must not spam
            if not self._tick_error_logged:
                self._tick_error_logged = True
                _log.exception("retarget failed")

    # --- focus / hooks -------------------------------------------------------------------------------------------
    def _write_focus(self, value):
        """Tell the driver whether Slicer has focus. Never raises (it runs from a Qt signal); logs the first failure."""
        try:
            value = bool(value)
            conn = self.connection
            if conn is not None:
                self.write_results[nl.FOCUS] = conn.write(nl.FOCUS, nl.BOOL, value)
        except Exception:  # noqa: BLE001
            if not self._focus_error_logged:
                self._focus_error_logged = True
                _log.exception("writing the focus failed")

    def _on_app_state(self, state=None):
        """slicer.app applicationStateChanged: the driver only gets focus while Slicer is the active application.
        The state may arrive as the enum or as an int; with no state, ask the application."""
        try:
            import qt
            active = self._app_is_active() if state is None else int(state) == int(qt.Qt.ApplicationActive)
        except Exception:  # noqa: BLE001
            if not self._focus_error_logged:
                self._focus_error_logged = True
                _log.exception("reading the application state failed")
            return
        self._write_focus(active)

    def _on_quit(self):
        self.stop()

    @staticmethod
    def _app_is_active():
        """app_is_active(), False if it fails (this runs from signals and timers)."""
        try:
            return app_is_active()
        except Exception:  # noqa: BLE001
            return False

    def _install_hooks(self):
        if self._hooks_installed:
            return
        import qt
        import slicer
        self._tick_slot = self._tick
        self._state_slot = self._on_app_state
        self._quit_slot = self._on_quit
        self._timer = qt.QTimer()
        self._timer.setInterval(RETARGET_INTERVAL_MS)
        self._timer.connect("timeout()", self._tick_slot)
        self._timer.start()
        slicer.app.connect("applicationStateChanged(Qt::ApplicationState)", self._state_slot)
        slicer.app.connect("aboutToQuit()", self._quit_slot)
        self._hooks_installed = True

    def _remove_hooks(self):
        timer, self._timer = self._timer, None
        if timer is not None:
            try:
                timer.stop()
                timer.disconnect("timeout()", self._tick_slot)
            except Exception:  # noqa: BLE001
                pass
        if self._hooks_installed:
            try:
                import slicer
                slicer.app.disconnect("applicationStateChanged(Qt::ApplicationState)", self._state_slot)
                slicer.app.disconnect("aboutToQuit()", self._quit_slot)
            except Exception:  # noqa: BLE001
                pass
        self._hooks_installed = False
        self._tick_slot = self._state_slot = self._quit_slot = None

    # --- lifecycle -----------------------------------------------------------------------------------------------
    def _make_reader(self):
        """The device reader for this platform, or None (Mac has none)."""
        if self._reader_factory is not None:
            return self._reader_factory()
        import sys
        if sys.platform == "win32":
            from .fallback import hid_windows
            return hid_windows.Reader()
        if sys.platform.startswith("linux"):
            from .fallback import spacenavd
            return spacenavd.Reader()
        return None

    def _fallback_motion(self, moving):
        """The navigator tells us motion began or ended: interactive update rate on the target while it moves (the
        retarget in _set_target carries it over when the pointer changes view mid-motion)."""
        self._moving = bool(moving)
        bridge = self._target
        if bridge is None:
            return
        if moving:
            bridge.set_motion(True)
        else:
            self._release(bridge)

    def _persist_fallback(self):
        """A device button changed the rotation lock: remember it."""
        from . import settings
        if self.navigator is not None:
            settings.set_fallback_rotation_lock(self.navigator.rotation_lock)

    def _start_fallback(self):
        """Start the device reader and the navigator. True when they run (the reader keeps looking for a device)."""
        from . import settings
        from .fallback import motion
        from .fallback.navigator import Navigator
        reader = self._make_reader()
        if reader is None:
            return False
        try:
            try:
                axis_settings = settings.fallback_axis_settings()
                lock = settings.fallback_rotation_lock()
            except Exception:  # noqa: BLE001
                _log.debug("could not read the fallback settings", exc_info=True)
                axis_settings, lock = motion.AxisSettings(), False
            integrator = motion.Integrator(axis_settings)
            navigator = Navigator(integrator, axis_settings, target=lambda: self._target,
                                  on_motion=self._fallback_motion, on_change=self._persist_fallback)
            navigator.rotation_lock = lock
            reader.on_report = navigator.handle_report
            self.reader, self.navigator = reader, navigator
            reader.start()
            navigator.start()
        except Exception:  # noqa: BLE001 - e.g. no HID layer: report "no device", never raise
            _log.exception("fallback reader failed to start")
            self._stop_fallback()
            return False
        return True

    def _stop_fallback(self):
        navigator, self.navigator = self.navigator, None
        reader, self.reader = self.reader, None
        if navigator is not None:
            try:
                navigator.stop()
            except Exception:  # noqa: BLE001
                _log.debug("navigator stop failed", exc_info=True)
        if reader is not None:
            try:
                reader.on_report = None
                reader.stop()
            except Exception:  # noqa: BLE001
                _log.debug("reader stop failed", exc_info=True)

    def start(self):
        """Choose the mode and connect. Returns "driver", "fallback" or "no device"; never raises for a missing
        driver. With MOUSENAV3D_FORCE_FALLBACK=1 the driver is not tried (force_fallback)."""
        if self.connection is not None or self.navigator is not None:
            return self.mode
        self.main_thread = threading.get_ident()
        try:
            from . import settings
            self.limb_side = normalize_limb_side(settings.get("limb_side", "right"))
        except Exception:  # noqa: BLE001
            _log.debug("could not read settings", exc_info=True)
        if force_fallback():
            return self._without_driver("Driver mode skipped (MOUSENAV3D_FORCE_FALLBACK=1).")
        lib = nl.load_library()
        if lib is None:
            return self._without_driver("The 3Dconnexion driver was not found.")
        getters, setters = self.build_accessors()
        connection = nl.Connection(self.app_name, getters, setters, lib)
        if not connection.handle:
            code = connection.create_result
            return self._without_driver(f"The 3Dconnexion driver refused the connection (code {code}).")
        self.connection = connection
        self._init_target()
        self.write_results[nl.ACTIVE] = connection.write(nl.ACTIVE, nl.BOOL, True)
        self._publish_commands()
        self._write_focus(self._app_is_active())
        self._install_hooks()
        self.mode = MODE_DRIVER
        self._status = "Connected to the 3Dconnexion driver."
        return self.mode

    def _without_driver(self, reason):
        self._bridges.clear()
        self._slice_bridges.clear()
        self._target = None
        if self._start_fallback():
            self.mode = MODE_FALLBACK
            self._fallback_reason = reason
            self._status = reason + " Using the built-in reader."
            self._init_target()
            self._install_hooks()
        else:
            self.mode = MODE_NO_DEVICE
            self._status = reason
        return self.mode

    def _publish_commands(self):
        """Write the action-set tree, then make the set active (the sequence FreeCAD's NavlibCmds uses)."""
        root, keep = commands.build_tree(self.app_name)
        conn = self.connection
        self._tree_keep = keep  # the nodes' strings; the Connection retains the root pointer itself
        self.write_results[nl.COMMANDS_TREE] = conn.write(nl.COMMANDS_TREE, nl.ACTIONNODEEX, root)
        self.write_results[nl.COMMANDS_ACTIVE_SET] = conn.write(nl.COMMANDS_ACTIVE_SET, nl.STRING, commands.SET_ID)
        _log.debug("commands.tree -> %s, commands.activeSet -> %s", self.write_results[nl.COMMANDS_TREE],
                   self.write_results[nl.COMMANDS_ACTIVE_SET])

    def stop(self):
        """Remove the timer and signal hooks, restore the still update rate, deactivate, close the connection, drop
        references (in that order). Idempotent."""
        self._remove_hooks()
        self._stop_fallback()
        for bridge in list(self._bridges.values()) + list(self._slice_bridges.values()):
            self._release(bridge)
        self._moving = False
        conn, self.connection = self.connection, None
        try:
            if conn is not None:
                try:
                    conn.write(nl.ACTIVE, nl.BOOL, False)
                finally:
                    conn.close()
        finally:
            self._target = None
            self._bridges.clear()
            self._slice_bridges.clear()
            self.mode = None
            self._status = "stopped"
            self._device_present = None


def install(controller):
    """Make `controller` the session's only controller (`slicer._mousenav3d_controller`), stopping a previous one.
    Module Reload creates the new controller and calls this; the old code stops the old connection."""
    import slicer
    previous = getattr(slicer, "_mousenav3d_controller", None)
    slicer._mousenav3d_controller = controller
    if previous is not None and previous is not controller:
        try:
            previous.stop()
        except Exception:  # noqa: BLE001
            _log.exception("stopping the previous controller failed")
    return controller
