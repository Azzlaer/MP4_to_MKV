@echo off
:: ================================
:: Ejecutar video_converter_pro.py
:: como Administrador
:: ================================

:: Verificar si ya es admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Directorio del BAT
cd /d "%~dp0"

echo Ejecutando Video Converter PRO como administrador...
echo.

python video_converter_pro.py

pause
