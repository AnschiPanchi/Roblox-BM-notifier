@echo off
title Eldorado Order Notifier Bot
color 0A
echo ==================================================
echo       Starting Eldorado Order Notifier Bot...     
echo ==================================================
echo.
py eldorado_notifier.py
if errorlevel 1 (
    echo.
    echo [!] An error occurred. Press any key to exit...
    pause >nul
)
