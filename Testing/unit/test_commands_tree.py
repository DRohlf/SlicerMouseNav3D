import ctypes

from MouseNav3DLib import commands
from MouseNav3DLib import navlib_ctypes as nl

EXPECTED = [
    ("mn3d.reset", "Reset view (centre)"),
    ("mn3d.anterior", "Anterior view"),
    ("mn3d.posterior", "Posterior view"),
    ("mn3d.left", "Left view (patient's left)"),
    ("mn3d.right", "Right view (patient's right)"),
    ("mn3d.superior", "Superior view"),
    ("mn3d.inferior", "Inferior view"),
    ("mn3d.lateral", "Lateral view"),
    ("mn3d.medial", "Medial view"),
]


def _walk(node):
    out = []
    while node:
        n = node.contents
        out.append(n)
        node = n.next
    return out


def test_commands_list():
    assert [(c[0], c[1]) for c in commands.COMMANDS] == EXPECTED
    assert all(c[2] for c in commands.COMMANDS)


def test_tree_shape():
    root, keep = commands.build_tree("3D Mouse Navigation")
    assert isinstance(keep, list) and keep
    roots = _walk(root)
    assert len(roots) == 1
    r = roots[0]
    assert r.type == nl.ACTIONSET_NODE == 0
    assert r.id == b"MouseNav3D"
    cats = _walk(r.children)
    assert len(cats) == 1
    assert cats[0].type == nl.CATEGORY_NODE == 1
    assert cats[0].label == b"Views"
    leaves = _walk(cats[0].children)
    assert len(leaves) == 9
    assert all(l.type == nl.ACTION_NODE == 2 for l in leaves)
    assert [(l.id.decode(), l.label.decode()) for l in leaves] == EXPECTED
    assert all(l.description for l in leaves)
    for n in roots + cats + leaves:
        assert n.size == ctypes.sizeof(nl.ActionNode)
    assert not leaves[0].children
