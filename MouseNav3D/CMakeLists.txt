#-----------------------------------------------------------------------------
set(MODULE_NAME MouseNav3D)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ${MODULE_NAME}Lib/__init__.py
  ${MODULE_NAME}Lib/camera_math.py
  ${MODULE_NAME}Lib/commands.py
  ${MODULE_NAME}Lib/controller.py
  ${MODULE_NAME}Lib/navlib_ctypes.py
  ${MODULE_NAME}Lib/recorder.py
  ${MODULE_NAME}Lib/settings.py
  ${MODULE_NAME}Lib/slice_bridge.py
  ${MODULE_NAME}Lib/view3d_bridge.py
  ${MODULE_NAME}Lib/fallback/__init__.py
  ${MODULE_NAME}Lib/fallback/hid_windows.py
  ${MODULE_NAME}Lib/fallback/motion.py
  ${MODULE_NAME}Lib/fallback/navigator.py
  ${MODULE_NAME}Lib/fallback/spacenavd.py
  )

# The licence texts and the notice ship inside the installed module (copies of the files in the repository root).
set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/LICENSE.txt
  Resources/LICENSE-LGPL.txt
  Resources/NOTICE.md
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )
