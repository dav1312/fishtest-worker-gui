@echo off
:: Update MSYS2 system packages
:: The first pass may only update the core packages and exit with an error when
:: pacman has to restart, so its result is not checked. The second pass upgrades the rest.
call C:\msys64\msys2_shell.cmd -defterm -ucrt64 -no-start -here -c "pacman -Syuu --noconfirm"
call C:\msys64\msys2_shell.cmd -defterm -ucrt64 -no-start -here -c "pacman -Syuu --noconfirm"
