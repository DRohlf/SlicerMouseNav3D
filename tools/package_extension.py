r"""Extension package for Slicer's Extensions Manager > Install from file: python tools/package_extension.py [dest]

Builds the archive that a Slicer extension build (CPack) would make for this pure-Python extension, without a Slicer
build tree, so Slicer's "Install from file" accepts it. Uses only the standard library. Output: <dest>/<name>.zip,
default dest dist/ in the repository.

Layout (Slicer 5.12, Windows and Linux; see the docstring of `layout_prefix` for macOS):

    <name>/share/Slicer-5.12/MouseNav3D.s4ext                     extension description (the manager looks for it)
    <name>/lib/Slicer-5.12/qt-scripted-modules/MouseNav3D.py      every MODULE_PYTHON_SCRIPTS entry
    <name>/lib/Slicer-5.12/qt-scripted-modules/MouseNav3DLib/...
    <name>/lib/Slicer-5.12/qt-scripted-modules/Resources/...      every MODULE_PYTHON_RESOURCES entry

<name> follows the CPack convention <slicer revision>-<os>-<arch>-MouseNav3D-git<commit>-<date of last commit>
(the commit shortened to 7 characters to keep installed paths short on Windows). Slicer does not parse the name:
it reads the extension name from the .s4ext file and takes os, arch and revision from the running Slicer.

Options: --slicer-version 5.12  --slicer-revision 34645  --os win|linux|macosx  --arch amd64|arm64
         --scm-revision <commit>  --date YYYY-MM-DD   (the last two default to the git checkout, else NA / today)
"""
import argparse
import datetime
import os
import platform
import re
import subprocess
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EXTENSION_NAME = "MouseNav3D"
DEFAULT_SLICER_VERSION = "5.12"
DEFAULT_SLICER_REVISION = "34645"
OS_NAMES = ("win", "linux", "macosx")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmake_list(text, variable, substitutions):
    """Items of `set(<variable> ...)` in a CMake file, `${VAR}` replaced from `substitutions`, comments dropped."""
    m = re.search(r"set\(\s*" + re.escape(variable) + r"\s(.*?)\)", text, re.S)
    if not m:
        raise ValueError(f"set({variable} ...) not found")
    body = "\n".join(line.split("#", 1)[0] for line in m.group(1).splitlines())
    items = []
    for item in body.split():
        for key, value in substitutions.items():
            item = item.replace("${" + key + "}", value)
        if "${" in item:
            raise ValueError(f"unresolved variable in {variable}: {item}")
        items.append(item)
    return items


def module_files(root=ROOT):
    """Paths relative to the module folder (MouseNav3D/) that the CMake build installs: scripts, then resources."""
    text = _read(os.path.join(root, EXTENSION_NAME, "CMakeLists.txt"))
    name = re.search(r"set\(\s*MODULE_NAME\s+(\w+)\s*\)", text).group(1)
    subs = {"MODULE_NAME": name}
    return cmake_list(text, "MODULE_PYTHON_SCRIPTS", subs) + cmake_list(text, "MODULE_PYTHON_RESOURCES", subs)


def extension_metadata(root=ROOT):
    """The EXTENSION_* values of the top-level CMakeLists.txt, keyed without the prefix (HOMEPAGE, CATEGORY, ...)."""
    text = _read(os.path.join(root, "CMakeLists.txt"))
    meta = {k: v for k, v in re.findall(r'set\(\s*EXTENSION_(\w+)\s+"([^"]*)"\s*\)', text)}
    meta.setdefault("NAME", EXTENSION_NAME)
    return meta


