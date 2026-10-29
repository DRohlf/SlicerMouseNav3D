"""A reader whose thread outlives the join timeout must still report running, and start() must not add a second
reader thread next to the stuck one. The thread is a stand-in that never finishes."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "MouseNav3D"))
from MouseNav3DLib.fallback import hid_windows, spacenavd


class StuckThread:
    started = 0

    def is_alive(self):
        return True

    def join(self, _wait=None):
        pass

    def start(self):
        StuckThread.started += 1


@pytest.mark.parametrize("module", [hid_windows, spacenavd])
def test_stop_timeout_keeps_the_thread_and_refuses_a_second_reader(module, monkeypatch):
    reader = module.Reader()
    stuck = StuckThread()
    reader._thread = stuck
    assert reader.stop(wait=0) is False
    assert reader.running is True and reader._thread is stuck
    made = []
    monkeypatch.setattr(module.threading, "Thread", lambda *a, **k: made.append(1) or StuckThread())
    reader.start()
    assert made == []


@pytest.mark.parametrize("module", [hid_windows, spacenavd])
def test_stop_of_a_finished_reader_clears_the_thread(module):
    reader = module.Reader()
    assert reader.stop(wait=0) is True and reader._thread is None and not reader.running
