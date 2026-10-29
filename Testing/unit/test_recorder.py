import json

from MouseNav3DLib import recorder as rc


def test_json_safe():
    assert rc.json_safe((1.0, (2, 3))) == [1.0, [2, 3]]
    assert rc.json_safe(None) is None
    assert rc.json_safe(object()).startswith("<object")
    assert rc.json_safe(float("nan")) == "nan"
    import numpy as np
    assert rc.json_safe(np.float64(1.5)) == 1.5
    assert rc.json_safe(np.array([1, 2])) == [1, 2]


def test_lines_flush_interval_and_close(tmp_path):
    now = [0.0]
    p = tmp_path / "sub" / "x.jsonl"
    r = rc.JsonlRecorder(str(p), main_thread=7, thread_id=lambda: 7, flush_interval=0.5, clock=lambda: now[0])
    r("get", "view.affine", (1.0, 2.0))
    assert p.read_text() == ""  # buffered
    now[0] = 0.6
    r("set", "motion", True)
    assert len(p.read_text().splitlines()) == 2
    now[0] = 0.7
    r("get", "focus", None)
    r.close()
    rows = [json.loads(s) for s in p.read_text().splitlines()]
    assert [x["name"] for x in rows] == ["view.affine", "motion", "focus"]
    assert rows[0]["value"] == [1.0, 2.0] and rows[0]["main"] is True and rows[2]["value"] is None
    assert r.lines == 3
    r("get", "x", 1)  # after close: ignored
    r.close()
