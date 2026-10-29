r"""Home test package: python tools/package_test_build.py <dest>

Writes into <dest>:
  MouseNav3D_test_<date>/                         the MouseNav3D module, tools/install_dev.py, the README, the hardware
                                                  checklist, the licence files, the README's images, INSTALL.txt and a
                                                  copy of the extension package
  MouseNav3D_test_<date>_direct-install.zip       the same folder as a zip, for the direct install (install_dev.py)
  <revision>-<os>-<arch>-MouseNav3D-git<commit>-<date>.zip
                                                  the extension package (tools/package_extension.py), for the
                                                  Extensions Manager's "Install from file"
then prints both install routes, the direct-install line with the package's real absolute path. INSTALL.txt says which
file is for which route. Uses only the standard library.
"""
import datetime
import os
import shutil
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import package_extension  # noqa: E402

INCLUDE = ["MouseNav3D", os.path.join("tools", "install_dev.py"), "README.md",
           os.path.join("docs", "HARDWARE_CHECKLIST.md"), os.path.join("docs", "images"), "LICENSE.txt",
           "LICENSE-LGPL.txt", "NOTICE.md"]


def install_line(package_dir):
    p = os.path.join(os.path.abspath(package_dir), "tools", "install_dev.py")
    return f'p = r"{p}"; exec(open(p).read(), {{"__file__": p}})'


def install_text(folder_name, extension_zip_name, line, slicer_version, slicer_revision):
    return f"""3D Mouse Navigation (MouseNav3D) test package

Two ways to install it. Use one of them, not both.

A. Extensions Manager > Install from file  (Slicer {slicer_version}.x on Windows or Linux)
   File: {extension_zip_name}
         (in this folder, and next to it)
   In Slicer: View > Extensions Manager > Install from file..., choose that file, then restart Slicer.
   Only this zip is an extension package. Any other zip here (MouseNav3D_test_*.zip) is refused there with
   "No extension description found in archive".
   Built for Slicer {slicer_version} (revision {slicer_revision}). For another Slicer version or for macOS use the
   Extensions Manager's catalogue once MouseNav3D is listed, or way B.

B. Direct install  (no restart)
   Folder: {folder_name} (this folder; unzip MouseNav3D_test_*_direct-install.zip first if you got the zip)
   In Slicer: View > Python Console, paste this line (it names this folder's full path; if you moved the folder,
   change the path to where tools\\install_dev.py is now):

   {line}

Only one copy of the module may be loaded. Switching from B to A: first remove the MouseNav3D folder from
Edit > Application Settings > Modules > Additional module paths and restart Slicer. Switching from A to B: first
uninstall the extension in the Extensions Manager and restart Slicer.
Then open the module at Modules > Utilities > 3D Mouse Navigation.
"""


def build(dest, root=ROOT, today=None, slicer_version=package_extension.DEFAULT_SLICER_VERSION,
          slicer_revision=package_extension.DEFAULT_SLICER_REVISION):
    """Create the package folder, its zip and the extension package under `dest`.
    Returns (folder, direct-install zip path, install line, extension package path)."""
    today = today or datetime.date.today().strftime("%Y%m%d")
    dest = os.path.abspath(dest)
    folder = os.path.join(dest, f"MouseNav3D_test_{today}")
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for rel in INCLUDE:
        src = os.path.join(root, rel)
        target = os.path.join(folder, rel)
        if os.path.isdir(src):
            shutil.copytree(src, target, ignore=ignore)
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src, target)
        elif rel == os.path.join("docs", "images"):
            continue  # a checkout without screenshots still packages
        else:
            raise FileNotFoundError(src)
    ext_zip, _name = package_extension.build(dest, root=root, slicer_version=slicer_version,
                                             slicer_revision=slicer_revision)
    shutil.copy2(ext_zip, os.path.join(folder, os.path.basename(ext_zip)))
    line = install_line(folder)
    with open(os.path.join(folder, "INSTALL.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(install_text(os.path.basename(folder), os.path.basename(ext_zip), line, slicer_version,
                             slicer_revision))
    stale = folder + ".zip"  # the name earlier versions of this script gave the direct-install zip
    if os.path.isfile(stale):
        os.remove(stale)
    zip_path = folder + "_direct-install.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(folder):
            for name in files:
                full = os.path.join(base, name)
                z.write(full, os.path.relpath(full, os.path.dirname(folder)))
    return folder, zip_path, line, ext_zip


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    folder, zip_path, line, ext_zip = build(argv[1])
    print(f"Package folder:     {folder}\n"
          f"Direct-install zip: {zip_path}\n"
          f"Extension package:  {ext_zip}\n\n"
          f"A. Extensions Manager > Install from file: choose\n   {ext_zip}\n   then restart Slicer "
          f"(built for Slicer {package_extension.DEFAULT_SLICER_VERSION}, revision "
          f"{package_extension.DEFAULT_SLICER_REVISION}; Windows or Linux).\n\n"
          f"B. Direct install: in Slicer's Python console (View > Python Console) paste:\n\n{line}\n\n"
          f"{os.path.join(folder, 'INSTALL.txt')} says the same.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
