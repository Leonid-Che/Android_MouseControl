@echo off
rem ============================================================
rem  Сборка TouchCursorServer.exe (PyInstaller, one-dir режим)
rem  Требуется: Windows 10 + Python 3.8 - 3.12 (один раз для сборки).
rem  Bluetooth-поддержка (pybluez) требует Python 3.8 - 3.11.
rem  Результат:  dist\TouchCursorServer\TouchCursorServer.exe
rem  Готовую папку dist\TouchCursorServer можно копировать на любые
rem  ПК без Python и запускать двойным кликом (run_exe.bat).
rem ============================================================
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem Сообщения пишутся в build_log.txt (UTF-8 с BOM) и перепечатываются
rem командой type: русский текст корректен при любой кодовой странице
rem консоли (OEM 866/1251), даже если chcp 65001 не применился.
set "LOGFILE=%~dp0build_log.txt"
if exist "%LOGFILE%" del "%LOGFILE%"
>("%LOGFILE%") <nul set /p "=е"

cd /d "%~dp0"

call :msg [0/4] Проверка версии Python...

rem ---------- [0] Поиск рабочего Python ----------
set "PY="
set "PYVER="
set "PYTEST=%TEMP%\tc_pyver_probe.py"
set "PYOUT=%TEMP%\tc_pyver_out.txt"

rem Версия определяется запуском ФАЙЛА (не "-c"), чтобы символы %% и кавычки
rem не искажались интерпретатором cmd; stderr уводится в nul. В %TEMP% всегда
rem попадает sys.path[0]=каталог скрипта, поэтому скрипт лежит в %TEMP%.
echo import sys > "%PYTEST%"
echo v=sys.version_info >> "%PYTEST%"
echo print("%%d.%%d"%%(v.major,v.minor)) >> "%PYTEST%"

for %%C in ("python" "py -3" "py" "python3") do call :try_py %%C
del "%PYTEST%" "%PYOUT%" >nul 2>nul

if defined PY goto :py_found

call :msg [ОШИБКА] Не удалось получить версию Python ни одной из команд:
call :msg          python, py -3, py, python3.
call :msg
call :msg   1. Если Python установлен без галки "Add Python to PATH",
call :msg      запустите установщик заново: Modify -^> отметить
call :msg      "Add Python to environment variables" (или используйте
call :msg      лаунчер - команда "py" ставится вместе с Python всегда).
call :msg   2. Проверьте вручную в НОВОМ окне командной строки:
call :msg          python --version
call :msg          py --version
call :msg      Если там работает, а здесь нет - перезапустите этот скрипт
call :msg      из нового окна (старое окно не видит обновлённый PATH).
call :msg   3. Установите Python 3.11 с https://www.python.org/downloads/
call :msg      (Install for all users + галка Add python.exe to PATH).
pause
exit /b 1

:try_py
if defined PY exit /b 0
set "CAND=%*"
"%CAND%" "%PYTEST%" >"%PYOUT%" 2>nul
if errorlevel 1 exit /b 0
set "V="
for /f "usebackq delims=" %%V in ("%PYOUT%") do set "V=%%V"
echo !V! | findstr /r /x "[3456789][.][0-9][0-9]*" >nul || exit /b 0
set "PY=!CAND!"
set "PYVER=!V!"
exit /b 0

:py_found
call :msg       Обнаружен Python !PYVER. ^(команда: !PY!^)

rem Разбираем мажор/минор версии в числа
set "VMajor="
set "VMinor="
for /f "tokens=1,2 delims=." %%A in ("!PYVER!") do (
    set "VMajor=%%A"
    set "VMinor=%%B"
)

if not "!VMajor!"=="3" (
    call :msg [ОШИБКА] Найден Python !PYVER!, а требуется Python 3.x.
    call :msg          Установите Python 3.11 ^(или любой 3.8-3.12^) с python.org.
    pause
    exit /b 1
)
if !VMinor! LSS 8 (
    call :msg [ОШИБКА] Python !PYVER! слишком старый ^(нужен 3.8 или новее^).
    call :msg          Установите Python 3.11 с https://www.python.org/downloads/
    pause
    exit /b 1
)
if !VMinor! GTR 12 (
    call :msg [ОШИБКА] Python !PYVER! слишком новый - PyInstaller и pybluez пока
    call :msg          не поддерживают эту версию.
    call :msg          Установите Python 3.11: https://www.python.org/downloads/release/python-3119/
    pause
    exit /b 1
)
if !VMinor! GTR 11 (
    call :msg       ! ВНИМАНИЕ: на Python !PYVER! библиотека pybluez скорее всего
    call :msg         не установится ^(нет готовых бинарных пакетов^), поэтому EXE
    call :msg         будет собран БЕЗ Bluetooth - только Wi-Fi. Если нужен
    call :msg         Bluetooth, используйте Python 3.8-3.11. Продолжаем сборку...
)

