#!/usr/bin/env python3
"""
phone_window.py - ITAD PhoneSeal station window (v0.8.0)

v0.8.0: same look and rules as LaptopSeal:
        - top corner: Wi-Fi icon + network name (tap it for the Network
          window), Reports (Ready / Not kept), time and date, technician
        - left menu ends with Settings and Shutdown (same icons)
        - the SAME Network window as LaptopSeal (netwin.py), plus the
          station Wi-Fi part
        - sign in like LaptopSeal: Add technician (approved by an existing
          technician), clear messages; technicians.txt and the reports
          folder are the same as LaptopSeal (Ventoy USB > ITAD_REPORTS)
        - Settings: where reports are saved, technician list, Add technician
        - same Location list as LaptopSeal

v0.3.0: no more flicker (lists update in place), Home / Back on every page,
        Shut down button, Network window (Wi-Fi list + password, station
        Wi-Fi hotspot with a join QR code), Android test page over the USB
        cable (no Wi-Fi needed), phone details read again when incomplete.

One phone at a time, in this order (phones must be tested BEFORE the wipe:
after the wipe the phone is back on the Hello / Welcome screen):

  1 Sign in      technician from technicians.txt on the ITAD_DATA stick
  2 Job + phone  Job ID, Asset ID, plug the phone in by USB
  3 Lock checks  Find My / Activation Lock, Google FRP, MDM, carrier
  4 Tests        the phone scans a QR code and runs the tests in its browser
  5 Wipe         erase, then the station checks the phone is on Hello
  6 Report       grade, notes, signed PDF certificate on the ITAD_DATA stick

Locked devices (passcode unknown) and devices without USB (Apple Watch...):
  Job + device > Device details > Wipe > lock checks on the setup screen
  AFTER the wipe > Report. Tests are reported "not tested - passcode
  unknown".

Run:  sudo python3 phone_window.py      (--windowed for a normal window)
"""
import argparse
import math
import os
import queue
import re
import sys
import threading
import time

import itad_common as C
import net
from netwin import NetworkWindow, StatusPoller
import phone_core as core
import phone_report as rpt
from test_server import TestServer, qr_png

VERSION = "0.8.1"
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))

BG, BG2, SIDE = "#050F22", "#081831", "#061430"
CARD, CARD2 = "#0B1F40", "#0E2448"
BORDER, BORDER_HI = "#1A3966", "#2B5FA8"
BLUE, BLUE2, CYAN = "#1E7BFF", "#2E9BFF", "#38BDF8"
TEXT, MUTED, DIM = "#EAF2FF", "#8EA6C8", "#4F6A92"
OK, BAD, WARN = "#34D399", "#F87171", "#FBBF24"
OKD, BADD = "#1FA971", "#C62F2F"
FONT = "DejaVu Sans"
# banner design (same as LaptopSeal)
BANNER, BANNER2 = "#07334A", "#0A4560"
TILE_COLS = {"r": "#E8453C", "o": "#F59E0B", "y": "#FACC15", "g": "#22C55E",
             "t": "#14B8A6", "c": "#38BDF8", "b": "#1E7BFF"}
TICK_TILES = ["...b", "..ct", "ygt.", ".o.."]
STEPS = [("login", "Sign in"), ("job", "Job + device"), ("checks", "Lock checks"),
         ("tests", "Tests"), ("wipe", "Wipe"), ("report", "Report")]
# Tests done on the phone's own test page (web/index.html), same order.
# "Charging" is also a phone-page test; it is listed with Battery health.
WEB_TESTS = ["Touch screen", "Multi-touch", "Telephony", "Microphone",
             "Speakers", "Earpiece", "Headphones", "Buttons & ports",
             "Vibration", "Display", "Front camera", "Rear camera",
             "Flash light", "Proximity sensor", "Motion sensors", "Wi-Fi",
             "Bluetooth"]
GRADES = ["A - like new", "B - light wear", "C - visible wear",
          "D - heavy wear / damage"]
# same list as LaptopSeal
LOCATIONS = ["Warehouse DPA3 Test Bay 1", "Warehouse DPA3 Test Bay 2",
             "Warehouse DPA3 Test Bay 3", "Warehouse DPA3 Test Bay 4", "Other"]
MIN_PASSWORD = 6
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'-]{1,29}$")


