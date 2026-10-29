"""Linux reader: the open-source spacenav daemon's local socket (the protocol Blender and FreeCAD use through libspnav),
spoken directly in Python. Nothing here needs Linux to import; the socket is only opened by `Reader`.

Protocol: connect to the AF_UNIX stream socket /var/run/spnav.sock (/run/spnav.sock on newer systems). The daemon
writes events of 8 native-endian int32:
    [0, x, y, z, rx, ry, rz, period]   motion (counts, about +-350 at full deflection; period in ms)
    [1, button, ...]                   button press
    [2, button, ...]                   button release
(other types are configuration replies and are ignored). libspnav numbers buttons from 0; this reader reports them
from 1, like the Windows reader, so button 1 = fit and button 2 = rotation lock on both.

Axis frame: spacenavd's x right, y up, z toward the user, rotations about those. That is the frame fallback/motion.py uses,
so the counts are only divided by 350 (SPNAV_SIGNS holds one sign per axis, all +1). This frame is from the daemon's
documentation and libspnav's behaviour as recalled; it could NOT be checked on a Linux machine (none available), so
the sign table is the one place to fix if a direction is wrong.
"""
import logging
import socket
import struct
import threading
import time

_log = logging.getLogger("MouseNav3D")

AXES = ("tx", "ty", "tz", "rx", "ry", "rz")
FULL = 350.0
SPNAV_SIGNS = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
SOCKET_PATHS = ("/var/run/spnav.sock", "/run/spnav.sock")
PACKET = struct.Struct("=8i")
EV_MOTION, EV_PRESS, EV_RELEASE = 0, 1, 2
THREAD_NAME = "MouseNav3D spacenavd reader"
DEVICE_NAME = "3D mouse (spacenavd)"


def decode_packet(data):
    """One 32-byte packet -> ("motion", {axis: -1..1}) | ("press", n) | ("release", n) | None (unknown type)."""
    values = PACKET.unpack(bytes(data))
    kind = values[0]
    if kind == EV_MOTION:
        axes = {}
        for name, sign, v in zip(AXES, SPNAV_SIGNS, values[1:7]):
            axes[name] = max(-1.0, min(1.0, sign * v / FULL))
        return "motion", axes
    if kind in (EV_PRESS, EV_RELEASE):
        return ("press" if kind == EV_PRESS else "release"), values[1] + 1
    return None


class PacketBuffer:
    """Reassembles the byte stream into whole packets (recv may split or join them)."""

    def __init__(self):
        self._data = b""

    def feed(self, chunk):
        self._data += chunk
        n = len(self._data) // PACKET.size
        packets = [self._data[i * PACKET.size:(i + 1) * PACKET.size] for i in range(n)]
        self._data = self._data[n * PACKET.size:]
        return packets


class Reader:
    """A background thread reading the daemon's socket; reconnects every 2 s while it is not there. Every packet calls
    `on_report(t, axes, buttons)` from the reader thread: t = time.monotonic(); axes = the six axes (a motion packet)
    or {} (a button packet); buttons = the buttons now held (a button packet) or None. `connect()` returns a
    socket-like object with settimeout/recv/close (tests replace it)."""

    def __init__(self, connect=None):
        self.on_report = None
        self.battery = None                                # the daemon does not report it
        self.devices = []
        self.error = ""
        self.reports = 0
        self._callback_error_logged = False
        self._connect = connect or self._connect_socket
        self._held = set()
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _connect_socket():
        last = OSError("no spacenavd socket path")
        for path in SOCKET_PATHS:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(path)
                return s
            except OSError as e:
                last = e
                s.close()
        raise last

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
            self._thread.start()

    def stop(self, wait=2.0):
        """Stop the thread; True when it is gone."""
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

    def handle(self, packet, t=None):
        """Decode one packet and call on_report."""
        decoded = decode_packet(packet)
        if decoded is None:
            return
        self.reports += 1
        kind, payload = decoded
        axes, buttons = {}, None
        if kind == "motion":
            axes = payload
        else:
            if kind == "press":
                self._held.add(payload)
            else:
                self._held.discard(payload)
            buttons = sorted(self._held)
        self._emit(time.monotonic() if t is None else t, axes, buttons)

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
                _log.exception("the spacenavd reader's report callback failed")

    def _run(self):
        while not self._stop.is_set():
            try:
                sock = self._connect()
            except OSError as e:
                self.error = f"spacenavd not reachable ({e.__class__.__name__})"
                self.devices = []
                self._stop.wait(2.0)
                continue
            self.error = ""
            self.devices = [DEVICE_NAME]
            try:
                self._read(sock)
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
                self.devices = []
                self._held.clear()
                self._emit(time.monotonic(), dict.fromkeys(AXES, 0.0), [])  # connection gone: the cap is released
            if not self._stop.is_set():
                self._stop.wait(1.0)

    def _read(self, sock):
        buf = PacketBuffer()
        sock.settimeout(0.2)                               # so stop() is noticed
        while not self._stop.is_set():
            try:
                chunk = sock.recv(PACKET.size * 16)
            except socket.timeout:
                continue
            except OSError as e:
                self.error = f"spacenavd: {e.__class__.__name__}"
                return
            if not chunk:
                self.error = "spacenavd closed the connection"
                return
            for packet in buf.feed(chunk):
                self.handle(packet)
