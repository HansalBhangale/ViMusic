@echo off
:: Batch script to allow ViMusic Port 8000 through Windows Defender Firewall
echo ========================================================
echo   ViMusic - Allow Port 8000 Through Windows Firewall
echo ========================================================
echo.

:: Check for administrative privileges
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Administrator privileges confirmed.
    echo Adding firewall rule for TCP port 8000...
    netsh advfirewall firewall delete rule name="ViMusic Streaming Engine" >nul 2>&1
    netsh advfirewall firewall add rule name="ViMusic Streaming Engine" dir=in action=allow protocol=TCP localport=8000 profile=any
    if %errorLevel% == 0 (
        echo.
        echo [SUCCESS] Port 8000 is now ALLOWED through Windows Firewall!
        echo Your Android phone can now connect to:
        echo http://10.208.66.48:8000
    ) else (
        echo [ERROR] Failed to add firewall rule.
    )
) else (
    echo Requesting Administrator privileges to add firewall rule...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

echo.
echo Press any key to close this window...
pause >nul
