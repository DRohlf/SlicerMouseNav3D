"""Failure guards in fallback mode: a raising frame or report callback is logged once, and the frame timer's slot and
the reader threads keep going (pure Python: no Slicer, no device, a fake socket stands in for spacenavd)."""
import logging
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "MouseNav3D"))
from MouseNav3DLib.fallback import hid_windows, motion, spacenavd
from MouseNav3DLib.fallback.navigator import Navigator


def errors(caplog):
    return [r for r in caplog.records if r.name == "MouseNav3D" and r.levelno >= logging.ERROR]


def wait_for(cond, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout and not cond():
        time.sleep(0.005)
    return cond()


def test_raising_apply_is_logged_once_and_the_frame_slot_keeps_running(caplog):
    nav = Navigator(motion.Integrator(), is_active=lambda: True, target=lambda: object())
    calls = []

    def bad_apply(d, bridge=None):
        calls.append(d)
        raise RuntimeError("view deleted")

    nav.apply = bad_apply
    caplog.set_level(logging.ERROR, logger="MouseNav3D")
    nav.handle_report(10.0, {"tx": 1.0}, None)
    for k in range(1, 4):
        nav.tick(10.0 + 0.01 * k)          # must not raise
    assert len(calls) == 3                 # every frame still runs
    assert len(errors(caplog)) == 1        # logged once


def raising_callback(count):
    def cb(_t, _axes, _buttons):
        count.append(1)
        raise ValueError("bad callback")
    return cb


def test_hid_reader_survives_a_raising_callback(caplog):
    caplog.set_level(logging.ERROR, logger="MouseNav3D")
    reader = hid_windows.Reader()
    count = []
    reader.on_report = raising_callback(count)
    reader.feed({"tx": 0.5})               # the read thread's path for every report
    reader.feed(None, [1])
    reader._lost()                         # the release report after a device went away
    assert len(count) == 3 and reader.reports == 2
    assert len(errors(caplog)) == 1


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        time.sleep(0.01)
        raise socket.timeout()

    def close(self):
        pass


def test_spacenavd_reader_thread_survives_a_raising_callback(caplog):
    caplog.set_level(logging.ERROR, logger="MouseNav3D")
    packets = [struct.pack("=8i", 0, 350, 0, 0, 0, 0, 0, 16), struct.pack("=8i", 1, 0, 0, 0, 0, 0, 0, 0),
               struct.pack("=8i", 2, 0, 0, 0, 0, 0, 0, 0)]
    connects = []

    def connect():
        connects.append(1)
        return FakeSocket(packets)

    reader = spacenavd.Reader(connect=connect)
    count = []
    reader.on_report = raising_callback(count)
    reader.start()
    try:
        assert wait_for(lambda: reader.reports >= 3)
        time.sleep(0.05)
        assert reader.running and len(connects) == 1   # not killed, not reconnected
        assert len(count) == 3
        assert len(errors(caplog)) == 1
    finally:
        assert reader.stop() is True
