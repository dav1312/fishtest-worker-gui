@echo off
setlocal

:: Check if MSYS2 base is already installed
if exist "C:\msys64\msys2_shell.cmd" (
    echo MSYS2 is already installed in C:\msys64. Skipping installer download.
    goto :install_packages
)

echo Downloading MSYS2 installer...
curl -L -f -o "%TEMP%\msys2.exe" https://github.com/msys2/msys2-installer/releases/download/nightly-x86_64/msys2-x86_64-latest.exe
if errorlevel 1 (
    echo Error: Failed to download MSYS2 installer.
    exit /b 1
)

echo Installing MSYS2 to C:\msys64 in silent mode, this may take several minutes...
start /B /wait "" "%TEMP%\msys2.exe" in --confirm-command --accept-messages --root C:/msys64
set "INSTALL_ERR=%ERRORLEVEL%"
del "%TEMP%\msys2.exe" 2>nul
if %INSTALL_ERR% neq 0 (
    echo Error: MSYS2 installation failed with exit code %INSTALL_ERR%.
    exit /b %INSTALL_ERR%
)

:install_packages
echo Updating MSYS2 system packages...
call "C:\msys64\msys2_shell.cmd" -defterm -ucrt64 -no-start -here -c "pacman -Syuu --noconfirm"

echo Installing required development tools and packages (unzip, make, gcc, python)...
call "C:\msys64\msys2_shell.cmd" -defterm -ucrt64 -no-start -here -c "pacman -S --noconfirm --needed wget unzip make mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-python && pacman -Scc --noconfirm"
if errorlevel 1 (
    echo Error: Failed to install required MSYS2 packages.
    exit /b 1
)

echo MSYS2 environment is fully configured.
exit /b 0