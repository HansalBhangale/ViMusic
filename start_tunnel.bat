@echo off
title ViMusic Cloud Tunnel
echo ========================================================
echo   ViMusic - Cloudflare Public HTTPS Tunnel
echo ========================================================
echo.
echo Starting local ViMusic server...
start /b python server\main.py
timeout /t 2 /nobreak >nul
echo.
echo Connecting Cloudflare Tunnel to port 8000...
echo Copy the https://....trycloudflare.com URL into your phone's Server Config!
echo.
cloudflared.exe tunnel --url http://127.0.0.1:8000
pause
