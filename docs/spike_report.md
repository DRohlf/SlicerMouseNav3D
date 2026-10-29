# Live navlib spike, 29 Oct 2026

Measurements from driver mode on real hardware, and the decisions they led to.

Setup: Slicer 5.12.4 with a large scene, 3DxWare driver, SpaceMouse Wireless (Bluetooth), Windows 10.
Recorder: `tools/spike_record.py`, which logs every property the driver reads or writes to
`Testing/slicer/out/spike_<date>-<time>.jsonl` (the logs are not committed). First session: 8,990 callbacks over
156 s.

## First impression

Motion was smooth. Fit appeared to do nothing. Front, Right and Top worked. Pan did not always pan. Rotation worked.

## Measurements

| Question | Result |
|---|---|
| Callback thread | All 8,990 callbacks on Slicer's main thread. |
| Frame rate | One camera write and one render per driver frame. Median frame interval 33 ms (30 fps); 27 % of frames at 16.7 ms (60 fps), 68 % at 33 ms. The scene is large, so 30 fps is likely the render cost. |
| Stop on release | No overshoot. The driver clears `motion` a median 133 ms after the last camera change; that is the driver's idle detection, not visible movement. |
| What the driver reads | `view.affine`, `view.perspective`, `view.extents` (orthographic), `view.rotatable`, `view.target`, `model.extents`, `hit.lookat`, `coordinateSystem`, `views.front`, `model.unitsToMeters`. It never read `view.fov` or `view.focusDistance`. |
| Orthographic | The view was switched to orthographic twice (115 s, 147 s). The driver then zoomed through `view.extents` as designed. |

## The driver's view commands

| Command | Camera side (back column of `view.affine`) | Up | Anatomical name in Slicer |
|---|---|---|---|
| Front | +y | +z | Anterior. Correct. |
| Top | +z | −y | Superior, with posterior at the top of the screen. |
| Right | **−x** | +z | **Slicer's Left side.** The driver's Right looks from −x. |

So the CAD convention holds: the driver's Right is the viewer's right when facing the front, which is the patient's
left. No `coordinateSystem` / `views.front` declaration can change this without also turning Front into Posterior,
because a rotation cannot mirror left and right.

## Fit

The driver's Fit frames `model.extents`. In this scene that box included Slicer's own 3D bounding box and axis labels.
Fit presses at 38 s, 44 s and 52 s moved the camera 0–30 mm, because the preceding view commands had already framed
the same box. Fit works; it just changed almost nothing here.

## Pan and pivot

- The driver set its rotation centre to `view.target` (Slicer's camera focal point) at the start of every motion. The
  bridge's focal point stays a fixed distance in front of the camera (a camera write keeps the focal distance), so it
  was often in empty space. Once the camera was 860 mm from the scene, the rotation centre was still in empty space.
- `hit.lookat` found nothing in 38 of 50 hit tests, so the object under the view centre was rarely used as the pivot.
- One pan attempt (108.4–109.2 s, 23 frames) moved the camera by 0.0 mm. Others with rotation near 0 moved 0–2 mm.
- FreeCAD, the reference implementation, does not provide `view.target`; it relies on hit testing and
  `pivot.position`.

## Decisions

- **Right/Left views:** the extension provides its own anatomical commands (Anterior, Posterior, Left = patient's
  left, Right = patient's right, Superior, Inferior, Lateral, Medial, Reset view) for the driver's button-mapping UI.
  The driver's own Front/Top stay available.
- **Pivot:** stop publishing `view.target`; make the hit test see every visible surface (segmentations and models)
  while ignoring Slicer's bounding box and axis labels; default pivot = centre of the visible data.

## Pan retest, after the pivot fix

Log of 46 s. Pan, rotate and zoom all behaved well. The rotation centre is now the centre of the data, not a point in
empty space. A hit query takes about 12 ms in the large scene, and about 1 ms when repeated after a per-prop locator
cache was added.

## 3D and slice views through the driver

Log of 358 s, 43 motions, all callbacks on the main thread.

- 3D view: rotate, pan, zoom and Fit work.
- Slice views: pan works. Push/pull did not step through slices. With `view.perspective` false the driver sends
  push/pull only as `view.extents` (zoom). Its camera-z movement was exactly 0 in every slice motion, so the slice
  offset never changed. One large pan (about 208 mm) moved a slice view off the data; pressing `r` over the view
  restores it.
- One apparent jump of the images while moving the ordinary mouse could not be reproduced, and the log has no driver
  camera write outside a motion, so it was disregarded.
- Extension commands: the 3Dconnexion settings window did not visibly change and no `commands.activeCommand`
  arrived. Accepted as is: the commands are offered, and Slicer's own view controls remain the reliable path.

**Decision:** slice views report a perspective camera, so push/pull arrives as camera-z movement and pages whole
planes. Zoom in slice views stays on Slicer's own mouse controls (wheel or right-drag). Reading the device directly
for slice views while the driver runs was not pursued.
