#!/usr/bin/env python3
"""
netwin.py - ITAD network window (Wi-Fi list + password), shared by
LaptopSeal, PhoneSeal and SwitchSeal (v1.1.0).
v1.1.0: ONE window for all tools. PhoneSeal opens it with hotspot=True,
        which adds the "station Wi-Fi" part (start / stop).
v1.0.1: when no Wi-Fi is found the window says the real reason.

    from netwin import NetworkWindow, StatusPoller
    NetworkWindow(tk, root, font=F, px=P)          # opens the window
    NetworkWindow(tk, root, hotspot=True)           # + station Wi-Fi
    StatusPoller(root, label, prefix="Network: ")   # live status label

Uses net.py (NetworkManager / nmcli). Never raises: errors are shown in
the window.
"""
import queue
import subprocess
import threading

import net

BG, CARD, CARD2 = "#0B1F40", "#0E2448", "#12305C"
BORDER, TEXT, MUTED = "#2B5FA8", "#EAF2FF", "#8EA6C8"
BLUE, CYAN, OK, BAD, WARN = "#1E7BFF", "#38BDF8", "#34D399", "#F87171", \
    "#FBBF24"


def _default_font(size, bold=False):
    return ("DejaVu Sans", int(size), "bold" if bold else "normal")


class _Worker:
    """Runs slow nmcli calls in a thread; results come back in the Tk
    thread (Tk must only be used from one thread)."""

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self._pump()

    def _pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        try:
            self.root.after(150, self._pump)
        except Exception:
            pass

    def run(self, work, done):
        def t():
            try:
                r = work()
            except Exception as e:
                r = e
            self.q.put(lambda: done(r))
        threading.Thread(target=t, daemon=True).start()


class StatusPoller:
    """Keeps a label showing the network ('Network: Wi-Fi Office 192...'),
    checked every 5 s, only redrawn when it changes."""

    def __init__(self, root, label, prefix="Network: ", every_ms=5000):
        self.root, self.label, self.prefix = root, label, prefix
        self.every = every_ms
        self.state = "none"
        self.w = _Worker(root)
        self.poll()

    def poll(self):
        def done(r):
            txt, st = ("No network", "none") if isinstance(r, Exception) \
                else r
            self.state = st
            t = self.prefix + txt
            try:
                if self.label.winfo_exists() and self.label.cget("text") != t:
                    self.label.configure(text=t, fg=OK if st == "ok" else
                                         CYAN if st == "hotspot" else WARN)
                self.root.after(self.every, self.poll)
            except Exception:
                pass
        self.w.run(net.summary, done)


