"""Windows HID reader for 3Dconnexion multi-axis controllers, used when 3Dconnexion's driver is not available.

Ported from the author's earlier reader (hid.dll / setupapi / kernel32 through ctypes; no SDK, no extra package). It reads next to a running 3DxWare. Devices: every HID collection with usage page 0x01 / usage 0x08
(multi-axis controller) from 3Dconnexion (VID 256F) or older Logitech-made ones (VID 046D). Reports are decoded through
the device's own HID descriptor (HidP_*), so one report with all six axes (SpaceMouse Wireless BT, report 1) and split
translation / rotation reports (older devices) both work; buttons are HID page 0x09 usages, battery page 0x06 usage 0x20.

Axis frame (the one fallback/motion.py uses): tx right, ty up (lift the cap), tz toward you (pull the cap), rx tilt back (about right),
ry spin (about up, anticlockwise seen from above), rz roll (about toward you). HID gives X right, Y toward you, Z down
(and rotations about those), so ty = -Z, tz = Y, ry = -Rz, rz = Ry. Each axis is -1..1 of full deflection (logical
+-350).

Changes from the earlier reader: the reader stamps every report with time.monotonic() and hands it to
`on_report(t, axes, buttons)` on its thread (no polled state, no stale handling here: the Integrator does that);
split reports are merged so `axes` always carries all six; a lost device sends a release report; the reader is a
plain class with start/stop/running/devices (no Slicer or Qt in this file).
"""
import ctypes as C
import logging
import sys
import threading
import time

_log = logging.getLogger("MouseNav3D")

AXES = ("tx", "ty", "tz", "rx", "ry", "rz")
VENDORS = (0x256F, 0x046D)
THREAD_NAME = "MouseNav3D HID reader"


