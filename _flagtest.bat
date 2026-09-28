@echo off
setlocal enabledelayedexpansion
set "REBUILD_UI=0"
set "SKIP_UI=0"
echo BEFORE rebuild=!REBUILD_UI! skip=!SKIP_UI!
if "%~1"=="" goto :flags_done
for %%A in (%*) do (
  if /i "%%~A"=="--rebuild-ui" set "REBUILD_UI=1"
  if /i "%%~A"=="--skip-ui" set "SKIP_UI=1"
)
:flags_done
echo AFTER rebuild=!REBUILD_UI! skip=!SKIP_UI! args=[%*]
endlocal
