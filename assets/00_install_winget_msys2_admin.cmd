@echo off
:: check if msys2 is already installed
if exist "C:\msys64\msys2_shell.cmd" (
    echo msys2 is already installed. Skipping installation.
    exit /b 0
)

echo Downloading MSYS2 installer...
curl -L -f -o "%TEMP%\msys2.exe" https://github.com/msys2/msys2-installer/releases/download/nightly-x86_64/msys2-x86_64-latest.exe
if errorlevel 1 (
    echo Error: Failed to download MSYS2 installer.
    exit /b 1
)

echo Installing MSYS2 to C:\msys64 in silent mode, it takes some time...
start /wait "" "%TEMP%\msys2.exe" in --confirm-command --accept-messages --root C:/msys64
set "INSTALL_ERR=%ERRORLEVEL%"
del "%TEMP%\msys2.exe" 2>nul
if %INSTALL_ERR% neq 0 (
    echo Error: MSYS2 installation failed with exit code %INSTALL_ERR%.
    exit /b %INSTALL_ERR%
)

echo Initializing MSYS2 packages...
C:\msys64\msys2_shell.cmd -defterm -msys2 -here -c "pacman -Syuu --noconfirm"
if errorlevel 1 (
    echo Error: Failed to initialize MSYS2 packages.
    exit /b 1
)