class _HID:
    """The bits of hid.dll / setupapi / kernel32 used here; created once."""

    def __init__(self):
        import ctypes.wintypes as W
        self.W = W
        self.hid, self.sa = C.WinDLL("hid"), C.WinDLL("setupapi")
        self.k32 = C.WinDLL("kernel32", use_last_error=True)

        class GUID(C.Structure):
            _fields_ = [("a", W.DWORD), ("b", W.WORD), ("c", W.WORD), ("d", C.c_ubyte * 8)]

        class IFD(C.Structure):
            _fields_ = [("cbSize", W.DWORD), ("g", GUID), ("flags", W.DWORD), ("res", C.c_void_p)]

        class ATTR(C.Structure):
            _fields_ = [("Size", W.ULONG), ("VendorID", W.USHORT), ("ProductID", W.USHORT), ("Version", W.USHORT)]

        class CAPS(C.Structure):
            _fields_ = [("Usage", W.USHORT), ("UsagePage", W.USHORT), ("InLen", W.USHORT), ("OutLen", W.USHORT),
                        ("FeatLen", W.USHORT), ("Res", W.USHORT * 17), ("nLinkColl", W.USHORT),
                        ("nInButtonCaps", W.USHORT), ("nInValueCaps", W.USHORT), ("nInDataIdx", W.USHORT),
                        ("o", W.USHORT * 3), ("f", W.USHORT * 3)]

        class VCAPS(C.Structure):          # HIDP_VALUE_CAPS
            _fields_ = [("UsagePage", W.USHORT), ("ReportID", C.c_ubyte), ("IsAlias", C.c_ubyte),
                        ("BitField", W.USHORT), ("LinkCollection", W.USHORT), ("LinkUsage", W.USHORT),
                        ("LinkUsagePage", W.USHORT), ("IsRange", C.c_ubyte), ("IsStringRange", C.c_ubyte),
                        ("IsDesignatorRange", C.c_ubyte), ("IsAbsolute", C.c_ubyte), ("HasNull", C.c_ubyte),
                        ("Reserved", C.c_ubyte), ("BitSize", W.USHORT), ("ReportCount", W.USHORT),
                        ("Reserved2", W.USHORT * 5), ("UnitsExp", W.ULONG), ("Units", W.ULONG),
                        ("LogicalMin", W.LONG), ("LogicalMax", W.LONG), ("PhysicalMin", W.LONG),
                        ("PhysicalMax", W.LONG), ("UsageMin", W.USHORT), ("UsageMax", W.USHORT),
                        ("x", W.USHORT * 6)]

        class OVL(C.Structure):            # OVERLAPPED
            _fields_ = [("Internal", C.c_void_p), ("InternalHigh", C.c_void_p), ("Offset", W.DWORD),
                        ("OffsetHigh", W.DWORD), ("hEvent", C.c_void_p)]

        self.GUID, self.IFD, self.ATTR, self.CAPS, self.VCAPS, self.OVL = GUID, IFD, ATTR, CAPS, VCAPS, OVL
        sa, k32, hid = self.sa, self.k32, self.hid
        sa.SetupDiGetClassDevsW.restype = C.c_void_p
        sa.SetupDiGetClassDevsW.argtypes = [C.POINTER(GUID), C.c_wchar_p, C.c_void_p, W.DWORD]
        sa.SetupDiEnumDeviceInterfaces.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(GUID), W.DWORD, C.POINTER(IFD)]
        sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [C.c_void_p, C.POINTER(IFD), C.c_void_p, W.DWORD,
                                                         C.POINTER(W.DWORD), C.c_void_p]
        sa.SetupDiDestroyDeviceInfoList.argtypes = [C.c_void_p]
        k32.CreateFileW.restype = C.c_void_p
        k32.CreateFileW.argtypes = [C.c_wchar_p, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, C.c_void_p]
        k32.CreateEventW.restype = C.c_void_p
        k32.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, C.c_wchar_p]
        k32.ResetEvent.argtypes = [C.c_void_p]
        k32.ReadFile.argtypes = [C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
        k32.GetOverlappedResult.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(W.DWORD), W.BOOL]
        k32.WaitForSingleObject.argtypes = [C.c_void_p, W.DWORD]
        k32.WaitForSingleObject.restype = W.DWORD
        k32.CancelIoEx.argtypes = [C.c_void_p, C.c_void_p]
        k32.CloseHandle.argtypes = [C.c_void_p]
        hid.HidD_GetHidGuid.argtypes = [C.POINTER(GUID)]
        hid.HidD_GetAttributes.argtypes = [C.c_void_p, C.POINTER(ATTR)]
        hid.HidD_GetProductString.argtypes = [C.c_void_p, C.c_void_p, W.ULONG]
        hid.HidD_GetPreparsedData.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
        hid.HidD_FreePreparsedData.argtypes = [C.c_void_p]
        hid.HidP_GetCaps.argtypes = [C.c_void_p, C.POINTER(CAPS)]
        hid.HidP_GetValueCaps.argtypes = [C.c_int, C.c_void_p, C.POINTER(W.USHORT), C.c_void_p]
        hid.HidP_GetUsageValue.argtypes = [C.c_int, W.USHORT, W.USHORT, W.USHORT, C.POINTER(W.ULONG), C.c_void_p,
                                           C.c_void_p, W.ULONG]
        hid.HidP_GetUsageValue.restype = C.c_long
        hid.HidP_GetUsages.argtypes = [C.c_int, W.USHORT, W.USHORT, C.POINTER(W.USHORT), C.POINTER(W.ULONG),
                                       C.c_void_p, C.c_void_p, W.ULONG]
        hid.HidP_GetUsages.restype = C.c_long
        self.INVALID = C.c_void_p(-1).value

    def paths(self):
        g = self.GUID()
        self.hid.HidD_GetHidGuid(C.byref(g))
        h = self.sa.SetupDiGetClassDevsW(C.byref(g), None, None, 0x12)      # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
        out, i = [], 0
        try:
            while True:
                ifd = self.IFD(cbSize=C.sizeof(self.IFD))
                if not self.sa.SetupDiEnumDeviceInterfaces(h, None, C.byref(g), i, C.byref(ifd)):
                    break
                i += 1
                need = self.W.DWORD()
                self.sa.SetupDiGetDeviceInterfaceDetailW(h, C.byref(ifd), None, 0, C.byref(need), None)
                buf = C.create_string_buffer(need.value)
                C.cast(buf, C.POINTER(self.W.DWORD))[0] = 8 if C.sizeof(C.c_void_p) == 8 else 6
                if self.sa.SetupDiGetDeviceInterfaceDetailW(h, C.byref(ifd), buf, need, None, None):
                    out.append(C.wstring_at(C.addressof(buf) + 4))
        finally:
            self.sa.SetupDiDestroyDeviceInfoList(h)
        return out


_hid = None


def _api():
    global _hid
    if _hid is None:
        if sys.platform != "win32":
            raise OSError("the HID reader is written for Windows (hid.dll)")
        _hid = _HID()
    return _hid


