import ctypes
import errno
import logging

import pytest

from MouseNav3DLib import navlib_ctypes as nl


def test_struct_sizes():
    assert ctypes.sizeof(nl.Matrix) == 128
    assert ctypes.sizeof(nl.Box) == 48
    # Hard-coded for 64-bit; the union is dominated by the 128-byte matrix, so C long width does not matter.
    assert ctypes.sizeof(nl.Value) == 8 + 128
    assert ctypes.sizeof(nl.Accessor) == 32
    assert ctypes.sizeof(nl.ActionNode) == 48
    assert ctypes.sizeof(nl.CreateOptions) == 12


SAMPLES = {
    nl.BOOL: True,
    nl.LONG: -12345,
    nl.FLOAT: 0.5,
    nl.DOUBLE: 1.0 / 3.0,
    nl.POINT: (1.0, -2.0, 3.5),
    nl.VECTOR: (0.0, 0.25, -1.0),
    nl.MATRIX: tuple(float(i) / 7.0 for i in range(16)),
    nl.PLANE: (0.0, 0.0, 1.0, -4.0),
    nl.BOX: ((-1.0, -2.0, -3.0), (4.0, 5.0, 6.0)),
    nl.FRUSTUM: (-1.0, 1.0, -0.5, 0.5, 0.1, 100.0),
    nl.CSTR: "hello",
    nl.STRING: "world",
}


@pytest.mark.parametrize("type_id", sorted(SAMPLES))
def test_value_roundtrip(type_id):
    v = nl.Value()
    keep = nl.fill_value(v, type_id, SAMPLES[type_id])
    assert v.type == type_id
    assert nl.value_to_python(v) == SAMPLES[type_id]
    del keep


def test_value_roundtrip_node_and_voidptr():
    node = nl.ActionNode()
    v = nl.Value()
    keep = nl.fill_value(v, nl.ACTIONNODEEX, ctypes.pointer(node))
    out = nl.value_to_python(v)
    assert ctypes.addressof(out.contents) == ctypes.addressof(node)
    v2 = nl.Value()
    nl.fill_value(v2, nl.VOIDPTR, 0x1234)
    assert nl.value_to_python(v2) == 0x1234
    del keep


def test_result_code():
    assert nl.NO_DATA < 0
    assert (nl.NO_DATA & 0xFFFF) == errno.ENODATA
    assert (nl.NOT_SUPPORTED & 0xFFFF) == errno.ENOSYS
    assert nl.result_code(0) == 0
    assert nl.result_code(-5) == -5
    assert nl.result_code(errno.ENODATA) == nl.NO_DATA


def _call_get(conn, name, value):
    for acc in conn.accessors:
        if acc.name == name.encode():
            return acc.fnGet(acc.param, acc.name, ctypes.byref(value))
    raise KeyError(name)


def _call_set(conn, name, value):
    for acc in conn.accessors:
        if acc.name == name.encode():
            return acc.fnSet(acc.param, acc.name, ctypes.byref(value))
    raise KeyError(name)


def test_getter_through_c_pointer():
    conn = nl.Connection("t", {nl.VIEW_EXTENTS: (nl.BOX, lambda: ((0, 0, 0), (1, 2, 3)))}, {}, None)
    v = nl.Value()
    assert _call_get(conn, nl.VIEW_EXTENTS, v) == 0
    assert nl.value_to_python(v) == ((0.0, 0.0, 0.0), (1.0, 2.0, 3.0))
    conn.close()


def test_nodata_getter_returns_no_data():
    def getter():
        raise nl.NoData()

    conn = nl.Connection("t", {nl.PIVOT_POSITION: (nl.POINT, getter)}, {}, None)
    assert _call_get(conn, nl.PIVOT_POSITION, nl.Value()) == nl.NO_DATA
    conn.close()


def test_callback_exception_returns_no_data(caplog):
    def getter():
        raise RuntimeError("boom")

    conn = nl.Connection("t", {nl.VIEW_AFFINE: (nl.MATRIX, getter)}, {}, None)
    with caplog.at_level(logging.WARNING, logger="MouseNav3D"):
        assert _call_get(conn, nl.VIEW_AFFINE, nl.Value()) == nl.NO_DATA
        assert _call_get(conn, nl.VIEW_AFFINE, nl.Value()) == nl.NO_DATA
    records = [r for r in caplog.records if r.name == "MouseNav3D"]
    assert len(records) == 1
    conn.close()


