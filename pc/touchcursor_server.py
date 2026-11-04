#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TouchCursor PC Server
=====================
Серверная часть программы управления курсором Windows 10 со смартфона Android.

Протокол (совпадает с android/app/src/main/java/.../Protocol.java):
  Транспорт — TCP, порт 8721, сообщения разделены '\\n':
    M <dx> <dy>   — смещение курсора (абсолютные пиксели)
    DL / UL       — левая кнопка мыши нажата / отпущена
    DR / UR       — правая кнопка мыши нажата / отпущена
    DC            — двойной клик левой
    DD            — двойной клик правой
    W <notches>   — колесо мыши (+ вверх / - вниз... см. ниже)
    PING          — проверка связи (сервер отвечает PONG)
    HELLO ...     — представление клиента (сервер отвечает OK)

  UDP-обнаружение, порт 8722:
    клиент шлёт "TOUCHCURSOR_DISCOVER" → сервер отвечает
    "TOUCHCURSOR_SERVER|<имя компьютера>".

Требования: Python 3.8+ и pyautogui — ЛИБО готовый EXE-файл, собранный
через PyInstaller (см. build_exe.bat / run_exe.bat; Python на ПК не нужен).

Запуск:      python touchcursor_server.py [--port 8721] [--udp-port 8722]
             [--scale 1.5] [--failsafe]
   или       TouchCursorServer.exe [--port 8721] [--scale 1.5] ...

Конфигурация через файл touchcursor.ini (рядом с EXE/скриптом):
    [server]
    port = 8721
    udp_port = 8722
    scale = 1.5
    failsafe = false
Аргументы командной строки имеют приоритет над ini-файлом.

Безопасность: сервер принимает соединения только из локальной подсети
(127.0.0.0/8, 10/8, 172.16/12, 192.168/16, 169.254/16).
"""

import argparse
import configparser
import ipaddress
import os
import socket
import sys
import threading
import time

# --- поддержка «замороженных» сборок (PyInstaller / Nuitka) -----------------
IS_FROZEN = getattr(sys, "frozen", False)  # собрано в EXE


def app_dir() -> str:
    """Каталог, где лежит скрипт или EXE (для поиска touchcursor.ini)."""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


try:
    import pyautogui
except ImportError:
    if IS_FROZEN:
        # В EXE-сборке pyautogui упакован внутрь — такая ошибка невозможна,
        # но на всякий случай подсказываем понятное сообщение.
        sys.stderr.write(
            "Внутренняя ошибка сборки EXE: не найден pyautogui.\r\n"
            "Пересоберите сервер через build_exe.bat\r\n")
    else:
        sys.stderr.write(
            "Не найден модуль pyautogui.\n"
            "Либо установите его:  pip install pyautogui\n"
            "либо используйте готовый TouchCursorServer.exe (см. build_exe.bat)\n")
    sys.exit(1)

DEFAULT_PORT = 8721
DEFAULT_UDP_PORT = 8722
DISCOVERY_MAGIC = b"TOUCHCURSOR_DISCOVER"
DISCOVERY_REPLY_PREFIX = "TOUCHCURSOR_SERVER"

MOVE_EPS = 0.5           # накопление дробных пикселей до целых
MAX_WHEEL_CLICKS = 25    # защита от «безумной прокрутки»


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def is_local(addr: str) -> bool:
    """Разрешаем подключение только из локальных сетей."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class MouseController:
    """Однопоточный исполнитель команд мыши (все вызовы сериализуются замком)."""

    def __init__(self, scale: float = 1.0):
        self.scale = scale
        self.lock = threading.Lock()
        self.frac_x = 0.0
        self.frac_y = 0.0
        # текущее состояние кнопок (для гарантированного отпускания при обрыве)
        self.pressed_buttons: "set[str]" = set()

    # ---------- движение ----------
    def move(self, dx: float, dy: float) -> None:
        if self.scale != 1.0:
            dx *= self.scale
            dy *= self.scale
        with self.lock:
            self.frac_x += dx
            self.frac_y += dy
            ix = int(round(self.frac_x))
            iy = int(round(self.frac_y))
            if ix == 0 and iy == 0:
                return
            self.frac_x -= ix
            self.frac_y -= iy
            try:
                pyautogui.moveRel(ix, iy, duration=0)
            except pyautogui.FailSafeException:
                raise
            except Exception as e:  # курсор мог «упереться» и т.п.
                log("move error: %s" % e)

    # ---------- кнопки ----------
    def _press(self, button: str) -> None:
        with self.lock:
            self.pressed_buttons.add(button)
            try:
                pyautogui.mouseDown(button=button)
            except Exception as e:
                log("mouseDown(%s) error: %s" % (button, e))

    def _release(self, button: str) -> None:
        with self.lock:
            self.pressed_buttons.discard(button)
            try:
                pyautogui.mouseUp(button=button)
            except Exception as e:
                log("mouseUp(%s) error: %s" % (button, e))

    def left_down(self) -> None:
        self._press("left")

    def left_up(self) -> None:
        self._release("left")

    def right_down(self) -> None:
        self._press("right")

    def right_up(self) -> None:
        self._release("right")

    def double_left(self) -> None:
        with self.lock:
            try:
                pyautogui.doubleClick(button="left")
            except Exception as e:
                log("doubleClick error: %s" % e)

    def double_right(self) -> None:
        with self.lock:
            try:
                pyautogui.doubleClick(button="right")
            except Exception as e:
                log("right doubleClick error: %s" % e)

    # ---------- колесо ----------
    def wheel(self, notches: int) -> None:
        notches = max(-MAX_WHEEL_CLICKS, min(MAX_WHEEL_CLICKS, notches))
        if notches == 0:
            return
        with self.lock:
            try:
                # в pyautogui положительное значение = колесо «на себя» (вниз по списку),
                # а на телефоне «свайп вверх» означает прокрутку вперёд — инвертируем.
                pyautogui.scroll(-notches)
            except Exception as e:
                log("scroll error: %s" % e)

    # ---------- аварийный сброс ----------
    def release_all(self) -> None:
        for button in list(self.pressed_buttons):
            self._release(button)


