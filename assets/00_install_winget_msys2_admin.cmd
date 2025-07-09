@echo off
:: install winget if missing
:: https://learn.microsoft.com/en-us/windows/package-manager/winget/
where winget >nul 2>nul || (
    echo Installing winget in silent mode, it takes some time...
    powershell -Command "$progressPreference = 'silentlyContinue'; Write-Information 'Downloading WinGet and its dependencies...'; Invoke-WebRequest -Uri https://aka.ms/getwinget -OutFile Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle; Invoke-WebRequest -Uri https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx -OutFile Microsoft.VCLibs.x64.14.00.Desktop.appx; Invoke-WebRequest -Uri https://github.com/microsoft/microsoft-ui-xaml/releases/download/v2.8.6/Microsoft.UI.Xaml.2.8.x64.appx -OutFile Microsoft.UI.Xaml.2.8.x64.appx; Add-AppxPackage Microsoft.VCLibs.x64.14.00.Desktop.appx; Add-AppxPackage Microsoft.UI.Xaml.2.8.x64.appx; Add-AppxPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle; Remove-Item Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle; Remove-Item Microsoft.VCLibs.x64.14.00.Desktop.appx; Remove-Item Microsoft.UI.Xaml.2.8.x64.appx"
)

:: check if msys2 is already installed
if exist "C:\msys64\msys2_shell.cmd" (
    echo msys2 is already installed. Skipping installation.
) else (
    :: install msys2
    winget install --id=MSYS2.MSYS2 --silent --accept-package-agreements --accept-source-agreements

    :: update msys2
    C:\msys64\msys2_shell.cmd -defterm -msys2 -here -c "pacman -Syuu --noconfirm"
)
