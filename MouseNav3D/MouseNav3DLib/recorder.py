"""Pure-Python JSON-lines recorder for the navlib spike (no slicer/qt/vtk)."""
import json
import os
import time


def json_safe(value):
    """tuples/lists -> lists, numbers/str/bool/None as is, numpy values -> Python, anything else -> repr."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else repr(value)
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if hasattr(value, "tolist"):  # numpy scalars and arrays
        return json_safe(value.tolist())
    return repr(value)


class JsonlRecorder:
    """Callable recorder(kind, name, value): buffers one JSON line per call, writes the buffer to disk at least every
    `flush_interval` seconds (checked on each call) and on close()."""

    def __init__(self, path, main_thread, thread_id, flush_interval=0.5, clock=time.perf_counter):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.main_thread = main_thread
        self._thread_id = thread_id  # callable returning the current thread id
        self._clock = clock
        self._flush_interval = flush_interval
        self._file = open(path, "w", encoding="utf-8")
        self._buffer = []
        self._last_flush = clock()
        self.lines = 0

    def __call__(self, kind, name, value):
        if self._file is None:
            return
        t = self._clock()
        tid = self._thread_id()
        self._buffer.append(json.dumps({"t": t, "kind": kind, "name": name, "value": json_safe(value),
                                        "thread": tid, "main": tid == self.main_thread}))
        self.lines += 1
        if t - self._last_flush >= self._flush_interval:
            self.flush()

    def flush(self):
        if self._file is None:
            return
        if self._buffer:
            self._file.write("\n".join(self._buffer) + "\n")
            self._buffer.clear()
        self._file.flush()
        self._last_flush = self._clock()

    def close(self):
        if self._file is None:
            return
        self.flush()
        self._file.close()
        self._file = None