def test_setter_receives_python_value_and_exception_is_contained(caplog):
    got = []

    def bad(_):
        raise ValueError("x")

    conn = nl.Connection(
        "t", {}, {nl.VIEW_AFFINE: lambda m: got.append(m), nl.MOTION: bad}, None
    )
    v = nl.Value()
    nl.fill_value(v, nl.MATRIX, SAMPLES[nl.MATRIX])
    assert _call_set(conn, nl.VIEW_AFFINE, v) == 0
    assert got == [SAMPLES[nl.MATRIX]]
    b = nl.Value()
    nl.fill_value(b, nl.BOOL, True)
    with caplog.at_level(logging.WARNING, logger="MouseNav3D"):
        assert _call_set(conn, nl.MOTION, b) == nl.NO_DATA
        assert _call_set(conn, nl.MOTION, b) == nl.NO_DATA
    records = [r for r in caplog.records if r.name == "MouseNav3D"]
    assert len(records) == 1 and nl.MOTION in records[0].getMessage()
    conn.close()


def test_string_getter_buffer_outlives_call():
    conn = nl.Connection("t", {nl.COMMANDS_ACTIVE_SET: (nl.CSTR, lambda: "abc")}, {}, None)
    v = nl.Value()
    assert _call_get(conn, nl.COMMANDS_ACTIVE_SET, v) == 0
    keep = conn._keep[nl.COMMANDS_ACTIVE_SET]
    assert keep is not None and ctypes.addressof(keep) == v.cstr.p
    assert keep.value == b"abc"
    conn.close()
    assert not conn._keep


def test_connection_without_library_has_no_handle():
    conn = nl.Connection("t", {}, {}, None)
    assert conn.handle == 0
    assert conn.create_result == nl.NOT_SUPPORTED
    assert conn.write(nl.MOTION, nl.BOOL, True) == nl.NOT_SUPPORTED
    with pytest.raises(nl.NavlibError):
        conn.read(nl.MOTION, nl.BOOL)
    conn.close()
    conn.close()


def test_load_library_never_raises():
    lib = nl.load_library()
    assert lib is None or hasattr(lib, "NlCreate")


def test_property_names():
    assert nl.VIEW_AFFINE == "view.affine"
    assert nl.COMMANDS_TREE == "commands.tree"
    assert nl.SETTINGS_CHANGED == "settings.changed"
    assert nl.DEVICE_PRESENT == "device.present"
    assert nl.HIT_SELECTION_ONLY == "hit.selectionOnly"
    assert nl.MODEL_UNITS_TO_METERS == "model.unitsToMeters"


class _FakeLib:
    def __init__(self):
        self.written = []

    def NlCreate(self, *args):
        return -1

    def NlWriteValue(self, handle, name, value_ref):
        self.written.append(name)
        return 0

    def NlClose(self, handle):
        return 0


def test_write_retains_buffers_until_replaced_or_close():
    lib = _FakeLib()
    conn = nl.Connection("t", {}, {}, lib)
    conn.handle = 1  # pretend connected (the fake NlCreate fails)
    node = nl.ActionNode()
    assert conn.write(nl.COMMANDS_TREE, nl.ACTIONNODEEX, node) == 0
    first = conn._keep[("write", nl.COMMANDS_TREE)]
    assert first is not None and ctypes.addressof(first.contents) == ctypes.addressof(node)
    assert conn.write(nl.COMMANDS_ACTIVE_SET, nl.CSTR, "abc") == 0
    assert conn._keep[("write", nl.COMMANDS_ACTIVE_SET)].value == b"abc"
    assert ("write", nl.COMMANDS_TREE) in conn._keep  # other property unaffected
    conn.close()
    assert not conn._keep


def test_long_out_of_range_raises():
    bits = 8 * ctypes.sizeof(ctypes.c_long)
    v = nl.Value()
    with pytest.raises(OverflowError):
        nl.fill_value(v, nl.LONG, 1 << (bits - 1))
    with pytest.raises(OverflowError):
        nl.fill_value(v, nl.LONG, -(1 << (bits - 1)) - 1)
    nl.fill_value(v, nl.LONG, (1 << (bits - 1)) - 1)