class NetworkWindow:
    def __init__(self, tk, root, font=None, px=None, on_change=None,
                 hotspot=False):
        self.tk, self.root = tk, root
        self.hotspot = hotspot
        self.F = font or _default_font
        self.P = px or (lambda n: int(n))
        self.on_change = on_change
        self.nets = []
        self.w = _Worker(root)
        self.build()
        self.refresh_status()
        self.scan()

    # ---- small helpers
    def lbl(self, parent, text, size=11, bold=False, fg=TEXT, bg=CARD,
            wrap=600):
        return self.tk.Label(parent, text=text, font=self.F(size, bold),
                             fg=fg, bg=bg, anchor="w", justify="left",
                             wraplength=self.P(wrap))

    def button(self, parent, text, cmd, kind="primary"):
        bg, fg, act = {"primary": (BLUE, "white", "#2E9BFF"),
                       "ghost": (CARD2, TEXT, "#1A3F75"),
                       "danger": ("#C62F2F", "white", "#E04545")}[kind]
        return self.tk.Button(parent, text=text, command=cmd,
                              font=self.F(11, True), bg=bg, fg=fg,
                              activebackground=act, activeforeground="white",
                              relief="flat", bd=0, padx=self.P(16),
                              pady=self.P(7), cursor="hand2",
                              highlightthickness=0)

    # ---- window
    def build(self):
        tk, P = self.tk, self.P
        win = tk.Toplevel(self.root)
        self.win = win
        win.title("Network")
        win.configure(bg=BG)
        try:
            win.transient(self.root)
            win.attributes("-topmost", True)
        except Exception:
            pass
        head = tk.Frame(win, bg="#07334A")
        head.pack(fill="x")
        self.lbl(head, "Network", 18, True, fg="white", bg="#07334A").pack(
            anchor="w", padx=P(22), pady=(P(12), 0))
        self.lbl(head, "Connect this computer to Wi-Fi or a network cable. "
                 "Needed for reports sent to the workbench and for some "
                 "downloads.", 10, fg="#BFD3F2", bg="#07334A",
                 wrap=640).pack(anchor="w", padx=P(22), pady=(0, P(12)))
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=P(18), pady=P(12))
        self.st = self.lbl(body, "Now: checking...", 12, True, fg=CYAN,
                           bg=BG)
        self.st.pack(anchor="w", pady=(0, P(8)))
        card = tk.Frame(body, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="both", expand=True, padx=P(16), pady=P(12))
        self.lbl(inner, "WI-FI NETWORKS (tap one)", 9, True, fg=CYAN).pack(
            anchor="w")
        self.lb = tk.Listbox(inner, font=self.F(13), height=7, bg=CARD2,
                             fg=TEXT, selectbackground=BLUE,
                             selectforeground="white", highlightthickness=0,
                             relief="flat", activestyle="none")
        self.lb.pack(fill="x", pady=(P(4), P(8)))
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        self.lbl(row, "PASSWORD", 9, True, fg=MUTED).pack(side="left")
        self.v_pw = tk.StringVar()
        self.pw = tk.Entry(row, textvariable=self.v_pw, show="•",
                           font=self.F(13), bg=CARD2, fg=TEXT,
                           insertbackground=TEXT, relief="flat",
                           highlightthickness=1, highlightbackground=BORDER,
                           highlightcolor=CYAN, width=24)
        self.pw.pack(side="left", padx=P(10), ipady=P(4))
        self.v_show = tk.IntVar(value=0)
        tk.Checkbutton(row, text="show", variable=self.v_show,
                       command=lambda: self.pw.configure(
                           show="" if self.v_show.get() else "•"),
                       font=self.F(10), fg=MUTED, bg=CARD,
                       selectcolor=CARD2, activebackground=CARD,
                       activeforeground=TEXT).pack(side="left")
        self.msg = self.lbl(inner, "", 11, fg=MUTED)
        self.msg.pack(anchor="w", pady=(P(8), 0))
        bf = tk.Frame(inner, bg=CARD)
        bf.pack(anchor="w", pady=(P(8), 0))
        self.button(bf, "Connect", self.connect).pack(side="left")
        self.button(bf, "Scan again", self.scan, "ghost").pack(
            side="left", padx=P(6))
        self.button(bf, "Disconnect Wi-Fi", self.disconnect, "ghost").pack(
            side="left")
        if self.hotspot:
            self.build_hotspot(body)
        foot = tk.Frame(win, bg=BG)
        foot.pack(fill="x", padx=P(18), pady=(0, P(14)))
        self.button(foot, "Close", win.destroy).pack(side="right")
        self.button(foot, "Cable / advanced settings", self.advanced,
                    "ghost").pack(side="left")
        self.lb.bind("<<ListboxSelect>>", lambda e: self.pw.focus_set())
        self.pw.bind("<Return>", lambda e: self.connect())
        # in the middle of the screen
        try:
            win.update_idletasks()
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            x = max(0, (win.winfo_screenwidth() - w) // 2)
            y = max(0, (win.winfo_screenheight() - h) // 3)
            win.geometry("+%d+%d" % (x, y))
        except Exception:
            pass
        win.lift()
        win.after(150, lambda: (win.lift(), win.focus_force()))

    def build_hotspot(self, body):
        """PhoneSeal: the station makes its own Wi-Fi for the phones."""
        tk, P = self.tk, self.P
        card = tk.Frame(body, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x", pady=(P(10), 0))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=P(16), pady=P(12))
        self.lbl(inner, "OR: STATION WI-FI (no router needed)", 9, True,
                 fg=CYAN).pack(anchor="w")
        self.lbl(inner, "The station makes its own Wi-Fi. The phone joins "
                 "it by scanning the QR code on the test page. While it is "
                 "on, the Wi-Fi list above stays empty.", 10,
                 fg=MUTED).pack(anchor="w", pady=(P(2), 0))
        self.hs_msg = self.lbl(inner, "", 11, fg=MUTED)
        self.hs_msg.pack(anchor="w", pady=(P(4), 0))
        bf = tk.Frame(inner, bg=CARD)
        bf.pack(anchor="w", pady=(P(6), 0))
        self.button(bf, "Start station Wi-Fi", self.hs_start).pack(
            side="left")
        self.button(bf, "Stop it", self.hs_stop, "ghost").pack(
            side="left", padx=P(6))

    def hs_say(self, r):
        ok, text = r if not isinstance(r, Exception) else (False, str(r))
        if self.alive():
            self.hs_msg.configure(text=text, fg=OK if ok else BAD)
        self.refresh_status()
        if ok and self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def hs_start(self):
        self.hs_msg.configure(text="Starting the station Wi-Fi...", fg=MUTED)
        self.w.run(lambda: tuple(net.hotspot_start()[:2]), self.hs_say)

    def hs_stop(self):
        self.hs_msg.configure(text="Stopping...", fg=MUTED)

        def work():
            net.hotspot_stop()
            return True, "Station Wi-Fi off"

        def done(r):
            self.hs_say(r)
            self.scan_later()
        self.w.run(work, done)

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def say(self, text, colour=MUTED):
        if self.alive():
            self.msg.configure(text=text, fg=colour)

    # ---- actions
    def refresh_status(self):
        def done(r):
            if self.alive() and not isinstance(r, Exception):
                self.st.configure(text="Now: %s" % r[0],
                                  fg=OK if r[1] == "ok" else
                                  CYAN if r[1] == "hotspot" else WARN)
        self.w.run(net.summary, done)

    def scan(self):
        self.say("Looking for Wi-Fi networks (up to 20 seconds)...")
        self.lb.delete(0, "end")
        self.lb.insert("end", "  searching...")

        def done(r):
            if not self.alive():
                return
            self.nets = [] if isinstance(r, Exception) else r
            self.lb.delete(0, "end")
            for n in self.nets:
                self.lb.insert("end", "%s%s   %d%%%s" % (
                    "* " if n["in_use"] else "  ", n["ssid"], n["signal"],
                    "   (password)" if n["secure"] else "   (open)"))
            if self.nets:
                n = len(self.nets)
                self.say("%d network%s found. * = connected now." % (
                    n, "" if n == 1 else "s"))
            else:
                self.lb.insert("end", "  (no Wi-Fi networks found)")
                self.say("No Wi-Fi found - checking why...", WARN)
                self.w.run(net.wifi_problem, self.show_problem)
        self.w.run(net.scan, done)

    def show_problem(self, r):
        text = "No Wi-Fi found." if isinstance(r, Exception) else r
        self.say(text, WARN)

    def connect(self):
        sel = self.lb.curselection()
        if not sel:
            self.say("Tap a network in the list first.", WARN)
            return
        if sel[0] >= len(self.nets):
            self.say("No Wi-Fi network to connect to.", WARN)
            return
        n = self.nets[sel[0]]
        if n["secure"] and not self.v_pw.get():
            self.say("Type the Wi-Fi password first.", WARN)
            self.pw.focus_set()
            return
        self.say("Connecting to %s..." % n["ssid"])
        self.w.run(lambda: net.connect(n["ssid"], self.v_pw.get()),
                   self.after_change)

    def disconnect(self):
        dev = net.wifi_device()
        if not dev:
            self.say("No Wi-Fi card.", WARN)
            return
        self.w.run(lambda: (net.run(["nmcli", "device", "disconnect", dev],
                                    20)[0] == 0, "Wi-Fi disconnected"),
                   self.after_change)

    def after_change(self, r):
        ok, text = r if not isinstance(r, Exception) else (False, str(r))
        self.say(text, OK if ok else BAD)
        if ok:
            self.v_pw.set("")
        self.refresh_status()
        self.scan_later()
        if ok and self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def scan_later(self):
        try:
            self.root.after(1500, lambda: self.alive() and self.scan())
        except Exception:
            pass

    def advanced(self):
        try:
            subprocess.Popen(["xterm", "-fa", "DejaVu Sans Mono", "-fs",
                              "12", "-e", "nmtui"])
        except Exception as e:
            self.say("Could not open: %s" % e, BAD)
