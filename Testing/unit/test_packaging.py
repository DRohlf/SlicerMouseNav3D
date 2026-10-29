"""Packaging: the home test package (direct install and the extension package), and the Extensions Index readiness of the repository (every module
file is in the CMake lists, the metadata has no placeholders, the index entry matches CMakeLists.txt)."""
import json
import os
import re
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import package_test_build as pkg  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_package_contents_and_install_line(tmp_path):
    folder, zip_path, line, ext_zip = pkg.build(str(tmp_path), today="20261029")
    assert os.path.basename(folder) == "MouseNav3D_test_20261029"
    for rel in ("MouseNav3D/MouseNav3D.py", "MouseNav3D/MouseNav3DLib/fallback/navigator.py",
                "MouseNav3D/Resources/Icons/MouseNav3D.png", "tools/install_dev.py", "README.md",
                "docs/HARDWARE_CHECKLIST.md", "LICENSE.txt", "LICENSE-LGPL.txt", "NOTICE.md", "INSTALL.txt"):
        assert os.path.isfile(os.path.join(folder, *rel.split("/"))), rel
    assert not any("__pycache__" in base for base, _d, _f in os.walk(folder))
    assert line == f'p = r"{os.path.join(folder, "tools", "install_dev.py")}"; exec(open(p).read(), {{"__file__": p}})'
    assert os.path.isabs(os.path.join(folder, "tools", "install_dev.py"))
    assert os.path.basename(zip_path) == "MouseNav3D_test_20261029_direct-install.zip"
    names = zipfile.ZipFile(zip_path).namelist()
    assert "MouseNav3D_test_20261029/tools/install_dev.py" in names


def test_package_carries_the_extension_package_and_says_which_file_is_which(tmp_path):
    folder, zip_path, line, ext_zip = pkg.build(str(tmp_path), today="20261029")
    name = os.path.basename(ext_zip)
    assert re.fullmatch(r"34645-\w+-\w+-MouseNav3D-git\w+-\d{4}-\d\d-\d\d\.zip", name), name
    assert os.path.dirname(ext_zip) == str(tmp_path)  # next to the folder ...
    assert os.path.isfile(os.path.join(folder, name))  # ... and inside it
    assert any(n.endswith("/share/Slicer-5.12/MouseNav3D.s4ext") for n in zipfile.ZipFile(ext_zip).namelist())
    text = open(os.path.join(folder, "INSTALL.txt"), encoding="utf-8").read()
    assert "Install from file" in text and name in text and line in text
    assert "No extension description found" in text and "Slicer 5.12" in text
    # the direct-install zip is not an extension package: Install from file would refuse it
    assert not any(n.endswith(".s4ext") for n in zipfile.ZipFile(zip_path).namelist())


def test_rebuild_replaces_the_folder(tmp_path):
    folder, _z, _l, _e = pkg.build(str(tmp_path), today="20261029")
    stale = os.path.join(folder, "stale.txt")
    open(stale, "w").close()
    old_zip = folder + ".zip"  # the direct-install zip's earlier name
    open(old_zip, "w").close()
    pkg.build(str(tmp_path), today="20261029")
    assert not os.path.exists(stale)
    assert not os.path.exists(old_zip)


def test_every_module_file_is_listed_in_cmake():
    cmake = read("MouseNav3D", "CMakeLists.txt")
    listed = set(re.findall(r"\$\{MODULE_NAME\}(Lib/[\w/]+\.py|\.py)", cmake))
    on_disk = {"Lib/" + os.path.relpath(os.path.join(b, f), os.path.join(ROOT, "MouseNav3D", "MouseNav3DLib")).replace(os.sep, "/")
               for b, _d, fs in os.walk(os.path.join(ROOT, "MouseNav3D", "MouseNav3DLib"))
               for f in fs if f.endswith(".py")} | {".py"}
    assert listed == on_disk
    assert "Resources/Icons/${MODULE_NAME}.png" in cmake
    assert os.path.isfile(os.path.join(ROOT, "MouseNav3D", "Resources", "Icons", "MouseNav3D.png"))


def test_licence_texts_ship_in_the_installed_module():
    """LICENSE.txt, LICENSE-LGPL.txt and NOTICE.md are module resources (so the Index-built package carries them),
    identical to the root copies GitHub and the Index read, and the panel's acknowledgement points at them."""
    cmake = read("MouseNav3D", "CMakeLists.txt")
    resources = re.search(r"set\(MODULE_PYTHON_RESOURCES(.*?)\)", cmake, re.S).group(1).split()
    for name in ("LICENSE.txt", "LICENSE-LGPL.txt", "NOTICE.md"):
        assert f"Resources/{name}" in resources, name
        assert read("MouseNav3D", "Resources", name).replace("\r\n", "\n") == read(name).replace("\r\n", "\n"), name
    module = read("MouseNav3D", "MouseNav3D.py")
    assert "Resources/NOTICE.md" in module and "Resources/LICENSE-LGPL.txt" in module
    header = read("MouseNav3D", "MouseNav3DLib", "navlib_ctypes.py")[:1500]
    assert "free software" in header and "LICENSE-LGPL.txt" in header


def test_extension_metadata_has_no_placeholders_and_matches_the_index_entry():
    cmake = read("CMakeLists.txt")
    assert "OWNER" not in cmake
    entry = json.loads(read("docs", "extensions-index", "MouseNav3D.json"))
    home = re.search(r'set\(EXTENSION_HOMEPAGE "([^"]+)"\)', cmake).group(1)
    assert home == "https://github.com/DRohlf/SlicerMouseNav3D"
    assert entry["scm_url"] == home + ".git"
    assert entry["category"] == re.search(r'set\(EXTENSION_CATEGORY "([^"]+)"\)', cmake).group(1) == "Utilities"
    assert entry["scm_revision"] == "main"
    assert entry["$schema"].endswith("slicer-extension-catalog-entry-schema-v1.0.2.json#")
    assert set(entry) <= {"$schema", "category", "scm_url", "scm_revision", "scm_type", "build_dependencies",
                          "dicom_support_rule", "build_subdirectory", "enabled", "tier"}
    assert entry["build_dependencies"] == [] and re.search(r'set\(EXTENSION_DEPENDS "NA"\)', cmake)
    icon = re.search(r'set\(EXTENSION_ICONURL "([^"]+)"\)', cmake).group(1)
    assert icon == "https://raw.githubusercontent.com/DRohlf/SlicerMouseNav3D/main/MouseNav3D/Resources/Icons/MouseNav3D.png"
    shots = re.search(r'set\(EXTENSION_SCREENSHOTURLS "([^"]+)"\)', cmake).group(1).split()
    assert shots
    prefix = "https://raw.githubusercontent.com/DRohlf/SlicerMouseNav3D/main/"
    for url in shots:
        assert url.startswith(prefix) and os.path.isfile(os.path.join(ROOT, *url[len(prefix):].split("/"))), url
    assert re.search(r"^project\(MouseNav3D\)", cmake, re.M)


def test_json_file_uses_lf_only():
    with open(os.path.join(ROOT, "docs", "extensions-index", "MouseNav3D.json"), "rb") as f:
        assert b"\r" not in f.read()
