r"""Navlib spike recorder. In Slicer's Python console:

    p = r"<path to>\tools\spike_record.py"
    exec(open(p).read(), {"__file__": p})

Connects the 3D view to the 3Dconnexion driver and logs every property the driver reads or writes, with time, value
and thread, to Testing/slicer/out/spike_<YYYYmmdd-HHMMSS>.jsonl. Move the 3D mouse in the 3D view, then run
spike_stop() in the console. Running this again first stops the previous spike.

The spike's controller replaces the module's installed controller (MouseNav3DLib.controller.install stops the old
one), so there is never more than one navlib connection. After spike_stop() the module's controller stays stopped
until "Enable 3D mouse" is switched off and on again in the module panel, or Slicer is restarted.
"""
import os
import sys
import threading
import time

import qt
import slicer


def _find_repo():
    """The repository root, from __file__ (pass it as exec's globals, as above). None if __file__ is missing, is not
    this script (a console may carry an unrelated __file__), or has no MouseNav3D/MouseNav3DLib next to it."""
    try:
        path = __file__
    except NameError:
        return None
    if os.path.basename(path) != "spike_record.py":
        return None
    repo = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), ".."))
    return repo if os.path.isdir(os.path.join(repo, "MouseNav3D", "MouseNav3DLib")) else None


def spike_stop():
    """Stop the spike controller, close the log, print the log path and line count."""
    spike = getattr(slicer, "_mousenav3d_spike", None)
    slicer._mousenav3d_spike = None
    if spike is None:
        print("No spike is running.")
        return
    controller, log, timer, on_quit = spike
    try:
        timer.stop()
        try:
            slicer.app.disconnect("aboutToQuit()", on_quit)
        except Exception:  # noqa: BLE001
            pass
        controller.stop()
        if getattr(slicer, "_mousenav3d_controller", None) is controller:
            slicer._mousenav3d_controller = None
    finally:
        log.close()
    print(f"Spike stopped. Log: {log.path} ({log.lines} lines)")
    print("Callback threads: " + ("all on the main thread" if controller.callback_threads <= {controller.main_thread}
                                  else f"NOT all on the main thread {sorted(controller.callback_threads)}"))
    print("The module's own controller stays stopped: switch 'Enable 3D mouse' off and on in the module panel, or "
          "restart Slicer, to start it again.")


def _spike_start():
    repo = _find_repo()
    if repo is None:
        print("Spike not started: run this script as  p = r\"<path to>\\tools\\spike_record.py\"; "
              "exec(open(p).read(), {\"__file__\": p})  so it can find MouseNav3D/MouseNav3DLib next to it.")
        return
    module_dir = os.path.join(repo, "MouseNav3D")
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    import importlib

    if getattr(slicer, "_mousenav3d_spike", None) is not None:
        spike_stop()  # before the reload: the old controller is stopped with the code it was built from

    from MouseNav3DLib import camera_math as _camera_math_mod
    from MouseNav3DLib import controller as _controller_mod
    from MouseNav3DLib import recorder as _recorder_mod
    from MouseNav3DLib import settings as _settings_mod
    from MouseNav3DLib import slice_bridge as _slice_bridge_mod
    from MouseNav3DLib import view3d_bridge as _bridge_mod
    from MouseNav3DLib.fallback import hid_windows as _hid_mod
    from MouseNav3DLib.fallback import motion as _motion_mod
    from MouseNav3DLib.fallback import navigator as _navigator_mod
    from MouseNav3DLib.fallback import spacenavd as _spacenavd_mod

    # Dependency order, so a re-run in the same Slicer session runs the current files (not navlib_ctypes: it holds
    # the loaded driver library and the ctypes callback types).
    for _mod in (_camera_math_mod, _bridge_mod, _slice_bridge_mod, _motion_mod, _hid_mod, _spacenavd_mod, _navigator_mod,
                 _recorder_mod, _settings_mod, _controller_mod):
        importlib.reload(_mod)

    _stamp = time.strftime("%Y%m%d-%H%M%S")
    _log_path = os.path.join(repo, "Testing", "slicer", "out", f"spike_{_stamp}.jsonl")
    _main = threading.get_ident()
    _log = _recorder_mod.JsonlRecorder(_log_path, main_thread=_main, thread_id=threading.get_ident)
    _ctl = _controller_mod.Controller(view_index=0, app_name="3D Mouse Navigation", recorder=_log)
    # Stop the module's controller first (install() does that), so there are never two navlib connections; the panel
    # and the startup hook then see this running controller and do not start another.
    _controller_mod.install(_ctl)
    try:
        _mode = _ctl.start()
    except Exception as _exc:  # noqa: BLE001
        _mode = None
        _log.close()
        print(f"Spike failed to start: {_exc!r}. The log was closed: {_log_path}")

    if _mode is not None:  # on a failed start slicer._mousenav3d_spike stays unset
        _timer = qt.QTimer()
        _timer.setInterval(500)
        _timer.connect("timeout()", _log.flush)  # the tail of a session is written even when no callback follows
        _timer.start()

        def _on_quit():
            _log.close()

        slicer.app.connect("aboutToQuit()", _on_quit)
        slicer._mousenav3d_spike = (_ctl, _log, _timer, _on_quit)
        print(f"Mode: {_mode} ({_ctl.status()})")
        print(f"Log: {_log_path}")
        if _mode == "driver":
            print("Move the 3D mouse in the 3D view; run spike_stop() when done.")
        else:
            print("No driver connection; run spike_stop() to close the log.")


# exec() with its own globals keeps spike_stop out of the console's namespace: put it there.
import __main__  # noqa: E402

__main__.spike_stop = spike_stop
_spike_start()
