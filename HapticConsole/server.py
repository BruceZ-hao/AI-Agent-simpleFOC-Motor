# -*- coding: utf-8 -*-
"""
DengFOC-Mini + ESP32-S3 弹簧回中 · 本地上位机服务
====================================================
零第三方依赖：Windows 原生 API (ctypes) 直接读写串口，Python 标准库提供
HTTP + Server-Sent Events，浏览器打开 http://127.0.0.1:8765 即为界面。

对应固件：ESP32S3_SimpleFOC_AS5600（STAGE 3 / Haptic v2）
串口命令：T / L / D / M / H / K / B / Z ，行结束符为 NL(\n)

用法：
    python server.py                     # 启动并自动打开浏览器
    python server.py --port 8766         # 换端口
    python server.py --selftest          # 不开服务，自检串口与 D 命令
    python server.py --selftest --com COM6
"""

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import webbrowser
import winreg
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

# ---------------------------------------------------------------- Win32 串口
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PURGE_TXABORT = 0x0001
PURGE_RXABORT = 0x0002
PURGE_TXCLEAR = 0x0004
PURGE_RXCLEAR = 0x0008


class DCB(ctypes.Structure):
    """Win32 DCB。位域那一整个 DWORD 由 BuildCommDCBW 填充，这里用一个 DWORD 占位。"""
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("wReserved", wintypes.WORD),
        ("XonLim", wintypes.WORD),
        ("XoffLim", wintypes.WORD),
        ("ByteSize", ctypes.c_ubyte),
        ("Parity", ctypes.c_ubyte),
        ("StopBits", ctypes.c_ubyte),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                        wintypes.HANDLE]
CreateFileW.restype = wintypes.HANDLE

BuildCommDCBW = kernel32.BuildCommDCBW
BuildCommDCBW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DCB)]
BuildCommDCBW.restype = wintypes.BOOL

SetCommState = kernel32.SetCommState
SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
SetCommState.restype = wintypes.BOOL

SetCommTimeouts = kernel32.SetCommTimeouts
SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
SetCommTimeouts.restype = wintypes.BOOL

PurgeComm = kernel32.PurgeComm
PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
PurgeComm.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

ReadFile = kernel32.ReadFile
ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
ReadFile.restype = wintypes.BOOL

WriteFile = kernel32.WriteFile
WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                      ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
WriteFile.restype = wintypes.BOOL


class SerialError(Exception):
    pass


class Win32Serial:
    """最小可用的阻塞式串口，只依赖 kernel32。DTR/RTS 保持关闭，避免打开端口时复位 ESP32。"""

    def __init__(self, port, baud=115200):
        self.port = port
        self.baud = int(baud)
        self.handle = None

    def open(self):
        path = "\\\\.\\" + self.port
        h = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, None,
                        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if not h or h == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise SerialError("打不开 %s（错误码 %d）。通常被 Arduino IDE 串口监视器占用，"
                              "或端口已被拔掉。" % (self.port, err))

        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        spec = "baud=%d parity=N data=8 stop=1" % self.baud
        if not BuildCommDCBW(spec, ctypes.byref(dcb)):
            CloseHandle(h)
            raise SerialError("BuildCommDCBW 失败：%s" % spec)
        dcb.DCBlength = ctypes.sizeof(DCB)
        if not SetCommState(h, ctypes.byref(dcb)):
            CloseHandle(h)
            raise SerialError("SetCommState 失败（错误码 %d）" % ctypes.get_last_error())

        to = COMMTIMEOUTS()
        to.ReadIntervalTimeout = 0
        to.ReadTotalTimeoutMultiplier = 0
        to.ReadTotalTimeoutConstant = 60      # 无数据时 60ms 返回，便于线程及时退出
        to.WriteTotalTimeoutMultiplier = 0
        to.WriteTotalTimeoutConstant = 300
        if not SetCommTimeouts(h, ctypes.byref(to)):
            CloseHandle(h)
            raise SerialError("SetCommTimeouts 失败")

        PurgeComm(h, PURGE_RXCLEAR | PURGE_TXCLEAR | PURGE_RXABORT | PURGE_TXABORT)
        self.handle = h

    def write(self, data):
        if self.handle is None:
            raise SerialError("串口未打开")
        written = wintypes.DWORD(0)
        buf = ctypes.create_string_buffer(data)
        ok = WriteFile(self.handle, buf, len(data), ctypes.byref(written), None)
        if not ok or written.value != len(data):
            raise SerialError("串口写入失败（错误码 %d，实际写入 %d/%d 字节）"
                              % (ctypes.get_last_error(), written.value, len(data)))

    def read(self, size=1024):
        if self.handle is None:
            raise SerialError("串口未打开")
        buf = ctypes.create_string_buffer(size)
        nread = wintypes.DWORD(0)
        ok = ReadFile(self.handle, buf, size, ctypes.byref(nread), None)
        if not ok:
            raise SerialError("串口读取失败（错误码 %d）" % ctypes.get_last_error())
        return buf.raw[:nread.value]

    def close(self):
        if self.handle is not None:
            try:
                CloseHandle(self.handle)
            finally:
                self.handle = None


