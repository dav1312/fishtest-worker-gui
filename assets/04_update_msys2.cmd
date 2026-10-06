@echo off
:: update msys2
C:\msys64\msys2_shell.cmd -defterm -msys2 -no-start -here -c "pacman -Syuu --noconfirm"
