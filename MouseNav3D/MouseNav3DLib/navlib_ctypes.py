# Python declarations of the 3Dconnexion Navigation Library interface, derived from navlib.h / navlib_types.h as
# published in FreeCAD (src/3rdParty/3Dconnexion), Copyright (c) 2014-2023 3Dconnexion, released under the GNU
# Library General Public License; this file is LGPL-2.1-or-later.
#
# This file is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser General
# Public License as published by the Free Software Foundation; either version 2.1 of the License, or (at your option)
# any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License
# for more details: LICENSE-LGPL.txt (in the repository root, and in the module's Resources folder when installed).
#
# This module imports nothing from slicer, qt or vtk. It declares the structures, constants and function signatures,
# loads the driver library if it is installed, and offers `Connection`, which owns every ctypes object the driver
# may call back into until `close()`.
import ctypes
import errno
import logging
import sys

_log = logging.getLogger("MouseNav3D")

# --- propertyType_t ----------------------------------------------------------------------------------------------
(VOIDPTR, BOOL, LONG, FLOAT, DOUBLE, POINT, VECTOR, MATRIX, STRING, ACTIONNODEEX, PLANE, BOX, FRUSTUM, CSTR,
 IMAGEARRAY) = range(15)

# --- nlOptions_t -------------------------------------------------------------------------------------------------
NONQUEUED_MESSAGES = 1
ROW_MAJOR_ORDER = 2
NO_UI = 4

# --- SiActionNodeType_t ------------------------------------------------------------------------------------------
ACTIONSET_NODE, CATEGORY_NODE, ACTION_NODE = range(3)

FACILITY_NAVLIB = 4


def result_code(errc):
    """navlib make_result_code: values <= 0 pass through, positive errno values get facility 4 and the error bit."""
    if errc <= 0:
        return errc
    code = (errc & 0xFFFF) | (FACILITY_NAVLIB << 16) | 0x80000000
    return code - (1 << 32)  # the header returns a signed 32-bit long


NO_DATA = result_code(errno.ENODATA)
NOT_SUPPORTED = result_code(errno.ENOSYS)

# --- property names (navlib.h) -----------------------------------------------------------------------------------
ACTIVE = "active"
FOCUS = "focus"
MOTION = "motion"
COORDINATE_SYSTEM = "coordinateSystem"
TRANSACTION = "transaction"
FRAME_TIME = "frame.time"
FRAME_TIMING_SOURCE = "frame.timingSource"
DEVICE_PRESENT = "device.present"
COMMANDS_TREE = "commands.tree"
COMMANDS_ACTIVE_COMMAND = "commands.activeCommand"
COMMANDS_ACTIVE_SET = "commands.activeSet"
IMAGES = "images"
VIEW_AFFINE = "view.affine"
VIEW_CONSTRUCTION_PLANE = "view.constructionPlane"
VIEW_EXTENTS = "view.extents"
VIEW_FOV = "view.fov"
VIEW_FRUSTUM = "view.frustum"
VIEW_PERSPECTIVE = "view.perspective"
VIEW_TARGET = "view.target"
VIEW_ROTATABLE = "view.rotatable"
VIEW_FOCUS_DISTANCE = "view.focusDistance"
VIEWS_FRONT = "views.front"
PIVOT_POSITION = "pivot.position"
PIVOT_USER = "pivot.user"
PIVOT_VISIBLE = "pivot.visible"
HIT_LOOKFROM = "hit.lookfrom"
HIT_DIRECTION = "hit.direction"
HIT_APERTURE = "hit.aperture"
HIT_LOOKAT = "hit.lookat"
HIT_SELECTION_ONLY = "hit.selectionOnly"
SELECTION_AFFINE = "selection.affine"
SELECTION_EMPTY = "selection.empty"
SELECTION_EXTENTS = "selection.extents"
MODEL_EXTENTS = "model.extents"
MODEL_FLOOR_PLANE = "model.floorPlane"
MODEL_UNITS_TO_METERS = "model.unitsToMeters"
POINTER_POSITION = "pointer.position"
EVENTS_KEY_PRESS = "events.keyPress"
EVENTS_KEY_RELEASE = "events.keyRelease"
SETTINGS = "settings"
SETTINGS_CHANGED = "settings.changed"


