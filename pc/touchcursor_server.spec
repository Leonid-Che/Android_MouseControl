# -*- mode: python ; coding: utf-8 -*-
#
# Спекуляция PyInstaller для сборки TouchCursorServer.exe.
# Используется скриптом build_exe.bat:
#     pyinstaller --noconfirm touchcursor_server.spec
#
# Режим one-dir выбран специально: он загружается заметно быстрее, чем
# one-file (one-file при каждом старте распаковывает ~30 МБ во временный
# каталог), и антивирусы реагируют на него спокойнее. Итог: папка
# dist/TouchCursorServer/ с TouchCursorServer.exe внутри — её можно
# целиком скопировать на любой Windows 10 ПК, Python не требуется.

block_cipher = None

a = Analysis(
    ['touchcursor_server.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pyautogui подгружает бэкенды динамически — фиксируем нужные явно
        'pyautogui',
        'mouseinfo',
        'pymsgbox',
        'pyscreeze',
        'pytweening',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        # Bluetooth (pybluez) — опционально: если не установлен, EXE работает
        # только по Wi-Fi (сервер сам сообщит об этом при запуске)
        'bluetooth',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # лишнее из matplotlib/numpy и прочего мусора, который иногда
        # притягивают транзитивные зависимости
        'matplotlib', 'numpy', 'scipy', 'tkinter.test',
        'pytest', 'setuptools', 'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # one-dir режим
    name='TouchCursorServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX часто даёт ложные срабатывания антивирусов
    console=True,            # консоль: видны логи сервера + Ctrl+C работает
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,               # можно указать свой .ico: icon='touchcursor.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='TouchCursorServer',
)