class Device:
    """One multi-axis collection: its handle, descriptor (preparsed data) and how to decode its reports."""

    def __init__(self, path):
        a = _api()
        self.path = path
        fh = a.k32.CreateFileW(path, 0, 3, None, 3, 0, None)                 # no access: attributes and descriptor
        if fh in (None, a.INVALID):
            raise OSError(f"cannot open {path}")
        try:
            at = a.ATTR(Size=C.sizeof(a.ATTR))
            a.hid.HidD_GetAttributes(fh, C.byref(at))
            self.vid, self.pid = at.VendorID, at.ProductID
            name = C.create_unicode_buffer(128)
            a.hid.HidD_GetProductString(fh, name, C.sizeof(name))
            self.pp = C.c_void_p()
            if not a.hid.HidD_GetPreparsedData(fh, C.byref(self.pp)):
                raise OSError(f"no HID descriptor for {path}")
        finally:
            a.k32.CloseHandle(fh)
        caps = a.CAPS()
        a.hid.HidP_GetCaps(self.pp, C.byref(caps))
        self.page, self.usage, self.in_len = caps.UsagePage, caps.Usage, caps.InLen
        n = a.W.USHORT(caps.nInValueCaps)
        vc = (a.VCAPS * max(n.value, 1))()
        a.hid.HidP_GetValueCaps(0, vc, C.byref(n), self.pp)
        self.values = {}                                   # (page, usage) -> (bits, logical min, logical max)
        for v in vc[:n.value]:
            for u in range(v.UsageMin, (v.UsageMax if v.IsRange else v.UsageMin) + 1):
                self.values[(v.UsagePage, u)] = (v.BitSize, v.LogicalMin, v.LogicalMax)
        self.name = name.value or {0xC63A: "SpaceMouse Wireless BT", 0xC633: "SpaceMouse Enterprise",
                                   0xC652: "3Dconnexion Universal Receiver"}.get(self.pid, f"3Dconnexion {self.pid:04X}")

    def close(self):
        if self.pp:
            _api().hid.HidD_FreePreparsedData(self.pp)
            self.pp = None

    def decode(self, report):
        """{axis: -1..1} for the axes in this report, the buttons pressed (HID usages) if this report carries buttons
        (else None), and the battery % if it carries that (else None)."""
        a = _api()
        buf = (C.c_ubyte * len(report)).from_buffer_copy(bytes(report))
        axes = {}
        for k, u in enumerate((0x30, 0x31, 0x32, 0x33, 0x34, 0x35)):
            cap = self.values.get((0x01, u))
            if cap is None:
                continue
            val = a.W.ULONG()
            if a.hid.HidP_GetUsageValue(0, 0x01, 0, u, C.byref(val), self.pp, buf, len(report)) != 0x110000:
                continue                                   # HIDP_STATUS_SUCCESS; else not in this report
            bits, lo, hi = cap
            x = val.value
            if lo < 0 and x >= 1 << (bits - 1):
                x -= 1 << bits                             # signed field
            axes[k] = max(-1.0, min(1.0, x / float(max(abs(lo), abs(hi), 1))))
        tx, ty, tz, rx, ry, rz = (axes.get(k) for k in range(6))
        out = {}
        for name, v in (("tx", tx), ("ty", None if tz is None else -tz), ("tz", ty),
                        ("rx", rx), ("ry", None if rz is None else -rz), ("rz", ry)):
            if v is not None:
                out[name] = v
        buttons = None
        n = a.W.ULONG(64)
        lst = (a.W.USHORT * 64)()
        st = a.hid.HidP_GetUsages(0, 0x09, 0, lst, C.byref(n), self.pp, buf, len(report))
        if st == 0x110000:
            buttons = sorted(lst[:n.value])
        battery = None
        if (0x06, 0x20) in self.values:
            val = a.W.ULONG()
            if a.hid.HidP_GetUsageValue(0, 0x06, 0, 0x20, C.byref(val), self.pp, buf, len(report)) == 0x110000:
                battery = int(val.value)
        return out, buttons, battery


def find_devices():
    """Every SpaceMouse multi-axis collection present now."""
    out = []
    for p in _api().paths():
        low = p.lower()
        if not any(f"{v:04x}" in low for v in VENDORS):
            continue
        try:
            d = Device(p)
        except OSError:
            continue
        if d.vid in VENDORS and (d.page, d.usage) == (0x01, 0x08):
            out.append(d)
        else:
            d.close()
    return out


