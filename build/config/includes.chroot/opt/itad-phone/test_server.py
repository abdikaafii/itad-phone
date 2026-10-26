#!/usr/bin/env python3
"""
test_server.py - ITAD PhoneSeal test page server (v0.1.0)

The phone opens the test page by scanning a QR code shown on the station.
The page runs the component tests in the phone's own browser (Safari on
iPhone, Chrome on Android) - no app to install - and sends every result
back to the station.

HTTPS is needed because browsers only allow the camera and microphone on
secure pages. The station makes its own certificate, so the phone shows a
warning once: tap "Show details > visit this website" (iPhone) or
"Advanced > Proceed" (Android).

    srv = TestServer(job_label="JOB-1 / AST-9")
    url = srv.start()          # https://<station-ip>:8443/t/<token>/
    srv.results                # {test name: {status, note, auto}}
    srv.stop()
"""
import json
import os
import secrets
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = "/tmp/itad-phone-cert"
PORT = 8443


def station_ip():
    """IP address of the station on the local network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # no packet is sent
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True,
                             text=True, timeout=5).stdout.split()
        for ip in out:
            if "." in ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return ""


def make_cert(ip):
    os.makedirs(CERT_DIR, exist_ok=True)
    crt = os.path.join(CERT_DIR, "station.crt")
    key = os.path.join(CERT_DIR, "station.key")
    if not (os.path.exists(crt) and os.path.exists(key)):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-days", "825", "-keyout", key, "-out", crt,
             "-subj", "/CN=ITAD PhoneSeal station",
             "-addext", "subjectAltName=IP:%s" % (ip or "127.0.0.1")],
            capture_output=True, timeout=60, check=True)
    return crt, key


class TestServer:
    def __init__(self, job_label="", on_result=None):
        self.token = secrets.token_urlsafe(8)
        self.job_label = job_label
        self.on_result = on_result
        self.results = {}
        self.events = []
        self.httpd = None
        self.url = ""

    def start(self):
        ip = station_ip()
        if not ip:
            raise RuntimeError("the station has no network connection - "
                               "connect it to the same Wi-Fi / network as "
                               "the phone")
        crt, key = make_cert(ip)
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                b = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                pre = "/t/%s" % srv.token
                if self.path.rstrip("/") == pre:
                    with open(os.path.join(HERE, "web", "index.html"),
                              encoding="utf-8") as f:
                        page = f.read()
                    page = page.replace("__TOKEN__", srv.token).replace(
                        "__JOB__", srv.job_label.replace("<", ""))
                    self._send(200, page)
                elif self.path == pre + "/state":
                    self._send(200, json.dumps(srv.results),
                               "application/json")
                else:
                    self._send(404, "Not found - scan the QR code again")

            def do_POST(self):
                if self.path != "/t/%s/result" % srv.token:
                    self._send(403, "no")
                    return
                try:
                    n = min(int(self.headers.get("Content-Length", "0")),
                            20000)
                    data = json.loads(self.rfile.read(n).decode("utf-8"))
                    name = str(data.get("name", ""))[:40]
                    st = str(data.get("status", ""))[:12].upper()
                    if name and st in ("PASS", "FAIL", "N/A", "SKIP"):
                        srv.results[name] = {
                            "status": st,
                            "note": str(data.get("note", ""))[:200],
                            "auto": bool(data.get("auto")),
                            "time": time.strftime("%H:%M:%S")}
                        srv.events.append(name)
                        if srv.on_result:
                            try:
                                srv.on_result(name, srv.results[name])
                            except Exception:
                                pass
                    self._send(200, '{"ok":true}', "application/json")
                except Exception as e:
                    self._send(400, json.dumps({"error": str(e)[:80]}),
                               "application/json")

        self.httpd = ThreadingHTTPServer(("0.0.0.0", PORT), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket,
                                            server_side=True)
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()
        self.url = "https://%s:%d/t/%s/" % (ip, PORT, self.token)
        return self.url

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None


def qr_png(text, path, box=8):
    """QR code PNG for the station screen. Uses python3-qrcode, or the
    QR encoder inside reportlab + Pillow when qrcode is missing."""
    try:
        import qrcode
        q = qrcode.QRCode(border=2, box_size=box)
        q.add_data(text)
        q.make(fit=True)
        q.make_image(fill_color="black", back_color="white").save(path)
        return path
    except ImportError:
        pass
    from reportlab.graphics.barcode import qrencoder
    from PIL import Image, ImageDraw
    q = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)
    q.addData(text)
    q.make()
    n = q.getModuleCount()
    border = 2
    img = Image.new("RGB", ((n + 2 * border) * box,) * 2, "white")
    d = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            if q.isDark(r, c):
                x, y = (c + border) * box, (r + border) * box
                d.rectangle([x, y, x + box - 1, y + box - 1], fill="black")
    img.save(path)
    return path


if __name__ == "__main__":
    s = TestServer("demo job")
    print("Open on the phone:", s.start())
    try:
        while True:
            time.sleep(2)
            if s.events:
                print(json.dumps(s.results, indent=1))
                s.events.clear()
    except KeyboardInterrupt:
        s.stop()