def list_ports():
    """从注册表读串口列表，并按 COM 编号排序。"""
    found = []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DEVICEMAP\SERIALCOMM")
        i = 0
        while True:
            try:
                _, value, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            if value:
                found.append(value)
            i += 1
        winreg.CloseKey(key)
    except OSError:
        pass

    def order(p):
        m = re.search(r"(\d+)", p)
        return (0, int(m.group(1))) if m else (1, p)

    return sorted(set(found), key=order)


# ---------------------------------------------------------------- DIAG 解析
RE_SUMMARY = re.compile(
    r"target=(\S+)\s+vlimit=(\S+)\s+drv_vlimit=(\S+)\s+enabled=(\d+)\s+status=(\d+)\s+mode=(\S+)")
RE_POS = re.compile(r"home=(\S+)\s+shaft=(\S+)\s+err=(\S+)\s+vel=(\S+)")
RE_GAIN = re.compile(r"spring Kp/Kd/db=(\S+)/(\S+)/(\S+)")
RE_OUT = re.compile(r"Uq\(out\)=(\S+)\s+velFilt=(\S+)")
RE_PHASE = re.compile(r"Ua/Ub/Uc=(\S+)/(\S+)/(\S+)")
RE_ANGLE = re.compile(r"angle=(\S+)")
RE_GPIO = re.compile(r"GPIO4 readback high%=(\S+)")


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_diag(lines):
    t = {}
    for raw in lines:
        s = raw.strip()
        m = RE_SUMMARY.search(s)
        if m:
            t["target"] = _f(m.group(1))
            t["vlimit"] = _f(m.group(2))
            t["drv_vlimit"] = _f(m.group(3))
            t["enabled"] = int(m.group(4))
            t["status"] = int(m.group(5))
            t["mode"] = m.group(6)
            continue
        m = RE_POS.search(s)
        if m:
            t["home"] = _f(m.group(1))
            t["shaft"] = _f(m.group(2))
            t["err"] = _f(m.group(3))
            t["vel"] = _f(m.group(4))
            continue
        m = RE_GAIN.search(s)
        if m:
            t["kp"] = _f(m.group(1))
            t["kd"] = _f(m.group(2))
            t["db"] = _f(m.group(3))
            continue
        m = RE_OUT.search(s)
        if m:
            t["uq"] = _f(m.group(1))
            t["velFilt"] = _f(m.group(2))
            continue
        m = RE_PHASE.search(s)
        if m:
            t["ua"] = _f(m.group(1))
            t["ub"] = _f(m.group(2))
            t["uc"] = _f(m.group(3))
            continue
        m = RE_ANGLE.search(s)
        if m:
            t["angle"] = _f(m.group(1))
            continue
        m = RE_GPIO.search(s)
        if m:
            t["gpio"] = _f(m.group(1))
    return t if "shaft" in t else {}


