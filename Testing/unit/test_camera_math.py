import numpy as np

from MouseNav3DLib import camera_math as cm


def test_roundtrip():
    rng = np.random.default_rng(1)
    for _ in range(20):
        p = rng.normal(size=3) * 100
        f = rng.normal(size=3) * 100
        u = rng.normal(size=3)
        A = cm.camera_to_affine(p, f, u)
        p2, f2, u2 = cm.affine_to_camera(A, float(np.linalg.norm(f - p)))
        d = (f - p) / np.linalg.norm(f - p)
        u_ortho = u - np.dot(u, d) * d
        u_ortho /= np.linalg.norm(u_ortho)
        assert np.allclose(p2, p, atol=1e-9)
        assert np.allclose(f2, f, atol=1e-9)
        assert np.allclose(u2, u_ortho, atol=1e-9)


def test_navlib_layout():
    rng = np.random.default_rng(2)
    A = cm.camera_to_affine(rng.normal(size=3), rng.normal(size=3), rng.normal(size=3))
    m = cm.to_navlib(A)
    assert len(m) == 16
    assert np.array_equal(np.array(m[12:15]), A[:3, 3])
    assert np.array_equal(cm.from_navlib(m), A)


def test_front_view_looks_from_anterior():
    A = cm.from_navlib(cm.FRONT_VIEW)
    assert np.allclose(A[:3, 2], (0, 1, 0))
    assert np.allclose(A[:3, 1], (0, 0, 1))
    assert np.allclose(A[:3, 0], (-1, 0, 0))


def test_coordinate_system_constant():
    assert cm.COORDINATE_SYSTEM == (1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1)


def test_safe_extents_empty():
    lo, hi = cm.safe_extents((1, -1, 1, -1, 1, -1))
    assert np.allclose(lo, (-0.5, -0.5, -0.5))
    assert np.allclose(hi, (0.5, 0.5, 0.5))
    lo, hi = cm.safe_extents((0, 0, 0, 0, 0, 0))
    assert np.all(hi - lo >= 1.0 - 1e-12)


def test_safe_extents_normal():
    lo, hi = cm.safe_extents((0, 10, -5, 5, 2, 4))
    assert np.allclose(lo, (0, -5, 2))
    assert np.allclose(hi, (10, 5, 4))


def test_degenerate_inputs_stay_finite():
    for pos, foc, up in [((1, 2, 3), (1, 2, 3), (0, 0, 1)),     # position == focal point
                         ((0, 0, 0), (0, 0, 5), (0, 0, 1)),     # view-up parallel to direction
                         ((0, 0, 0), (0, 0, 5), (0, 0, -2)),    # anti-parallel
                         ((0, 0, 0), (0, 5, 0), (0, 0, 0))]:    # zero view-up
        A = cm.camera_to_affine(pos, foc, up)
        assert np.all(np.isfinite(A))
        assert np.allclose(A[:3, :3].T @ A[:3, :3], np.eye(3), atol=1e-9)