class CommandExecutor(threading.Thread):
    """
    Очередь команд: сетевой поток только кладёт строки в очередь,
    этот поток их исполняет. Если сеть быстрее мыши — команды движения
    накапливаются (дельты суммируются), а клики не теряются.
    """

    def __init__(self, mouse: MouseController):
        super().__init__(daemon=True, name="cmd-exec")
        self.mouse = mouse
        self.cv = threading.Condition()
        self.queue: "list[tuple]" = []
        self.alive = True

    def submit(self, cmd: tuple) -> None:
        with self.cv:
            # дельты движения сливаем с последней незакрытой MOVE-записью
            if cmd[0] == "M" and self.queue and self.queue[-1][0] == "M":
                last = self.queue[-1]
                self.queue[-1] = ("M", last[1] + cmd[1], last[2] + cmd[2])
            else:
                self.queue.append(cmd)
            self.cv.notify()

    def run(self) -> None:
        while self.alive:
            with self.cv:
                while not self.queue and self.alive:
                    self.cv.wait(0.5)
                if not self.alive:
                    break
                batch, self.queue = self.queue, []
            for cmd in batch:
                try:
                    self._exec(cmd)
                except pyautogui.FailSafeException:
                    log("FAIL-SAFE: курсор у угла экрана, команда проигнорирована.")
                    self.mouse.release_all()
                except Exception as e:
                    log("cmd %r error: %s" % (cmd, e))

    def stop(self) -> None:
        self.alive = False
        with self.cv:
            self.cv.notify_all()

    def _exec(self, cmd: tuple) -> None:
        kind = cmd[0]
        if kind == "RESET":
            self.mouse.release_all()
        elif kind == "M":
            self.mouse.move(cmd[1], cmd[2])
        elif kind == "DL":
            self.mouse.left_down()
        elif kind == "UL":
            self.mouse.left_up()
        elif kind == "DR":
            self.mouse.right_down()
        elif kind == "UR":
            self.mouse.right_up()
        elif kind == "DC":
            self.mouse.double_left()
        elif kind == "DD":
            self.mouse.double_right()
        elif kind == "W":
            self.mouse.wheel(cmd[1])


def parse_line(line: str):
    """Разбирает текстовую команду протокола; возвращает ('RAW', text) для PING/HELLO."""
    parts = line.split()
    if not parts:
        return None
    c = parts[0].upper()
    try:
        if c == "M" and len(parts) >= 3:
            return ("M", float(parts[1]), float(parts[2]))
        if c in ("DL", "UL", "DR", "UR", "DC", "DD"):
            return (c,)
        if c == "W" and len(parts) >= 2:
            return ("W", int(float(parts[1])))
    except (ValueError, IndexError):
        return None
    if c in ("PING", "HELLO"):
        return ("RAW", c)
    return None