# ---------------------------------------------------------------- 应用状态
class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.session = None
        self.connected = False
        self.port = ""
        self.baud = 115200
        self.poll_ms = 120
        self.clients = []
        self.last_telem = {}
        self.line_buf = ""
        self.in_diag = False
        self.diag_lines = []

    # ---------- 事件广播 ----------
    def broadcast(self, kind, data):
        msg = {"kind": kind, "data": data, "ts": time.time()}
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except queue.Empty:
                    pass

    def log(self, source, text):
        self.broadcast("log", {"src": source, "text": text, "ts": time.time()})

    def status(self):
        return {"connected": self.connected, "port": self.port,
                "baud": self.baud, "poll_ms": self.poll_ms}

    # ---------- 串口生命周期 ----------
    def connect(self, port, baud):
        self.disconnect(silent=True)
        ser = Win32Serial(port, baud)
        ser.open()                       # 失败直接抛给 HTTP 层
        session = {"ser": ser, "stop": threading.Event()}
        with self.lock:
            self.session = session
            self.connected = True
            self.port = port
            self.baud = int(baud)
            self.line_buf = ""
            self.in_diag = False
            self.diag_lines = []
        threading.Thread(target=self._reader, args=(session,), daemon=True).start()
        threading.Thread(target=self._poller, args=(session,), daemon=True).start()
        self.log("system", "已连接 %s @ %d，等待固件启动/校准（约 4 秒）" % (port, int(baud)))
        self.broadcast("status", self.status())

    def disconnect(self, silent=False):
        with self.lock:
            session = self.session
            self.session = None
            self.connected = False
        if session:
            session["stop"].set()
            try:
                session["ser"].close()
            except Exception:
                pass
        if not silent:
            self.log("system", "已断开串口")
        self.broadcast("status", self.status())

    def send(self, cmd):
        cmd = str(cmd).strip()
        if not cmd:
            return
        if "\n" in cmd or "\r" in cmd:
            cmd = cmd.replace("\r", " ").replace("\n", " ")
        with self.lock:
            session = self.session
            connected = self.connected
        if not connected or not session:
            raise SerialError("尚未连接串口")
        payload = (cmd + "\n").encode("utf-8")
        with self.write_lock:
            session["ser"].write(payload)
        self.log("tx", cmd)

    # ---------- 后台线程 ----------
    def _reader(self, session):
        stop = session["stop"]
        ser = session["ser"]
        while not stop.is_set():
            try:
                chunk = ser.read(1024)
            except Exception as e:
                if not stop.is_set():
                    self.log("system", "串口读取异常：%s" % e)
                    self.disconnect()
                break
            if not chunk:
                continue
            self.line_buf += chunk.decode("utf-8", errors="replace")
            while "\n" in self.line_buf:
                line, self.line_buf = self.line_buf.split("\n", 1)
                self._handle_line(line.replace("\r", "").rstrip())
        # 退出时把残留半行也丢出去
        if self.line_buf.strip():
            self.log("rx", self.line_buf.strip())

    def _handle_line(self, line):
        s = line.strip()
        if not s:
            return
        if s == "--- DIAG ---":
            self.in_diag = True
            self.diag_lines = []
            return
        if self.in_diag:
            if s == "--- end ---":
                telem = parse_diag(self.diag_lines)
                self.in_diag = False
                if telem:
                    self.last_telem = telem
                    self.broadcast("telem", telem)
            else:
                self.diag_lines.append(line)
            return          # 诊断块内部行不进日志，避免 10Hz 轮询刷屏
        self.log("rx", line)

    def _poller(self, session):
        stop = session["stop"]
        while not stop.is_set():
            interval = max(0.02, self.poll_ms / 1000.0)
            if stop.wait(interval):
                break
            if self.poll_ms <= 0:
                continue
            with self.lock:
                alive = self.session is session and self.connected
            if not alive:
                break
            try:
                with self.write_lock:
                    session["ser"].write(b"D\n")
            except Exception as e:
                if not stop.is_set():
                    self.log("system", "轮询写入失败：%s" % e)
                    self.disconnect()
                break


