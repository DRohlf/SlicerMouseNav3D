"""spacenavd packet decoding and the reader loop, with synthetic bytes (this PC is Windows: the socket itself is not
opened; a fake socket stands in)."""
import os
import socket
import struct
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "MouseNav3D"))
from MouseNav3DLib.fallback import spacenavd as sp


def pkt(*vals):
    vals = list(vals) + [0] * (8 - len(vals))
    return struct.pack("=8i", *vals)


def test_motion_packet_axes_normalised_by_350():
    kind, axes = sp.decode_packet(pkt(0, 350, -175, 70, -350, 35, 700, 16))
    assert kind == "motion"
    assert axes == {"tx": 1.0, "ty": -0.5, "tz": pytest.approx(0.2), "rx": -1.0, "ry": pytest.approx(0.1), "rz": 1.0}


def test_buttons_are_numbered_from_one():
    assert sp.decode_packet(pkt(1, 0)) == ("press", 1)
    assert sp.decode_packet(pkt(2, 1)) == ("release", 2)


def test_unknown_type_ignored():
    assert sp.decode_packet(pkt(7, 1, 2, 3)) is None


def test_stream_reassembly():
    b = sp.PacketBuffer()
    data = pkt(0, 1) + pkt(1, 0) + pkt(2, 0)
    assert b.feed(data[:10]) == []
    out = b.feed(data[10:40])
    assert len(out) == 1 and out[0] == pkt(0, 1)
    out += b.feed(data[40:])
    assert len(out) == 3 and out[2] == pkt(2, 0)


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        time.sleep(0.01)
        raise socket.timeout()

    def close(self):
        self.closed = True


def wait_for(cond, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout and not cond():
        time.sleep(0.005)
    return cond()


def test_reader_dispatches_reports_and_stops_cleanly():
    first = pkt(0, 350, 0, 0, 0, 0, 0, 16) + pkt(1, 0)[:5]          # a packet split across two recv calls
    second = pkt(1, 0)[5:] + pkt(1, 1) + pkt(2, 0)
    sock = FakeSocket([first, second])
    got = []
    r = sp.Reader(connect=lambda: sock)
    r.on_report = lambda t, axes, buttons: got.append((t, axes, buttons))
    before = threading.active_count()
    r.start()
    assert wait_for(lambda: len(got) >= 4)
    assert r.devices == [sp.DEVICE_NAME] and r.running
    assert got[0][1]["tx"] == 1.0 and got[0][2] is None
    assert got[1][1] == {} and got[1][2] == [1]
    assert got[2][2] == [1, 2]
    assert got[3][2] == [2]
    assert r.stop() is True
    assert not r.running and sock.closed
    assert threading.active_count() == before
    assert got[-1][1] == dict.fromkeys(sp.AXES, 0.0) and got[-1][2] == []   # released when the connection ended


def test_reader_without_daemon_keeps_looking_and_stops():
    def refuse():
        raise FileNotFoundError("no socket")
    r = sp.Reader(connect=refuse)
    r.start()
    assert wait_for(lambda: r.error != "")
    assert r.devices == [] and "not reachable" in r.error
    assert r.stop() is True
