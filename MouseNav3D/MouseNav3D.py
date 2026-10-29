"""3D Mouse Navigation: module and panel.

The module owns no state of its own: the single Controller lives in `slicer._mousenav3d_controller`
(MouseNav3DLib.controller.install). It is started when "Enable 3D mouse" is on, at Slicer startup (so the mouse works
without opening this panel) and whenever the panel is set up; module Reload and Slicer exit stop it through the
widget's cleanup() and the controller's own aboutToQuit hook.
"""
import logging
import os
import time

import qt
import slicer
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleTest,
    ScriptedLoadableModuleWidget,
)

_log = logging.getLogger("MouseNav3D")

AXIS_LABELS = (("tx", "Left / right (tx)"), ("ty", "Up / down (ty)"), ("tz", "Push / pull (tz)"),
               ("rx", "Tilt (rx)"), ("ry", "Twist (ry)"), ("rz", "Roll (rz)"))
SETTINGS_NOTE = "Open 3Dconnexion's settings from the tray icon."
HELP_TEXT = (
    "Navigate the 3D and slice views with a 3D mouse (works with 3Dconnexion SpaceMouse devices). With the "
    "3Dconnexion driver installed the driver does the motion and its own settings apply; without it a built-in reader "
    "takes over (settings below). The view under the mouse pointer moves. Nothing in the scene is changed."
)
ACKNOWLEDGEMENT = (
    "Apache-2.0; the navigation library interface is LGPL-2.1-or-later, (c) 3Dconnexion, via FreeCAD. The licence "
    "texts and the notice are in this module's folder: Resources/NOTICE.md, Resources/LICENSE.txt and "
    "Resources/LICENSE-LGPL.txt. "
    "3Dconnexion and SpaceMouse are trademarks of 3Dconnexion; this extension is not affiliated with or endorsed by "
    "3Dconnexion."
)


def _controller():
    return getattr(slicer, "_mousenav3d_controller", None)


def ensure_controller(factory=None):
    """Return the running controller, creating, installing and starting a new one when there is none (or it stopped).
    A controller whose start found no driver and no device ("no device") is replaced on the next call, which
    retries."""
    current = _controller()
    if current is not None and current.mode in ("driver", "fallback"):
        return current
    from MouseNav3DLib import controller as ctlmod
    new = (factory or ctlmod.Controller)()
    ctlmod.install(new)
    new.start()
    return new


def stop_controller():
    """Stop and forget the installed controller."""
    current = _controller()
    slicer._mousenav3d_controller = None
    if current is not None:
        try:
            current.stop()
        except Exception:  # noqa: BLE001
            _log.exception("stopping the controller failed")


def _enabled():
    from MouseNav3DLib import settings
    return bool(settings.get("enabled", True))


def _autostart_allowed():
    """Not in a scripted run (self-tests, --python-script/--python-code) and not when MOUSENAV3D_NO_AUTOSTART is set."""
    if os.environ.get("MOUSENAV3D_NO_AUTOSTART"):
        return False
    try:
        options = slicer.app.commandOptions()
        for name in ("pythonScript", "pythonCode"):
            value = getattr(options, name, "")
            value = value() if callable(value) else value
            if value:
                return False
    except Exception:  # noqa: BLE001
        pass
    return True


_startup_slot = None


def _on_startup_completed():
    try:
        if _enabled():
            ensure_controller()
    except Exception:  # noqa: BLE001 - never break Slicer's startup
        _log.exception("starting 3D Mouse Navigation at startup failed")


class MouseNav3D(ScriptedLoadableModule):
    def __init__(self, parent):
        global _startup_slot
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "3D Mouse Navigation"
        parent.categories = ["Utilities"]
        parent.dependencies = []
        parent.contributors = ["Devon Rohlf"]
        parent.helpText = HELP_TEXT
        parent.acknowledgementText = ACKNOWLEDGEMENT
        icon = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "MouseNav3D.png")
        if os.path.exists(icon):
            parent.icon = qt.QIcon(icon)
        if _startup_slot is None and _autostart_allowed():
            _startup_slot = _on_startup_completed
            slicer.app.connect("startupCompleted()", _startup_slot)


