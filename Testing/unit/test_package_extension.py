"""Extension package for the Extensions Manager's "Install from file" (tools/package_extension.py): archive layout,
description file content, and every file the CMake lists install. The rules come from Slicer 5.12's
qSlicerExtensionsManagerModel (installExtension, extractExtensionArchive, extractArchive) and its extension CMake
(SlicerExtensionCPack, extension_description.s4ext.in, SlicerExtensionDescriptionSpec)."""
import os
import re
import sys
import zipfile

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import package_extension as pe  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
NAME = "34645-win-amd64-MouseNav3D-git0123456-2026-10-29"


def build(tmp_path, **kw):
    kw = {"scm_revision": SHA, "date": "2026-10-29", "os_name": "win", "arch": "amd64", **kw}
    return pe.build(str(tmp_path), **kw)


def parse_s4ext(text):
    """As qSlicerExtensionsManagerModel::parseExtensionDescriptionFile: '#' lines and blank lines skipped, first
    token is the key, the remaining tokens joined by one space are the value."""
    meta = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts:
            meta[parts[0]] = " ".join(parts[1:])
    return meta


def cmake_listed():
    text = open(os.path.join(ROOT, "MouseNav3D", "CMakeLists.txt"), encoding="utf-8").read()
    items = []
    for var in ("MODULE_PYTHON_SCRIPTS", "MODULE_PYTHON_RESOURCES"):
        body = re.search(r"set\(" + var + r"(.*?)\)", text, re.S).group(1)
        items += [i.replace("${MODULE_NAME}", "MouseNav3D") for i in body.split()]
    return items


def test_archive_name_and_single_top_folder(tmp_path):
    zip_path, name = build(tmp_path)
    assert name == NAME
    assert os.path.basename(zip_path) == NAME + ".zip"
    assert os.path.dirname(zip_path) == str(tmp_path)
    names = zipfile.ZipFile(zip_path).namelist()
    # extractArchive takes the top folder from the first entry and assumes everything is under it
    assert {n.split("/")[0] for n in names} == {NAME}
    assert not any(n.endswith("/") for n in names), "file entries only"
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_description_file_location(tmp_path):
    zip_path, _ = build(tmp_path)
    names = zipfile.ZipFile(zip_path).namelist()
    s4ext = [n for n in names if n.endswith(".s4ext")]
    # installExtension(archive) takes the first .s4ext as the extension name; the model then reads
    # <install>/<name>/share/Slicer-X.Y/<name>.s4ext
    assert s4ext == [f"{NAME}/share/Slicer-5.12/MouseNav3D.s4ext"]
    assert names[0] == s4ext[0]


def test_every_cmake_listed_file_is_in_the_scripted_modules_folder(tmp_path):
    zip_path, _ = build(tmp_path)
    z = zipfile.ZipFile(zip_path)
    prefix = f"{NAME}/lib/Slicer-5.12/qt-scripted-modules/"
    module = sorted(n[len(prefix):] for n in z.namelist() if n.startswith(prefix))
    listed = cmake_listed()
    assert module == sorted(listed)
    assert len(z.namelist()) == len(listed) + 1  # plus the description file, nothing else
    for rel in listed:
        with open(os.path.join(ROOT, "MouseNav3D", *rel.split("/")), "rb") as f:
            assert z.read(prefix + rel) == f.read(), rel
    for must in ("MouseNav3D.py", "MouseNav3DLib/__init__.py", "MouseNav3DLib/fallback/navigator.py",
                 "Resources/Icons/MouseNav3D.png", "Resources/LICENSE.txt", "Resources/LICENSE-LGPL.txt",
                 "Resources/NOTICE.md"):
        assert must in module, must


def test_module_files_parses_the_cmake_lists():
    assert pe.module_files(ROOT) == cmake_listed()


def test_description_content(tmp_path):
    zip_path, _ = build(tmp_path)
    text = zipfile.ZipFile(zip_path).read(f"{NAME}/share/Slicer-5.12/MouseNav3D.s4ext").decode("utf-8")
    meta = parse_s4ext(text)
    cmake = open(os.path.join(ROOT, "CMakeLists.txt"), encoding="utf-8").read()

    def ext(var):
        return re.search(r'set\(EXTENSION_' + var + r' "([^"]*)"\)', cmake).group(1)

    # every key of Slicer's extension_description.s4ext.in, in its order
    keys = [line.split()[0] for line in text.splitlines() if line and not line.startswith("#")]
    assert keys == ["scm", "scmurl", "scmrevision", "depends", "recommends", "build_subdirectory", "homepage",
                    "contributors", "category", "iconurl", "status", "tier", "description", "screenshoturls",
                    "enabled", "dicom_support_rule", "keywords"]
    assert meta["scm"] == "git"
    assert meta["scmurl"] == ext("HOMEPAGE") + ".git"
    assert meta["scmrevision"] == SHA
    assert meta["depends"] == "NA" == ext("DEPENDS")
    assert meta["build_subdirectory"] == "."
    assert meta["homepage"] == ext("HOMEPAGE")
    assert meta["contributors"] == ext("CONTRIBUTORS")
    assert meta["category"] == ext("CATEGORY") == "Utilities"
    assert meta["iconurl"] == ext("ICONURL")
    assert meta["description"] == ext("DESCRIPTION")
    assert meta["screenshoturls"].split() == ext("SCREENSHOTURLS").split()
    assert meta["enabled"] == "1" and meta["tier"] == "1"
    assert "\r" not in text and text.endswith("\n")
    # nothing names a Slicer revision, OS or architecture: the manager takes those from the running Slicer
    assert not {"slicer_revision", "os", "arch"} & set(meta)


