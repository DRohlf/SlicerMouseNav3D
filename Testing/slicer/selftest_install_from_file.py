"""Slicer self-test: the package from tools/package_extension.py goes through the Extensions Manager's "Install from
file" code path (qSlicerExtensionsManagerModel.installExtension(archive), what the button calls) and the installed
module loads in a fresh Slicer.

Isolation: nothing is installed into this Slicer's real extensions folder or settings. This process (the one
run_slicer.sh starts) only builds packages and starts two child Slicers with --disable-settings:
  install child: points the live extensions manager model at a scratch settings file whose Extensions/InstallPath is
                 a temporary folder, installs the package there (and checks that the direct-install test zip is
                 refused with "No extension description found");
  load child:    starts with --additional-module-paths set to the module path the install wrote into the scratch
                 settings (what a restart would use) and checks that the module loads from the temporary install.
The real extensions folder and the real revision settings' Extensions/* and Modules/AdditionalPaths keys are recorded
before and after and must be unchanged. The temporary folders are removed at the end.
"""
# Everything lives inside main(): Slicer's --python-script namespace does not make module-level imports visible to
# functions, and a NameError in the finally block would skip slicer.util.exit and hang the process.


def main():
    import hashlib
    import os
    import shutil
    import subprocess
    import sys
    import tempfile
    import traceback

    import qt
    import slicer

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    role = os.environ.get("MOUSENAV3D_SELFTEST_ROLE", "parent")
    log_path = os.environ.get("MOUSENAV3D_SELFTEST_LOG") or os.path.join(here, "out", "selftest_install_from_file.log")
    lines = []

    def check(name, ok):
        lines.append(f"{'PASS' if ok else 'FAIL'}: {name}")
        return bool(ok)

    def info(text):
        lines.append(f"  {text}")

    def error_log_messages():
        """Every message in Slicer's error log (module loading happens before the script runs; the log keeps it)."""
        out = []
        for _ in range(5):  # entries reach the model through queued signals
            slicer.app.processEvents()
        try:
            model = slicer.app.errorLogModel()
            for row in range(model.logEntryCount()):
                out.append(model.logEntryDescription(row))
        except Exception as exc:  # noqa: BLE001
            out.append(f"(error log not readable: {exc!r})")
        return out

    def disabled_settings():
        """--disable-settings makes Slicer use temporary "Slicer-tmp" settings files."""
        return all("-tmp" in os.path.basename(f) for f in
                   (slicer.app.slicerUserSettingsFilePath, slicer.app.slicerRevisionUserSettingsFilePath))

    # ----------------------------------------------------------------------------------------------- install child
    def run_install():
        archive = os.environ["MOUSENAV3D_ARCHIVE"]
        wrong_archive = os.environ["MOUSENAV3D_WRONG_ARCHIVE"]
        install_dir = os.environ["MOUSENAV3D_INSTALL_DIR"]
        scratch_ini = os.environ["MOUSENAV3D_SCRATCH_INI"]
        m = slicer.app.extensionsManagerModel()
        info(f"Slicer {slicer.app.applicationVersion} revision {slicer.app.revision} "
             f"os {m.slicerOs} arch {m.slicerArch}")
        info(f"user settings file: {slicer.app.slicerUserSettingsFilePath}")
        info(f"model settings file at start: {m.extensionsSettingsFilePath}")
        info(f"app extensionsInstallPath (not used): {slicer.app.extensionsInstallPath}")
        ok = check("child runs with --disable-settings (temporary settings files)", disabled_settings())
        s = qt.QSettings(scratch_ini, qt.QSettings.IniFormat)
        s.setValue("Extensions/InstallPath", install_dir)
        s.sync()
        m.extensionsSettingsFilePath = scratch_ini
        info(f"model settings file now: {m.extensionsSettingsFilePath}")
        info(f"model extensionsInstallPath now: {m.extensionsInstallPath()}")
        ok &= check("model points at the scratch settings file",
                    os.path.normcase(os.path.normpath(m.extensionsSettingsFilePath))
                    == os.path.normcase(os.path.normpath(scratch_ini)))
        ok &= check("model install path is the temporary folder",
                    os.path.normcase(os.path.normpath(m.extensionsInstallPath()))
                    == os.path.normcase(os.path.normpath(install_dir)))
        if not ok:
            return False  # never install anywhere else
        m.interactive = False  # no message boxes
        logged = []
        try:
            m.connect("messageLogged(QString,ctkErrorLogLevel::LogLevels)", lambda text, level: logged.append(text))
        except Exception as exc:  # noqa: BLE001
            info(f"messageLogged not connectable: {exc!r}")
        n0 = len(error_log_messages())
        refused = m.installExtension(wrong_archive, False, True)
        new = error_log_messages()[n0:] + logged
        info(f"direct-install test zip: installExtension returned {refused}; log: "
             f"{sorted(set(t.strip() for t in new if 'archive' in t))}")
        ok &= check("direct-install test zip is refused with 'No extension description found'",
                    refused is False and any("No extension description found in archive" in t for t in new))
        n0 = len(error_log_messages())
        accepted = m.installExtension(archive, False, True)
        new = error_log_messages()[n0:]
        info(f"extension package: installExtension returned {accepted}")
        for t in new:
            info(f"log: {t.strip()}")
        ok &= check("Install from file accepts the extension package", accepted is True)
        ok &= check("model lists MouseNav3D as installed", m.isExtensionInstalled("MouseNav3D"))
        meta = m.extensionMetadata("MouseNav3D")
        info("installed metadata: " + ", ".join(f"{k}={meta.get(k)}" for k in
                                                 ("extensionname", "archivename", "category", "scmurl", "revision",
                                                  "os", "arch", "slicer_revision", "enabled", "installed")))
        ok &= check("metadata came from the package's .s4ext",
                    meta.get("category") == "Utilities"
                    and str(meta.get("scmurl", "")).endswith("SlicerMouseNav3D.git"))
        ok &= check("extension is enabled", m.isExtensionEnabled("MouseNav3D"))
        ok &= check("extension is compatible with this Slicer", list(m.isExtensionCompatible("MouseNav3D")) == [])
        paths = qt.QSettings(scratch_ini, qt.QSettings.IniFormat).value("Modules/AdditionalPaths")
        paths = [paths] if isinstance(paths, str) else list(paths or [])
        info(f"Modules/AdditionalPaths written to the scratch settings: {paths}")
        expected = os.path.join(install_dir, "MouseNav3D", "lib",
                                f"Slicer-{slicer.app.majorVersion}.{slicer.app.minorVersion}", "qt-scripted-modules")
        ok &= check("module path written for the next start is the installed qt-scripted-modules folder",
                    [os.path.normcase(os.path.normpath(p)) for p in paths] == [os.path.normcase(expected)])
        return ok

    # -------------------------------------------------------------------------------------------------- load child
    def run_load():
        install_dir = os.environ["MOUSENAV3D_INSTALL_DIR"]
        ok = check("child runs with --disable-settings (temporary settings files)", disabled_settings())
        if not ok:
            return False  # never write settings unless they are the temporary ones
        info(f"user settings file: {slicer.app.slicerUserSettingsFilePath}")
        info(f"additional module paths: {list(getattr(slicer.app.commandOptions(), 'additionalModulePaths', []))}")
        ok &= check("slicer.modules.mousenav3d exists", hasattr(slicer.modules, "mousenav3d"))
        if not hasattr(slicer.modules, "mousenav3d"):
            return False
        path = os.path.normcase(os.path.normpath(slicer.modules.mousenav3d.path))
        info(f"module loaded from: {slicer.modules.mousenav3d.path}")
        ok &= check("module file is in the temporary install",
                    path.startswith(os.path.normcase(os.path.normpath(install_dir)) + os.sep))
        ok &= check("module title", slicer.modules.mousenav3d.title == "3D Mouse Navigation")
        res = os.path.join(os.path.dirname(slicer.modules.mousenav3d.path), "Resources")
        ok &= check("icon and licence texts installed next to the module",
                    all(os.path.isfile(os.path.join(res, *n.split("/"))) for n in
                        ("Icons/MouseNav3D.png", "LICENSE.txt", "LICENSE-LGPL.txt", "NOTICE.md")))
        qt.QSettings().setValue("MouseNav3D/enabled", False)  # temporary settings (--disable-settings)
        ok &= check("widget representation builds", slicer.modules.mousenav3d.widgetRepresentation() is not None)
        lib = sys.modules.get("MouseNav3DLib")
        lib_file = os.path.normcase(os.path.normpath(getattr(lib, "__file__", "") or ""))
        info(f"MouseNav3DLib: {getattr(lib, '__file__', None)}")
        ok &= check("MouseNav3DLib imported from the temporary install",
                    lib is not None and lib_file.startswith(os.path.normcase(os.path.normpath(install_dir)) + os.sep))
        log = error_log_messages()
        bad = [t for t in log if "GetModuleHomeDirectory" in t]
        mine = [t for t in log if "mousenav3d" in t.lower() and ("warning" in t.lower() or "error" in t.lower())]
        info(f"warnings or errors mentioning the module: {len(mine)}")
        for t in mine:
            info(f"  {' / '.join(t.strip().splitlines())[:300]}")
        ok &= check("no warnings or errors mentioning the module", not mine)
        ok &= check("no GetModuleHomeDirectory warning", not bad)
        # canary: the same warning, provoked on purpose, does reach the log (so the check above can see it)
        slicer.vtkSlicerApplicationLogic.GetModuleShareDirectory("MouseNav3D", "x/MouseNav3D.py")
        canary = [t for t in error_log_messages()[len(log):] if "GetModuleHomeDirectory" in t]
        info(f"canary: {canary[:1]}")
        ok &= check("canary: a provoked GetModuleHomeDirectory warning is captured by the log", bool(canary))
        return ok

    # ------------------------------------------------------------------------------------------------------ parent
    def listing(path):
        rows = []
        for base, dirs, files in os.walk(path):
            dirs.sort()
            for name in sorted(dirs) + sorted(files):
                full = os.path.join(base, name)
                st = os.stat(full)
                rows.append(f"{os.path.relpath(full, path)} {'<dir>' if os.path.isdir(full) else st.st_size} "
                            f"{int(st.st_mtime)}")
        return rows

    def settings_keys(ini):
        s = qt.QSettings(ini, qt.QSettings.IniFormat)
        keys = sorted(k for k in s.allKeys() if k.startswith("Extensions/") or k == "Modules/AdditionalPaths")
        return {k: str(s.value(k)) for k in keys}

    def run_child(role_name, extra_args, env_extra, tmp):
        child_log = os.path.join(tmp, f"{role_name}.log")
        env = dict(os.environ)
        env.update(env_extra)
        env.update({"MOUSENAV3D_SELFTEST_ROLE": role_name, "MOUSENAV3D_SELFTEST_LOG": child_log,
                    "MOUSENAV3D_NO_AUTOSTART": "1"})
        exe = slicer.app.launcherExecutableFilePath or sys.executable
        cmd = [exe, "--no-splash", "--no-main-window", "--disable-settings", *extra_args,
               "--python-script", os.path.abspath(__file__)]
        info(f"start {role_name} child: {' '.join(os.path.basename(c) if c == exe else c for c in cmd)}")
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            info(f"{role_name} child timed out; stopping only that process tree (pid {proc.pid})")
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
            proc.wait()
        text = open(child_log).read() if os.path.isfile(child_log) else "no log\n"
        lines.append(f"--- {role_name} child log ---")
        lines.extend(text.rstrip("\n").splitlines())
        lines.append(f"--- end of {role_name} child log ---")
        return text.rstrip("\n").splitlines()[-1:] == ["OVERALL: PASS"]

    def run_parent():
        sys.path.insert(0, os.path.join(root, "tools"))
        import package_extension
        import package_test_build

        real_ext = slicer.app.extensionsInstallPath
        real_ini = slicer.app.slicerRevisionUserSettingsFilePath
        info(f"Slicer {slicer.app.applicationVersion} revision {slicer.app.revision} "
             f"({slicer.app.os}-{slicer.app.arch})")
        info(f"real extensions folder (must not change): {real_ext}")
        info(f"real revision settings (Extensions/* and Modules/AdditionalPaths must not change): {real_ini}")
        before = listing(real_ext) if os.path.isdir(real_ext) else ["(missing)"]
        keys_before = settings_keys(real_ini)
        info(f"real extensions folder before: {len(before)} entries, sha1 "
             f"{hashlib.sha1(chr(10).join(before).encode()).hexdigest()[:12]}")
        for row in before:
            info(f"  before: {row}")
        tmp = tempfile.mkdtemp(prefix="mousenav3d_iff_")
        ok = True
        try:
            install_dir = os.path.join(tmp, "Extensions-test")
            os.makedirs(install_dir)
            info(f"temporary extensions install path: {install_dir}")
            zip_path, name = package_extension.build(
                os.path.join(tmp, "dist"), slicer_version=f"{slicer.app.majorVersion}.{slicer.app.minorVersion}",
                slicer_revision=str(slicer.app.revision),
                os_name={"win": "win", "linux": "linux", "macosx": "macosx"}.get(slicer.app.os, "linux"),
                arch=slicer.app.arch)
            info(f"package: {os.path.basename(zip_path)}")
            _folder, wrong_zip, _line, _ext = package_test_build.build(os.path.join(tmp, "testbuild"), today="00000000")
            env = {"MOUSENAV3D_ARCHIVE": zip_path, "MOUSENAV3D_WRONG_ARCHIVE": wrong_zip,
                   "MOUSENAV3D_INSTALL_DIR": install_dir,
                   "MOUSENAV3D_SCRATCH_INI": os.path.join(tmp, "scratch-extensions-settings.ini")}
            ok &= check("install child: OVERALL PASS", run_child("install", [], env, tmp))
            # the installed files are exactly the CMake-listed module files, byte for byte
            version = f"{slicer.app.majorVersion}.{slicer.app.minorVersion}"
            mod_dir = os.path.join(install_dir, "MouseNav3D", "lib", f"Slicer-{version}", "qt-scripted-modules")
            listed = package_extension.module_files(root)
            installed = sorted(os.path.relpath(os.path.join(b, f), mod_dir).replace(os.sep, "/")
                               for b, _d, fs in os.walk(mod_dir) for f in fs)
            ok &= check("installed module files = CMake lists", installed == sorted(listed))
            same = installed == sorted(listed) and all(open(os.path.join(mod_dir, *r.split("/")), "rb").read()
                       == open(os.path.join(root, "MouseNav3D", *r.split("/")), "rb").read() for r in listed)
            ok &= check("installed files identical to the repository's", same)
            ok &= check("package description installed at share/Slicer-X.Y/MouseNav3D.s4ext", os.path.isfile(
                os.path.join(install_dir, "MouseNav3D", "share", f"Slicer-{version}", "MouseNav3D.s4ext")))
            ok &= check("manager wrote its MouseNav3D.s4ext record",
                        os.path.isfile(os.path.join(install_dir, "MouseNav3D.s4ext")))
            ok &= check("archive top folder was removed after the copy",
                        not os.path.exists(os.path.join(install_dir, "MouseNav3D", name)))
            for row in listing(install_dir):
                info(f"  installed: {row}")
            if os.path.isdir(mod_dir):
                ok &= check("load child: OVERALL PASS",
                            run_child("load", ["--additional-module-paths", mod_dir], env, tmp))
            else:
                ok &= check("load child skipped: nothing installed", False)
        finally:
            try:
                after = listing(real_ext) if os.path.isdir(real_ext) else ["(missing)"]
                keys_after = settings_keys(real_ini)
                info(f"real extensions folder after: {len(after)} entries, sha1 "
                     f"{hashlib.sha1(chr(10).join(after).encode()).hexdigest()[:12]}")
                ok &= check("real extensions folder unchanged", after == before)
                info(f"real settings keys before: {keys_before}")
                info(f"real settings keys after:  {keys_after}")
                ok &= check("real settings Extensions/* and Modules/AdditionalPaths unchanged", keys_after == keys_before)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            ok &= check(f"temporary folder removed ({tmp})", not os.path.exists(tmp))
        return ok

    ok = False
    try:
        ok = {"parent": run_parent, "install": run_install, "load": run_load}[role]()
    except Exception:
        lines.append(traceback.format_exc())
    finally:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            lines.append("OVERALL: PASS" if ok else "OVERALL: FAIL")
            with open(log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        finally:
            slicer.util.exit(0)


main()
