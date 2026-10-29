"""Commands published to the driver's button-mapping UI: anatomical view presets and Reset view.

slicer, ctk and qt are imported inside run() only, so build_tree and COMMANDS import under plain Python.
"""
import ctypes
import logging

from . import navlib_ctypes as nl

_log = logging.getLogger("MouseNav3D")

SET_ID = "MouseNav3D"
CATEGORY_LABEL = "Views"

# (id, label, description)
COMMANDS = [
    ("mn3d.reset", "Reset view (centre)", "Centre the 3D view on the visible data."),
    ("mn3d.anterior", "Anterior view", "Look at the patient from the front."),
    ("mn3d.posterior", "Posterior view", "Look at the patient from behind."),
    ("mn3d.left", "Left view (patient's left)", "Look at the patient's left side."),
    ("mn3d.right", "Right view (patient's right)", "Look at the patient's right side."),
    ("mn3d.superior", "Superior view", "Look at the patient from above."),
    ("mn3d.inferior", "Inferior view", "Look at the patient from below."),
    ("mn3d.lateral", "Lateral view", "Look at the outer side of the limb (follows the limb side setting)."),
    ("mn3d.medial", "Medial view", "Look at the inner side of the limb (follows the limb side setting)."),
]
COMMAND_IDS = frozenset(c[0] for c in COMMANDS)

# command id -> ctkAxesWidget axis name; lateral/medial are resolved from the limb side
_AXIS = {
    "mn3d.anterior": "Anterior",
    "mn3d.posterior": "Posterior",
    "mn3d.left": "Left",
    "mn3d.right": "Right",
    "mn3d.superior": "Superior",
    "mn3d.inferior": "Inferior",
}


def _node(keep, type_id, id_, label, description, size=None):
    node = nl.ActionNode()
    node.size = ctypes.sizeof(nl.ActionNode)
    node.type = type_id
    for field, text in (("id", id_), ("label", label), ("description", description)):
        if text is not None:
            buf = ctypes.create_string_buffer(text.encode("utf-8"))
            keep.append(buf)
            setattr(node, field, ctypes.cast(buf, ctypes.c_char_p))
    keep.append(node)
    return node


def build_tree(app_label):
    """The action-set tree for `commands.tree`: (pointer to the root node, buffers that must stay alive)."""
    keep = []
    root = _node(keep, nl.ACTIONSET_NODE, SET_ID, app_label, app_label)
    category = _node(keep, nl.CATEGORY_NODE, "mn3d.views", CATEGORY_LABEL, CATEGORY_LABEL)
    leaves = [_node(keep, nl.ACTION_NODE, cid, label, desc) for cid, label, desc in COMMANDS]
    for a, b in zip(leaves, leaves[1:]):
        a.next = ctypes.pointer(b)
    category.children = ctypes.pointer(leaves[0])
    root.children = ctypes.pointer(category)
    return ctypes.pointer(root), keep


def resolve_axis(command_id, limb_side):
    """Axis name for a preset command, or None for reset / unknown ids."""
    if command_id in _AXIS:
        return _AXIS[command_id]
    if command_id in ("mn3d.lateral", "mn3d.medial"):
        right_limb = str(limb_side).lower() != "left"
        lateral = "Right" if right_limb else "Left"
        medial = "Left" if right_limb else "Right"
        return lateral if command_id == "mn3d.lateral" else medial
    return None


def run(command_id, view_index, limb_side):
    """Execute one command on 3D view `view_index`. No-op for an unknown id or a missing view."""
    if command_id not in COMMAND_IDS:
        _log.debug("unknown command %r ignored", command_id)
        return
    import ctk
    import slicer

    manager = slicer.app.layoutManager()
    widget = manager.threeDWidget(int(view_index)) if manager is not None else None
    if widget is None:
        _log.debug("command %s: no 3D view at index %s", command_id, view_index)
        return
    view = widget.threeDView()
    if command_id == "mn3d.reset":
        view.resetFocalPoint()
    else:
        axis = getattr(ctk.ctkAxesWidget, resolve_axis(command_id, limb_side))
        camera = view.renderWindow().GetRenderers().GetFirstRenderer().GetActiveCamera()
        distance = camera.GetDistance()
        view.lookFromAxis(axis)
        # lookFromAxis frames the data at its own distance; keep the one the user had
        focal = camera.GetFocalPoint()
        direction = camera.GetDirectionOfProjection()
        camera.SetPosition(*(focal[i] - direction[i] * distance for i in range(3)))
        camera.OrthogonalizeViewUp()
        view.renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange()
    view.forceRender()
