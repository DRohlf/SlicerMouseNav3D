# Hardware test checklist

For trying 3D Mouse Navigation on a real device (any 3Dconnexion SpaceMouse, for example a SpaceMouse Wireless or a
SpaceMouse Enterprise) in Slicer 5.12.4.

Install one way (see the package's `INSTALL.txt` or the README): View > Extensions Manager > Install from file... with
the extension package zip (`34645-...-MouseNav3D-git...zip`) and a restart, or View > Python Console and the line that
`tools/package_test_build.py` printed for your package (in a clone, the same line with the full path of your copy's
`tools\install_dev.py`). Open Modules > Utilities > 3D Mouse Navigation. With 3DxWare running the panel reads
"Connected to the 3Dconnexion driver" and says whether a 3D mouse is connected. Restart Slicer once and check that the mouse works without opening the panel.

Write what felt wrong next to each line; "ok" is enough when it felt right.

## Views (driver buttons and the extension's commands)

- [ ] The device's view buttons (Front, Back, Top, Bottom, Left, Right, iso, as your device has them): note which anatomical view each gives. The driver's own Right is the CAD right, which is the **patient's left**; that is expected (see the README).
- [ ] Fit: frames the data.
- [ ] Rotation lock (driver): rotation stops, pan and zoom stay.
- [ ] In 3Dconnexion's window, look under the "3D Mouse Navigation" profile for the extension's commands (Anterior, Posterior, Left, Right, Superior, Inferior, Lateral, Medial, Reset view). If they are listed, assign two of them to buttons and press them: they give the anatomical views (Right = the patient's right). If they are not listed, note it; nothing else depends on it.
- [ ] Limb for lateral/medial: set Right, then Left; Lateral/Medial swap sides.

## Feel

- [ ] 3D view: rotate, pan, zoom are smooth; nothing overshoots when you let go.
- [ ] 3D view: the rotation centre is the middle of the data, not empty space.
- [ ] Slice view: pan works; push/pull steps through slices one plane at a time; zoom stays on Slicer's mouse wheel / right-drag.
- [ ] Mouse over a slice view, then a 3D view: the view under the pointer moves.
- [ ] Switch to another program: Slicer does not move.
- [ ] Sensitivity: set in 3Dconnexion's own app (the panel's "3Dconnexion settings..." button only says where). Slice paging speed follows the driver's speed setting.

## Panel

- [ ] Untick "Enable 3D mouse": the mouse stops; tick it: it works again.
- [ ] Module > Reload (developer buttons): no error, the mouse keeps working.

## Built-in reader (no driver)

- [ ] Windows: start Slicer with the environment variable `MOUSENAV3D_FORCE_FALLBACK=1` (or on a machine without 3DxWare). The panel shows "Using the built-in reader", the device and its battery. 3D view: rotate, pan, zoom; slice view: push/pull pages, slide/lift pans, twist zooms; button 1 fits, button 2 toggles the rotation lock. Note whether push pages the same way as in driver mode.
- [ ] Linux, spacenavd running: the same checks.
- [ ] Hold a push for longer than 0.25 s: does the motion keep going (steady hold) or stop after a quarter second? A reader that does not repeat reports while the cap is held still would need a longer limit (`STALE_S` in `fallback/motion.py`).

## What felt wrong

(write here)