APP = App()


# ---------------------------------------------------------------- HTTP / SSE
class Handler(BaseHTTPRequestHandler):
    server_version = "HapticConsole/1.0"

    def log_message(self, fmt, *args):
        pass                                  # 控制台保持干净

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(INDEX_FILE, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except OSError as e:
                self._json({"ok": False, "error": "index.html 不存在：%s" % e}, 500)
        elif path == "/api/ports":
            self._json({"ok": True, "ports": list_ports()})
        elif path == "/api/status":
            self._json({"ok": True, **APP.status()})
        elif path == "/api/events":
            self._sse()
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        try:
            if path == "/api/connect":
                APP.connect(body.get("port", "COM6"), int(body.get("baud", 115200)))
                self._json({"ok": True})
            elif path == "/api/disconnect":
                APP.disconnect()
                self._json({"ok": True})
            elif path == "/api/send":
                APP.send(body.get("cmd", ""))
                self._json({"ok": True})
            elif path == "/api/config":
                ms = int(body.get("poll_ms", 120))
                APP.poll_ms = max(0, min(5000, ms))
                APP.broadcast("status", APP.status())
                self._json({"ok": True, "poll_ms": APP.poll_ms})
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 400)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = queue.Queue(maxsize=400)
        with APP.lock:
            APP.clients.append(q)
        try:
            hello = {"kind": "status", "data": APP.status(), "ts": time.time()}
            self._sse_write(hello)
            if APP.last_telem:
                self._sse_write({"kind": "telem", "data": APP.last_telem, "ts": time.time()})
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._sse_write(msg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with APP.lock:
                if q in APP.clients:
                    APP.clients.remove(q)

    def _sse_write(self, msg):
        payload = json.dumps(msg["data"], ensure_ascii=False)
        chunk = ("event: %s\ndata: %s\n\n" % (msg["kind"], payload)).encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------- 入口
def selftest():
    ports = list_ports()
    print("可用串口:", ", ".join(ports) if ports else "(无)")
    print("sizeof(DCB)=%d  sizeof(COMMTIMEOUTS)=%d"
          % (ctypes.sizeof(DCB), ctypes.sizeof(COMMTIMEOUTS)))
    port = "COM6"
    if "--com" in sys.argv:
        idx = sys.argv.index("--com")
        if idx + 1 < len(sys.argv):
            port = sys.argv[idx + 1]
    if port not in ports:
        print("警告: %s 不在注册表列表里，仍尝试打开" % port)
    ser = Win32Serial(port, 115200)
    try:
        ser.open()
        ser.write(b"D\n")
        time.sleep(0.8)
        data = ser.read(8192)
        text = data.decode("utf-8", errors="replace").replace("\r", "")
        print("---- 串口回显 ----")
        print(text if text.strip() else "(无回显：检查固件是否在运行、COM 口是否正确)")
        print("---- 解析结果 ----")
        print(json.dumps(parse_diag(text.splitlines()), ensure_ascii=False, indent=2))
    finally:
        ser.close()


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    port = 8765
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
    # 端口被占用（例如已经开了一个实例）时自动往后找，避免双击 bat 直接报错
    srv, actual = None, None
    for candidate in range(port, port + 10):
        try:
            srv = Server(("127.0.0.1", candidate), Handler)
            actual = candidate
            break
        except OSError:
            continue
    if srv is None:
        print("端口 %d~%d 都被占用，请用 --port 指定其它端口。" % (port, port + 9))
        return
    url = "http://127.0.0.1:%d/" % actual
    if "--nobrowser" not in sys.argv:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print("=" * 58)
    print(" SimpleFOC 弹簧回中上位机已启动")
    print(" 浏览器打开: %s" % url)
    print(" 串口列表: %s" % (", ".join(list_ports()) or "(无)"))
    print(" 关闭本窗口即退出服务；重烧固件前请先在此断开串口。")
    print("=" * 58)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.disconnect(silent=True)
        srv.server_close()


if __name__ == "__main__":
    main()