def round_rect(c, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def draw_icon(c, kind, cx, cy, s, color, width=2):
    """Line icons, the same drawings as LaptopSeal. s = size in pixels."""
    h = s / 2.0
    w = max(1, int(width))

    def L(*p, **k):
        k.setdefault("width", w)
        return c.create_line(*p, fill=color, capstyle="round",
                             joinstyle="round", **k)
    if kind == "gear":
        r1, r2 = h * .50, h * .80
        for k in range(8):
            a = math.radians(k * 45 + 22.5)
            L(cx + r1 * math.cos(a), cy + r1 * math.sin(a),
              cx + r2 * math.cos(a), cy + r2 * math.sin(a),
              width=max(3, int(s * .16)))
        c.create_oval(cx - r1 - 1, cy - r1 - 1, cx + r1 + 1, cy + r1 + 1,
                      outline=color, fill=color, width=1)
        c.create_oval(cx - h * .22, cy - h * .22, cx + h * .22, cy + h * .22,
                      outline=color, fill=c["bg"], width=1)
    elif kind in ("wifi", "wifi_off"):
        by = cy + h * .55
        for r in (1.05, 0.70, 0.36):
            rr = h * r
            c.create_arc(cx - rr, by - rr, cx + rr, by + rr, start=45,
                         extent=90, style="arc", outline=color,
                         width=w + 1)
        d = max(2.0, s * .08)
        c.create_oval(cx - d, by - d, cx + d, by + d, fill=color,
                      outline=color)
        if kind == "wifi_off":
            L(cx - h * .75, cy - h * .65, cx + h * .75, cy + h * .7,
              width=w + 1)
    elif kind == "power":
        c.create_arc(cx - h * .65, cy - h * .6, cx + h * .65, cy + h * .7,
                     start=120, extent=300, style="arc", outline=color,
                     width=w)
        L(cx, cy - h * .75, cx, cy - h * .05)
    elif kind == "user":
        c.create_oval(cx - h * .3, cy - h * .7, cx + h * .3, cy - h * .1,
                      outline=color, width=w)
        c.create_arc(cx - h * .65, cy + h * .05, cx + h * .65, cy + h * 1.25,
                     start=0, extent=180, style="arc", outline=color,
                     width=w)
NOT_TESTED = "NOT TESTED"
PASSCODE_NOTE = "not tested - passcode unknown"


class App:
    def __init__(self, tk, ttk, root, windowed):
        self.tk, self.ttk, self.root = tk, ttk, root
        self.q = queue.Queue()
        self.out_dir, self.persistent = C.pick_out_dir()
        self.log = []
        self.fails, self.locked_until = 0, 0.0
        self.tech = ""
        self.server = None
        self.qr_img = None
        self.wifi_img = None
        self.res_gen = 0          # stops old refresh loops (flicker fix)
        self.poll_gen = 0
        self.last_sig = None
        self.read_tries = 0
        self.net_win = None
        self.net_state = "none"
        self.cur_page = ""
        self.reset_job()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.sc = max(0.7, min(1.3, min(sw / 1600.0, sh / 900.0)))
        root.title("ITAD PhoneSeal")
        root.configure(bg=BG)
        if windowed:
            root.geometry("1366x768")
        else:
            try:
                root.attributes("-fullscreen", True)
            except Exception:
                pass
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                        foreground=TEXT, arrowcolor=TEXT)
        root.option_add("*TCombobox*Listbox.background", CARD2)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.font", self.F(13))
        self.build_shell()
        self.show_login()
        root.bind("<Control-q>", lambda e: self.quit())
        root.after(100, self.pump)
        root.after(200, self.tick)

    # ---------- small helpers ----------
    def F(self, size, bold=False):
        return (FONT, max(8, int(size * self.sc)), "bold" if bold else
                "normal")

    def px(self, n):
        return int(n * self.sc)

    def lbl(self, parent, text="", size=12, bold=False, fg=TEXT, bg=None,
            **kw):
        if "wraplength" in kw:
            kw["wraplength"] = self.px(kw["wraplength"])
        kw.setdefault("anchor", "w")
        kw.setdefault("justify", "left")
        return self.tk.Label(parent, text=text, font=self.F(size, bold),
                             fg=fg, bg=bg or parent["bg"], **kw)

    def btn(self, parent, text, cmd, kind="primary", width=None):
        bg, fg, act = {"primary": (BLUE, "white", BLUE2),
                       "ok": (OKD, "white", "#23C285"),
                       "danger": (BADD, "white", "#E04545"),
                       "ghost": (CARD, MUTED, CARD2)}[kind]
        b = self.tk.Button(parent, text=text, command=cmd, font=self.F(12,
                                                                        True),
                           bg=bg, fg=fg, activebackground=act,
                           activeforeground="white", relief="flat", bd=0,
                           padx=self.px(18), pady=self.px(9),
                           highlightthickness=1 if kind == "ghost" else 0,
                           highlightbackground=BORDER_HI, cursor="hand2")
        if width:
            b.configure(width=width)
        return b

    def entry(self, parent, var, secret=False, width=28):
        e = self.tk.Entry(parent, textvariable=var, font=self.F(14),
                          bg=CARD2, fg=TEXT, insertbackground=TEXT,
                          relief="flat", highlightthickness=1,
                          highlightbackground=BORDER, highlightcolor=CYAN,
                          width=width, show="•" if secret else "")
        return e

    def card(self, parent, title=None):
        f = self.tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                          highlightthickness=1)
        inner = self.tk.Frame(f, bg=CARD)
        inner.pack(fill="both", expand=True, padx=self.px(18),
                   pady=self.px(14))
        if title:
            self.lbl(inner, title.upper(), 10, True, fg=CYAN).pack(
                anchor="w", pady=(0, self.px(8)))
        return f, inner

    def say(self, msg):
        self.log.append("%s %s" % (time.strftime("%H:%M:%S"), msg))

    def pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def bg(self, work, done):
        """Run work() in a thread, then done(result) in the window."""
        def t():
            try:
                r = work()
            except Exception as e:
                r = e
            self.q.put(lambda: done(r))
        threading.Thread(target=t, daemon=True).start()

    # ---------- shell ----------
    def build_shell(self):
        tk = self.tk
        p = self.px
        # ---- banner (same design as LaptopSeal)
        head = tk.Frame(self.root, bg=BANNER, height=p(84))
        head.pack(fill="x")
        head.pack_propagate(False)
        sq, gp = p(13), p(3)
        mark = tk.Canvas(head, width=4 * sq + 3 * gp + 2,
                         height=4 * sq + 3 * gp + 2, bg=BANNER,
                         highlightthickness=0)
        mark.pack(side="left", padx=(p(22), p(12)))
        for r, line in enumerate(TICK_TILES):
            for k, ch in enumerate(line):
                if ch in TILE_COLS:
                    x0, y0 = 1 + k * (sq + gp), 1 + r * (sq + gp)
                    mark.create_rectangle(x0, y0, x0 + sq, y0 + sq,
                                          fill=TILE_COLS[ch], outline="")
        tk.Label(head, text="IT", font=self.F(34, True), fg="white",
                 bg=BANNER).pack(side="left")
        tk.Label(head, text="AD", font=self.F(34, True), fg=CYAN,
                 bg=BANNER).pack(side="left")
        tk.Label(head, text=" PHONESEAL", font=self.F(15, True), fg="white",
                 bg=BANNER).pack(side="left", anchor="s", pady=(0, p(18)))
        tk.Frame(head, bg="#D7E7F2", width=2, height=p(50)).pack(
            side="left", padx=p(18))
        tk.Label(head, text="Certified\nPhone Erasure\n& Testing",
                 font=self.F(10), fg="white", bg=BANNER,
                 justify="left").pack(side="left")
        conf = tk.Canvas(head, width=4 * p(13) + 3 * p(4), height=p(13),
                         bg=BANNER, highlightthickness=0)
        conf.place(relx=1.0, rely=1.0, anchor="se")
        for k, ch in enumerate("yoct"):
            x0 = k * (p(13) + p(4))
            conf.create_rectangle(x0, 0, x0 + p(13), p(13),
                                  fill=TILE_COLS[ch], outline="")
        # status box (right) - same as LaptopSeal
        box = tk.Frame(head, bg=BANNER2, highlightbackground="#2E6E8E",
                       highlightthickness=1)
        box.pack(side="right", padx=p(26))
        s0 = tk.Frame(box, bg=BANNER2, cursor="hand2")
        s0.pack(side="left", padx=(p(14), p(12)), pady=p(8))
        self.h_net_i = tk.Canvas(s0, width=p(30), height=p(30), bg=BANNER2,
                                 highlightthickness=0, cursor="hand2")
        self.h_net_i.pack(side="left", padx=(0, p(8)))
        s0t = tk.Frame(s0, bg=BANNER2, cursor="hand2")
        s0t.pack(side="left")
        self.h_net_t = tk.Label(s0t, text="Network", font=self.F(9),
                                fg="#BFD3F2", bg=BANNER2, cursor="hand2")
        self.h_net_t.pack(anchor="w")
        self.h_net = tk.Label(s0t, text="Checking...", font=self.F(10, True),
                              fg=MUTED, bg=BANNER2, cursor="hand2")
        self.h_net.pack(anchor="w")
        for wdg in (s0, self.h_net_i, s0t, self.h_net_t, self.h_net):
            wdg.bind("<Button-1>", lambda e: self.network_window())
        tk.Frame(box, bg="#2E6E8E", width=1).pack(side="left", fill="y",
                                                  pady=p(8))
        self.paint_net("", "none")
        self.f_net = tk.Label(self.root, text="")     # hidden, fed by netwin
        try:
            self.net_poller = StatusPoller(self.root, self.f_net, prefix="")
            self.root.after(1000, self.watch_net)
        except Exception as e:
            self.h_net.configure(text="Not available", fg=WARN)
            sys.stderr.write("network status not available: %s\n" % e)
        s1 = tk.Frame(box, bg=BANNER2)
        s1.pack(side="left", padx=(p(16), p(16)), pady=p(8))
        tk.Label(s1, text="Reports", font=self.F(9), fg="#BFD3F2",
                 bg=BANNER2).pack(anchor="w")
        self.h_ready = tk.Label(s1, text="", font=self.F(10, True),
                                bg=BANNER2)
        self.h_ready.pack(anchor="w")
        tk.Frame(box, bg="#2E6E8E", width=1).pack(side="left", fill="y",
                                                  pady=p(8))
        s2 = tk.Frame(box, bg=BANNER2)
        s2.pack(side="left", padx=p(16))
        self.h_time = tk.Label(s2, text="", font=self.F(11, True), fg=TEXT,
                               bg=BANNER2)
        self.h_time.pack(anchor="w")
        self.h_date = tk.Label(s2, text="", font=self.F(9), fg="#BFD3F2",
                               bg=BANNER2)
        self.h_date.pack(anchor="w")
        self.h_sep2 = tk.Frame(box, bg="#2E6E8E", width=1)
        self.h_user_i = self.icon(box, "user", 24, "#D8E6FA", BANNER2)
        self.h_user = tk.Label(box, text="", font=self.F(10, True), fg=TEXT,
                               bg=BANNER2)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        side = tk.Frame(body, bg=SIDE, width=self.px(220))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.step_lbls = {}
        tk.Frame(side, bg=SIDE, height=self.px(20)).pack()
        for i, (k, name) in enumerate(STEPS, start=1):
            l = tk.Label(side, text="  %d   %s" % (i, name),
                         font=self.F(13, True), fg=DIM, bg=SIDE, anchor="w",
                         padx=self.px(12), pady=self.px(10))
            l.pack(fill="x", padx=self.px(10), pady=2)
            self.step_lbls[k] = l
        tk.Label(side, text="PhoneSeal v%s" % VERSION, font=self.F(9),
                 fg=DIM, bg=SIDE).pack(side="bottom", pady=self.px(10))
        self.nav_item(side, "Shutdown", "power", self.power_off)
        self.nav_item(side, "Settings", "gear", self.settings_window)
        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True,
                          padx=self.px(26), pady=self.px(18))

    def icon(self, parent, kind, size=26, color=CYAN, bg=None, width=2):
        s = self.px(size)
        c = self.tk.Canvas(parent, width=s, height=s, bg=bg or parent["bg"],
                           highlightthickness=0)
        draw_icon(c, kind, s / 2.0, s / 2.0, s * .8, color, width)
        return c

    def nav_item(self, parent, text, ic, cmd):
        """Left-menu button, same look as LaptopSeal (packed at the bottom)."""
        tk = self.tk
        f = tk.Frame(parent, bg=SIDE, highlightthickness=1,
                     highlightbackground=SIDE, cursor="hand2")
        f.pack(side="bottom", fill="x", padx=self.px(12), pady=self.px(4))
        c = tk.Canvas(f, width=self.px(40), height=self.px(40), bg=SIDE,
                      highlightthickness=0)
        c.pack(side="left", padx=(self.px(8), self.px(12)), pady=self.px(6))
        lab = tk.Label(f, text=text, font=self.F(12), fg=TEXT, bg=SIDE)
        lab.pack(side="left")

        def paint(hover=False):
            bg = "#0F2A52" if hover else SIDE
            f.configure(bg=bg, highlightbackground=bg)
            c.configure(bg=bg)
            lab.configure(bg=bg)
            c.delete("all")
            s = self.px(40)
            round_rect(c, 2, 2, s - 2, s - 2, self.px(9), fill="#0E2447",
                       outline="#21406E", width=1)
            draw_icon(c, ic, s / 2.0, s / 2.0, s * .48, "white", 2)
        for w in (f, c, lab):
            w.bind("<Button-1>", lambda e: cmd())
            w.bind("<Enter>", lambda e: paint(True))
            w.bind("<Leave>", lambda e: paint(False))
        paint()
        return f

    def paint_net(self, text, state):
        """Top-corner network box: Wi-Fi icon coloured by the state."""
        col = {"ok": OK, "hotspot": CYAN}.get(state, WARN)
        c = self.h_net_i
        c.delete("all")
        s = self.px(30)
        draw_icon(c, "wifi" if state in ("ok", "hotspot") else "wifi_off",
                  s / 2.0, s / 2.0, s * .78, col, 2)
        if state in ("ok", "hotspot"):
            name, _, ip = text.partition("  ")
            name = name.strip() or "Connected"
            if len(name) > 22:
                name = name[:21] + "..."
            self.h_net_t.configure(text=ip.strip() or "Network")
            self.h_net.configure(text=name, fg=col)
        else:
            self.h_net_t.configure(text="Network")
            self.h_net.configure(text="No network" if text in (
                "", "No network") else text, fg=col)

    def watch_net(self):
        """Copy what the netwin poller found into the top-corner box."""
        try:
            txt = self.f_net.cget("text")
            st = getattr(self.net_poller, "state", "none")
            self.net_state = st
            if (txt, st) != getattr(self, "_net_last", None):
                self._net_last = (txt, st)
                self.paint_net(txt, st)
        except Exception:
            pass
        self.root.after(1000, self.watch_net)

    def tick(self):
        t = C.now()
        self.h_time.configure(text=t.strftime("%I:%M %p").lstrip("0"))
        self.h_date.configure(text="%d %s" % (t.day, t.strftime("%b %Y")))
        if self.persistent:
            self.h_ready.configure(text="\u25cf Ready", fg=OK)
        else:
            self.h_ready.configure(text="\u25cf Not kept (no USB)", fg=WARN)
        self.root.after(1000, self.tick)

    def show_user(self, name):
        """Technician name in the top-corner box (hidden when signed out)."""
        if name:
            self.h_sep2.pack(side="left", fill="y", pady=self.px(8))
            self.h_user_i.pack(side="left", padx=(self.px(14), self.px(6)))
            self.h_user.configure(text=name)
            self.h_user.pack(side="left", padx=(0, self.px(16)))
        else:
            for w in (self.h_sep2, self.h_user_i, self.h_user):
                w.pack_forget()

    def page(self, key, title, sub="", back=None):
        self.res_gen += 1         # any refresh loop of the old page stops
        for w in self.content.winfo_children():
            w.destroy()
        keys = [k for k, _ in STEPS]
        cur = keys.index(key)
        self.cur_page = key
        for i, k in enumerate(keys):
            self.step_lbls[k].configure(
                bg=BLUE if i == cur else SIDE,
                fg="white" if i == cur else (OK if i < cur else DIM))
        self.lbl(self.content, title, 24, True).pack(anchor="w")
        if sub:
            self.lbl(self.content, sub, 12, fg=MUTED, wraplength=1150).pack(
                anchor="w", pady=(2, self.px(12)))
        bar = self.tk.Frame(self.content, bg=BG)
        bar.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        nav = self.tk.Frame(bar, bg=BG)
        nav.pack(side="left")
        if key not in ("login", "job"):
            self.btn(nav, "Home", self.go_home, "ghost").pack(
                side="left", padx=(0, 6))
        if back:
            self.btn(nav, "< Back", back, "ghost").pack(
                side="left", padx=(0, self.px(14)))
        self.status = self.lbl(bar, "", 11, fg=MUTED, wraplength=650)
        self.status.pack(side="left")
        self.bar_right = self.tk.Frame(bar, bg=BG)
        self.bar_right.pack(side="right")
        return self.content

    def set_status(self, text, fg=MUTED):
        if self.status.cget("text") != text or self.status.cget("fg") != fg:
            self.status.configure(text=text, fg=fg)

    def popup(self, title):
        """Small window that always stays on top of the full screen."""
        win = self.tk.Toplevel(self.root)
        win.configure(bg=CARD)
        win.title(title)
        win.transient(self.root)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        return win

    def ask(self, title, text, on_yes, yes="Yes", no="Cancel"):
        win = self.popup(title)
        self.lbl(win, title, 15, True, bg=CARD).pack(
            anchor="w", padx=self.px(22), pady=(self.px(16), 4))
        self.lbl(win, text, 12, bg=CARD, wraplength=520).pack(
            anchor="w", padx=self.px(22))
        bf = self.tk.Frame(win, bg=CARD)
        bf.pack(anchor="e", padx=self.px(22), pady=self.px(16))

        def go():
            win.destroy()
            on_yes()
        self.btn(bf, no, win.destroy, "ghost").pack(side="left", padx=4)
        self.btn(bf, yes, go, "danger").pack(side="left", padx=4)
        win.lift()
        win.focus_force()

    # ---------- top bar: home, shut down, network ----------
    def go_home(self):
        """Back to the Job + device page (this device's job is dropped)."""
        if not self.tech:
            self.show_login()
            return
        if self.s.get("phone") is None:
            self.show_job()
            return
        txt = "Leave this device and go back to the start?"
        w = (self.s.get("wipe") or {}).get("state")
        if w and w != "RUNNING":
            txt += ("\n\nThe device was already wiped (%s). Save its report "
                    "first, or it is lost." % w)
        elif w == "RUNNING":
            txt = ("A wipe is running. Leave only if the device is "
                   "disconnected.")
        self.ask("Go back to the start", txt, self.next_phone, "Leave")

    def power_off(self):
        w = (self.s.get("wipe") or {}).get("state")
        txt = "Switch off this station now?"
        if w == "RUNNING":
            txt = "A WIPE IS RUNNING. Switch off anyway?"
        elif self.s.get("phone") is not None:
            txt = "A device job is open (its report is not saved). " \
                  "Switch off anyway?"

        def off():
            import subprocess
            if self.server:
                self.server.stop()
            subprocess.call(["sync"])
            if subprocess.call(["systemctl", "poweroff"]) != 0:
                subprocess.call(["poweroff"])
        self.ask("Shut down", txt, off, "Shut down")

    def network_window(self):
        """The same Network window as LaptopSeal, plus station Wi-Fi."""
        try:
            if self.net_win is not None and self.net_win.alive():
                self.net_win.win.lift()
                return
        except Exception:
            pass
        self.net_win = NetworkWindow(self.tk, self.root, font=self.F,
                                     px=self.px, hotspot=True,
                                     on_change=self.after_net_change)

    def after_net_change(self):
        if self.server and self.cur_page == "tests":
            self.root.after(1500, self.show_tests)   # new address / QR

    # ---------- settings ----------
    def settings_window(self):
        """Where reports are saved, technicians, Add technician."""
        win = self.popup("Settings")
        self.lbl(win, "Settings", 18, True, bg=CARD).pack(
            anchor="w", padx=self.px(22), pady=(self.px(16), self.px(6)))
        f, c = self.card(win, "Reports and accounts")
        f.pack(fill="x", padx=self.px(22), pady=(0, self.px(10)))
        self.lbl(c, ("Reports are saved on %s:\n%s\n(reports folder: %s)" % (
            C.store_name() or "the USB stick", self.out_dir,
            os.path.join(self.out_dir, "reports")))
            if self.persistent else
            ("Reports are NOT kept: no USB stick to save them on.\nThey are "
             "only in memory (%s) and are lost at power off.\nBoot from the "
             "Ventoy USB (or plug in any USB stick) and restart." %
             self.out_dir), 11, fg=OK if self.persistent else BAD,
            wraplength=560).pack(anchor="w")
        f, c = self.card(win, "Technicians")
        f.pack(fill="x", padx=self.px(22))
        acc = C.load_accounts(self.out_dir)
        ready = sorted((a["name"] for a in acc.values() if a["hash"]),
                       key=str.lower)
        self.lbl(c, ("%d technician%s: %s" % (
            len(ready), "" if len(ready) == 1 else "s", ", ".join(ready)))
            if ready else "No technician accounts yet.", 11,
            wraplength=560).pack(anchor="w", pady=(0, self.px(8)))

        def add():
            win.destroy()
            self.add_tech_dialog()
        self.btn(c, "Add technician", add, "ghost").pack(anchor="w")
        bf = self.tk.Frame(win, bg=CARD)
        bf.pack(fill="x", padx=self.px(22), pady=self.px(16))
        self.btn(bf, "Close", win.destroy).pack(side="right")
        self.lbl(bf, "PhoneSeal v%s" % VERSION, 10, fg=MUTED,
                 bg=CARD).pack(side="left")
        win.lift()
        win.focus_force()

    # ---------- 1. sign in ----------
    def show_login(self):
        tk = self.tk
        self.page("login", "Technician sign in",
                  "Choose your name, then type your password.")
        f, c = self.card(self.content)
        f.pack(anchor="w", pady=self.px(10))
        acc = C.load_accounts(self.out_dir)
        names = sorted((a["name"] for a in acc.values() if a["hash"]),
                       key=str.lower)
        self.v_user = tk.StringVar(value=names[0] if len(names) == 1 else "")
        self.v_pass = tk.StringVar(value="")
        self.lbl(c, "TECHNICIAN", 10, True, fg=MUTED).pack(anchor="w")
        cb = self.ttk.Combobox(c, textvariable=self.v_user, values=names,
                               state="readonly", font=self.F(14), width=28)
        cb.pack(anchor="w", pady=(2, self.px(12)), ipady=self.px(4))
        self.lbl(c, "PASSWORD", 10, True, fg=MUTED).pack(anchor="w")
        pw = self.entry(c, self.v_pass, secret=True, width=30)
        pw.pack(anchor="w", pady=(2, self.px(12)), ipady=self.px(6))
        self.l_msg = self.lbl(c, "" if names else
                              "No technician accounts yet. Press 'Add "
                              "technician' (bottom right) to create the "
                              "first one.", 11, fg=WARN,
                              wraplength=520)
        self.l_msg.pack(anchor="w", pady=(0, self.px(10)))
        self.btn(c, "Sign in", self.do_login).pack(anchor="w")
        self.l_pw = pw
        self.btn(self.bar_right, "Add technician", self.add_tech_dialog,
                 "ghost").pack(side="left")
        if not self.persistent:
            self.set_status("No USB stick to save on: new accounts and "
                            "reports are lost at power off.", WARN)
        cb.bind("<<ComboboxSelected>>", lambda e: pw.focus_set())
        pw.bind("<Return>", lambda e: self.do_login())
        w_f = pw if names else cb
        self.root.after(200, lambda: w_f.winfo_exists() and w_f.focus_set())

    def do_login(self):
        left = self.locked_until - time.time()
        if left > 0:
            self.l_msg.configure(text="Too many wrong tries. Wait %d s." %
                                 (int(left) + 1), fg=BAD)
            return
        name, pw = self.v_user.get().strip(), self.v_pass.get()
        if not name or not pw:
            self.l_msg.configure(text="Choose your name and type your "
                                      "password.", fg=WARN)
            return
        a = C.load_accounts(self.out_dir).get(name.lower())
        if a and a["hash"] and C.verify_password(pw, a["hash"]):
            self.fails = 0
            self.tech = a["name"]
            self.show_user(self.tech)
            self.say("signed in: %s" % self.tech)
            self.show_job()
            return
        self.v_pass.set("")
        self.fails += 1
        txt = "Wrong name or password."
        if self.fails >= C.MAX_TRIES:
            self.fails = 0
            self.locked_until = time.time() + C.LOCK_SECONDS
            txt += " Locked for %d s." % C.LOCK_SECONDS
        self.l_msg.configure(text=txt, fg=BAD)

    def add_tech_dialog(self):
        """Add or change a technician. The first account needs no approval;
        after that an existing technician must approve with their password.
        Saved as a secure hash in technicians.txt (same file as LaptopSeal)."""
        tk = self.tk
        acc = C.load_accounts(self.out_dir)
        approvers = {k: a for k, a in acc.items() if a["hash"]}
        need_ok = bool(approvers)
        win = self.popup("Add technician")
        inner = tk.Frame(win, bg=CARD)
        inner.pack(padx=self.px(30), pady=self.px(22))
        self.lbl(inner, "Add or change a technician", 16, True).pack(
            anchor="w")
        self.lbl(inner, "The password is saved as a secure hash, never as "
                        "plain text.", 10, fg=MUTED).pack(
            anchor="w", pady=(2, self.px(14)))
        v = {k: tk.StringVar(value="") for k in
             ("name", "pw1", "pw2", "by", "bypw")}
        fields = [("NEW TECHNICIAN NAME", "name", False),
                  ("PASSWORD (at least %d characters)" % MIN_PASSWORD,
                   "pw1", True),
                  ("TYPE THE PASSWORD AGAIN", "pw2", True)]
        if need_ok:
            fields += [("APPROVED BY (an existing technician)", "by", False),
                       ("THEIR PASSWORD", "bypw", True)]
        first = None
        for label, key, secret in fields:
            self.lbl(inner, label, 9, True, fg=MUTED).pack(anchor="w")
            e = self.entry(inner, v[key], secret=secret, width=34)
            e.pack(fill="x", pady=(2, self.px(10)), ipady=self.px(4))
            first = first or e
        msg = self.lbl(inner, "" if need_ok else
                       "This is the first account, so no approval is "
                       "needed.", 10, fg=MUTED, wraplength=380)
        msg.pack(anchor="w", pady=(0, self.px(10)))

        def save():
            name = v["name"].get().strip()
            p1, p2 = v["pw1"].get(), v["pw2"].get()
            if not NAME_RE.match(name):
                msg.configure(text="Name: 2-30 letters or numbers (spaces, "
                                   "dot, dash allowed).", fg=BAD)
                return
            if len(p1) < MIN_PASSWORD:
                msg.configure(text="Password is too short.", fg=BAD)
                return
            if p1 != p2:
                msg.configure(text="The two passwords are not the same.",
                              fg=BAD)
                return
            if need_ok:
                a = approvers.get(v["by"].get().strip().lower())
                if not a or not C.verify_password(v["bypw"].get(),
                                                  a["hash"]):
                    v["bypw"].set("")
                    msg.configure(text="Approval name or password is wrong.",
                                  fg=BAD)
                    return
            try:
                path = C.save_account(self.out_dir, name, p1)
            except Exception as e:
                why = ("the USB stick gave a write error - check it in "
                       "Windows (or use another stick) and restart"
                       if getattr(e, "errno", None) == 5 else str(e))
                msg.configure(text="Could not save: %s" % why, fg=BAD)
                return
            win.destroy()
            note = "Saved %s in %s." % (name, path)
            if not self.persistent:
                note += ("  WARNING: no USB stick, this account is lost at "
                         "power off.")
            if self.cur_page == "login" and not self.tech:
                self.show_login()
                self.v_user.set(name)
                self.l_msg.configure(text=note + "  Now sign in.",
                                     fg=OK if self.persistent else WARN)
                try:
                    self.l_pw.focus_set()
                except Exception:
                    pass

        bf = tk.Frame(inner, bg=CARD)
        bf.pack(fill="x")
        self.btn(bf, "Save", save).pack(side="left")
        self.btn(bf, "Cancel", win.destroy, "ghost").pack(
            side="left", padx=self.px(8))
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry("+%d+%d" % (max(0, (sw - w) // 2),
                                 max(0, (sh - h) // 2)))
        try:
            win.grab_set()
        except Exception:
            pass
        first.focus_set()

    # ---------- 2. job + phone ----------
    def reset_job(self):
        self.s = {"job_id": "JOB-" + C.now().strftime("%Y%m%d-%H%M%S"),
                  "asset_id": "", "location": LOCATIONS[0], "phone": None,
                  "info": {}, "checks": [], "tests": {}, "wipe": {},
                  "started": None, "locked": False}
        self.polling = False

    def show_job(self):
        tk = self.tk
        self.page("job", "Job and device", "Enter the job, then plug the "
                  "phone or tablet into the station with a USB cable.")
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x")
        self.v_job = tk.StringVar(value=self.s["job_id"])
        self.v_asset = tk.StringVar(value=self.s["asset_id"])
        self.v_loc = tk.StringVar(value=self.s["location"])
        for lab, var in (("JOB ID", self.v_job), ("ASSET ID", self.v_asset)):
            f, c = self.card(row)
            f.pack(side="left", padx=(0, self.px(12)))
            self.lbl(c, lab, 10, True, fg=MUTED).pack(anchor="w")
            self.entry(c, var, width=22).pack(anchor="w", ipady=self.px(5))
        f, c = self.card(row)
        f.pack(side="left")
        self.lbl(c, "LOCATION", 10, True, fg=MUTED).pack(anchor="w")
        self.ttk.Combobox(c, textvariable=self.v_loc, values=LOCATIONS,
                          font=self.F(13), width=16).pack(anchor="w")
        f, c = self.card(self.content, "Phones and tablets on this station")
        f.pack(fill="both", expand=True, pady=(self.px(14), 0))
        self.ph_list = tk.Frame(c, bg=CARD)
        self.ph_list.pack(fill="both", expand=True)
        self.lbl(c, "iPhone / iPad: unlock it and tap 'Trust This "
                 "Computer'.   Android: Settings > Developer options > USB "
                 "debugging ON, then tap 'Allow'.   Passcode unknown? Use "
                 "'Passcode unknown' on its row.", 11, fg=MUTED,
                 wraplength=1100).pack(anchor="w", pady=(self.px(8), 0))
        self.btn(c, "Add a device by hand (no USB: Apple Watch, other)",
                 self.add_manual, "ghost").pack(anchor="w",
                                                pady=(self.px(8), 0))
        self.btn(self.bar_right, "Sign out", self.sign_out, "ghost").pack(
            side="left", padx=6)
        self.polling = True
        self.poll_gen += 1
        self.last_sig = None
        self.poll_phones(self.poll_gen)

    def sign_out(self):
        self.polling = False
        self.tech = ""
        self.show_user("")
        self.reset_job()
        self.show_login()

    def poll_phones(self, gen):
        if not self.polling or gen != self.poll_gen:
            return
        self.bg(core.list_phones, lambda r: self.draw_phones(r, gen))

    def draw_phones(self, phones, gen):
        if not self.polling or gen != self.poll_gen:
            return
        if isinstance(phones, Exception):
            phones = []
        sig = repr([(p["platform"], p["id"], p["state"], p["label"])
                    for p in phones])
        if sig == self.last_sig:
            # nothing changed: leave the screen alone (no flicker)
            self.root.after(2500, lambda: self.poll_phones(gen))
            return
        self.last_sig = sig
        for w in self.ph_list.winfo_children():
            w.destroy()
        if not phones:
            self.lbl(self.ph_list, "Waiting for a device... plug it in "
                     "with a USB cable.", 14, fg=MUTED).pack(anchor="w",
                                                         pady=self.px(10))
        for p in phones:
            r = self.tk.Frame(self.ph_list, bg=CARD2,
                              highlightbackground=BORDER, highlightthickness=1)
            r.pack(fill="x", pady=4)
            self.lbl(r, p["label"], 14, True).pack(side="left",
                                                    padx=self.px(14),
                                                    pady=self.px(10))
            self.lbl(r, p["id"][:28], 10, fg=MUTED).pack(side="left")
            hint = {"ready": ("Ready", OK),
                    "trust": ("Tap Trust / Allow on the device", WARN),
                    "locked": ("Unlock it, then tap Trust", WARN),
                    "recovery": ("Recovery mode - ready to erase", WARN),
                    "dfu": ("DFU mode - ready to erase", WARN),
                    "fastboot": ("Bootloader mode", WARN),
                    "nodebug": ("USB debugging off or screen locked", WARN),
                    "offline": ("Offline - reconnect the cable", BAD)}.get(
                p["state"], (p["state"], WARN))
            self.lbl(r, hint[0], 12, True, fg=hint[1]).pack(
                side="left", padx=self.px(20))
            if p["state"] == "ready":
                self.btn(r, "Use this phone",
                         lambda p=p: self.pick_phone(p)).pack(
                    side="right", padx=self.px(10), pady=6)
            if p["state"] != "ready" and p["state"] != "offline":
                self.btn(r, "Passcode unknown",
                         lambda p=p: self.pick_phone(p, locked=True),
                         "danger").pack(side="right", padx=self.px(10),
                                        pady=6)
            if p["platform"] == "ios" and p["state"] in ("trust", "locked"):
                self.btn(r, "Ask to trust", lambda p=p: self.bg(
                    lambda: core.pair_ios(p["id"]), lambda r: None),
                    "ghost").pack(side="right", padx=self.px(10), pady=6)
        self.root.after(2500, lambda: self.poll_phones(gen))

    def add_manual(self):
        self.pick_phone({"platform": "manual", "id": "manual",
                         "state": "manual", "label": "Device added by hand"},
                        locked=None)

    def pick_phone(self, p, locked=False):
        """locked: True = passcode unknown, None = added by hand (ask)."""
        if not self.v_job.get().strip() or not self.v_asset.get().strip():
            self.set_status("Job ID and Asset ID are needed.", WARN)
            return
        self.polling = False
        self.read_tries = 0
        self.s.update(job_id=self.v_job.get().strip(),
                      asset_id=self.v_asset.get().strip(),
                      location=self.v_loc.get().strip(), phone=p,
                      started=C.now())
        self.say("job %s asset %s device %s %s %s" % (
            self.s["job_id"], self.s["asset_id"], p["platform"], p["id"],
            "PASSCODE UNKNOWN" if locked else
            "added by hand" if locked is None else ""))
        if locked or locked is None:
            self.s["locked"] = bool(locked)
            self.s["manual"] = locked is None
            self.show_device_form()
        else:
            self.show_checks()

    # ---------- device details (locked device / added by hand) ----------
    def show_device_form(self):
        tk = self.tk
        p = self.s["phone"]
        info = self.s["info"] or core.locked_info(p)
        self.s["info"] = info
        manual = self.s.get("manual")
        self.page("checks", "Device details",
                  "Type what is on the device, its box or SIM tray (IMEI: "
                  "dial *#06# or look on the SIM tray / back).",
                  back=self.back_to_job)
        f, c = self.card(self.content)
        f.pack(fill="x")
        grid = tk.Frame(c, bg=CARD)
        grid.pack(anchor="w")
        self.v_kind = tk.StringVar(value=info.get("kind") if info.get("kind")
                                   in core.KINDS else
                                   ("iPhone" if p["platform"] == "ios" else
                                    "Android phone" if p["platform"] ==
                                    "android" else "Apple Watch"))
        self.f_vars = {}
        fields = [("make", "MAKE"), ("model", "MODEL"), ("serial", "SERIAL"),
                  ("imei", "IMEI"), ("colour", "COLOUR"), ("os", "OS VERSION")]
        self.lbl(grid, "TYPE", 10, True, fg=MUTED).grid(row=0, column=0,
                                                        sticky="w")
        self.ttk.Combobox(grid, textvariable=self.v_kind, values=core.KINDS,
                          state="readonly", font=self.F(13), width=22).grid(
            row=1, column=0, sticky="w", padx=(0, self.px(14)),
            pady=(0, self.px(10)))
        for i, (k, lab) in enumerate(fields, start=1):
            v = info.get(k) or ""
            if isinstance(v, list):
                v = ", ".join(v)
            var = tk.StringVar(value=v)
            self.f_vars[k] = var
            r, col = (i // 4) * 2, i % 4
            self.lbl(grid, lab, 10, True, fg=MUTED).grid(row=r, column=col,
                                                         sticky="w")
            self.entry(grid, var, width=22).grid(
                row=r + 1, column=col, sticky="w", padx=(0, self.px(14)),
                pady=(0, self.px(10)), ipady=self.px(4))
        self.v_known = tk.StringVar(value="yes" if manual and not
                                    self.s.get("locked") else "no")
        if manual:
            f2, c2 = self.card(self.content, "Passcode")
            f2.pack(fill="x", pady=(self.px(12), 0))
            for val, txt in (("yes", "I can unlock it - check its Settings "
                              "and run the tests"),
                             ("no", "Passcode unknown - wipe it, then check "
                              "the setup screen (no tests)")):
                tk.Radiobutton(c2, text=txt, variable=self.v_known,
                               value=val, font=self.F(12), fg=TEXT, bg=CARD,
                               selectcolor=CARD2, activebackground=CARD,
                               activeforeground=TEXT, anchor="w").pack(
                    anchor="w")
        else:
            self.lbl(self.content, "Passcode unknown: the device can't be "
                     "tested. It is wiped first, then its locks are checked "
                     "on the setup screen. The report says 'not tested - "
                     "passcode unknown'.", 12, fg=WARN,
                     wraplength=1100).pack(anchor="w", pady=self.px(12))
        if p.get("state") not in (None, "manual"):
            f3, c3 = self.card(self.content, "Fill in automatically")
            f3.pack(fill="x", pady=(self.px(4), 0))
            got = [k for k in ("make", "model", "serial") if info.get(k)]
            self.lbl(c3, ("Read from the device over USB: %s." % ", ".join(
                got)) if got else "The device did not share its details "
                "over USB yet.", 11, fg=OK if got else MUTED,
                wraplength=1100).pack(anchor="w")
            tips = []
            if p["platform"] == "android":
                tips.append("More details (exact model, serial, bootloader "
                            "lock): switch the phone off, hold Power + "
                            "Volume Down until the bootloader screen "
                            "(Pixel, Motorola, OnePlus...), then press "
                            "Read again.")
                tips.append("IMEI: on the lock screen tap Emergency call and "
                            "dial *#06# - or look on the SIM tray / box.")
            else:
                tips.append("More details (exact model, serial, ECID): put "
                            "it in recovery mode, then press Read again.\n" +
                            core.ios_recovery_steps(info.get("kind", ""),
                                                    info.get("model", "")))
                tips.append("IMEI: on the SIM tray, the back of older "
                            "iPhones, or the box.")
            for t in tips:
                self.lbl(c3, "- " + t, 10, fg=TEXT, wraplength=1100).pack(
                    anchor="w", pady=(self.px(3), 0))
            self.btn(c3, "Read again", self.read_again, "ghost").pack(
                anchor="w", pady=(self.px(8), 0))
        self.btn(self.bar_right, "Continue", self.device_form_done).pack(
            side="left", padx=6)

    def read_again(self):
        """Look at the device again (bootloader / recovery mode gives more)
        and fill only the empty fields."""
        info, old = self.s["info"], self.s["phone"]
        for k, var in self.f_vars.items():       # keep what was typed
            v = var.get().strip()
            if v:
                info[k] = [x.strip() for x in v.split(",") if x.strip()] \
                    if k == "imei" else v
        info["kind"] = self.v_kind.get()

        def done(phones):
            if isinstance(phones, Exception):
                phones = []
            same = [x for x in phones if x["id"] == old["id"] or (
                x.get("serial") and x.get("serial") == info.get("serial"))]
            if not same:
                same = [x for x in phones if x["platform"] ==
                        old["platform"] and x["state"] != "ready"]
            if not same:
                self.set_status("Device not found - check the cable.", WARN)
                return
            newp = same[0]
            filled = core.merge_locked_info(info, newp)
            self.s["phone"] = newp
            self.say("read again (%s): filled %s" % (newp["state"], filled))
            self.show_device_form()
            self.set_status(("Filled: %s" % ", ".join(filled)) if filled
                            else "Nothing new - try bootloader / recovery "
                            "mode.", OK if filled else WARN)
        self.set_status("Reading the device again...")
        self.bg(core.list_phones, done)

    def back_to_job(self):
        self.s["info"] = {}
        self.s["locked"] = False
        self.s["manual"] = False
        self.show_job()

    def device_form_done(self):
        info = self.s["info"]
        info["kind"] = self.v_kind.get()
        for k, var in self.f_vars.items():
            v = var.get().strip()
            info[k] = [x.strip() for x in v.split(",") if x.strip()] \
                if k == "imei" else v
        if not info.get("make") and core.kind_platform(info["kind"]) == "ios":
            info["make"] = "Apple"
        if not (info.get("serial") or info.get("imei")):
            self.set_status("Type the serial number or the IMEI.", WARN)
            return
        known = self.v_known.get() == "yes"
        self.s["locked"] = not known
        info["passcode_known"] = known
        p = self.s["phone"]
        if p["platform"] == "manual":
            p["platform"] = core.kind_platform(info["kind"])
            p["usb"] = False
        self.v_imei = self.tk.StringVar(value=", ".join(info.get("imei")
                                                        or []))
        self.say("device details: %s" % {k: info.get(k) for k in (
            "kind", "make", "model", "serial", "imei")})
        if known:
            self.s["checks"] = core.manual_checks(info["kind"])
            self.draw_checks()
        else:
            self.s["checks"] = core.locked_checks(info["kind"])
            for n in WEB_TESTS + ["Battery health", "Charging"]:
                self.s["tests"][n] = {"status": NOT_TESTED,
                                      "note": PASSCODE_NOTE, "auto": True}
            self.show_wipe()

    # ---------- 3. lock checks ----------
    def show_checks(self):
        self.read_tries = 0
        self.page("checks", "Lock checks", "The phone must be free of the "
                  "customer's locks before it is wiped.",
                  back=self.back_to_job)
        self.lbl(self.content, "Reading the phone (all details)...", 14,
                 fg=CYAN).pack(anchor="w")
        self.bg(lambda: core.read_phone(self.s["phone"]), self.checks_read)

    def checks_read(self, res):
        if isinstance(res, Exception):
            self.set_status("Could not read the phone: %s" % res, BAD)
            return
        info, checks = res
        missing = [k for k in ("serial", "model", "os", "battery_level")
                   if not info.get(k) or info.get(k) in ("unknown", "iOS ?",
                                                         "Android ?")]
        if missing and not info.get("error") and self.read_tries < 2:
            # right after Trust / Allow the phone does not give everything
            # yet - wait a moment and read it again
            self.read_tries += 1
            self.say("read %d incomplete (%s) - reading again" % (
                self.read_tries, ", ".join(missing)))
            self.root.after(3000, lambda: self.bg(
                lambda: core.read_phone(self.s["phone"]), self.checks_read))
            return
        self.s["info"], self.s["checks"] = info, checks
        self.say("read: %s" % {k: info.get(k) for k in ("make", "model",
                                                        "serial", "os")})
        self.draw_checks()

    def draw_checks(self):
        tk = self.tk
        if self.s.get("locked") and self.s["wipe"]:
            self.page("checks", "Lock checks on the setup screen",
                      "The device was wiped. Switch it on and go through the "
                      "first setup screens: confirm what it asks for.")
        else:
            self.page("checks", "Lock checks", "The device must be free of "
                      "the customer's locks before it is wiped.",
                      back=self.show_device_form if self.s.get("manual")
                      else self.back_to_job)
        info = self.s["info"]
        if info.get("error"):
            self.lbl(self.content, info["error"], 14, fg=BAD,
                     wraplength=1100).pack(anchor="w")
            self.btn(self.bar_right, "Read again", self.show_checks).pack()
            return
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="both", expand=True)
        f, c = self.card(row, info.get("kind") or "Device")
        f.pack(side="left", fill="y", padx=(0, self.px(14)))
        self.v_imei = tk.StringVar(value=", ".join(info.get("imei") or []))
        self.lbl(c, "%s %s" % (info.get("make", ""), info.get("model", "")),
                 15, True, wraplength=340).pack(anchor="w")
        self.lbl(c, " ".join(x for x in (info.get("os"), (
            "%s GB" % info["storage_gb"]) if info.get("storage_gb") else "",
            info.get("colour")) if x), 11, fg=CYAN, wraplength=340).pack(
            anchor="w", pady=(0, self.px(8)))
        grid = tk.Frame(c, bg=CARD)
        grid.pack(anchor="w", fill="x")
        for i, (k, v) in enumerate((
                ("SERIAL", info.get("serial")),
                ("BATTERY", rpt.battery_text(info)),
                ("STORAGE USED", ("%s / %s GB free" % (
                    info["storage_used_gb"], info["storage_free_gb"]))
                 if info.get("storage_used_gb") is not None else ""),
                ("SIM", info.get("sim") or ""))):
            if not v:
                continue
            self.lbl(grid, k, 9, True, fg=MUTED).grid(
                row=i * 2, column=0, sticky="w")
            self.lbl(grid, v, 12, True, wraplength=340).grid(
                row=i * 2 + 1, column=0, sticky="w", pady=(0, self.px(6)))
        self.lbl(c, "IMEI (dial *#06# if empty)", 9, True, fg=MUTED).pack(
            anchor="w")
        self.entry(c, self.v_imei, width=20).pack(anchor="w",
                                                  ipady=self.px(4))
        for n in info.get("notes") or []:
            self.lbl(c, n, 9, fg=WARN, wraplength=340).pack(anchor="w")
        if info.get("details"):
            self.btn(c, "All details (%d)" % len(info["details"]),
                     self.show_details, "ghost").pack(
                anchor="w", pady=(self.px(10), 0))
        f, c = self.card(row, "Locks")
        f.pack(side="left", fill="both", expand=True)
        for i, ch in enumerate(self.s["checks"]):
            r = tk.Frame(c, bg=CARD2, highlightbackground=BORDER,
                         highlightthickness=1)
            r.pack(fill="x", pady=4)
            col = {"CLEAR": OK, "BLOCKED": BAD}.get(ch["result"], WARN)
            top = tk.Frame(r, bg=CARD2)
            top.pack(fill="x", padx=self.px(12), pady=(self.px(8), 0))
            self.lbl(top, ch["name"], 13, True).pack(side="left")
            self.lbl(top, ch["result"] if ch["result"] != "CHECK" else
                     "CHECK BY HAND", 12, True, fg=col).pack(side="right")
            self.lbl(r, ch.get("detail", ""), 11, fg=MUTED,
                     wraplength=760).pack(anchor="w", padx=self.px(12))
            if ch["result"] != "CLEAR" and ch.get("how"):
                self.lbl(r, ch["how"], 10, fg=TEXT, wraplength=760).pack(
                    anchor="w", padx=self.px(12), pady=(2, 0))
            if ch["result"] == "CHECK":
                b = tk.Frame(r, bg=CARD2)
                b.pack(anchor="w", padx=self.px(12), pady=self.px(6))
                self.btn(b, "Checked - no lock", lambda i=i: self.confirm(
                    i, "CLEAR"), "ok").pack(side="left", padx=(0, 6))
                self.btn(b, "It is locked", lambda i=i: self.confirm(
                    i, "BLOCKED"), "danger").pack(side="left")
            else:
                tk.Frame(r, bg=CARD2, height=self.px(8)).pack()
        overall = core.overall_check(self.s["checks"])
        if self.s.get("locked") or self.s.get("manual"):
            self.after_wipe_buttons(overall)
            return
        self.btn(self.bar_right, "Read again", self.show_checks,
                 "ghost").pack(side="left", padx=6)
        if overall == "BLOCKED":
            path = self.removal_request()
            self.set_status("LOCKED - do not wipe. Removal request saved: %s"
                            % (path or "(could not save)"), BAD)
            self.btn(self.bar_right, "Next device", self.next_phone,
                     "ghost").pack(side="left", padx=6)
        elif overall == "CHECK BY HAND":
            self.set_status("Check the yellow items on the device, then "
                            "confirm each one.", WARN)
        else:
            self.set_status("All clear.", OK)
            self.btn(self.bar_right, "Continue to tests",
                     self.show_tests).pack(side="left", padx=6)

    def show_details(self):
        """Everything read from the device, grouped in sections."""
        info = self.s["info"]
        if self.v_imei.get().strip():
            info["imei"] = [x.strip() for x in self.v_imei.get().split(",")
                            if x.strip()]
        rows = core.details_list(info)
        win = self.popup("Device details")
        self.lbl(win, "%s %s" % (info.get("make", ""), info.get("model", "")),
                 17, True, bg=CARD).pack(anchor="w", padx=self.px(22),
                                         pady=(self.px(14), 2))
        body = self.tk.Frame(win, bg=CARD)
        body.pack(fill="both", padx=self.px(16), pady=self.px(6))
        sections = []
        for sec, lab, val in rows:
            if not sections or sections[-1][0] != sec:
                sections.append((sec, []))
            sections[-1][1].append((lab, val))
        # two columns of section cards, balanced by number of lines
        cols = [self.tk.Frame(body, bg=CARD), self.tk.Frame(body, bg=CARD)]
        for cf in cols:
            cf.pack(side="left", fill="y", anchor="n", padx=self.px(6))
        heights = [0, 0]
        for sec, items in sections:
            ci = 0 if heights[0] <= heights[1] else 1
            heights[ci] += len(items) + 2
            box = self.tk.Frame(cols[ci], bg=CARD2,
                                highlightbackground=BORDER,
                                highlightthickness=1)
            box.pack(fill="x", pady=self.px(4))
            self.lbl(box, sec.upper(), 9, True, fg=CYAN).grid(
                row=0, column=0, columnspan=2, sticky="w",
                padx=self.px(10), pady=(self.px(6), 2))
            for j, (lab, val) in enumerate(items, start=1):
                self.lbl(box, lab, 10, fg=MUTED).grid(
                    row=j, column=0, sticky="nw", padx=(self.px(10), 6))
                self.lbl(box, val, 10, True, wraplength=300).grid(
                    row=j, column=1, sticky="nw", padx=(0, self.px(10)))
            self.tk.Frame(box, bg=CARD2, height=self.px(6)).grid(
                row=len(items) + 1, column=0)
        self.btn(win, "Close", win.destroy).pack(anchor="e", padx=self.px(22),
                                                 pady=self.px(12))
        win.lift()
        win.focus_force()

    def after_wipe_buttons(self, overall):
        """Locked / hand-added devices: checks are confirmed by the
        technician (locked: on the setup screen after the wipe)."""
        wiped = bool(self.s["wipe"])
        if overall == "BLOCKED":
            path = self.removal_request()
            self.set_status("LOCKED - removal request saved: %s" % (
                path or "(could not save)"), BAD)
        elif overall == "CHECK BY HAND":
            self.set_status(("Look at the setup screen and confirm each "
                             "item." if wiped else "Check each item in the "
                             "device's Settings and confirm it."), WARN)
        else:
            self.set_status("All clear.", OK)
        if overall == "CHECK BY HAND":
            return
        if wiped:
            self.btn(self.bar_right, "Continue to report",
                     self.show_report).pack(side="left", padx=6)
        elif overall == "BLOCKED":
            self.btn(self.bar_right, "Next device", self.next_phone,
                     "ghost").pack(side="left", padx=6)
        else:
            self.btn(self.bar_right, "Continue to tests",
                     self.show_tests).pack(side="left", padx=6)

    def confirm(self, i, result):
        ch = self.s["checks"][i]
        ch["result"] = result
        ch["confirmed_by"] = self.tech
        ch["detail"] = (ch.get("detail", "") + " - checked by hand" +
                        (" on the setup screen after the wipe"
                         if self.s.get("locked") and self.s["wipe"] else "") +
                        ": " + ("no lock" if result == "CLEAR" else
                                "LOCKED"))
        self.say("%s confirmed %s by %s" % (ch["name"], result, self.tech))
        self.draw_checks()

    def removal_request(self):
        info = self.s["info"]
        ident = (", ".join(info.get("imei") or []) or info.get("serial") or
                 "unknown")
        lines = ["Subject: Device removal needed - %s %s (job %s)" % (
            info.get("model", ""), ident, self.s["job_id"]), "",
            "Hello,", "", "We received the phone below for secure erasure "
            "and reuse. It is still linked to your organisation or an "
            "account, so we cannot process it yet:", "",
            "  Model     : %s %s" % (info.get("make", ""),
                                     info.get("model", "")),
            "  Serial    : %s" % info.get("serial", "-"),
            "  IMEI      : %s" % ident, "  Our job   : %s" % self.s["job_id"],
            "  Asset ID  : %s" % self.s["asset_id"], "", "What we found:"]
        for ch in self.s["checks"]:
            if ch["result"] == "BLOCKED":
                lines += ["  - %s: %s" % (ch["name"], ch.get("detail", "")),
                          "    %s" % ch.get("how", "")]
        lines += ["", "Please reply when this is done.", "", "Thank you"]
        try:
            d = os.path.join(self.out_dir, "requests")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "PHONE_REMOVAL_REQUEST_%s_%s.txt" % (
                C.safe_name(ident.split(",")[0]),
                C.now().strftime("%Y%m%d-%H%M")))
            with open(p, "w") as f:
                f.write("\n".join(lines) + "\n")
            return p
        except Exception:
            return ""

    # ---------- 4. tests ----------
    def show_tests(self):
        tk = self.tk
        info, p = self.s["info"], self.s["phone"]
        if self.v_imei.get().strip():
            info["imei"] = [x.strip() for x in self.v_imei.get().split(",")
                            if x.strip()]
        usb_android = p["platform"] == "android" and p.get("state") == \
            "ready" and p.get("usb") is not False
        self.page("tests", "Component tests",
                  "The tests run on the phone, in its web browser. "
                  + ("The test page opens on the phone over the USB cable."
                     if usb_android else
                     "Join the phone to the same network as the station "
                     "(or the station Wi-Fi), then scan the QR code."),
                  back=self.draw_checks)
        self.station_results()
        hs = net.hotspot_info()
        ip = hs[2] if hs and hs[2] else None
        err = ""
        if not self.server:
            self.server = TestServer("%s / %s" % (self.s["job_id"],
                                                  self.s["asset_id"]))
            try:
                self.server.start(ip)
            except Exception as e:
                self.server = None
                err = str(e)
        else:
            from test_server import station_ip
            self.server.set_ip(ip or station_ip())
        url = self.server.url if self.server else ""
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="both", expand=True)
        f, c = self.card(row, "Open the test page on the phone")
        f.pack(side="left", fill="y", padx=(0, self.px(14)))
        if err:
            self.lbl(c, "The test page could not start: %s" % err, 11,
                     fg=BAD, wraplength=330).pack(anchor="w")
        elif usb_android:
            self.u_msg = self.lbl(c, "Installing the PhoneSeal app over USB...", 12,
                                  True, fg=CYAN, wraplength=330)
            self.u_msg.pack(anchor="w")
            self.lbl(c, "The PhoneSeal app is installed and opens on the "
                     "phone. Follow the tests there. (If it opens in the "
                     "browser instead: tap Advanced > Proceed once.)", 10,
                     fg=MUTED, wraplength=330).pack(
                anchor="w", pady=(self.px(6), 0))
            self.btn(c, "Open it again on the phone", self.open_usb,
                     "ghost").pack(anchor="w", pady=(self.px(8), 0))
            self.open_usb()
        if not err and url and not usb_android:
            if hs:
                self.lbl(c, "1. Join the station Wi-Fi: scan this", 11, True,
                         fg=CYAN).pack(anchor="w")
                try:
                    qr_png(net.wifi_qr_text(hs[0], hs[1]),
                           "/tmp/phoneseal_wifi.png", 4)
                    self.wifi_img = tk.PhotoImage(
                        file="/tmp/phoneseal_wifi.png")
                    tk.Label(c, image=self.wifi_img, bg="white").pack(
                        pady=self.px(4))
                except Exception:
                    pass
                self.lbl(c, "Wi-Fi %s   password %s" % (hs[0], hs[1]), 10,
                         fg=TEXT, wraplength=330).pack(anchor="w")
                self.lbl(c, "2. Then scan this to open the tests", 11, True,
                         fg=CYAN).pack(anchor="w", pady=(self.px(8), 0))
            try:
                qr_png(url, "/tmp/phoneseal_qr.png", 4 if hs else 7)
                self.qr_img = tk.PhotoImage(file="/tmp/phoneseal_qr.png")
                tk.Label(c, image=self.qr_img, bg="white").pack(
                    pady=self.px(4))
            except Exception:
                pass
            self.lbl(c, url, 9, fg=CYAN, wraplength=330).pack(anchor="w")
            self.lbl(c, "The phone warns about the certificate once: iPhone "
                     "Show Details > visit this website; Android Advanced > "
                     "Proceed.", 9, fg=MUTED, wraplength=330).pack(
                anchor="w", pady=(self.px(4), 0))
        elif not err and not usb_android:
            self.lbl(c, "No network yet.", 14, True, fg=WARN).pack(anchor="w")
            self.lbl(c, "Press Network: pick the Wi-Fi and type its password, "
                     "or start the station Wi-Fi. Or test by hand.", 11,
                     fg=TEXT, wraplength=330).pack(anchor="w",
                                                   pady=self.px(6))
            self.btn(c, "Network", self.network_window).pack(
                anchor="w", pady=(self.px(4), 0))
        self.btn(c, "Test by hand", self.test_by_hand, "ghost").pack(
            anchor="w", pady=(self.px(10), 0))
        f, c = self.card(row, "Results (tap one to change it)")
        f.pack(side="left", fill="both", expand=True)
        self.res_box = tk.Frame(c, bg=CARD)
        self.res_box.pack(fill="both", expand=True)
        self.build_results()
        self.btn(self.bar_right, "Finish tests", self.finish_tests).pack(
            side="left", padx=6)
        gen = self.res_gen
        self.refresh_results(gen)

    def open_usb(self):
        p = self.s["phone"]
        if not self.server:
            return

        def done(r):
            ok, txt = r if not isinstance(r, Exception) else (False, str(r))
            try:
                self.u_msg.configure(text=txt,
                                     fg=OK if ok else WARN)
            except Exception:
                pass
        self.bg(lambda: net.android_usb_open(p["id"], self.server.path),
                done)

    def test_by_hand(self):
        self.set_status("Test each item on the phone yourself, then tap its "
                        "result on the right to set PASS / FAIL.", CYAN)

    def wifi(self):
        self.network_window()

    def station_results(self):
        info, t = self.s["info"], self.s["tests"]
        if self.s["phone"].get("usb") is False:
            for n in ("Battery health", "Charging"):
                t.setdefault(n, {"status": "CHECK", "note": "no USB - check "
                                 "in Settings > Battery and tap to set",
                                 "auto": True})
        h = info.get("battery_health_pct")
        if "Battery health" not in t:
            if h is None:
                t["Battery health"] = {"status": "CHECK", "note": "not "
                                       "readable - check in Settings > "
                                       "Battery", "auto": True}
            else:
                t["Battery health"] = {"status": "PASS" if h >= 80 else
                                       "WARN", "note": "%s%%%s" % (
                                           h, "" if h >= 80 else
                                           " - below 80%, service "
                                           "recommended"), "auto": True}
        if "Charging" not in t:
            ch = str(info.get("battery_charging", "")).lower()
            t["Charging"] = {"status": "PASS" if ch in ("true", "1") else
                             "CHECK", "note": "charging from the station"
                             if ch in ("true", "1") else
                             "not charging - check cable / port",
                             "auto": True}

    def test_names(self):
        return WEB_TESTS + ["Battery health", "Charging"]

    def build_results(self):
        """The result rows are made ONCE; refresh only changes the text."""
        self.res_labels = {}
        for i, n in enumerate(self.test_names()):
            fr = self.tk.Frame(self.res_box, bg=CARD2)
            fr.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=3)
            self.lbl(fr, n, 12, True).pack(side="left", padx=self.px(10),
                                           pady=self.px(6))
            lab = self.lbl(fr, "", 12, True, cursor="hand2")
            lab.pack(side="right", padx=self.px(10))
            lab.bind("<Button-1>", lambda e, n=n: self.change_result(n))
            fr.bind("<Button-1>", lambda e, n=n: self.change_result(n))
            self.res_labels[n] = lab
        self.res_box.grid_columnconfigure(0, weight=1)
        self.res_box.grid_columnconfigure(1, weight=1)

    def refresh_results(self, gen=None):
        if gen is not None and gen != self.res_gen:
            return                     # page changed: this loop ends
        if not getattr(self, "res_labels", None):
            return
        if self.server:
            for k, v in self.server.results.items():
                if not self.s["tests"].get(k, {}).get("set_by"):
                    self.s["tests"][k] = dict(v)
        done = 0
        for n, lab in self.res_labels.items():
            r = self.s["tests"].get(n)
            st = r["status"] if r else "waiting"
            if r and st in ("PASS", "FAIL", "N/A"):
                done += 1
            col = {"PASS": OK, "FAIL": BAD, "N/A": MUTED, "waiting": DIM,
                   NOT_TESTED: MUTED}.get(st, WARN)
            txt = st if st != "SKIP" else "skipped"
            if lab.cget("text") != txt or lab.cget("fg") != col:
                lab.configure(text=txt, fg=col)
        if not str(self.status.cget("text")).startswith("Test each item"):
            self.set_status("%d of %d results in" % (done,
                                                      len(self.res_labels)))
        if gen is not None:
            self.root.after(1000, lambda: self.refresh_results(gen))

    def change_result(self, name):
        tk = self.tk
        win = self.popup(name)
        self.lbl(win, name, 16, True, bg=CARD).pack(padx=20, pady=(16, 8))
        bf = tk.Frame(win, bg=CARD)
        bf.pack(padx=20, pady=(0, 16))

        def set_(st):
            self.s["tests"][name] = {"status": st, "note": "set by %s" %
                                     self.tech, "auto": False,
                                     "set_by": self.tech,
                                     "time": time.strftime("%H:%M:%S")}
            win.destroy()
            self.refresh_results()
        self.btn(bf, "PASS", lambda: set_("PASS"), "ok").pack(side="left",
                                                              padx=4)
        self.btn(bf, "FAIL", lambda: set_("FAIL"), "danger").pack(
            side="left", padx=4)
        self.btn(bf, "Not fitted", lambda: set_("N/A"), "ghost").pack(
            side="left", padx=4)
        self.btn(bf, "Cancel", win.destroy, "ghost").pack(side="left",
                                                          padx=4)
        win.lift()
        win.focus_force()

    def finish_tests(self):
        if self.server:
            for k, v in self.server.results.items():
                if not self.s["tests"].get(k, {}).get("set_by"):
                    self.s["tests"][k] = dict(v)
            self.server.stop()
            self.server = None
        p = self.s["phone"]
        if p.get("platform") == "android" and p.get("usb") is not False:
            # take the test app off the phone again (the wipe also removes it)
            self.bg(lambda: net.android_app_remove(p["id"]), lambda r: None)
        self.say("tests: %s" % {k: v["status"] for k, v in
                                self.s["tests"].items()})
        self.show_wipe()

    # ---------- 5. wipe ----------
    def show_wipe(self):
        tk = self.tk
        p, info = self.s["phone"], self.s["info"]
        back = None
        if not self.s["wipe"]:
            back = self.show_device_form if self.s.get("locked") else \
                self.show_tests
        self.page("wipe", "Wipe", "Erases everything on the phone. The "
                  "phone's storage is encrypted, so this destroys the "
                  "keys and the data cannot be read.", back=back)
        f, c = self.card(self.content, "Method")
        f.pack(fill="x")
        methods = core.wipe_methods(p, info, self.s.get("locked") or
                                    p.get("usb") is False)
        self.w_methods = dict(methods)
        self.v_method = tk.StringVar(value=methods[0][0])
        for k, txt in methods:
            tk.Radiobutton(c, text=txt, variable=self.v_method, value=k,
                           font=self.F(12), fg=TEXT, bg=CARD,
                           selectcolor=CARD2, activebackground=CARD,
                           activeforeground=TEXT, anchor="w",
                           wraplength=self.px(1000), justify="left").pack(
                anchor="w", pady=2)
        if any(k == "to_recovery" for k, _ in methods):
            self.lbl(c, "Passcode unknown: put it in recovery mode with the "
                     "cable in this station.\n" + core.ios_recovery_steps(
                         info.get("kind", ""), info.get("model", "")), 11,
                     fg=WARN, wraplength=1000).pack(anchor="w", pady=4)
            self.btn(c, "It shows the recovery screen - find it",
                     self.find_recovery, "ghost").pack(anchor="w", pady=4)
        elif any(k in ("guided", "manual", "manual_restore", "settings")
                 for k, _ in methods):
            self.lbl(c, core.manual_wipe_steps(methods[0][0], p, info), 11,
                     fg=WARN, wraplength=1000).pack(anchor="w", pady=4)
        if any(k in ("restore", "restore_recovery") for k, _ in methods):
            wd, free = core.ipsw_workdir([os.path.join(self.out_dir,
                                                       "ios-downloads")])
            self.ipsw_dir = wd
            self.lbl(c, "iOS download folder: %s (%s GB free%s)" % (
                wd, free, "" if free >= 9 else " - may be too small: use a "
                "bigger USB B or restore on another computer"), 10,
                fg=MUTED if free >= 9 else WARN, wraplength=1000).pack(
                anchor="w", pady=2)
        if p["platform"] == "android" and str(info.get("encrypted")) not in \
                ("encrypted", "", "None") and not self.s.get("locked") and \
                p.get("usb") is not False:
            self.lbl(c, "Warning: the phone does not report encryption "
                     "(%s). Ask a manager before resetting." %
                     info.get("encrypted"), 11, fg=WARN,
                     wraplength=1000).pack(anchor="w", pady=4)
        f, c = self.card(self.content, "Confirm")
        f.pack(fill="x", pady=self.px(12))
        ident = (info.get("imei") or [""])[0] or info.get("serial") or "WIPE"
        ident = ident.strip() or "WIPE"
        self.need = ident[-4:].upper()
        self.lbl(c, "Type the last 4 characters of %s to allow the wipe:" %
                 ident, 12, fg=WARN).pack(anchor="w")
        self.v_conf = tk.StringVar()
        self.entry(c, self.v_conf, width=10).pack(anchor="w", pady=6,
                                                  ipady=self.px(4))
        self.w_go = self.btn(c, "Wipe now", self.do_wipe, "danger")
        self.w_go.pack(anchor="w")
        self.w_msg = self.lbl(self.content, "", 13, True, fg=CYAN,
                              wraplength=1100)
        self.w_msg.pack(anchor="w", pady=self.px(8))
        self.btn(self.bar_right, "Skip wipe (report: NOT wiped)",
                 self.skip_wipe, "ghost").pack(side="left", padx=6)

    def find_recovery(self):
        """The locked iPhone / iPad was put in recovery mode: pick it up."""
        def done(phones):
            if isinstance(phones, Exception):
                phones = []
            rec = [x for x in phones if x["state"] in ("recovery", "dfu")]
            if not rec:
                self.set_status("No device in recovery mode yet - follow "
                                "the steps, keep the cable in.", WARN)
                return
            p = rec[0]
            self.s["phone"] = p
            info = self.s["info"]
            if p.get("serial") and not info.get("serial"):
                info["serial"] = p["serial"]
            if p.get("product") and not info.get("model_id"):
                info["model_id"] = p["product"]
                info["model"] = info.get("model") or core.apple_name(
                    p["product"])
            self.say("found in %s mode: %s" % (p["state"], p.get("label")))
            self.show_wipe()
        self.set_status("Looking for the device in recovery mode...")
        self.bg(core.list_phones, done)

    def skip_wipe(self):
        self.s["wipe"] = {"state": "NOT WIPED", "method": "-",
                          "verify_note": "skipped by %s" % self.tech}
        self.show_report()

    def do_wipe(self):
        if self.v_conf.get().strip().upper() != self.need:
            self.set_status("The 4 characters do not match.", WARN)
            return
        p, m = self.s["phone"], self.v_method.get()
        if m == "to_recovery":
            self.find_recovery()
            return
        self.w_go.configure(state="disabled")
        self.s["wipe"] = {"state": "RUNNING", "started":
                          C.now().strftime("%H:%M:%S")}
        self.wipe_t0 = C.now()
        self.say("wipe start %s %s" % (p["platform"], m))
        self.w_msg.configure(text="Working... do not unplug the phone.",
                             fg=CYAN)
        info = self.s["info"]
        if m in ("manual", "manual_restore", "guided", "settings"):
            self.wipe_started({"ok": None, "method": self.w_methods.get(
                m, m), "steps": core.manual_wipe_steps(m, p, info)})
        elif p["platform"] == "ios":
            wd = getattr(self, "ipsw_dir", None)
            self.bg(lambda: core.ios_wipe(p["id"], m, log=self.say,
                                          ecid=p.get("ecid", ""),
                                          workdir=wd), self.wipe_started)
        else:
            self.bg(lambda: core.android_wipe(p["id"], log=self.say),
                    self.wipe_started)

    def wipe_started(self, res):
        if isinstance(res, Exception):
            res = {"ok": False, "method": "?", "note": str(res)}
        self.s["wipe"]["method"] = res.get("method", "")
        self.say("wipe step: %s" % res)
        p = self.s["phone"]
        if res.get("ok") is False:
            self.wipe_done("FAILED", res.get("note", "") or "the wipe "
                           "command failed")
            return
        if res.get("ok") is True and p["platform"] == "ios":
            self.w_msg.configure(text="Erase started - waiting for the "
                                 "device to restart on the Hello screen...")
            udid = None if p["state"] in ("recovery", "dfu") else p["id"]
            serial = self.s["info"].get("serial", "")
            self.bg(lambda: core.ios_verify_wiped(udid, 900, log=self.say,
                                                  serial=serial),
                    lambda r: self.wipe_done(
                        "WIPED" if r[0] else "FAILED", r[1]))
            return
        # technician step (manual iPhone erase, Android recovery)
        txt = res.get("steps") or core.manual_wipe_steps(
            "manual" if p["platform"] == "ios" else "recovery", p,
            self.s["info"])
        self.w_msg.configure(text=txt + "\nWhen the phone shows the Hello / "
                             "Welcome setup screen, press the green button.",
                             fg=WARN)
        self.btn(self.bar_right, "Phone shows the setup screen",
                 lambda: self.wipe_done(
                     "WIPED", "setup screen confirmed by %s" % self.tech),
                 "ok").pack(side="left", padx=6)
        self.btn(self.bar_right, "Wipe failed", lambda: self.wipe_done(
            "FAILED", "reported by %s" % self.tech), "danger").pack(
            side="left", padx=6)

    def wipe_done(self, state, note):
        w = self.s["wipe"]
        w.update(state=state, verify_note=note,
                 finished=C.now().strftime("%H:%M:%S"),
                 duration=C.fmt_dur(self.wipe_t0, C.now()))
        self.say("wipe %s: %s" % (state, note))
        if self.s.get("locked") and state == "WIPED":
            # locks of a locked device are only visible on the setup screen
            self.draw_checks()
            return
        self.show_report()

    # ---------- 6. report ----------
    def show_report(self):
        tk = self.tk
        self.page("report", "Report", "Add the condition, then save the "
                  "signed certificate.")
        f, c = self.card(self.content, "Condition")
        f.pack(fill="x")
        self.v_grade = tk.StringVar(value=GRADES[1])
        self.ttk.Combobox(c, textvariable=self.v_grade, values=GRADES,
                          state="readonly", font=self.F(13), width=28).pack(
            anchor="w", pady=4)
        self.lbl(c, "NOTES", 10, True, fg=MUTED).pack(anchor="w",
                                                     pady=(8, 0))
        self.v_notes = tk.StringVar()
        self.entry(c, self.v_notes, width=70).pack(anchor="w",
                                                   ipady=self.px(4))
        self.r_box = tk.Frame(self.content, bg=BG)
        self.r_box.pack(fill="both", expand=True, pady=self.px(12))
        self.btn(self.bar_right, "Save report", self.save_report).pack(
            side="left", padx=6)

    def build_rep(self):
        info, s = self.s["info"], self.s
        tests = []
        for n in WEB_TESTS + ["Battery health", "Charging"]:
            r = s["tests"].get(n)
            if not r:
                tests.append({"component": n, "status": "WARN",
                              "notes": ["Not tested"]})
            else:
                st = r["status"]
                if st in ("SKIP", "CHECK"):
                    st = "WARN"
                if st == NOT_TESTED and not r.get("note"):
                    r["note"] = PASSCODE_NOTE
                when = r.get("time") or ""
                by = r.get("set_by") or self.tech
                tests.append({"component": n, "status": st,
                              "notes": [x for x in (r.get("note", ""), (
                                  "%s (%s)" % (when, by)) if when else
                                  "(%s)" % by) if x],
                              "time": when, "by": by})
        fin = C.now()
        rep = {"tool": "phone_window.py", "version": VERSION,
               "job_id": s["job_id"], "asset_id": s["asset_id"],
               "technician": self.tech, "location": s["location"],
               "started": C.fmt_time(s["started"]),
               "finished": fin.strftime("%Y-%m-%d %H:%M:%S"),
               "duration": C.fmt_dur(s["started"], fin),
               "device": dict({k: v for k, v in info.items()
                               if k != "raw_keys"},
                              details=core.details_list(info)),
               "checks": s["checks"], "wipe": s["wipe"], "tests": tests,
               "observations": {"grade": self.v_grade.get(),
                                "notes": self.v_notes.get().strip()},
               "passcode_unknown": bool(s.get("locked")),
               "company": rpt.company_name(self.out_dir),
               "test_mode": False}
        rep["overall"], rep["reasons"] = rpt.compute_overall(rep)
        rep["erasure_id"] = rpt.erasure_id(rep)
        return rep

    def save_report(self):
        rep = self.build_rep()
        errs = []
        saved = rpt.save_all(rep, self.out_dir, self.persistent, self.log,
                             errs)
        for w in self.r_box.winfo_children():
            w.destroy()
        col = {"PASS": OKD, "FAIL": BADD}.get(rep["overall"], "#B7791F")
        self.tk.Label(self.r_box, text=rep["overall"], font=self.F(40, True),
                      fg="white", bg=col, padx=self.px(40),
                      pady=self.px(10)).pack(anchor="w")
        for r in rep["reasons"][:6]:
            self.lbl(self.r_box, "- " + r, 12, fg=TEXT).pack(anchor="w")
        pdf = [x for x in saved if x.endswith(".pdf")]
        self.lbl(self.r_box, ("Saved and digitally signed: %s" % pdf[0])
                 if pdf and (rep.get("integrity") or {}).get("signed") else
                 ("Saved (NOT signed): %s" % (pdf[0] if pdf else saved))
                 if saved else "Report NOT saved - %s" % (
                     errs[-1] if errs else "unknown error"), 11,
                 fg=OK if pdf else BAD, wraplength=1100).pack(
            anchor="w", pady=self.px(8))
        if not self.persistent or (saved and saved[0].startswith("/tmp")):
            self.lbl(self.r_box, "No USB stick: the report is only in "
                     "memory and is lost at power off. %s" % (
                         errs[-1] if errs else ""), 11, fg=BAD,
                     wraplength=1100).pack(anchor="w")
        for w in self.bar_right.winfo_children():
            w.destroy()
        self.btn(self.bar_right, "Next device", self.next_phone).pack(
            side="left", padx=6)

    def next_phone(self):
        if self.server:
            self.server.stop()
            self.server = None
        self.reset_job()
        self.log = ["technician %s" % self.tech]
        self.show_job()

    def quit(self):
        if self.server:
            self.server.stop()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="ITAD PhoneSeal window")
    ap.add_argument("--windowed", action="store_true")
    a = ap.parse_args()
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Run as root: sudo python3 phone_window.py")
        sys.exit(3)
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    App(tk, ttk, root, a.windowed)
    root.mainloop()


if __name__ == "__main__":
    main()