def test_slicer_version_and_revision_are_overridable(tmp_path):
    zip_path, name = build(tmp_path, slicer_version="5.10", slicer_revision="33241", os_name="linux")
    assert name.startswith("33241-linux-amd64-MouseNav3D-git0123456-")
    names = zipfile.ZipFile(zip_path).namelist()
    assert f"{name}/share/Slicer-5.10/MouseNav3D.s4ext" in names
    assert f"{name}/lib/Slicer-5.10/qt-scripted-modules/MouseNav3D.py" in names
    with pytest.raises(ValueError):
        build(tmp_path, slicer_version="5.12.4")
    with pytest.raises(ValueError):
        build(tmp_path, os_name="android")


def test_windows_and_linux_layouts_are_the_same(tmp_path):
    win, wname = build(tmp_path / "w", os_name="win")
    lin, lname = build(tmp_path / "l", os_name="linux")
    strip = lambda names, top: sorted(n[len(top) + 1:] for n in names)  # noqa: E731
    assert strip(zipfile.ZipFile(win).namelist(), wname) == strip(zipfile.ZipFile(lin).namelist(), lname)


def test_macos_layout_sits_in_the_bundle_folder_of_its_revision(tmp_path):
    zip_path, name = build(tmp_path, os_name="macosx", arch="arm64")
    names = zipfile.ZipFile(zip_path).namelist()
    base = f"{name}/Slicer.app/Contents/Extensions-34645/MouseNav3D/"
    assert names[0] == base + "share/Slicer-5.12/MouseNav3D.s4ext"
    assert base + "lib/Slicer-5.12/qt-scripted-modules/MouseNav3D.py" in names
    assert all(n.startswith(base) for n in names)


def test_missing_listed_file_is_an_error(tmp_path):
    fake = tmp_path / "repo"
    (fake / "MouseNav3D").mkdir(parents=True)
    (fake / "CMakeLists.txt").write_text(open(os.path.join(ROOT, "CMakeLists.txt"), encoding="utf-8").read())
    (fake / "MouseNav3D" / "CMakeLists.txt").write_text(
        "set(MODULE_NAME MouseNav3D)\nset(MODULE_PYTHON_SCRIPTS\n  ${MODULE_NAME}.py\n  )\n"
        "set(MODULE_PYTHON_RESOURCES\n  # a comment\n  Resources/Icons/${MODULE_NAME}.png\n  )\n")
    (fake / "MouseNav3D" / "MouseNav3D.py").write_text("")
    assert pe.module_files(str(fake)) == ["MouseNav3D.py", "Resources/Icons/MouseNav3D.png"]
    with pytest.raises(FileNotFoundError):
        pe.build(str(tmp_path / "out"), root=str(fake), scm_revision=SHA, date="2026-10-29", os_name="win")
    assert not list((tmp_path / "out").glob("*.zip"))


def test_unresolved_cmake_variable_is_an_error():
    with pytest.raises(ValueError):
        pe.cmake_list("set(X\n  ${OTHER}/a.py\n)", "X", {"MODULE_NAME": "M"})


def test_cli_names_the_target(tmp_path, capsys):
    assert pe.main([str(tmp_path), "--os", "win", "--arch", "amd64", "--scm-revision", SHA, "--date",
                    "2026-10-29"]) == 0
    out = capsys.readouterr().out
    assert "Slicer 5.12 (revision 34645)" in out and NAME + ".zip" in out
    assert os.path.isfile(tmp_path / (NAME + ".zip"))


def test_default_output_is_dist(tmp_path):
    import shutil
    copy = tmp_path / "repo"
    shutil.copytree(os.path.join(ROOT, "MouseNav3D"), copy / "MouseNav3D",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(os.path.join(ROOT, "CMakeLists.txt"), copy / "CMakeLists.txt")
    zip_path, _ = pe.build(None, root=str(copy), scm_revision=SHA, date="2026-10-29", os_name="win", arch="amd64")
    assert zip_path == str(copy / "dist" / (NAME + ".zip"))