rem ---------- [1] Зависимости ----------
call :msg [1/4] Проверка зависимостей...
"!PY!" -c "import pyautogui" 2>nul
if errorlevel 1 (
    call :msg       Установка pyautogui...
    "!PY!" -m pip install --upgrade pip >nul 2>nul
    "!PY!" -m pip install --upgrade pyautogui || goto :fail_pip
)

rem Bluetooth-поддержка опциональна: pybluez имеет бинарные пакеты только
rem для Python 3.8-3.11; для более новых версий потребовались бы Visual C++
rem Build Tools. Если установка не удалась - EXE соберётся без Bluetooth.
set "BT_OK=0"
"!PY!" -c "import bluetooth" 2>nul
if errorlevel 1 (
    call :msg       Установка pybluez ^(Bluetooth, опционально^)...
    "!PY!" -m pip install pybluez >"%~dp0bt_install.log" 2>&1
    if errorlevel 1 goto :bt_fail
    "!PY!" -c "import bluetooth" 2>nul
    if errorlevel 1 goto :bt_fail
    set "BT_OK=1"
) else (
    set "BT_OK=1"
)
goto :bt_done

:bt_fail
call :msg
call :msg ============================================================
call :msg  Bluetooth НЕ будет включён в EXE - сборка продолжится только
call :msg  с Wi-Fi. Возможные причины и решения:
call :msg
call :msg   1. Версия Python !PYVER! не поддерживается pybluez.
call :msg      Решение: установите Python 3.11
call :msg      https://www.python.org/downloads/release/python-3119/
call :msg      и запустите этот скрипт заново из-под него.
call :msg
call :msg   2. Нет готового бинарного пакета для вашей платформы
call :msg      ^(например, Windows on ARM^).
call :msg      Решение: установите Visual Studio Build Tools ^(галлка
call :msg      "Desktop development with C++"^) и повторите вручную:
call :msg      "!PY!" -m pip install cython wheel pybluez
call :msg
call :msg   3. Корпоративный прокси или антивирус блокируют pip.
call :msg      Полный текст ошибки установки - в файле bt_install.log
call :msg      ^(рядом с этим скриптом^).
call :msg
call :msg  Если Bluetooth не нужен - просто дождитесь окончания сборки.
call :msg ============================================================
call :msg

:bt_done
"!PY!" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    call :msg       Установка PyInstaller...
    "!PY!" -m pip install --upgrade pyinstaller || goto :fail_pip
)

rem ---------- [2] Очистка ----------
call :msg [2/4] Очистка предыдущей сборки...
if exist build rd /s /q build
if exist dist rd /s /q dist

rem ---------- [3] Сборка ----------
call :msg [3/4] Сборка EXE ^(может занять 1-3 минуты^)...
"!PY!" -m PyInstaller --noconfirm touchcursor_server.spec || goto :fail

rem ---------- [4] Копирование вспомогательных файлов ----------
call :msg [4/4] Копирование вспомогательных файлов в dist...
copy /y run_exe.bat dist\TouchCursorServer\ >nul
copy /y touchcursor.ini dist\TouchCursorServer\ >nul
if exist bt_pair_server.py copy /y bt_pair_server.py dist\TouchCursorServer\ >nul
if exist run_bt_pair.bat copy /y run_bt_pair.bat dist\TouchCursorServer\ >nul

call :msg
call :msg ============================================================
call :msg  ГОТОВО! Результат: %~dp0dist\TouchCursorServer\
if "!BT_OK!"=="1" (
    call :msg  Поддерживаемые транспорты: Wi-Fi + Bluetooth
) else (
    call :msg  Поддерживаемые транспорты: только Wi-Fi ^(Bluetooth недоступен -
    call :msg  см. подсказки выше; пересоберите под Python 3.8-3.11, если нужен BT^)
)
call :msg  Запуск:  двойной клик по TouchCursorServer.exe
call :msg  или:     run_exe.bat ^(он же добавит правила брандмауэра^)
call :msg  Скопируйте папку TouchCursorServer на целевой ПК целиком.
call :msg ============================================================
pause
exit /b 0

:fail_pip
call :msg
call :msg [ОШИБКА] Не удалось установить зависимости через pip.
call :msg          Проверьте интернет-соединение и права ^(попробуйте запустить
call :msg          скрипт от администратора^). Текст ошибки выше.
pause
exit /b 1

:fail
call :msg
call :msg [ОШИБКА] Сборка не удалась. Текст ошибки выше.
pause
exit /b 1

rem ---- Служебная подпрограмма вывода сообщения ----
rem Пишет строку в UTF-8 журнал и перепечатывает его целиком командой type.
:msg
>>"%LOGFILE%" echo(%*
type "%LOGFILE%"
exit /b 0
