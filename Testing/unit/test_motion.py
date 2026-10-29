"""Fallback motion: per-axis settings and the report-time integrator (pure Python, no slicer)."""
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "MouseNav3D"))
from MouseNav3DLib.fallback import motion
from MouseNav3DLib.fallback.motion import AXES, AxisSettings, Integrator, apply_settings

ZERO = dict.fromkeys(AXES, 0.0)


def total(d):
    return sum(abs(v) for v in d.values())


def test_axes_order():
    assert AXES == ("tx", "ty", "tz", "rx", "ry", "rz")


def test_per_axis_reverse_and_sensitivity():
    s = AxisSettings(reverse={"rx": True}, sensitivity={"rx": 2.0}, speed=1.0, dead_zone=0.0)
    raw = {"tx": 0.3, "ty": -0.4, "tz": 0.5, "rx": 0.25, "ry": -0.6, "rz": 0.7}
    out = apply_settings(raw, s)
    assert out["rx"] == pytest.approx(-2 * raw["rx"])
    for k in AXES:
        if k != "rx":
            assert out[k] == pytest.approx(raw[k])


def test_speed_and_dead_zone():
    s = AxisSettings(reverse={}, sensitivity={"ty": 0.5}, speed=2.0, dead_zone=0.04)
    out = apply_settings({"tx": 0.03, "ty": 0.5, "tz": -0.04, "rx": 0.041}, s)
    assert out["tx"] == 0.0 and out["tz"] == 0.0           # inside the dead zone (edge included)
    assert out["ty"] == pytest.approx(0.5)                  # 0.5 x 0.5 x 2
    assert out["rx"] == pytest.approx(0.082)
    assert out["ry"] == 0.0 and out["rz"] == 0.0            # missing axes are at rest


def test_default_settings_are_neutral():
    s = AxisSettings()
    assert s.speed == 1.0 and s.dead_zone == motion.DEAD_ZONE
    out = apply_settings({"tx": 0.5}, s)
    assert out["tx"] == pytest.approx(0.5)


def simulate(integ, report_times, take_times, axes):
    """Feed reports and call take in time order; returns the list of (take time, displacement)."""
    events = [(t, 0, "r") for t in report_times] + [(t, 1, "t") for t in take_times]
    events.sort()
    out = []
    for t, _, kind in events:
        if kind == "r":
            integ.feed(t, axes(t))
        else:
            out.append((t, integ.take(t)))
    return out


def test_constant_deflection_even_steps():
    rnd = random.Random(7)
    v = 0.6
    t, reports = 0.0, []
    while t < 1.2:
        reports.append(t)
        t += 1 / 60 + rnd.uniform(-0.004, 0.004)             # jittered arrival
    t, takes = 0.0, [0.0]
    while takes[-1] < 1.0:
        takes.append(min(1.0, takes[-1] + rnd.uniform(0.005, 0.040)))
    integ = Integrator(AxisSettings(dead_zone=0.0))
    res = simulate(integ, reports, takes, lambda _t: {"tx": v, "rz": -v})
    sum_tx = sum(d["tx"] for _, d in res)
    assert sum_tx == pytest.approx(v * 1.0, rel=0.02)
    assert sum(d["rz"] for _, d in res) == pytest.approx(-v * 1.0, rel=0.02)
    prev = takes[0]
    for t_, d in res[1:]:
        share = v * (t_ - prev)
        assert abs(d["tx"]) <= 2 * share + 1e-12
        prev = t_


def test_no_motion_after_release():
    v = 0.5
    integ = Integrator(AxisSettings(dead_zone=0.04))
    for k in range(60):                                       # 60 Hz up to 0.9833
        integ.feed(k / 60, {"tx": v})
    assert integ.take(0.990)["tx"] == pytest.approx(v * 0.990)
    integ.feed(1.000, dict(ZERO))                             # release report
    after = integ.take(1.050)
    assert after["tx"] == pytest.approx(v * 0.010)            # only the 10 ms before the release
    assert integ.idle
    for k in range(1, 20):
        assert total(integ.take(1.050 + 0.008 * k)) == 0.0


def test_release_in_dead_zone_counts_as_release():
    integ = Integrator(AxisSettings(dead_zone=0.04))
    integ.feed(0.0, {"ty": 0.8})
    integ.feed(0.1, {"ty": 0.03, "tx": -0.02})                # the cap springs back into the dead zone
    d = integ.take(0.5)
    assert d["ty"] == pytest.approx(0.8 * 0.1)
    assert total(integ.take(0.9)) == 0.0


def test_stale_counts_as_release():
    integ = Integrator(AxisSettings(dead_zone=0.0))
    integ.feed(0.0, {"ty": 0.4})
    assert integ.take(0.1)["ty"] == pytest.approx(0.04)
    assert integ.take(1.0)["ty"] == pytest.approx(0.4 * (motion.STALE_S - 0.1))
    assert total(integ.take(2.0)) == 0.0
    assert integ.idle


def test_smoothing_is_first_order_and_exact():
    tau = motion.SMOOTH_S
    integ = Integrator(AxisSettings(dead_zone=0.0))
    integ.feed(0.0, {"tx": 1.0})
    integ.feed(0.1, {"tx": 0.0, "ty": 0.0})                   # release: no filter tail
    integ.feed(0.2, {"tx": 0.2})
    integ.feed(0.3, {"tx": 1.0})                              # a change while moving is filtered
    d = integ.take(0.4)
    expected = 0.1 * 1.0 + 0.1 * 0.2 + (1.0 * 0.1 + (0.2 - 1.0) * tau * (1 - math.exp(-0.1 / tau)))
    assert d["tx"] == pytest.approx(expected, rel=1e-9)


def test_takes_split_anywhere_give_the_same_total():
    rnd = random.Random(3)
    reports = [(i / 60, rnd.uniform(-1, 1)) for i in range(60)]
    def run(takes):
        integ = Integrator(AxisSettings(dead_zone=0.0))
        res = simulate(integ, [t for t, _ in reports], takes, lambda t: {"rx": dict(reports)[t]})
        return sum(d["rx"] for _, d in res)
    one = run([0.0, 1.0])
    many = run([0.0] + sorted(rnd.uniform(0.0, 1.0) for _ in range(50)) + [1.0])
    assert many == pytest.approx(one, rel=1e-9, abs=1e-12)


def test_late_report_is_not_applied_to_the_past():
    integ = Integrator(AxisSettings(dead_zone=0.0))
    integ.feed(0.0, {"tx": 1.0})
    assert integ.take(0.1)["tx"] == pytest.approx(0.1)
    integ.feed(0.05, dict(ZERO))                              # stamped before the cursor: takes effect now
    assert total(integ.take(0.2)) == 0.0


def test_settings_change_applies_to_new_reports():
    s = AxisSettings(dead_zone=0.0)
    integ = Integrator(s)
    s.reverse["tx"] = True
    integ.feed(0.0, {"tx": 1.0})
    assert integ.take(0.1)["tx"] == pytest.approx(-0.1)
