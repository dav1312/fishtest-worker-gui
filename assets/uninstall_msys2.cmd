@echo off
setlocal

if not exist "C:\msys64\uninstall.exe" (
    echo MSYS2 not found.
    exit /b 0
)

start /B /wait "" "C:\msys64\uninstall.exe" pr --confirm-command
set "UNINSTALL_ERR=%ERRORLEVEL%"
if %UNINSTALL_ERR% neq 0 (
    echo Error: MSYS2 uninstallation failed with exit code %UNINSTALL_ERR%.
    exit /b %UNINSTALL_ERR%
)

:: The uninstaller deletes itself only after it exits, so wait for that
:: before returning, or the GUI would still see MSYS2 as installed
set /a WAITED=0
:wait_for_removal
if not exist "C:\msys64\uninstall.exe" goto :done
if %WAITED% geq 60 (
    echo MSYS2 uninstaller is still finishing in the background.
    goto :done
)
ping -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto :wait_for_removal

:done
exit /b 0
