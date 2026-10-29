# 3D Mouse Navigation: design notes

How the extension works today, and why. The README is the user guide; `docs/spike_report.md` holds the hardware
measurements behind several of the decisions below.

## Goal

A 3D mouse (3Dconnexion SpaceMouse devices) moves Slicer's 3D view and slice views the way it moves a CAD program:
smooth, immediate, stopping the moment the cap is released, configured in 3Dconnexion's own settings window. The
extension is view only: it changes cameras and slice positions and nothing else in the scene, and it never moves
Slicer while another program is the active application.

## Two modes

The controller (`MouseNav3DLib/controller.py`) picks one mode at start-up:

1. **Driver mode** (Windows, Mac): 3Dconnexion's Navigation Library (navlib), installed with the 3DxWare driver, is
   loaded from the local 3Dconnexion installation (Windows `TDxNavLib`, Mac
   `/Library/Frameworks/3DconnexionNavlib.framework/3DconnexionNavlib`). The extension describes the view under the
   mouse; the driver computes motion, smoothing, speed and axis settings and handles its own buttons.
2. **Fallback mode** (no driver): a built-in reader reads the device and the extension moves the views itself
   (Windows: HID; Linux: the spacenavd socket). Mac has no built-in reader.
3. **No device**: no driver and no reader for this platform. The panel retries every 5 s while it is shown.

`MOUSENAV3D_FORCE_FALLBACK=1` skips the driver, so fallback mode can be tried on a machine that has it.

## Driver mode

### The navlib interface

`MouseNav3DLib/navlib_ctypes.py` (the only LGPL file) declares navlib's C API through ctypes: `NlCreate`, `NlClose`,
`NlReadValue`, `NlWriteValue`, the value union and the property names. One connection is created per session with
an accessor (getter and/or setter) per property. The accessors delegate to the bridge of the current target view
(`view3d_bridge.py` for a 3D view, `slice_bridge.py` for a slice view); changing the target never reconnects. After
connecting, the extension writes `active`, publishes its command tree and writes `focus`.

Rendering follows the driver's frames: camera writes do not render; the end of a transaction (`transaction` = 0)
renders once. While `motion` is true the render window is on Slicer's interactive update rate (as during mouse
dragging) and goes back to the still rate when motion ends.

In driver mode the panel's status says whether a 3D mouse is connected (`device.present`, read at most once a
second); if the driver does not answer that property it only says it is connected to the driver.

### The driver's views follow the CAD convention

The driver builds its standard views from `views.front` and `coordinateSystem` the CAD way: its Front is Slicer's
Anterior and its Top is Superior, but its **Right** looks from the viewer's right when facing the front, which is the
**patient's left**. A rotation of the declared frames cannot change that without also turning Front into Posterior,
since a rotation cannot mirror left and right. The extension therefore publishes its own anatomical commands to the
driver's button-mapping UI (`commands.py`): Anterior, Posterior, Left (patient's left), Right (patient's right),
Superior, Inferior, Lateral and Medial (from the limb side chosen in the panel) and Reset view (centre the 3D view on
the visible data). The presets keep the current viewing distance. Whether the driver lists these commands depends on
its version and profile; Slicer's own view controls always work.

### 3D view

- `view.affine` is the camera-to-world matrix; writes keep the focal distance.
- Orthographic (parallel projection) views zoom through `view.extents`; perspective views through camera motion.
- `model.extents` is the bounding box of the visible data: every visible prop in the view's renderer except Slicer's
  own decorations (the 3D bounding box outline and the axis labels, which Slicer creates non-pickable as an outline
  actor and as followers). An empty view reports a small safe box, never NaN or a zero-size box.
- **Pivot**: the centre of the visible data, unless the driver sets one (`pivot.position`). `view.target` is not
  published: with it the driver rotated about Slicer's camera focal point, which is often in empty space.
- **Hit test** (`hit.lookat`): the nearest visible data surface along the driver's ray (a ring of rays covers the
  aperture), using the same rule as `model.extents`, so the bounding box and axis labels are never hit. Cell
  locators are cached per prop and rebuilt only when the data or its transform change.

### Slice views

A slice view is reported as a **perspective** camera: it sits a fixed distance (`CAMERA_DISTANCE`, 100 mm) in front of
the slice on the +normal side and looks at the slice centre, and it is not rotatable. For an orthographic view the
driver turns push/pull into zoom (`view.extents` writes) and never moves the camera along the normal (measured on
hardware), so slices could not be paged. With the perspective report:

- the in-plane part of a written camera move pans the slice;
- the part along the normal accumulates and **pages through whole image planes** of the shown volume's slice spacing
  (1 mm without a volume); a camera move into the screen pages toward −normal;
- rotation in a written affine and `view.extents` writes are ignored: **zoom in slice views stays on Slicer's mouse
  wheel or right-drag**.

The distance sets how fast a push pages relative to a pan, because the driver scales its translation speed with the
distance to the pivot (the slice centre). The driver's own speed setting adjusts both.

