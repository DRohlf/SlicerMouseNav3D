cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(MouseNav3D)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_NAME MouseNav3D)
set(EXTENSION_HOMEPAGE "https://github.com/DRohlf/SlicerMouseNav3D")
set(EXTENSION_CATEGORY "Utilities")
set(EXTENSION_CONTRIBUTORS "Devon Rohlf")
set(EXTENSION_DESCRIPTION "Navigate Slicer's 3D and slice views with a 3D mouse (works with 3Dconnexion SpaceMouse devices).")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/DRohlf/SlicerMouseNav3D/main/MouseNav3D/Resources/Icons/MouseNav3D.png")
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/DRohlf/SlicerMouseNav3D/main/docs/images/layout.png https://raw.githubusercontent.com/DRohlf/SlicerMouseNav3D/main/docs/images/panel_fallback.png https://raw.githubusercontent.com/DRohlf/SlicerMouseNav3D/main/docs/images/panel_driver.png")
set(EXTENSION_DEPENDS "NA")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(MouseNav3D)

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
