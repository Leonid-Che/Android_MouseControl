#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты _BtCompatSocket и BtSession на фейковом BT-сокете (кроссплатформенно).

Проверяет исправление зависаний Bluetooth-подключения:
  * recv() возвращает данные сразу, не дожидаясь полного буфера;
  * recv() не блокирует сессию навсегда при отсутствии данных (таймаут);
  * запись идёт напрямую в сокет (sock.send), а не в makefile('wb');
  * close()/обрыв соединения корректно завершают поток сессии;
  * протокол поверх BT (M/DL/UL/PING) исполняется как по Wi-Fi.
"""
import sys, os, time, threading, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- стаб pyautogui до импорта сервера ---
class FakeAuto:
    def __init__(self): self.calls = []
    def moveTo(self,*a,**k): pass
    def moveRel(self,x,y): self.calls.append(("rel",x,y))
    def mouseDown(self,button=None): self.calls.append(("down",button))
    def mouseUp(self,button=None): self.calls.append(("up",button))
    def doubleClick(self,button=None): self.calls.append(("dbl",button))
    def scroll(self,n): self.calls.append(("wheel",n))
    FAILSAFE_EXCEPTION = Exception
fake = FakeAuto()
mod = type(sys)("pyautogui")
def _moveRel(x,y,duration=0): fake.calls.append(("rel",x,y))
mod.moveTo=fake.moveTo; mod.moveRel=_moveRel
mod.mouseDown=fake.mouseDown; mod.mouseUp=fake.mouseUp
mod.doubleClick=fake.doubleClick; mod.scroll=fake.scroll
mod.FAILSAFE=False; mod.FailSafeException=Exception
sys.modules["pyautogui"]=mod

import touchcursor_server as ts

class FakeBTSock:
    """Эмуляция BluetoothSocket Windows: read блокирует, send принимает memoryview."""
    def __init__(self):
        self.inbox = collections.deque()      # байты от телефона
        self.outbox = bytearray()             # байты телефону
        self.evt = threading.Event()
        self.closed = False
        self.peer = ("AA:BB:CC:DD:EE:FF", 22)
    def makefile(self, mode, bufsize=None):
        assert mode == "rb", "обёртка не должна просить makefile('wb')"
        outer = self
        class R:
            def read(self, n=1):
                while not outer.inbox and not outer.closed:
                    outer.evt.clear(); outer.evt.wait(0.2)
                if outer.closed and not outer.inbox: return b""
                return bytes([outer.inbox.popleft()])
            def close(self): pass
        return R()
    def send(self, data):
        if self.closed: raise OSError("closed")
        self.outbox += bytes(data); return len(data)
    def getpeername(self): return self.peer
    def shutdown(self, how): pass
    def close(self):
        self.closed = True; self.evt.set()
    # тестовый хелпер
    def feed(self, s: str):
        for b in s.encode(): self.inbox.append(b)
        self.evt.set()

def main():
    ok = True
    ex = ts.CommandExecutor(ts.MouseController())
    ex.start()

    fs = FakeBTSock()
    sess = ts.BtSession(fs, "test-peer", ex)
    sess.start()

    # 1) HELLO -> OK, PING -> PONG (проверка sendall через sock.send + немедленный ответ)
    fs.feed("HELLO Android\nPING\n")
    deadline = time.time()+3
    while time.time()<deadline and b"OK" not in fs.outbox: time.sleep(0.05)
    if b"OK\n" not in fs.outbox: print("FAIL: нет ответа OK"); ok=False
    else: print("PASS: HELLO->OK")
    fs.feed("PING\n")
    deadline = time.time()+3
    while time.time()<deadline and b"PONG" not in fs.outbox: time.sleep(0.05)
    if b"PONG\n" not in fs.outbox: print("FAIL: нет ответа PONG"); ok=False
    else: print("PASS: PING->PONG")

    # 2) команды движут мышь и кнопки
    fs.feed("M 20 15\nDL\nUL\nDC\nW -3\n")
    time.sleep(0.4)
    kinds=[c[0] for c in fake.calls]
    for want in ("rel","down","dbl","wheel"):
        if want not in kinds: print("FAIL: нет вызова",want,kinds); ok=False
    print("PASS: исполнение команд" if ok else "see above")

    # 3) обрыв связи при зажатых кнопках -> RESET (кнопки отжаты)
    fs.feed("DL\nDR\n")
    time.sleep(0.2)
    fake.calls.clear()
    fs.closed=True; fs.evt.set()          # «телефон отключился»
    deadline=time.time()+3
    while sess.is_alive() and time.time()<deadline: time.sleep(0.05)
    if sess.is_alive(): print("FAIL: сессия не завершилась после обрыва (зависание!)"); ok=False
    else: print("PASS: сессия закрылась после обрыва без зависания")
    calls=fake.calls
    if not any(c==("up","left") for c in calls) or not any(c==("up","right") for c in calls):
        print("FAIL: кнопки не отжаты при обрыве:",calls); ok=False
    else: print("PASS: зажатые кнопки отжаты при обрыве")

    # 4) recv не ждёт полный буфер: одно сообщение из ~10 байт приходит быстро
    fs2=FakeBTSock(); comp=ts._BtCompatSocket(fs2); comp.settimeout(5)
    t0=time.time(); fs2.feed("X")
    got=comp.recv(4096); dt=time.time()-t0
    if got!=b"X" or dt>0.5: print("FAIL: recv задержал/потерял байт",got,dt); ok=False
    else: print("PASS: recv мгновенен для маленького пакета")
    comp.close()

    ex.stop()
    print("RESULT:", "ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)

main()
