# Submitting MouseNav3D to Slicer's Extensions Index

Prepared for the index's current format, checked 29 Oct 2026 against github.com/Slicer/ExtensionsIndex (`README.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `AGENTS.md`, `scripts/check_description_files.py`, `schemas/slicer-extension-catalog-entry-schema-v1.0.2.json`). Entries are `<ExtensionName>.json` at the index's root, validated against the v1.0.2 schema (required: `$schema`, `category`, `scm_url`). The ready file is `docs/extensions-index/MouseNav3D.json`.

## Checklist (PR template) and status

Tier 1 (required)

| Item | Status |
|---|---|
| Reasonable name, not starting with `Slicer` | Done: `MouseNav3D` |
| Repository named Slicer+ExtensionName | Done: `SlicerMouseNav3D` (the index's checker requires the prefix) |
| GitHub topic `3d-slicer-extension` | USER: set it on GitHub (About, settings icon, Topics); the checker queries the GitHub API |
| 1-2 sentence description for non-experts | Done: `EXTENSION_DESCRIPTION` in `CMakeLists.txt`, README opening |
| Known related patents mentioned | USER: none known to the author; confirm, and add a sentence to the description if you know of any |
| `LICENSE.txt` in the root, licence named on the homepage | Done: Apache-2.0 `LICENSE.txt`; README "Licences and attribution" names it (LGPL file noted) |
| URL and revision correct, branch name preferred | Done: `https://github.com/DRohlf/SlicerMouseNav3D.git`, `main` (the branch must be named `main` and pushed) |
| Icon URL is the raw data URL | Done: raw.githubusercontent.com `.../main/MouseNav3D/Resources/Icons/MouseNav3D.png`; resolves after the push |
| At least one screenshot URL | Done: three raw URLs for `docs/images/*.png` in `EXTENSION_SCREENSHOTURLS`; resolve after the push to `main` |
| JSON consistent with top-level `CMakeLists.txt` | Done: `project(MouseNav3D)`, category Utilities, no dependencies (`EXTENSION_DEPENDS NA`, `build_dependencies []`); `Testing/unit/test_packaging.py` checks it |
| Homepage has name, short description, image, one sentence per module, publication | Done in the README (the homepage is the repository page): name, description, screenshots, module description. No publication exists |
| Hide unused GitHub features: Wiki, Projects, Discussions, Releases, Packages | USER: Settings, uncheck Wiki, Projects, Discussions; About settings icon, uncheck Releases and Packages |
| Safe: no binaries from unreliable sources | Done: no binaries shipped or downloaded; the Navigation Library is loaded from the user's own 3Dconnexion install |
| Safe: sends nothing without opt-in | Done: no network code |

Tier 3 (optional; the entry is submitted as tier 1)

| Item | Status |
|---|---|
| Documentation, tutorial with screenshots, test data | README has usage and screenshots; no sample data needed (the module acts on any loaded data) |
| Slicer programming and UI conventions | Panel uses standard Qt/ctk widgets, no custom styling, no popups |
| Builds and packages on Windows, macOS, Linux | Pure-Python scripted module in the standard layout (`slicerMacroBuildScriptedModule`, every `.py` and the icon listed; a unit test checks the list). Not built here against a Slicer source tree: the index's CI does that |
| Maintainers respond to issues, PRs, forum mentions | USER |
| Permissive licence for main functions | Apache-2.0; the one LGPL interface file is declared in NOTICE.md |

The index reviewers' stated admission requirements (AGENTS.md) are safety, clear distribution permission (`LICENSE.txt`, `LICENSE-LGPL.txt`, `NOTICE.md`) and a usable catalog entry. They also look for package installation at startup (none here) and for packaged Python files that CMake does not install (all are listed).

## Steps left for you

1. Create `github.com/DRohlf/SlicerMouseNav3D` (public). Its `main` branch is a single squashed commit of `develop`'s tree; only `main` is pushed. The entry and the URLs point at `main`; the raw icon and screenshot URLs resolve only once it is pushed and public.
2. Set the topic `3d-slicer-extension`; switch off Wiki, Projects, Discussions, Releases, Packages.
3. Fork github.com/Slicer/ExtensionsIndex, copy `docs/extensions-index/MouseNav3D.json` to the fork's root as `MouseNav3D.json`, open a pull request, keep the "New extension" section of the template and tick the Tier 1 boxes.
4. Optional local check, from a checkout of the index: `python scripts/check_description_files.py MouseNav3D.json` (needs network and the public repository).
5. Answer the review on the PR; later revisions need no new PR while the entry names `main`.