# --- structures --------------------------------------------------------------------------------------------------
class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double)]


class Vector(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double)]


class Plane(ctypes.Structure):
    _fields_ = [("n", Vector), ("d", ctypes.c_double)]


class Box(ctypes.Structure):
    _fields_ = [("min", Point), ("max", Point)]


class Frustum(ctypes.Structure):
    _fields_ = [(n, ctypes.c_double) for n in ("left", "right", "bottom", "top", "nearVal", "farVal")]


class Matrix(ctypes.Structure):
    """16 doubles in memory order (m00, m01, ... m33)."""
    _fields_ = [("m", ctypes.c_double * 16)]


class StringT(ctypes.Structure):
    _fields_ = [("p", ctypes.c_void_p), ("length", ctypes.c_size_t)]


class CstrT(ctypes.Structure):
    _fields_ = [("p", ctypes.c_void_p), ("length", ctypes.c_size_t)]


class ImageArrayT(ctypes.Structure):
    _fields_ = [("p", ctypes.c_void_p), ("count", ctypes.c_size_t)]


class ActionNode(ctypes.Structure):
    """SiActionNodeEx_t"""


ActionNode._fields_ = [
    ("size", ctypes.c_uint32),
    ("type", ctypes.c_int),
    ("next", ctypes.POINTER(ActionNode)),
    ("children", ctypes.POINTER(ActionNode)),
    ("id", ctypes.c_char_p),
    ("label", ctypes.c_char_p),
    ("description", ctypes.c_char_p),
]


class _ValueUnion(ctypes.Union):
    _fields_ = [
        ("p", ctypes.c_void_p),
        ("b", ctypes.c_uint32),
        ("l", ctypes.c_long),  # C long: 32-bit on Windows, 64-bit on Linux/Mac
        ("f", ctypes.c_float),
        ("d", ctypes.c_double),
        ("point", Point),
        ("vector", Vector),
        ("plane", Plane),
        ("box", Box),
        ("frustum", Frustum),
        ("matrix", Matrix),
        ("pnode", ctypes.POINTER(ActionNode)),
        ("string", StringT),
        ("cstr", CstrT),
        ("imagearray", ImageArrayT),
    ]


class Value(ctypes.Structure):
    """value_t: type tag plus anonymous union."""
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_int), ("u", _ValueUnion)]


GETTER_T = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_uint64, ctypes.c_char_p, ctypes.POINTER(Value))
SETTER_T = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_uint64, ctypes.c_char_p, ctypes.POINTER(Value))


class Accessor(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("fnGet", GETTER_T), ("fnSet", SETTER_T), ("param", ctypes.c_uint64)]


class CreateOptions(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("bMultiThreaded", ctypes.c_int8), ("options", ctypes.c_int)]


class NoData(Exception):
    """Raised by a getter that has no value to offer; the driver receives NO_DATA."""


class NavlibError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or f"navlib error {code}")
        self.code = code


