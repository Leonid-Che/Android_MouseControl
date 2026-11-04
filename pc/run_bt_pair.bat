@echo off
rem ============================================================
rem  Одноразовая подготовка Bluetooth для TouchCursor
rem  Публикует SPP-сервис, чтобы телефон мог подключиться к ПК.
rem  Запускать ОДИН РАЗ от имени администратора.
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

net session >nul 2>nul
if errorlevel 1 (
    echo Запускаю от имени администратора...
    powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python с python.org ^("Add to PATH"^),
    echo либо используйте готовый EXE-сборку.
    pause
    exit /b 1
)

python -c "import bluetooth" 2>nul
if errorlevel 1 (
    echo Установка pybluez...
    python -m pip install --upgrade setuptools wheel
    python -m pip install pybluez || (echo [ОШИБКА] pybluez не установилась & pause & exit /b 1)
)

python bt_pair_server.py
pause
