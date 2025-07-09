@echo off
:: update msys2
C:\msys64\msys2_shell.cmd -defterm -msys2 -here -c "pacman -Syuu --noconfirm"