# --- conversion --------------------------------------------------------------------------------------------------
def fill_value(v, type_id, value):
    """Store a Python value into `v`. Returns an object that must be kept alive while the driver may read `v`."""
    v.type = type_id
    keep = None
    if type_id == BOOL:
        v.b = 1 if value else 0
    elif type_id == LONG:
        n = int(value)
        bits = 8 * ctypes.sizeof(ctypes.c_long)
        if not -(1 << (bits - 1)) <= n < (1 << (bits - 1)):
            raise OverflowError(f"{n} does not fit a C long ({bits} bit)")
        v.l = n
    elif type_id == FLOAT:
        v.f = float(value)
    elif type_id == DOUBLE:
        v.d = float(value)
    elif type_id == POINT:
        v.point.x, v.point.y, v.point.z = (float(c) for c in value)
    elif type_id == VECTOR:
        v.vector.x, v.vector.y, v.vector.z = (float(c) for c in value)
    elif type_id == MATRIX:
        if len(value) != 16:
            raise ValueError("matrix needs 16 values")
        for i, c in enumerate(value):
            v.matrix.m[i] = float(c)
    elif type_id == PLANE:
        v.plane.n.x, v.plane.n.y, v.plane.n.z, v.plane.d = (float(c) for c in value)
    elif type_id == BOX:
        lo, hi = value
        v.box.min.x, v.box.min.y, v.box.min.z = (float(c) for c in lo)
        v.box.max.x, v.box.max.y, v.box.max.z = (float(c) for c in hi)
    elif type_id == FRUSTUM:
        f = v.frustum
        f.left, f.right, f.bottom, f.top, f.nearVal, f.farVal = (float(c) for c in value)
    elif type_id in (CSTR, STRING):
        data = value.encode("utf-8")
        keep = ctypes.create_string_buffer(data)  # NUL-terminated; length excludes the terminator
        target = v.cstr if type_id == CSTR else v.string
        target.p = ctypes.addressof(keep)
        target.length = len(data)
    elif type_id == ACTIONNODEEX:
        if isinstance(value, ActionNode):
            value = ctypes.pointer(value)
        v.pnode = value
        keep = value
    elif type_id == VOIDPTR:
        v.p = int(value) if value else None
    else:
        raise ValueError(f"unsupported property type {type_id}")
    return keep


def value_to_python(v):
    t = v.type
    if t == BOOL:
        return bool(v.b)
    if t == LONG:
        return int(v.l)
    if t == FLOAT:
        return float(v.f)
    if t == DOUBLE:
        return float(v.d)
    if t == POINT:
        return (v.point.x, v.point.y, v.point.z)
    if t == VECTOR:
        return (v.vector.x, v.vector.y, v.vector.z)
    if t == MATRIX:
        return tuple(v.matrix.m)
    if t == PLANE:
        return (v.plane.n.x, v.plane.n.y, v.plane.n.z, v.plane.d)
    if t == BOX:
        b = v.box
        return ((b.min.x, b.min.y, b.min.z), (b.max.x, b.max.y, b.max.z))
    if t == FRUSTUM:
        f = v.frustum
        return (f.left, f.right, f.bottom, f.top, f.nearVal, f.farVal)
    if t in (CSTR, STRING):
        s = v.cstr if t == CSTR else v.string
        if not s.p:
            return ""
        return ctypes.string_at(s.p, s.length).decode("utf-8", "replace")
    if t == ACTIONNODEEX:
        return v.pnode
    if t == VOIDPTR:
        return v.p or 0
    raise ValueError(f"unsupported property type {t}")


# --- library -----------------------------------------------------------------------------------------------------
_MAC_PATH = "/Library/Frameworks/3DconnexionNavlib.framework/3DconnexionNavlib"


def load_library():
    """The navlib CDLL (C calling convention) with signatures set, or None if the driver is not installed."""
    try:
        if sys.platform == "win32":
            lib = ctypes.CDLL("TDxNavLib")
        elif sys.platform == "darwin":
            lib = ctypes.CDLL(_MAC_PATH)
        else:
            return None
        lib.NlCreate.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p, ctypes.POINTER(Accessor),
                                 ctypes.c_size_t, ctypes.POINTER(CreateOptions)]
        lib.NlCreate.restype = ctypes.c_long
        lib.NlClose.argtypes = [ctypes.c_uint64]
        lib.NlClose.restype = ctypes.c_long
        lib.NlReadValue.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.POINTER(Value)]
        lib.NlReadValue.restype = ctypes.c_long
        lib.NlWriteValue.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.POINTER(Value)]
        lib.NlWriteValue.restype = ctypes.c_long
        return lib
    except Exception as exc:
        _log.debug("navlib library not loaded: %r", exc)
        return None


