@echo off
title Bobot
cd /d "%~dp0"

set PY=venv\Scripts\python.exe

if not exist "%PY%" (
    echo Sanal ortam olusturuluyor...
    py -3.12 -m venv venv
    if errorlevel 1 py -m venv venv
    "%PY%" -m pip install -r requirements.txt
)

echo.
echo  Bobot
echo  =====
echo  1) Dongu (5 dk) — onerilen
echo  2) Tek analiz / islem
echo  3) Kontrol paneli
echo.

set /p choice="Seciminiz (1-3): "

if "%choice%"=="1" "%PY%" main.py --loop 300
if "%choice%"=="2" "%PY%" main.py
if "%choice%"=="3" "%PY%" main.py --dashboard

pause
