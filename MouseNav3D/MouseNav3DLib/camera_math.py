"""Camera <-> affine conversions and navlib matrix layout. numpy only (no slicer/vtk imports)."""
import numpy as np

# Slicer RAS is Z-up like FreeCAD, so FreeCAD's coordinate-system matrix applies unchanged.
COORDINATE_SYSTEM = (1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1)

# Camera-to-world looking from anterior (camera on +y looking -y), superior up:
# columns right=(-1,0,0), up=(0,0,1), back=(0,1,0), position=origin.
FRONT_VIEW = (-1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1)


def camera_to_affine(position, focal_point, view_up):
    """4x4 camera-to-world; columns are right, up, back (= -direction of projection), position.

    Degenerate input never yields NaN: position == focal point looks along -y (back = +y, the front view's
    direction); a zero or parallel view-up falls back to the first world axis (z, y, x) not parallel to back.
    """
    position = np.asarray(position, dtype=float)
    back = position - np.asarray(focal_point, dtype=float)
    n = np.linalg.norm(back)
    back = back / n if n > 1e-12 else np.array([0.0, 1.0, 0.0])
    up = np.asarray(view_up, dtype=float)
    right = np.cross(up, back)
    if np.linalg.norm(right) < 1e-9 * max(1.0, np.linalg.norm(up)):
        for axis in np.eye(3)[[2, 1, 0]]:
            right = np.cross(axis, back)
            if np.linalg.norm(right) > 1e-3:
                break
    right /= np.linalg.norm(right)
    up = np.cross(back, right)
    affine = np.eye(4)
    affine[:3, 0], affine[:3, 1], affine[:3, 2], affine[:3, 3] = right, up, back, position
    return affine


def affine_to_camera(affine, focal_distance):
    """Return (position, focal point, view-up) for a camera-to-world affine."""
    affine = np.asarray(affine, dtype=float)
    position = affine[:3, 3].copy()
    return position, position - focal_distance * affine[:3, 2], affine[:3, 1].copy()


def to_navlib(affine):
    """16 values m00..m33, column-major (translation at indices 12..14)."""
    return tuple(float(v) for v in np.asarray(affine, dtype=float).flatten(order="F"))


def from_navlib(m16):
    return np.array(m16, dtype=float).reshape(4, 4, order="F")


def safe_extents(bounds6):
    """(min, max) from VTK bounds (xmin,xmax,ymin,ymax,zmin,zmax); never empty or flat."""
    b = np.asarray(bounds6, dtype=float)
    lo, hi = b[0::2].copy(), b[1::2].copy()
    if not (np.all(np.isfinite(b)) and np.all(lo <= hi)):
        return np.full(3, -0.5), np.full(3, 0.5)
    for i in range(3):
        if hi[i] - lo[i] < 1.0:
            mid = 0.5 * (hi[i] + lo[i])
            lo[i], hi[i] = mid - 0.5, mid + 0.5
    return lo, hi
