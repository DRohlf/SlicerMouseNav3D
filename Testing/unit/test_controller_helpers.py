import logging
import threading

from MouseNav3DLib import controller as ctlmod
from MouseNav3DLib import navlib_ctypes as nl
from MouseNav3DLib.controller import Controller, normalize_limb_side


def test_limb_side_accepts_right_and_left_any_case():
    assert normalize_limb_side("left") == "left"
    assert normalize_limb_side(" Right ") == "right"
    assert normalize_limb_side("LEFT") == "left"


def test_limb_side_defaults_to_right():
    for bad in ("", "banana", None, 3, "both"):
        assert normalize_limb_side(bad) == "right"


class FakeBridge:
    """A target with one getter and one setter (no Slicer)."""

    def __init__(self):
        self.written = []

    def getters(self):
        return {nl.VIEW_PERSPECTIVE: (nl.BOOL, lambda: True)}

    def setters(self):
        return {nl.VIEW_AFFINE: self.written.append}


def in_thread(fn):
    out = {}

    def run():
        try:
            out["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            out["error"] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join(5)
    return out


def test_accessors_refuse_calls_off_the_main_thread_and_log_once(caplog):
    caplog.set_level(logging.WARNING, logger="MouseNav3D")
    c = Controller()
    bridge = FakeBridge()
    c._target = bridge
    getters, setters = c.build_accessors()
    get = getters[nl.VIEW_PERSPECTIVE][1]
    put = setters[nl.VIEW_AFFINE]
    assert get() is True                                   # main thread: served
    put((1.0,) * 16)
    assert bridge.written == [(1.0,) * 16]
    for _ in range(2):
        assert isinstance(in_thread(get).get("error"), nl.NoData)
        assert isinstance(in_thread(lambda: put((2.0,) * 16)).get("error"), nl.NoData)
    assert bridge.written == [(1.0,) * 16]                 # nothing reached the view from the other thread
    warnings = [r for r in caplog.records if r.name == "MouseNav3D" and "main thread" in r.getMessage()]
    assert len(warnings) == 1
    assert len(c.callback_threads) >= 2                    # the other threads are still recorded


def test_force_fallback_skips_the_driver(monkeypatch):
    loads = []
    monkeypatch.setattr(nl, "load_library", lambda: loads.append(1))
    monkeypatch.setenv("MOUSENAV3D_FORCE_FALLBACK", "1")
    c = Controller()
    c._reader_factory = lambda: None                       # no reader: "no device", but the driver was never tried
    assert c.start() == ctlmod.MODE_NO_DEVICE
    assert loads == [] and c.connection is None and "MOUSENAV3D_FORCE_FALLBACK" in c.status()
    c.stop()
    monkeypatch.setenv("MOUSENAV3D_FORCE_FALLBACK", "0")
    c = Controller()
    c._reader_factory = lambda: None
    c.start()
    assert loads == [1]                                    # not "1": the driver is tried as before
    c.stop()


def test_driver_status_names_whether_a_device_is_connected():
    class Conn:
        present = True

        def read(self, name, type_id):
            assert (name, type_id) == (nl.DEVICE_PRESENT, nl.BOOL)
            return self.present

    c = Controller()
    c.mode, c.connection, c._status = ctlmod.MODE_DRIVER, Conn(), "Connected to the 3Dconnexion driver."
    assert c.status().endswith("a 3D mouse is connected.")
    c.connection.present = False
    c._device_present = None
    assert c.status().endswith("no 3D mouse is connected.")
    c.connection = object()                                # no read(): the plain text
    c._device_present = None
    assert c.status() == "Connected to the 3Dconnexion driver."
