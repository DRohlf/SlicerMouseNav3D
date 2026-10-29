r"""Direct-install test package: python tools/package_test_build.py <dest>

Copies the MouseNav3D module, tools/install_dev.py, the README, the hardware checklist, the licence files and the
README's images into <dest>/MouseNav3D_test_<date>/ (and a .zip of the same), then prints the line to paste into
Slicer's Python console, with the package's real absolute path. Uses only the standard library.
"""
import datetime
import os
import shutil
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
INCLUDE = ["MouseNav3D", os.path.join("tools", "install_dev.py"), "README.md",
           os.path.join("docs", "HARDWARE_CHECKLIST.md"), os.path.join("docs", "images"), "LICENSE.txt",
           "LICENSE-LGPL.txt", "NOTICE.md"]


def install_line(package_dir):
    p = os.path.join(os.path.abspath(package_dir), "tools", "install_dev.py")
    return f'p = r"{p}"; exec(open(p).read(), {{"__file__": p}})'


def build(dest, root=ROOT, today=None):
    """Create the package folder and zip under `dest`; returns (folder, zip path, install line)."""
    today = today or datetime.date.today().strftime("%Y%m%d")
    folder = os.path.join(os.path.abspath(dest), f"MouseNav3D_test_{today}")
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
    zip_path = folder + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(folder):
            for name in files:
                full = os.path.join(base, name)
                z.write(full, os.path.relpath(full, os.path.dirname(folder)))
    return folder, zip_path, install_line(folder)


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    folder, zip_path, line = build(argv[1])
    print(f"Package: {folder}\nZip:     {zip_path}\n\nIn Slicer's Python console (View > Python Console) paste:\n\n{line}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
