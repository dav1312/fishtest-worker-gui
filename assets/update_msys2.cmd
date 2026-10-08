@echo off
:: Update MSYS2 system packages
C:\msys64\msys2_shell.cmd -defterm -ucrt64 -no-start -here -c "pacman -Syuu --noconfirm"