class ClientSession(threading.Thread):
    def __init__(self, sock: socket.socket, addr, executor: CommandExecutor):
        super().__init__(daemon=True, name="client-%s" % addr[0])
        self.sock = sock
        self.addr = addr
        self.executor = executor
        self.alive = True

    def peer_name(self) -> str:
        return "%s:%d" % self.addr

    def run(self) -> None:
        log("клиент подключён: %s" % self.peer_name())
        buf = b""
        try:
            self.sock.settimeout(30.0)
            while self.alive:
                try:
                    data = self.sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._handle(line.decode("utf-8", "replace").strip())
        except OSError:
            pass
        finally:
            self.close()
            log("клиент отключился: %s" % self.peer_name().split(":")[0])

    def _handle(self, line: str) -> None:
        if not line:
            return
        cmd = parse_line(line)
        if cmd is None:
            return
        if cmd[0] == "RAW":
            # служебные сообщения — отвечаем сразу, минуя очередь
            try:
                reply = "PONG\n" if cmd[1] == "PING" else "OK\n"
                self.sock.sendall(reply.encode("ascii"))
            except OSError:
                pass
            return
        self.executor.submit(cmd)

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass
        # если оборвалась связь — обязательно отжать все кнопки
        self.executor.submit(("RESET",))


class BtSession(ClientSession):
    """Сессия поверх Bluetooth RFCOMM-сокета (протокол сообщений — тот же)."""

    def __init__(self, sock, peer_desc: str, executor: CommandExecutor):
        super().__init__(_BtCompatSocket(sock), ("bluetooth", 0), executor)
        self.addr = ("bluetooth", 0)
        self.bt_raw = sock
        self.peer_desc = peer_desc

    def peer_name(self) -> str:
        return "Bluetooth (%s)" % self.peer_desc

    def close(self) -> None:
        # прерываем блокирующий read в потоке сессии (см. _BtCompatSocket.recv)
        try:
            self.bt_raw.shutdown(getattr(socket, "SHUT_RDWR", 2))
        except OSError:
            pass
        ClientSession.close(self)


class _BtCompatSocket:
    """Обёртка BluetoothSocket под «сокето-подобный» интерфейс recv/sendall/close.

    Bluetooth-сокет Windows отдаёт поток; читаем побайтово в чанки по 4096.
    """

    def __init__(self, sock):
        self.sock = sock
        self._r = None
        self._w = None

    def _streams(self):
        if self._r is None:
            self._r = self.sock.makefile("rb")
            self._w = self.sock.makefile("wb")
        return self._r, self._w

    def settimeout(self, t):
        # pybluez на Windows поддерживает settimeout — пробуем передать,
        # если нет — блокирующий read (PING клиента не даёт «висеть» вечно).
        try:
            self.sock.settimeout(t)
        except Exception:
            pass

    def recv(self, n):
        r, _ = self._streams()
        buf = bytearray()
        while len(buf) < n:
            b = r.read(1)
            if not b:
                break
            buf += b
            # возвращаем то, что уже есть, не дожидаясь полного буфера —
            # иначе small-talk (PONG/OK) и команды будут задерживаться
            if len(buf) >= 64:
                break
        return bytes(buf)

    def sendall(self, data):
        _, w = self._streams()
        w.write(data)
        w.flush()

    def close(self):
        try:
            if self._r: self._r.close()
            if self._w: self._w.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


BT_DEFAULT_CHANNEL = 22  # RFCOMM-канал по умолчанию (SPP-подобный сервис)


def load_bluetooth():
    """Импортирует pybluez (Bluetooth RFCOMM). Возвращает модуль или None.

    Если библиотека не установлена — Bluetooth-режим просто отключается,
    Wi-Fi работает как раньше. Установка:  pip install pybluez
    (для EXE-сборки pybluez упакован через build_exe.bat / .spec).
    """
    try:
        import bluetooth  # pybluez
        return bluetooth
    except Exception:
        return None


