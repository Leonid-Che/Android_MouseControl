#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TouchCursor Bluetooth Pairing Helper
====================================
Windows не показывает входящие RFCOMM-соединения от уже сопряжённых
устройств, если сервис SPP не опубликован в SDP. Этот скрипт публикует
SPP-сервис и включает режим «разрешить соединения» — после его запуска
телефон сможет подключиться к серверу TouchCursor по Bluetooth.

Запуск (ОДИН РАЗ, от администратора, на том же ПК где touchcursor_server):
    python bt_pair_server.py            # или двойным кликом через run_bt_pair.bat

Требует: pybluez (устанавливается build_exe.bat / pip install pybluez)
"""
import sys


def main() -> int:
    try:
        import bluetooth  # pybluez
        from bluetooth import BluetoothService, advertise_service
    except Exception:
        print("[ОШИБКА] Не найдена библиотека pybluez.")
        print("Установите её командой:")
        print("    python -m pip install pybluez")
        return 1

    chan = 22
    if len(sys.argv) > 1:
        try:
            chan = int(sys.argv[1])
        except ValueError:
            pass

    print("Публикую SPP-сервис TouchCursor на RFCOMM-канале %d ..." % chan)
    print("Теперь телефон может подключаться (запустите touchcursor_server).")
    print("Окно можно свернуть; для выхода — Ctrl+C или закрытие окна.")
    try:
        advertise_service(
            None,                                   # none=True: без сокета
            "TouchCursor",
            service_classes=[BluetoothService.SERIAL_PORT],
            profiles=[{"Provider": 0x1101, "ServiceID": 0x1101}],
            provider="TouchCursor Server",
        )
    except Exception as e:
        print("\nНе удалось опубликовать сервис: %s" % e)
        print("Возможные причины:")
        print("  * запуск не от имени администратора;")
        print("  * Bluetooth-стек Windows не даёт сторонним приложениям")
        print("    публиковать SPP (некоторые адаптеры/дрова);")
        print("  * канал %d занят — попробуйте другой: python bt_pair_server.py 25" % chan)
        input("\nНажмите Enter для выхода...")
        return 2

    # keep-alive: сервис остаётся активным, пока работает процесс
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nСервис снят с публикации.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
