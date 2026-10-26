#!/usr/bin/env python3
"""
net.py - ITAD PhoneSeal: simple network helpers (v0.3.0)

The test page runs in the phone's browser, so the phone must reach the
station. Three ways, easiest first:

  1. Android with USB debugging: over the USB cable (adb reverse). No Wi-Fi.
  2. Station Wi-Fi (hotspot): the station makes its own Wi-Fi network and
     the phone joins it by scanning a QR code. No router needed.
  3. Same Wi-Fi / network: the station joins the office Wi-Fi (simple list
     + password) or a network cable, and the phone is on the same network.

Everything uses NetworkManager (nmcli). All functions return plain values
and never raise.
"""
import random
import re
import subprocess
import time

HOTSPOT_CON = "itad-hotspot"
PORT = 8443


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "%s not installed" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except Exception as e:
        return 1, "", str(e)


def _split(line):
    """nmcli -t line -> fields (handles \\: inside values)."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def devices():
    """[{device, type, state, connection}]"""
    rc, o, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION",
                    "device"], 10)
    out = []
    for ln in o.splitlines():
        f = _split(ln)
        if len(f) >= 4:
            out.append({"device": f[0], "type": f[1], "state": f[2],
                        "connection": f[3]})
    return out


def wifi_device():
    for d in devices():
        if d["type"] == "wifi":
            return d["device"]
    return ""


def ip_of(dev):
    rc, o, _ = run(["ip", "-4", "-o", "addr", "show", "dev", dev], 5)
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", o)
    return m.group(1) if m else ""


def hotspot_info():
    """(ssid, password, ip) when the station Wi-Fi is running, else None."""
    for d in devices():
        if d["connection"] == HOTSPOT_CON and d["state"].startswith(
                "connected"):
            rc, o, _ = run(["nmcli", "-s", "-t", "-f",
                            "802-11-wireless.ssid,802-11-wireless-security.psk",
                            "connection", "show", HOTSPOT_CON], 10)
            vals = {}
            for ln in o.splitlines():
                k, _, v = ln.partition(":")
                vals[k] = v
            return (vals.get("802-11-wireless.ssid", ""),
                    vals.get("802-11-wireless-security.psk", ""),
                    ip_of(d["device"]))
    return None


def summary():
    """One short line for the top bar, and the state:
    ('Wi-Fi Office  192.168.1.20', 'ok') / ('No network', 'none')."""
    hs = hotspot_info()
    if hs:
        return "Station Wi-Fi %s  %s" % (hs[0], hs[2]), "hotspot"
    best = None
    for d in devices():
        if not d["state"].startswith("connected") or d["type"] in (
                "loopback", "bridge", "tun"):
            continue
        ip = ip_of(d["device"])
        if not ip:
            continue
        kind = {"wifi": "Wi-Fi", "ethernet": "Cable"}.get(d["type"],
                                                         d["type"])
        txt = "%s %s  %s" % (kind, d["connection"], ip)
        if d["type"] == "wifi" or best is None:
            best = txt
    if best:
        return best, "ok"
    return "No network", "none"


def scan():
    """Wi-Fi networks: [{ssid, signal, secure, in_use}] strongest first."""
    run(["rfkill", "unblock", "wifi"], 5)
    rc, o, e = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                    "device", "wifi", "list", "--rescan", "yes"], 30)
    nets = {}
    for ln in o.splitlines():
        f = _split(ln)
        if len(f) < 4 or not f[1]:
            continue
        try:
            sig = int(f[2])
        except ValueError:
            sig = 0
        n = {"ssid": f[1], "signal": sig,
             "secure": bool(f[3].strip() and f[3].strip() != "--"),
             "in_use": f[0].strip() == "*"}
        if f[1] not in nets or nets[f[1]]["signal"] < sig:
            nets[f[1]] = n
    return sorted(nets.values(), key=lambda n: (-n["in_use"], -n["signal"]))


def connect(ssid, password=""):
    """(ok, message)"""
    hotspot_stop()
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    rc, o, e = run(cmd, 60)
    msg = (o + e).strip().splitlines()
    msg = msg[-1] if msg else ""
    if rc == 0:
        return True, "Connected to %s" % ssid
    if "Secrets were required" in msg or "802-1x" in msg or \
            "password" in msg.lower():
        return False, "Wrong password for %s" % ssid
    return False, msg or "could not connect"


def hotspot_start():
    """Station Wi-Fi. (ok, message, ssid, password, ip)"""
    run(["rfkill", "unblock", "wifi"], 5)
    dev = wifi_device()
    if not dev:
        return (False, "This station has no Wi-Fi card that works - use a "
                "network cable, or Android over USB.", "", "", "")
    ssid = "ITAD-PhoneSeal-%04d" % random.randint(0, 9999)
    pw = "%08d" % random.randint(0, 99999999)
    run(["nmcli", "connection", "delete", HOTSPOT_CON], 15)
    rc, o, e = run(["nmcli", "device", "wifi", "hotspot", "ifname", dev,
                    "con-name", HOTSPOT_CON, "ssid", ssid, "password", pw],
                   45)
    if rc != 0:
        msg = (e or o).strip().splitlines()
        return (False, "This Wi-Fi card can't make a hotspot (%s). Use the "
                "office Wi-Fi, a network cable, or Android over USB." %
                (msg[-1] if msg else "error"), "", "", "")
    ip = ""
    for _ in range(10):
        ip = ip_of(dev)
        if ip:
            break
        time.sleep(1)
    return True, "Station Wi-Fi is on", ssid, pw, ip


def hotspot_stop():
    run(["nmcli", "connection", "down", HOTSPOT_CON], 15)


def wifi_qr_text(ssid, password):
    """Text for a QR code that a phone camera uses to join the Wi-Fi."""
    def esc(s):
        for ch in "\\;,:\"":
            s = s.replace(ch, "\\" + ch)
        return s
    return "WIFI:T:WPA;S:%s;P:%s;;" % (esc(ssid), esc(password))


def android_usb_open(serial, url_path):
    """Open the test page on an Android phone over the USB cable: the phone
    reaches the station through adb (no Wi-Fi). (ok, message)"""
    rc, o, e = run(["adb", "-s", serial, "reverse", "tcp:%d" % PORT,
                    "tcp:%d" % PORT], 15)
    if rc != 0:
        return False, (e or o).strip()[:120] or "adb reverse failed"
    url = "https://127.0.0.1:%d%s" % (PORT, url_path)
    rc, o, e = run(["adb", "-s", serial, "shell", "am", "start", "-a",
                    "android.intent.action.VIEW", "-d", url], 15)
    if rc != 0 or "Error" in o + e:
        return False, "open this on the phone: %s" % url
    return True, "test page opened on the phone"