### Retargeting

A 50 ms timer looks for the layout manager's visible view under the mouse pointer (slice views first, then 3D views)
and makes its bridge the target. When the pointer is over no view the target stays; when the target's widget is gone
it falls back to the first 3D view, else to none. Bridges are cached per view and dropped when their view
disappears, so no reference to a deleted widget is kept. On a change the driver is told (`model.extents` and
`view.affine` of the new view are written), and an ongoing motion's interactive update rate moves to the new view.

### Focus

The driver gets `focus` = true only while Slicer is the active application (`applicationStateChanged`, plus one
shared check, `controller.app_is_active()`, for the initial state). Another program in front gets no motion.

## Fallback mode

### Input and smoothing

The readers (`fallback/hid_windows.py`, `fallback/spacenavd.py`) run on their own threads and stamp every report with
`time.monotonic()`. The integrator (`fallback/motion.py`) holds each report's velocity from its own timestamp to the
next one's, through a short first-order filter integrated in closed form, so motion follows the device's clock rather
than the frame timer's: a late frame moves the view by the time that really elapsed. A report inside the dead zone
ends the motion at once (no coasting); a device that sends nothing for 0.25 s counts as released.

An 8 ms precise timer (`fallback/navigator.py`) takes the displacement since the last frame and applies it to the
target view. Per-axis reverse and sensitivity, overall speed, dead zone and rotation lock come from the panel and are
saved in Slicer's settings. While Slicer is not the active application (the same `app_is_active()` check), frames
discard the motion and button presses.

### Mapping

The device's axes: tx right, ty up (lift the cap), tz toward you (pull the cap), rx tilt, ry twist, rz roll.

| View | Motion |
|---|---|
| 3D view | Object mode: the scene moves as the cap. Pan (tx, ty), dolly (tz: pull = closer), turn (rx, ry, rz) about the camera's focal point. Rotation lock leaves pan and dolly. |
| Slice view | As in driver mode: push/pull (tz) pages through whole image planes, faster the further you push (push = toward −normal, pull = toward +normal); tx/ty pan (the picture moves with the cap). Unlike driver mode, twist (ry) zooms (anticlockwise seen from above = in). |
| Button 1 | Fit the view under the mouse. |
| Button 2 | Rotation lock on/off (3D view). |

Every device gets the same two buttons in fallback mode; other dedicated buttons work in driver mode only.

## Settings keys

Slicer's settings, prefix `MouseNav3D/`:

| Key | Meaning | Default |
|---|---|---|
| `enabled` | "Enable 3D mouse" | true |
| `limb_side` | `right` or `left`: the side Lateral/Medial look from | `right` |
| `fallback/reverse_<axis>` | reverse one axis (tx, ty, tz, rx, ry, rz) | false |
| `fallback/sensitivity_<axis>` | per-axis factor, 0.1 to 3 | 1.0 |
| `fallback/speed` | overall speed, 0.1 to 3 | 1.0 |
| `fallback/dead_zone` | of full deflection | 0.04 |
| `fallback/rotation_lock` | rotation lock, also toggled by button 2 | false |

Driver-mode settings live in 3Dconnexion's profile for the application "3D Mouse Navigation".

## Threading

All Slicer, Qt and VTK calls happen on Slicer's main thread.

- navlib is created single-threaded; its callbacks were measured on the main thread on Windows. A getter or setter
  that is nevertheless called on another thread raises NoData (logged once) instead of touching Slicer.
- The ctypes callback objects, accessor array and every buffer handed to the driver stay referenced by the
  `Connection` until it is closed.
- Fallback readers call the navigator from their threads; the navigator only queues (the integrator is locked, button
  changes are queued) and applies everything on the main-thread timer. A raising callback or frame is logged once;
  the reader thread and the timer keep running.
- One controller per session (`slicer._mousenav3d_controller`): module Reload and Slicer exit stop the old one
  (timer and signal hooks removed, still update rate restored, `active` false, connection closed).

## Start-up

The module starts the controller at `startupCompleted` when "Enable 3D mouse" is on, so the mouse works without
opening the panel. Auto-start is skipped for `--python-script`, `--python-code` and when `MOUSENAV3D_NO_AUTOSTART` is
set; opening the panel starts it too.

## Known limits

- Mac driver mode uses the Navigation Library path of other navlib clients but has not been tested on a Mac. There is
  no Mac built-in reader.
- The Windows built-in reader has been tested with synthetic input, not yet with a device in place of the driver.
- The Linux reader (spacenavd) is written from the daemon's protocol without a Linux test machine; its axis signs are
  in one table (`SPNAV_SIGNS`) in case a direction is wrong.
- Whether the extension's commands appear in 3Dconnexion's button-mapping UI depends on the driver version and
  profile.
- Slice-view zoom is not on the 3D mouse in driver mode.
- In fallback mode the 3D view turns about the camera's focal point, not the centre of the visible data.
