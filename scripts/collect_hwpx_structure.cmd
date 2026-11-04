@echo off
setlocal
if "%~1"=="" (
  echo Drag a copy of PT.hwpx onto this CMD file.
  echo Keep collect_hwpx_structure.ps1 in the same folder.
  pause
  exit /b 2
)
powershell.exe -NoLogo -NoProfile -File "%~dp0collect_hwpx_structure.ps1" -SourcePath "%~f1"
set "bbolprom_exit=%errorlevel%"
if not "%bbolprom_exit%"=="0" echo Collection did not complete. Keep the error text for diagnosis.
pause
exit /b %bbolprom_exit%
