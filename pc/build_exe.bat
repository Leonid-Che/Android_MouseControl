@echo off
rem ============================================================
rem  Сборка TouchCursorServer.exe (PyInstaller, one-dir режим)
rem  Требуется: Windows 10 + Python 3.8+ (один раз для сборки).
rem  Результат:  dist\TouchCursorServer\TouchCursorServer.exe
rem  Готовую папку dist\TouchCursorServer можно копировать на любые
rem  ПК без Python и запускать двойным кликом (run_exe.bat).
rem ============================================================
chcp 65001 >nul
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите с python.org ^("Add Python to PATH"^).
    pause
    exit /b 1
)

echo [1/4] Проверка зависимостей...
python -c "import pyautogui" 2>nul
if errorlevel 1 (
    echo       Установка pyautogui...
    python -m pip install --upgrade pyautogui || goto :fail
)
rem Bluetooth-поддержка опциональна: pybluez требует Visual C++ Build Tools.
rem Если установка не удалась — EXE соберётся без Bluetooth (только Wi-Fi).
python -c "import bluetooth" 2>nul
if errorlevel 1 (
    echo       Установка pybluez ^(Bluetooth, опционально^)...
    python -m pip install pybluez 2>nul
    if errorlevel 1 echo       ! pybluez не установлен - EXE будет работать только по Wi-Fi.
)
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo       Установка PyInstaller...
    python -m pip install --upgrade pyinstaller || goto :fail
)

echo [2/4] Очистка предыдущей сборки...
if exist build rd /s /q build
if exist dist rd /s /q dist

echo [3/4] Сборка EXE ^(может занять 1-3 минуты^)...
python -m PyInstaller --noconfirm touchcursor_server.spec || goto :fail

echo [4/4] Копирование вспомогательных файлов в dist...
copy /y run_exe.bat dist\TouchCursorServer\ >nul
copy /y touchcursor.ini dist\TouchCursorServer\ >nul

echo.
echo ============================================================
echo  ГОТОВО! Результат: %~dp0dist\TouchCursorServer\
echo  Запуск:  двойной клик по TouchCursorServer.exe
echo  или:     run_exe.bat ^(он же добавит правила брандмауэра^)
echo  Скопируйте папку TouchCursorServer на целевой ПК целиком.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [ОШИБКА] Сборка не удалась. Текст ошибки выше.
pause
exit /b 1
