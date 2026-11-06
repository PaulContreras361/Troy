@echo off
cd /d "%~dp0"
start "" pythonw troy_hotkey.py
echo Troy Hotkey is starting (bottom of the screen). Hold Ctrl+Alt+Space and talk.
echo Quit it any time with Ctrl+Alt+Shift+Q.
timeout /t 5 >nul
