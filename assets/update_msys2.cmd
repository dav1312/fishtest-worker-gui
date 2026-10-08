@echo off
:: Update MSYS2 system packages
:: Run twice, see setup_msys2.cmd
call C:\msys64\msys2_shell.cmd -defterm -ucrt64 -no-start -here -c "pacman -Syuu --noconfirm"
call C:\msys64\msys2_shell.cmd -defterm -ucrt64 -no-start -here -c "pacman -Syuu --noconfirm"