class MouseNav3DWidget(ScriptedLoadableModuleWidget):
    REFRESH_MS = 250
    RETRY_S = 5.0

    def setup(self):
        import ctk
        from MouseNav3DLib import settings
        from MouseNav3DLib.controller import normalize_limb_side

        ScriptedLoadableModuleWidget.setup(self)
        self.controllerFactory = None  # tests: callable returning the Controller to use
        self._timer = None
        self._last_start = time.monotonic()
        self._fallback_shown = False
        self._syncing = False
        layout = self.layout

        self.enableCheckBox = qt.QCheckBox("Enable 3D mouse")
        self.enableCheckBox.toolTip = "Switch the 3D mouse navigation on or off."
        self.enableCheckBox.checked = _enabled()
        layout.addWidget(self.enableCheckBox)

        self.statusLabel = qt.QLabel("")
        self.statusLabel.wordWrap = True
        layout.addWidget(self.statusLabel)

        form = qt.QFormLayout()
        self.limbComboBox = qt.QComboBox()
        self.limbComboBox.addItems(["Right", "Left"])
        self.limbComboBox.toolTip = "Which limb is shown: sets which side the Lateral and Medial views look from."
        self.limbComboBox.currentText = normalize_limb_side(settings.get("limb_side", "right")).capitalize()
        form.addRow("Limb for lateral/medial:", self.limbComboBox)
        layout.addLayout(form)

        self.settingsButton = qt.QPushButton("3Dconnexion settings...")
        self.settingsButton.toolTip = "Sensitivity, speed and button assignments are set in 3Dconnexion's own app."
        layout.addWidget(self.settingsButton)
        self.settingsNote = qt.QLabel("")
        self.settingsNote.wordWrap = True
        self.settingsNote.visible = False
        layout.addWidget(self.settingsNote)

        # --- built-in reader (fallback mode) only --------------------------------------------------------------------
        self.fallbackGroup = ctk.ctkCollapsibleGroupBox()
        self.fallbackGroup.title = "Built-in reader settings"
        grid = qt.QGridLayout(self.fallbackGroup)
        grid.addWidget(qt.QLabel("Axis"), 0, 0)
        grid.addWidget(qt.QLabel("Reverse"), 0, 1)
        grid.addWidget(qt.QLabel("Sensitivity"), 0, 2)
        self.reverseBoxes, self.sensitivitySliders = {}, {}
        for row, (axis, label) in enumerate(AXIS_LABELS, start=1):
            grid.addWidget(qt.QLabel(label), row, 0)
            box = qt.QCheckBox()
            self.reverseBoxes[axis] = box
            grid.addWidget(box, row, 1)
            slider = self._slider(0.1, 3.0, 0.1, 1)
            self.sensitivitySliders[axis] = slider
            grid.addWidget(slider, row, 2)
        row = len(AXIS_LABELS) + 1
        self.speedSlider = self._slider(0.1, 3.0, 0.1, 1)
        grid.addWidget(qt.QLabel("Overall speed"), row, 0)
        grid.addWidget(self.speedSlider, row, 1, 1, 2)
        self.deadZoneSlider = self._slider(0.0, 0.25, 0.01, 2)
        grid.addWidget(qt.QLabel("Dead zone"), row + 1, 0)
        grid.addWidget(self.deadZoneSlider, row + 1, 1, 1, 2)
        self.rotationLockBox = qt.QCheckBox("Rotation lock (3D view: pan and zoom only)")
        grid.addWidget(self.rotationLockBox, row + 2, 0, 1, 3)
        self.axesLabel = qt.QLabel("")
        self.axesLabel.toolTip = "The device's six axes as the built-in reader sees them, -1 to 1."
        grid.addWidget(self.axesLabel, row + 3, 0, 1, 3)
        layout.addWidget(self.fallbackGroup)
        self.fallbackGroup.visible = False
        layout.addStretch(1)

        self.enableCheckBox.connect("toggled(bool)", self.onEnableToggled)
        self.limbComboBox.connect("currentIndexChanged(int)", self.onLimbChanged)
        self.settingsButton.connect("clicked()", self.onSettingsClicked)
        for axis in self.reverseBoxes:
            self.reverseBoxes[axis].connect("toggled(bool)", self.onFallbackChanged)
            self.sensitivitySliders[axis].connect("valueChanged(double)", self.onFallbackChanged)
        self.speedSlider.connect("valueChanged(double)", self.onFallbackChanged)
        self.deadZoneSlider.connect("valueChanged(double)", self.onFallbackChanged)
        self.rotationLockBox.connect("toggled(bool)", self.onRotationLockToggled)

        self._timer = qt.QTimer()
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.connect("timeout()", self.refresh)

        if self.enableCheckBox.checked:
            self._start()
        self.refresh()

    @staticmethod
    def _slider(low, high, step, decimals):
        import ctk
        s = ctk.ctkSliderWidget()
        s.minimum, s.maximum, s.singleStep, s.decimals = low, high, step, decimals
        s.value = low
        return s

    # --- controller -----------------------------------------------------------------------------------------------
    def _start(self):
        self._last_start = time.monotonic()
        try:
            ensure_controller(self.controllerFactory)
        except Exception:  # noqa: BLE001 - the panel shows the state; a failure must not break the module
            _log.exception("starting 3D Mouse Navigation failed")

    def onEnableToggled(self, on):
        from MouseNav3DLib import settings
        if self._syncing:
            return
        settings.set("enabled", bool(on))
        if on:
            self._start()
        else:
            stop_controller()
        self.refresh()

    def onLimbChanged(self, _index=None):
        from MouseNav3DLib import settings
        from MouseNav3DLib.controller import normalize_limb_side
        side = normalize_limb_side(self.limbComboBox.currentText)
        settings.set("limb_side", side)
        ctl = _controller()
        if ctl is not None:
            ctl.limb_side = side

    def onSettingsClicked(self):
        """No navlib property opens 3Dconnexion's settings, so say where they are."""
        self.settingsNote.text = SETTINGS_NOTE
        self.settingsNote.visible = True

    # --- built-in reader settings -----------------------------------------------------------------------------------
    def _fallback_navigator(self):
        ctl = _controller()
        if ctl is not None and ctl.mode == "fallback":
            return ctl.navigator
        return None

    def _load_fallback_values(self, navigator):
        s = navigator.settings
        self._syncing = True
        try:
            for axis in self.reverseBoxes:
                self.reverseBoxes[axis].checked = bool(s.reverse.get(axis, False))
                self.sensitivitySliders[axis].value = float(s.sensitivity.get(axis, 1.0))
            self.speedSlider.value = float(s.speed)
            self.deadZoneSlider.value = float(s.dead_zone)
            self.rotationLockBox.checked = bool(navigator.rotation_lock)
        finally:
            self._syncing = False

    def onFallbackChanged(self, _value=None):
        """A reverse box or slider moved: write it to the settings and to the running reader."""
        if self._syncing:
            return
        from MouseNav3DLib import settings
        navigator = self._fallback_navigator()
        for axis in self.reverseBoxes:
            reverse = bool(self.reverseBoxes[axis].checked)
            sens = float(self.sensitivitySliders[axis].value)
            settings.set(f"fallback/reverse_{axis}", reverse)
            settings.set(f"fallback/sensitivity_{axis}", sens)
            if navigator is not None:
                navigator.settings.reverse[axis] = reverse
                navigator.settings.sensitivity[axis] = sens
        settings.set("fallback/speed", float(self.speedSlider.value))
        settings.set("fallback/dead_zone", float(self.deadZoneSlider.value))
        if navigator is not None:
            navigator.settings.speed = float(self.speedSlider.value)
            navigator.settings.dead_zone = float(self.deadZoneSlider.value)

    def onRotationLockToggled(self, on):
        if self._syncing:
            return
        from MouseNav3DLib import settings
        settings.set_fallback_rotation_lock(bool(on))
        navigator = self._fallback_navigator()
        if navigator is not None:
            navigator.rotation_lock = bool(on)

    # --- display ------------------------------------------------------------------------------------------------------
    def refresh(self):
        """Status line, fallback group visibility and the live axes line. Cheap; runs from a timer only while the panel
        is shown. While the panel is shown, a controller that found no driver and no device is retried every
        RETRY_S seconds (a driver started or a device plugged in later is then picked up)."""
        ctl = _controller()
        if (ctl is not None and ctl.mode == "no device" and self.enableCheckBox.checked and self._timer is not None
                and self._timer.isActive() and time.monotonic() - self._last_start >= self.RETRY_S):
            self._start()
            ctl = _controller()
        text = ctl.status() if ctl is not None else ("Off." if not self.enableCheckBox.checked else "not started")
        if self.statusLabel.text != text:
            self.statusLabel.text = text
        navigator = self._fallback_navigator()
        show = navigator is not None
        if show and not self._fallback_shown:
            self._load_fallback_values(navigator)
        self._fallback_shown = show
        if self.fallbackGroup.visible != show:
            self.fallbackGroup.visible = show
        # the driver's settings button matters only in driver mode; the built-in reader has its own group
        self.settingsButton.visible = not show
        if show:
            axes = getattr(navigator, "last_axes", None) or {}
            self.axesLabel.text = "Axes: " + "  ".join(f"{a} {axes.get(a, 0.0):+.2f}" for a, _l in AXIS_LABELS)

    def enter(self):
        if self._timer is not None:
            self._timer.start()
        self.refresh()

    def exit(self):
        if self._timer is not None:
            self._timer.stop()

    def cleanup(self):
        """Module Reload or Slicer exit: stop the refresh timer and the controller (the next setup starts a new one)."""
        timer, self._timer = getattr(self, "_timer", None), None
        if timer is not None:
            timer.stop()
        stop_controller()
        ScriptedLoadableModuleWidget.cleanup(self)


class MouseNav3DTest(ScriptedLoadableModuleTest):
    """Smoke test for the Extensions Index CI (no device, no driver): the library imports, and a controller whose
    driver loader finds nothing and which has no device reader starts without raising and reports a mode. Nothing
    is installed as the session's controller and no settings are written."""

    def setUp(self):
        slicer.mrmlScene.Clear(0)

    def runTest(self):
        self.setUp()
        self.test_start_without_driver_or_device()

    def test_start_without_driver_or_device(self):
        from MouseNav3DLib import controller as ctlmod
        from MouseNav3DLib import navlib_ctypes as nl

        real_load = nl.load_library
        nl.load_library = lambda: None  # no driver, whatever is installed on the machine
        ctl = ctlmod.Controller(app_name="3D Mouse Navigation (self-test)")
        ctl._reader_factory = lambda: None  # never start a device reader
        try:
            mode = ctl.start()
            self.assertEqual(mode, ctlmod.MODE_NO_DEVICE)  # no driver and no reader: the only possible mode
            self.assertIsInstance(ctl.status(), str)
        finally:
            nl.load_library = real_load
            ctl.stop()
        self.assertIsNone(ctl.mode)
        self.delayDisplay("3D Mouse Navigation: start without driver or device passed")