def _git(root, *args):
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def s4ext_text(meta, scm_revision):
    """The description file as Slicer's template Utilities/Templates/Extensions/extension_description.s4ext.in
    writes it (defaults from Extensions/CMake/SlicerExtensionDescriptionSpec.cmake). One key per line: the first
    token is the key, the rest of the line the value."""
    def one_line(value):
        return " ".join(value.split())

    homepage = meta.get("HOMEPAGE", "")
    fields = [
        ("This is source code manager", [("scm", "git"), ("scmurl", homepage + ".git" if homepage else ""),
                                         ("scmrevision", scm_revision)]),
        ("list dependencies\n# - These should be names of other modules that have .s4ext files\n"
         "# - The dependencies will be built first", [("depends", one_line(meta.get("DEPENDS", "NA")) or "NA")]),
        ("list recommendations\n# - These should be names of other modules that have .s4ext files\n"
         "# - The user is recommended to install the extensions", [("recommends", "NA")]),
        ('Inner build directory (default is ".")', [("build_subdirectory", ".")]),
        ("homepage", [("homepage", homepage)]),
        ("Firstname1 Lastname1 ([SubOrg1, ]Org1), Firstname2 Lastname2 ([SubOrg2, ]Org2)\n"
         "# For example: Jane Roe (Superware), John Doe (Lab1, Nowhere), Joe Bloggs (Noware)",
         [("contributors", one_line(meta.get("CONTRIBUTORS", "")))]),
        ("Match category in the xml description of the module (where it shows up in Modules menu)",
         [("category", meta.get("CATEGORY", ""))]),
        ("url to icon (png, size 128x128 pixels)", [("iconurl", meta.get("ICONURL", ""))]),
        ("Give people an idea what to expect from this code\n#  - Is it just a test or something you stand behind?",
         [("status", meta.get("STATUS", ""))]),
        ("Extension tier: 1 to 5\n# See https://slicer.readthedocs.io/en/latest/developer_guide/extensions.html",
         [("tier", meta.get("TIER", "1"))]),
        ("One line stating what the module does", [("description", one_line(meta.get("DESCRIPTION", "")))]),
        ("Space separated list of urls", [("screenshoturls", one_line(meta.get("SCREENSHOTURLS", "")))]),
        ("0 or 1: Define if the extension should be enabled after its installation.",
         [("enabled", meta.get("ENABLED", "1"))]),
        ("Rule expression to determine if extension should handle specific DICOM data",
         [("dicom_support_rule", meta.get("DICOM_SUPPORT_RULE", ""))]),
        ("Space separated list of keywords to help when searching for extensions",
         [("keywords", one_line(meta.get("KEYWORDS", "")))]),
    ]
    out = ["#", "# First token of each non-comment line is the keyword and the rest of the line",
           "# (including spaces) is the value.", "# - the value can be blank", "#"]
    for comment, pairs in fields:
        out += ["", "# " + comment] + [f"{k} {v}".rstrip() if v else k + " " for k, v in pairs]
    return "\n".join(out) + "\n"


def default_os():
    return {"win32": "win", "darwin": "macosx"}.get(sys.platform, "linux")


def default_arch():
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"


def layout_prefix(os_name, slicer_revision):
    """Folder inside the archive's top folder that holds lib/ and share/. Empty on Windows and Linux. On macOS the
    manager copies <top>/Slicer.app/Contents/Extensions-<running revision>/<extension>/ (qSlicerExtensionsManagerModel
    ::extractExtensionArchive), so a macOS package only installs into the Slicer revision it names."""
    if os_name == "macosx":
        return f"Slicer.app/Contents/Extensions-{slicer_revision}/{EXTENSION_NAME}/"
    return ""


def package_name(slicer_revision, os_name, arch, scm_revision, date):
    short = scm_revision[:7] if scm_revision != "NA" else "NA"
    return f"{slicer_revision}-{os_name}-{arch}-{EXTENSION_NAME}-git{short}-{date}"


def archive_members(root=ROOT, slicer_version=DEFAULT_SLICER_VERSION, slicer_revision=DEFAULT_SLICER_REVISION,
                    os_name="win"):
    """(path below the archive's top folder, source file relative to the module folder) for every file of the
    package; the description file comes first, with source None."""
    prefix = layout_prefix(os_name, slicer_revision)
    module_dir = f"{prefix}lib/Slicer-{slicer_version}/qt-scripted-modules/"
    members = [(f"{prefix}share/Slicer-{slicer_version}/{EXTENSION_NAME}.s4ext", None)]
    return members + [(module_dir + rel, rel) for rel in module_files(root)]


