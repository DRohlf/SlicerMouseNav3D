import math

from MouseNav3DLib.slice_bridge import step_planes


def test_one_mm_with_third_mm_spacing_steps_three_planes():
    planes, rest = step_planes(1.0, 0.333)
    assert planes == 3
    assert math.isclose(rest, 0.001, abs_tol=1e-9)


def test_small_motion_steps_nothing_and_is_carried():
    assert step_planes(0.2, 0.333) == (0, 0.2)


def test_negative_motion_steps_toward_zero():
    planes, rest = step_planes(-0.7, 0.333)
    assert planes == -2
    assert math.isclose(rest, -0.034, abs_tol=1e-9)


def test_exact_multiple_survives_rounding():
    assert step_planes(0.999, 0.333)[0] == 3


def test_bad_spacing_falls_back_to_one_mm():
    for bad in (0.0, -1.0, float("nan"), float("inf"), None):
        assert step_planes(2.5, bad)[0] == 2