class BluetoothListener(threading.Thread):
    """RFCOMM-сервер Windows: ждёт входящие соединения от смартфона Android.

    Протокол сообщений поверх канала — идентичен TCP (см. ClientSession),
    поэтому клиент переключается между Wi-Fi и Bluetooth без изменений.
    """

    def __init__(self, channel: int, executor: CommandExecutor,
                 sessions: "list[ClientSession]", sessions_lock):
        super().__init__(daemon=True, name="bt-listener")
        self.channel = channel
        self.executor = executor
        self.sessions = sessions
        self.lock = sessions_lock
        self.alive = True
        self.sock = None
        self.bt = load_bluetooth()

    @staticmethod
    def _peer_desc(sock) -> str:
        try:
            addr = sock.getpeername()
            if isinstance(addr, tuple):
                return "%s ch=%d" % (addr[0], addr[1] if len(addr) > 1 else 0)
            return str(addr)
        except OSError:
            return "неизвестное устройство"

    def run(self) -> None:
        bt = self.bt
        if bt is None:
            log("Bluetooth недоступен: библиотека pybluez не установлена "
                "(pip install pybluez). Работает только Wi-Fi.")
            return
        if self.channel <= 0:
            log("Bluetooth-слушатель отключён (bt_channel = 0)")
            return
        try:
            s = bt.BluetoothSocket(bt.RFCOMM)
            s.bind(("", self.channel))
            s.listen(1)
            self.sock = s
        except Exception as e:
            log("Не удалось открыть Bluetooth-канал %d: %s" % (self.channel, e))
            log("Проверьте: адаптер включён, ПК виден телефону, "
                "или укажите свободный канал --bt-channel N")
            return
        log("Bluetooth-слушатель запущен (RFCOMM-канал %d)" % self.channel)
        while self.alive:
            try:
                conn, _ = s.accept()
            except OSError:
                break
            peer = self._peer_desc(conn)
            desc = "Bluetooth-клиент подключён: %s" % peer
            with self.lock:
                for old in list(self.sessions):
                    old.close()
                    self.sessions.remove(old)
                sess = BtSession(conn, peer, self.executor)
                self.sessions.append(sess)
            sess.start()
        log("Bluetooth-слушатель остановлен")

    def stop(self) -> None:
        self.alive = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