# --- connection --------------------------------------------------------------------------------------------------
class Connection:
    """One navlib instance. getters: name -> (type_id, fn() -> value); setters: name -> fn(value).

    Without a library (lib is None) the accessors are still built, so callbacks can be exercised, but no connection
    is made: `handle` is 0 and `create_result` is NOT_SUPPORTED.

    The callbacks, accessor array, name buffers and last-returned value buffers stay referenced by this object, so
    they outlive the driver's use of them; keep the Connection itself alive until after close().

    Buffers and nodes handed to the driver (getter results, written values) are kept per property until that property's
    next getter/write call replaces them, and are all released in close(). Replacing is safe because, in single-threaded
    mode, the callbacks run synchronously on the calling thread. read() does not support STRING/CSTR (the driver owns
    that memory).
    """

    def __init__(self, app_name, getters, setters, lib):
        self._lib = lib
        self._closed = False
        self._logged = set()
        self._getters = dict(getters)
        self._setters = dict(setters)
        self._keep = {}  # last buffer / node handed to the driver, per property
        self._app_name = app_name.encode("utf-8")
        self.handle = 0
        self.create_result = NOT_SUPPORTED

        names = list(dict.fromkeys(list(self._getters) + list(self._setters)))
        self._names = [n.encode("ascii") for n in names]
        self._get_cb = GETTER_T(self._on_get)
        self._set_cb = SETTER_T(self._on_set)
        self.accessors = (Accessor * max(len(names), 1))()
        for i, n in enumerate(names):
            acc = self.accessors[i]
            acc.name = self._names[i]
            if n in self._getters:
                acc.fnGet = self._get_cb
            if n in self._setters:
                acc.fnSet = self._set_cb
            acc.param = 0
        self._count = len(names)
        self._options = CreateOptions(size=ctypes.sizeof(CreateOptions), bMultiThreaded=0, options=0)

        if lib is not None:
            handle = ctypes.c_uint64(0)
            self.create_result = lib.NlCreate(ctypes.byref(handle), self._app_name, self.accessors, self._count,
                                              ctypes.byref(self._options))
            self.handle = int(handle.value) if self.create_result == 0 else 0

    def _log_once(self, name, exc):
        if name not in self._logged:
            self._logged.add(name)
            _log.warning("navlib callback for %s failed: %r", name, exc)

    def _on_get(self, _param, name, value_ptr):
        key = name.decode("ascii", "replace") if name else ""
        try:
            type_id, fn = self._getters[key]
            self._keep[key] = fill_value(value_ptr.contents, type_id, fn())
            return 0
        except NoData:
            return NO_DATA
        except BaseException as exc:  # a Python exception must never unwind into the driver
            self._log_once(key, exc)
            return NO_DATA

    def _on_set(self, _param, name, value_ptr):
        key = name.decode("ascii", "replace") if name else ""
        try:
            self._setters[key](value_to_python(value_ptr.contents))
            return 0
        except NoData:
            return NO_DATA
        except BaseException as exc:
            self._log_once(key, exc)
            return NO_DATA

    def write(self, name, type_id, value):
        if not self.handle or self._lib is None:
            return NOT_SUPPORTED
        v = Value()
        # The driver may keep reading the tree/string after the call returns: retain until replaced or close().
        self._keep[("write", name)] = fill_value(v, type_id, value)
        return self._lib.NlWriteValue(self.handle, name.encode("ascii"), ctypes.byref(v))

    def read(self, name, type_id):
        if not self.handle or self._lib is None:
            raise NavlibError(NOT_SUPPORTED, "not connected")
        v = Value()
        v.type = type_id
        rc = self._lib.NlReadValue(self.handle, name.encode("ascii"), ctypes.byref(v))
        if rc != 0:
            raise NavlibError(rc, f"NlReadValue({name}) returned {rc}")
        return value_to_python(v)

    def close(self):
        """Close the driver connection. Callbacks stay referenced by this object, which the owner drops afterwards."""
        if self._closed:
            return
        self._closed = True
        handle, self.handle = self.handle, 0
        if handle and self._lib is not None:
            rc = self._lib.NlClose(handle)
            if rc != 0:
                _log.warning("NlClose returned %s", rc)
        self._keep.clear()