def build(dest=None, root=ROOT, slicer_version=DEFAULT_SLICER_VERSION, slicer_revision=DEFAULT_SLICER_REVISION,
          os_name=None, arch=None, scm_revision=None, date=None):
    """Write the package zip under `dest` (default <root>/dist); returns (zip path, package name)."""
    os_name = os_name or default_os()
    if os_name not in OS_NAMES:
        raise ValueError(f"os must be one of {OS_NAMES}, not {os_name!r}")
    if not re.fullmatch(r"\d+\.\d+", slicer_version):
        raise ValueError(f"slicer version is major.minor (e.g. 5.12), not {slicer_version!r}")
    arch = arch or default_arch()
    scm_revision = scm_revision or _git(root, "rev-parse", "HEAD") or "NA"
    date = date or _git(root, "log", "-1", "--format=%cs") or datetime.date.today().isoformat()
    name = package_name(slicer_revision, os_name, arch, scm_revision, date)
    dest = os.path.abspath(dest or os.path.join(root, "dist"))
    os.makedirs(dest, exist_ok=True)
    zip_path = os.path.join(dest, name + ".zip")
    description = s4ext_text(extension_metadata(root), scm_revision)
    members = archive_members(root, slicer_version, slicer_revision, os_name)
    for _arc, rel in members[1:]:
        if not os.path.isfile(os.path.join(root, EXTENSION_NAME, *rel.split("/"))):
            raise FileNotFoundError(f"listed in {EXTENSION_NAME}/CMakeLists.txt but missing: {rel}")
    tmp = zip_path + ".part"
    # File entries only, all under one top folder: the manager takes the top folder from the first entry.
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, rel in members:
            if rel is None:
                z.writestr(f"{name}/{arc}", description)
            else:
                z.write(os.path.join(root, EXTENSION_NAME, *rel.split("/")), f"{name}/{arc}")
    os.replace(tmp, zip_path)
    return zip_path, name


def main(argv=None):
    p = argparse.ArgumentParser(description="Build the MouseNav3D extension package for Slicer's Extensions Manager "
                                            "> Install from file.")
    p.add_argument("dest", nargs="?", help="output folder (default: dist/ in the repository)")
    p.add_argument("--slicer-version", default=DEFAULT_SLICER_VERSION, help="major.minor (default %(default)s)")
    p.add_argument("--slicer-revision", default=DEFAULT_SLICER_REVISION, help="default %(default)s (Slicer 5.12.4)")
    p.add_argument("--os", dest="os_name", choices=OS_NAMES, help=f"default: this computer's ({default_os()})")
    p.add_argument("--arch", help=f"default: this computer's ({default_arch()})")
    p.add_argument("--scm-revision", help="commit recorded in the package (default: git HEAD)")
    p.add_argument("--date", help="YYYY-MM-DD in the package name (default: date of the last commit)")
    a = p.parse_args(argv)
    zip_path, name = build(a.dest, slicer_version=a.slicer_version, slicer_revision=a.slicer_revision,
                           os_name=a.os_name, arch=a.arch, scm_revision=a.scm_revision, date=a.date)
    os_name = a.os_name or default_os()
    print(f"Extension package: {zip_path}\n"
          f"Built for Slicer {a.slicer_version} (revision {a.slicer_revision}), {os_name} {a.arch or default_arch()}.\n"
          "Install: Slicer > View > Extensions Manager > Install from file..., choose this zip, restart Slicer.")
    if os_name == "macosx":
        print(f"macOS package: installs only into a Slicer of revision {a.slicer_revision}; not tested.")
    else:
        print("The same zip works on Windows and Linux Slicer " + a.slicer_version + ".x (same layout, pure Python).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