class DiscoveryServer(threading.Thread):
    """UDP-ответчик для автоматического поиска сервера в локальной сети."""

    def __init__(self, udp_port: int):
        super().__init__(daemon=True, name="discovery")
        self.udp_port = udp_port
        self.sock = None
        self.alive = True
        self.hostname = os.environ.get("COMPUTERNAME") or socket.gethostname()

    def run(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", self.udp_port))
            self.sock = s
        except OSError as e:
            log("UDP-порт %d занят (%s) — автопоиск недоступен." % (self.udp_port, e))
            return
        log("UDP-обнаружение запущено на порту %d" % self.udp_port)
        while self.alive:
            try:
                data, addr = s.recvfrom(1024)
            except OSError:
                break
            if DISCOVERY_MAGIC in data and is_local(addr[0]):
                reply = ("%s|%s" % (DISCOVERY_REPLY_PREFIX, self.hostname)).encode("utf-8")
                try:
                    s.sendto(reply, addr)
                except OSError:
                    pass
        log("UDP-обнаружение остановлено")

    def stop(self) -> None:
        self.alive = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


class TouchCursorServer:
    def __init__(self, port: int, udp_port: int, scale: float, failsafe: bool,
                 bt_channel: int = BT_DEFAULT_CHANNEL):
        self.port = port
        self.scale = scale
        self.bt_channel = bt_channel
        pyautogui.FAILSAFE = failsafe
        pyautogui.PAUSE = 0
        try:
            pyautogui.FAILSAFE_THRESHOLD = (10, 10)
        except Exception:
            pass
        self.mouse = MouseController(scale)
        self.executor = CommandExecutor(self.mouse)
        self.discovery = DiscoveryServer(udp_port)
        self.sessions: "list[ClientSession]" = []
        self.sessions_lock = threading.Lock()
        self.bt_listener = BluetoothListener(
            bt_channel, self.executor, self.sessions, self.sessions_lock)
        self.tcp = None
        self.alive = True

    def run(self) -> None:
        self.executor.start()
        self.discovery.start()
        self.bt_listener.start()

        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.tcp.bind(("0.0.0.0", self.port))
        except OSError as e:
            log("Не удалось занять TCP-порт %d: %s" % (self.port, e))
            sys.exit(1)
        self.tcp.listen(4)
        w, h = pyautogui.size()
        log("Сервер запущен. TCP :%d | UDP :%d | Bluetooth канал %d | экран %dx%d | масштаб %.2f"
            % (self.port, self.discovery.udp_port, self.bt_channel, w, h, self.scale))
        log("Подключение со смартфона: Wi-Fi (та же сеть) или Bluetooth (сопряжение).")
        log("Ctrl+C — остановка сервера.")

        try:
            while self.alive:
                conn, addr = self.tcp.accept()
                if not is_local(addr[0]):
                    log("Отклонено внешнее подключение: %s" % addr[0])
                    conn.close()
                    continue
                # новый клиент вытесняет предыдущих (один телефон = одно управление)
                with self.sessions_lock:
                    for s in list(self.sessions):
                        s.close()
                        self.sessions.remove(s)
                    sess = ClientSession(conn, addr, self.executor)
                    self.sessions.append(sess)
                sess.start()
        except OSError:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        log("Остановка сервера…")
        self.alive = False
        with self.sessions_lock:
            for s in self.sessions:
                s.close()
        self.discovery.stop()
        self.bt_listener.stop()
        self.executor.stop()
        self.mouse.release_all()
        if self.tcp:
            try:
                self.tcp.close()
            except OSError:
                pass


def load_ini_config() -> dict:
    """Читает touchcursor.ini (рядом со скриптом/EXE). Неброские ошибки игнорируются."""
    path = os.path.join(app_dir(), "touchcursor.ini")
    cfg = {}
    if not os.path.isfile(path):
        return cfg
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8-sig")
    except Exception as e:
        log("Не удалось прочитать %s: %s — использую настройки по умолчанию." % (path, e))
        return cfg
    sec = "server" if parser.has_section("server") else None
    if sec is None:
        return cfg

    def get_num(key, cast):
        if parser.has_option(sec, key):
            try:
                cfg[key] = cast(parser.get(sec, key))
            except ValueError:
                log("Неверное значение '%s' в touchcursor.ini — пропущено." % key)

    def get_bool(key):
        if parser.has_option(sec, key):
            cfg[key] = parser.getboolean(sec, key)

    get_num("port", int)
    get_num("udp_port", int)
    get_num("scale", float)
    get_bool("failsafe")
    get_num("bt_channel", int)
    return cfg


def set_console_title(title: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


def main() -> None:
    ini = load_ini_config()

    ap = argparse.ArgumentParser(description="TouchCursor server for Windows 10")
    ap.add_argument("--port", type=int, default=None, help="TCP-порт (по умолч. 8721)")
    ap.add_argument("--udp-port", type=int, default=None,
                    help="UDP-порт автопоиска (по умолч. 8722)")
    ap.add_argument("--scale", type=float, default=None,
                    help="множитель чувствительности (например 1.5)")
    ap.add_argument("--failsafe", action="store_true", default=None,
                    help="включить FAIL-SAFE pyautogui: курсор в угол экрана → стоп")
    ap.add_argument("--bt-channel", type=int, default=None,
                    help="RFCOMM-канал Bluetooth (по умолч. 22; 0 — выключить Bluetooth)")
    args = ap.parse_args()

    # приоритет: аргументы командной строки > touchcursor.ini > умолчания
    port = args.port if args.port is not None else ini.get("port", DEFAULT_PORT)
    udp_port = (args.udp_port if args.udp_port is not None
                else ini.get("udp_port", DEFAULT_UDP_PORT))
    scale = args.scale if args.scale is not None else ini.get("scale", 1.0)
    failsafe = (args.failsafe if args.failsafe is not None
                else ini.get("failsafe", False))
    bt_channel = (args.bt_channel if args.bt_channel is not None
                  else ini.get("bt_channel", BT_DEFAULT_CHANNEL))

    if sys.platform.startswith("win"):
        # стабильнее на высоких DPI
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        set_console_title("TouchCursor Server — порт TCP %d" % port)

    srv = TouchCursorServer(port, udp_port, scale, failsafe, bt_channel)
    try:
        srv.run()
    except KeyboardInterrupt:
        srv.shutdown()
    finally:
        if IS_FROZEN:
            # Двойной клик по EXE: окно консоли не должно исчезать мгновенно,
            # чтобы пользователь успел увидеть сообщения сервера/ошибок.
            try:
                input("\nНажмите Enter, чтобы закрыть окно…")
            except EOFError:
                pass


if __name__ == "__main__":
    main()