class Reader:
    """One background thread per device reading reports (overlapped, so it stops within 0.2 s). Looks for a device
    every 2 s while none is connected. Every report calls `on_report(t, axes, buttons)` from the reader thread:
    t = time.monotonic(); axes = all six axes merged from the reports seen so far, or {} for a report without axes
    (buttons only); buttons = the pressed HID button usages if the report carries buttons, else None."""

    def __init__(self):
        self.on_report = None
        self.battery = None
        self.devices = []                                  # names of the devices being read
        self.error = ""
        self.reports = 0
        self._callback_error_logged = False
        self._axes = dict.fromkeys(AXES, 0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
            self._thread.start()

    def stop(self, wait=2.0):
        """Stop the threads; True when they are gone."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(wait)
        alive = self._thread is not None and self._thread.is_alive()
        if not alive:
            self._thread = None  # a thread that outlived the join stays referenced: running stays True, start() will not add a second reader
        return not alive

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def feed(self, axes=None, buttons=None, battery=None, t=None):
        """Take one decoded report (this is also how tests drive the callback without a device)."""
        with self._lock:
            if axes:
                self._axes.update(axes)
                merged = dict(self._axes)
            else:
                merged = {}
            if battery is not None:
                self.battery = battery
            self.reports += 1
        self._emit(time.monotonic() if t is None else t, merged, None if buttons is None else list(buttons))

    def _emit(self, t, axes, buttons):
        """Call on_report. A failing callback is logged once and never stops or restarts the reader thread."""
        cb = self.on_report
        if cb is None:
            return
        try:
            cb(t, axes, buttons)
        except Exception:  # noqa: BLE001 - the reader must outlive a bad callback
            if not self._callback_error_logged:
                self._callback_error_logged = True
                _log.exception("the HID reader's report callback failed")

    def _lost(self):
        """A device went away: whatever the cap was doing, it is released."""
        with self._lock:
            self._axes = dict.fromkeys(AXES, 0.0)
            merged = dict(self._axes)
        self._emit(time.monotonic(), merged, [])

    def _run(self):
        while not self._stop.is_set():
            try:
                devs = find_devices()
            except Exception as e:                         # noqa: BLE001 - shown in the panel
                self.error, devs = repr(e), []
            if not devs:
                self.devices = []
                self._stop.wait(2.0)
                continue
            self.error = ""
            threads = [threading.Thread(target=self._read, args=(d,), daemon=True) for d in devs]
            self.devices = [d.name for d in devs]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            for d in devs:
                d.close()
            self.devices = []
            self._lost()
            if not self._stop.is_set():
                self._stop.wait(1.0)                       # unplugged / out of range: look again shortly

    def _read(self, dev):
        a = _api()
        fh = a.k32.CreateFileW(dev.path, 0x80000000, 3, None, 3, 0x40000000, None)  # GENERIC_READ, shared, overlapped
        if fh in (None, a.INVALID):
            self.error = f"cannot read {dev.name} (error {C.get_last_error()})"
            return
        ev = a.k32.CreateEventW(None, True, False, None)
        ovl = a.OVL(hEvent=ev)
        buf = (C.c_ubyte * max(dev.in_len, 64))()
        got = a.W.DWORD()
        try:
            while not self._stop.is_set():
                a.k32.ResetEvent(ev)
                ok = a.k32.ReadFile(fh, buf, dev.in_len, None, C.byref(ovl))
                if not ok and C.get_last_error() != 997:   # ERROR_IO_PENDING
                    self.error = f"{dev.name}: read error {C.get_last_error()}"
                    return
                while not self._stop.is_set() and a.k32.WaitForSingleObject(ev, 200) != 0:
                    pass
                if self._stop.is_set():
                    a.k32.CancelIoEx(fh, C.byref(ovl))
                    a.k32.GetOverlappedResult(fh, C.byref(ovl), C.byref(got), True)
                    return
                if not a.k32.GetOverlappedResult(fh, C.byref(ovl), C.byref(got), False):
                    self.error = f"{dev.name}: disconnected (error {C.get_last_error()})"
                    return
                axes, buttons, battery = dev.decode(bytes(buf[:got.value]))
                self.feed(axes, buttons, battery)
        finally:
            a.k32.CloseHandle(ev)
            a.k32.CloseHandle(fh)
