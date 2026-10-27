#!/usr/bin/env python3
"""
phone_core.py - ITAD PhoneSeal: find phones, read them, lock checks, wipe
(v0.2.0)

v0.2.0: iPad / iPod names, Amazon Fire and other brand-account checks,
        locked devices (passcode unknown): iPhone/iPad recovery and DFU
        mode, Android with USB debugging off, recovery or fastboot mode.

Phones are plugged into the station by USB cable.
  iPhone / iPad : libimobiledevice (idevice_id, ideviceinfo, idevicepair,
                  idevicediagnostics, idevicerestore)
  Android       : adb (USB debugging must be ON on the phone)

Honesty rules used everywhere in this file:
  * A value the phone does not report is "unknown", never guessed.
  * A lock check that cannot be read is "CHECK BY HAND" with the exact
    place to look - never CLEAR.
  * A wipe is only "verified" when the station saw the result itself;
    a step the technician confirmed is marked "confirmed by technician".

Can also be run on its own for testing:
    sudo python3 phone_core.py            (lists phones and everything read)
"""
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time

VERSION = "0.3.1"


def run(cmd, timeout=30, inp=None):
    """(returncode, stdout, stderr) - never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=inp)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "%s not installed" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except Exception as e:
        return 1, "", str(e)


def run_bytes(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, b""


def have(tool):
    return shutil.which(tool) is not None


def luhn_ok(num):
    if not re.fullmatch(r"\d{15}", num or ""):
        return False
    s = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0


# Apple model identifiers -> marketing names (unknown ones are shown as-is)
IPHONE_NAMES = {
    "iPhone10,1": "iPhone 8", "iPhone10,4": "iPhone 8",
    "iPhone10,2": "iPhone 8 Plus", "iPhone10,5": "iPhone 8 Plus",
    "iPhone10,3": "iPhone X", "iPhone10,6": "iPhone X",
    "iPhone11,2": "iPhone XS", "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max", "iPhone11,8": "iPhone XR",
    "iPhone12,1": "iPhone 11", "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max", "iPhone12,8": "iPhone SE (2nd gen)",
    "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13",
    "iPhone14,2": "iPhone 13 Pro", "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,6": "iPhone SE (3rd gen)", "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus", "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max", "iPhone15,4": "iPhone 15",
    "iPhone15,5": "iPhone 15 Plus", "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max", "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus", "iPhone17,1": "iPhone 16 Pro",
    "iPhone17,2": "iPhone 16 Pro Max", "iPhone17,5": "iPhone 16e",
    # older iPhones
    "iPhone8,1": "iPhone 6s", "iPhone8,2": "iPhone 6s Plus",
    "iPhone8,4": "iPhone SE (1st gen)", "iPhone9,1": "iPhone 7",
    "iPhone9,3": "iPhone 7", "iPhone9,2": "iPhone 7 Plus",
    "iPhone9,4": "iPhone 7 Plus",
}

IPAD_NAMES = {
    # iPad
    "iPad6,11": "iPad (5th gen)", "iPad6,12": "iPad (5th gen)",
    "iPad7,5": "iPad (6th gen)", "iPad7,6": "iPad (6th gen)",
    "iPad7,11": "iPad (7th gen)", "iPad7,12": "iPad (7th gen)",
    "iPad11,6": "iPad (8th gen)", "iPad11,7": "iPad (8th gen)",
    "iPad12,1": "iPad (9th gen)", "iPad12,2": "iPad (9th gen)",
    "iPad13,18": "iPad (10th gen)", "iPad13,19": "iPad (10th gen)",
    "iPad15,7": "iPad (A16)", "iPad15,8": "iPad (A16)",
    # iPad mini
    "iPad5,1": "iPad mini 4", "iPad5,2": "iPad mini 4",
    "iPad11,1": "iPad mini (5th gen)", "iPad11,2": "iPad mini (5th gen)",
    "iPad14,1": "iPad mini (6th gen)", "iPad14,2": "iPad mini (6th gen)",
    "iPad16,1": "iPad mini (A17 Pro)", "iPad16,2": "iPad mini (A17 Pro)",
    # iPad Air
    "iPad5,3": "iPad Air 2", "iPad5,4": "iPad Air 2",
    "iPad11,3": "iPad Air (3rd gen)", "iPad11,4": "iPad Air (3rd gen)",
    "iPad13,1": "iPad Air (4th gen)", "iPad13,2": "iPad Air (4th gen)",
    "iPad13,16": "iPad Air (5th gen)", "iPad13,17": "iPad Air (5th gen)",
    "iPad14,8": "iPad Air 11-inch (M2)", "iPad14,9": "iPad Air 11-inch (M2)",
    "iPad14,10": "iPad Air 13-inch (M2)",
    "iPad14,11": "iPad Air 13-inch (M2)",
    "iPad15,3": "iPad Air 11-inch (M3)", "iPad15,4": "iPad Air 11-inch (M3)",
    "iPad15,5": "iPad Air 13-inch (M3)", "iPad15,6": "iPad Air 13-inch (M3)",
    # iPad Pro
    "iPad6,3": "iPad Pro 9.7-inch", "iPad6,4": "iPad Pro 9.7-inch",
    "iPad6,7": "iPad Pro 12.9-inch (1st gen)",
    "iPad6,8": "iPad Pro 12.9-inch (1st gen)",
    "iPad7,1": "iPad Pro 12.9-inch (2nd gen)",
    "iPad7,2": "iPad Pro 12.9-inch (2nd gen)",
    "iPad7,3": "iPad Pro 10.5-inch", "iPad7,4": "iPad Pro 10.5-inch",
    "iPad8,1": "iPad Pro 11-inch (1st gen)",
    "iPad8,2": "iPad Pro 11-inch (1st gen)",
    "iPad8,3": "iPad Pro 11-inch (1st gen)",
    "iPad8,4": "iPad Pro 11-inch (1st gen)",
    "iPad8,5": "iPad Pro 12.9-inch (3rd gen)",
    "iPad8,6": "iPad Pro 12.9-inch (3rd gen)",
    "iPad8,7": "iPad Pro 12.9-inch (3rd gen)",
    "iPad8,8": "iPad Pro 12.9-inch (3rd gen)",
    "iPad8,9": "iPad Pro 11-inch (2nd gen)",
    "iPad8,10": "iPad Pro 11-inch (2nd gen)",
    "iPad8,11": "iPad Pro 12.9-inch (4th gen)",
    "iPad8,12": "iPad Pro 12.9-inch (4th gen)",
    "iPad13,4": "iPad Pro 11-inch (3rd gen)",
    "iPad13,5": "iPad Pro 11-inch (3rd gen)",
    "iPad13,6": "iPad Pro 11-inch (3rd gen)",
    "iPad13,7": "iPad Pro 11-inch (3rd gen)",
    "iPad13,8": "iPad Pro 12.9-inch (5th gen)",
    "iPad13,9": "iPad Pro 12.9-inch (5th gen)",
    "iPad13,10": "iPad Pro 12.9-inch (5th gen)",
    "iPad13,11": "iPad Pro 12.9-inch (5th gen)",
    "iPad14,3": "iPad Pro 11-inch (4th gen)",
    "iPad14,4": "iPad Pro 11-inch (4th gen)",
    "iPad14,5": "iPad Pro 12.9-inch (6th gen)",
    "iPad14,6": "iPad Pro 12.9-inch (6th gen)",
    "iPad16,3": "iPad Pro 11-inch (M4)", "iPad16,4": "iPad Pro 11-inch (M4)",
    "iPad16,5": "iPad Pro 13-inch (M4)", "iPad16,6": "iPad Pro 13-inch (M4)",
    # iPod touch
    "iPod7,1": "iPod touch (6th gen)", "iPod9,1": "iPod touch (7th gen)",
}
APPLE_NAMES = dict(IPHONE_NAMES, **IPAD_NAMES)


def apple_name(pt):
    """Model identifier (iPad13,18) -> name (iPad (10th gen)).
    A model newer than this list is shown by its identifier."""
    return APPLE_NAMES.get(pt, pt or "")


def apple_kind(pt):
    pt = pt or ""
    for pre, kind in (("iPhone", "iPhone"), ("iPad", "iPad"),
                      ("iPod", "iPod touch"), ("Watch", "Apple Watch")):
        if pt.startswith(pre):
            return kind
    return "iPhone / iPad"


# USB IDs, for devices that are NOT talking to the station normally
# (passcode unknown, USB debugging off, recovery / DFU / fastboot mode)
APPLE_VID = "05ac"
APPLE_RECOVERY_PIDS = {"1280", "1281", "1282", "1283"}
APPLE_DFU_PIDS = {"1222", "1227"}
ANDROID_VIDS = {
    "04e8": "Samsung", "18d1": "Google", "22b8": "Motorola", "1004": "LG",
    "0bb4": "HTC", "0fce": "Sony", "12d1": "Huawei", "339b": "Honor",
    "2717": "Xiaomi", "2a70": "OnePlus", "22d9": "OPPO / realme",
    "2d95": "vivo", "19d2": "ZTE", "2e04": "Nokia (HMD)", "1949": "Amazon",
    "29a9": "Nothing",
}

ANDROID_HEALTH = {"1": "Unknown", "2": "Good", "3": "Overheat", "4": "Dead",
                  "5": "Over voltage", "6": "Failure", "7": "Cold"}


# =============================================================================
# finding phones
# =============================================================================
def lsusb_list():
    """[{bus, dev, vid, pid, name}] of everything on USB."""
    out = []
    rc, o, _ = run(["lsusb"], 10)
    for ln in o.splitlines():
        m = re.search(r"Bus (\d+) Device (\d+): ID ([0-9a-fA-F]{4}):"
                      r"([0-9a-fA-F]{4})\s*(.*)", ln)
        if m:
            out.append({"bus": m.group(1), "dev": m.group(2),
                        "vid": m.group(3).lower(), "pid": m.group(4).lower(),
                        "name": m.group(5).strip()})
    return out


def usb_sysfs(bus, dev):
    """What a device says about itself on the USB cable, even when it is
    locked: maker, product name and serial number."""
    base = "/sys/bus/usb/devices"
    try:
        names = os.listdir(base)
    except OSError:
        return {}
    for n in names:
        d = os.path.join(base, n)
        try:
            with open(os.path.join(d, "busnum")) as f:
                b = int(f.read().strip())
            with open(os.path.join(d, "devnum")) as f:
                v = int(f.read().strip())
        except (OSError, ValueError):
            continue
        if b != int(bus) or v != int(dev):
            continue
        out = {}
        for k in ("manufacturer", "product", "serial", "idVendor",
                  "idProduct"):
            try:
                with open(os.path.join(d, k), errors="replace") as f:
                    out[k] = f.read().strip()
            except OSError:
                out[k] = ""
        return out
    return {}


# Google Pixel code names (bootloader / USB) -> names
PIXEL_NAMES = {
    "sunfish": "Pixel 4a", "bramble": "Pixel 4a (5G)", "redfin": "Pixel 5",
    "barbet": "Pixel 5a", "oriole": "Pixel 6", "raven": "Pixel 6 Pro",
    "bluejay": "Pixel 6a", "panther": "Pixel 7", "cheetah": "Pixel 7 Pro",
    "lynx": "Pixel 7a", "felix": "Pixel Fold", "tangorpro": "Pixel Tablet",
    "shiba": "Pixel 8", "husky": "Pixel 8 Pro", "akita": "Pixel 8a",
    "tokay": "Pixel 9", "caiman": "Pixel 9 Pro", "komodo": "Pixel 9 Pro XL",
    "comet": "Pixel 9 Pro Fold", "tegu": "Pixel 9a",
}

# USB product strings that are not a model name
GENERIC_USB_NAMES = ("android", "samsung_android", "mtp", "adb", "gadget",
                     "composite", "phone", "mobile", "device")


def usb_model_name(product):
    """'Pixel 7' -> 'Pixel 7'; 'SAMSUNG_Android' -> '' (not a model)."""
    p = (product or "").strip()
    if not p or p.lower().replace(" ", "_") in GENERIC_USB_NAMES or \
            p.lower() in GENERIC_USB_NAMES:
        return ""
    return PIXEL_NAMES.get(p.lower(), p)


def fastboot_info(serial):
    """A locked Android in bootloader / fastboot mode still tells its
    model, serial and lock state."""
    rc, o, e = run(["fastboot", "-s", serial, "getvar", "all"], 20)
    txt = o + e
    vals = {}
    for m in re.finditer(r"\(bootloader\)\s+([\w\-\.]+):\s*(.*)", txt):
        vals.setdefault(m.group(1).strip(), m.group(2).strip())
    for ln in txt.splitlines():          # some phones: "name: value"
        k, sep, v = ln.partition(":")
        if sep and k and " " not in k.strip():
            vals.setdefault(k.strip(), v.strip())
    prod = vals.get("product", "")
    return {"product": prod,
            "model": PIXEL_NAMES.get(prod.lower(), "") or prod,
            "serial": vals.get("serialno", "") or serial,
            "unlocked": vals.get("unlocked", ""),
            "secure": vals.get("secure", ""),
            "variant": vals.get("variant", "")}


def irecovery_info():
    """What an iPhone / iPad in recovery or DFU mode says about itself
    (ECID, PRODUCT, SRNM = serial, MODE). Empty if irecovery is missing."""
    if not have("irecovery"):
        return {}
    rc, o, e = run(["irecovery", "-q"], 10)
    return _kv(o) if rc == 0 else {}


def ios_basic(udid):
    """The few values an iPhone gives WITHOUT being unlocked / trusted."""
    rc, o, _ = run(["ideviceinfo", "-u", udid, "-s"], 10)
    return _kv(o) if rc == 0 else {}


def list_phones():
    """All phones / tablets on USB: [{platform, id, state, label, ...}]

    state: ready    - unlocked and trusted, everything can be read
           trust    - tap Trust / Allow on the device
           locked   - iPhone / iPad screen locked
           recovery / dfu - iPhone / iPad (or Android) in recovery / DFU
           fastboot - Android in bootloader mode
           nodebug  - Android on USB, but USB debugging is off or the
                      screen is locked
    """
    out = []
    if have("idevice_id"):
        rc, o, _ = run(["idevice_id", "-l"], 10)
        for udid in sorted(set(l.strip() for l in o.splitlines()
                               if l.strip())):
            rc2, o2, e2 = run(["idevicepair", "-u", udid, "validate"], 10)
            txt = (o2 + e2).lower()
            if rc2 == 0 and "success" in txt:
                st = "ready"
            elif "passcode" in txt or "locked" in txt:
                st = "locked"     # unlock the phone, then tap Trust
            else:
                st = "trust"      # tap "Trust this computer" on the phone
            b = ios_basic(udid)
            pt = b.get("ProductType", "")
            out.append({"platform": "ios", "id": udid, "state": st,
                        "label": apple_name(pt) or "iPhone / iPad",
                        "product": pt, "kind": apple_kind(pt),
                        "serial": b.get("SerialNumber", ""),
                        "os": b.get("ProductVersion", "")})
    usb = lsusb_list()
    rec = [d for d in usb if d["vid"] == APPLE_VID and
           (d["pid"] in APPLE_RECOVERY_PIDS or d["pid"] in APPLE_DFU_PIDS)]
    if rec:
        q = irecovery_info() if len(rec) == 1 else {}
        for d in rec:
            mode = "dfu" if d["pid"] in APPLE_DFU_PIDS else "recovery"
            pt = q.get("PRODUCT", "")
            out.append({"platform": "ios",
                        "id": "%s-%s:%s" % (mode, d["bus"], d["dev"]),
                        "state": mode,
                        "label": "%s (%s mode)" % (
                            apple_name(pt) or "iPhone / iPad",
                            "DFU" if mode == "dfu" else "Recovery"),
                        "product": pt, "kind": apple_kind(pt),
                        "ecid": q.get("ECID", ""),
                        "serial": q.get("SRNM", "").strip("[] ")})
    seen_android = 0
    if have("adb"):
        rc, o, _ = run(["adb", "devices", "-l"], 15)
        for ln in o.splitlines()[1:]:
            parts = ln.split()
            if len(parts) < 2:
                continue
            ser, st = parts[0], parts[1]
            model = dev_code = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p[6:].replace("_", " ")
                elif p.startswith("device:"):
                    dev_code = p[7:]
            state = {"device": "ready", "unauthorized": "trust",
                     "offline": "offline", "recovery": "recovery",
                     "sideload": "recovery"}.get(st, st)
            seen_android += 1
            out.append({"platform": "android", "id": ser, "state": state,
                        "label": PIXEL_NAMES.get(dev_code, "") or model or
                        "Android phone / tablet",
                        "model": PIXEL_NAMES.get(dev_code, "") or model,
                        "model_id": model, "serial": ser})
    if have("fastboot"):
        rc, o, _ = run(["fastboot", "devices"], 8)
        for ln in o.splitlines():
            parts = ln.split()
            if len(parts) >= 2 and parts[1] == "fastboot":
                seen_android += 1
                fb = fastboot_info(parts[0])
                out.append({"platform": "android", "id": parts[0],
                            "state": "fastboot",
                            "label": "%s (bootloader mode)" % (
                                fb["model"] or "Android"),
                            "model": fb["model"], "model_id": fb["product"],
                            "serial": fb["serial"],
                            "bootloader": "UNLOCKED" if fb["unlocked"] ==
                            "yes" else ("locked" if fb["unlocked"] == "no"
                                        else "")})
    # Android devices that are on USB but not talking to adb
    andr = [d for d in usb if d["vid"] in ANDROID_VIDS]
    for d in andr[seen_android:]:
        brand = ANDROID_VIDS[d["vid"]]
        u = usb_sysfs(d["bus"], d["dev"])
        model = usb_model_name(u.get("product"))
        make = brand if "/" not in brand else (u.get("manufacturer") or
                                               brand)
        out.append({"platform": "android",
                    "id": "usb-%s:%s" % (d["bus"], d["dev"]),
                    "state": "nodebug", "make": make, "model": model,
                    "serial": u.get("serial", ""),
                    "usb_product": u.get("product", ""),
                    "label": ("%s %s" % (make, model)).strip()
                    if model else "%s device" % make})
    return out


def pair_ios(udid):
    """Ask the iPhone to trust this station (user taps Trust)."""
    rc, o, e = run(["idevicepair", "-u", udid, "pair"], 30)
    return rc == 0, (o + e).strip()


# =============================================================================
# iPhone
# =============================================================================
def _kv(text):
    d = {}
    for ln in text.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def _num(v, div=1.0, nd=1):
    try:
        x = float(v) / div
        return round(x, nd) if nd else int(round(x))
    except (TypeError, ValueError):
        return None


def _gb(v):
    try:
        return round(int(v) / 1e9, 1)
    except (TypeError, ValueError):
        return None


def details_list(r):
    """Everything read, grouped, for the screen and the report:
    [(section, label, value)] - empty values are left out."""
    yes = lambda b: {True: "Yes", False: "No"}.get(b, b)  # noqa: E731
    rows = [
        ("Identity", "Type", r.get("kind")),
        ("Identity", "Make", r.get("make")),
        ("Identity", "Model", r.get("model")),
        ("Identity", "Model code", r.get("model_id")),
        ("Identity", "Model number", r.get("model_number")),
        ("Identity", "Region", r.get("region")),
        ("Identity", "Colour", r.get("colour")),
        ("Identity", "Serial", r.get("serial")),
        ("Identity", "IMEI", ", ".join(r.get("imei") or [])),
        ("Identity", "MEID", r.get("meid")),
        ("Identity", "ECID", r.get("ecid")),
        ("Identity", "UDID", r.get("udid")),
        ("Identity", "Device code", r.get("device_code")),
        ("Software", "OS", r.get("os")),
        ("Software", "Build", r.get("build")),
        ("Software", "Security patch", r.get("security_patch")),
        ("Software", "Modem firmware", r.get("baseband")),
        ("Software", "Region / CSC", r.get("csc")),
        ("Software", "Bootloader", r.get("bootloader")),
        ("Software", "Rooted / modified", yes(r.get("rooted"))),
        ("Software", "Encryption", r.get("encrypted")),
        ("Hardware", "Chip", r.get("chip")),
        ("Hardware", "RAM", ("%s GB" % r["ram_gb"]) if r.get("ram_gb")
         else ""),
        ("Hardware", "Storage", ("%s GB" % r["storage_gb"])
         if r.get("storage_gb") else ""),
        ("Hardware", "Storage used", ("%s GB used, %s GB free" % (
            r["storage_used_gb"], r["storage_free_gb"]))
         if r.get("storage_used_gb") is not None and
         r.get("storage_free_gb") is not None else ""),
        ("Hardware", "Screen", r.get("screen")),
        ("Hardware", "Wi-Fi MAC", r.get("wifi_mac")),
        ("Hardware", "Bluetooth MAC", r.get("bt_mac")),
        ("Battery", "Charge", ("%s%%" % r["battery_level"])
         if str(r.get("battery_level", "")).strip() else ""),
        ("Battery", "Health", ("%s%%" % r["battery_health_pct"])
         if r.get("battery_health_pct") is not None else ""),
        ("Battery", "Condition", r.get("battery_status")),
        ("Battery", "Cycles", r.get("battery_cycles")),
        ("Battery", "Capacity", ("%s of %s mAh" % (
            r["battery_full_mah"], r["battery_design_mah"]))
         if r.get("battery_full_mah") and r.get("battery_design_mah")
         else ""),
        ("Battery", "Temperature", ("%s C" % r["battery_temp_c"])
         if r.get("battery_temp_c") is not None else ""),
        ("Battery", "Voltage", ("%s V" % r["battery_voltage"])
         if r.get("battery_voltage") else ""),
        ("Battery", "Type", r.get("battery_tech")),
        ("Battery", "Charging", yes({"true": True, "false": False}.get(
            str(r.get("battery_charging", "")).lower(),
            r.get("battery_charging")))),
        ("Network", "SIM", r.get("sim")),
        ("Network", "Carrier", r.get("carrier")),
        ("Status", "Activation", r.get("activation_state")),
        ("Status", "Passcode set", yes({"true": True, "false": False}.get(
            str(r.get("passcode_set", "")).lower(), r.get("passcode_set")))),
    ]
    return [(s, l, str(v)) for s, l, v in rows
            if v not in (None, "", [], "unknown", "None")]


def ios_info(udid):
    r = {"platform": "ios", "id": udid, "notes": [], "udid": udid}
    rc, o, e = run(["ideviceinfo", "-u", udid], 20)
    if rc != 0:
        r["error"] = (e or o).strip()[:200] or "could not read the device"
        return r
    k = _kv(o)
    r["raw_keys"] = sorted(k.keys())
    pt = k.get("ProductType", "")
    r["make"] = "Apple"
    r["model"] = apple_name(pt) or "unknown"
    r["kind"] = apple_kind(pt)
    r["model_id"] = pt
    r["model_number"] = (k.get("ModelNumber", "") +
                         k.get("RegionInfo", "")).strip()
    r["region"] = k.get("RegionInfo", "")
    ver = k.get("ProductVersion", "?")
    major = ver.split(".")[0]
    major = int(major) if major.isdigit() else 0
    r["os"] = ("iPadOS %s" if r["kind"] == "iPad" and major >= 13 else
               "iOS %s") % ver
    r["build"] = k.get("BuildVersion", "")
    r["baseband"] = k.get("BasebandVersion", "")
    r["serial"] = k.get("SerialNumber", "")
    imeis = [k.get("InternationalMobileEquipmentIdentity", ""),
             k.get("InternationalMobileEquipmentIdentity2", "")]
    r["imei"] = [i for i in imeis if i]
    r["meid"] = k.get("MobileEquipmentIdentifier", "")
    r["ecid"] = k.get("UniqueChipID", "")
    col = k.get("DeviceColor", "")
    r["colour"] = "" if col.isdigit() or col.startswith("#") else col
    r["chip"] = " ".join(x for x in (k.get("HardwareModel", ""),
                                     k.get("CPUArchitecture", "")) if x)
    r["wifi_mac"] = k.get("WiFiAddress", "")
    r["bt_mac"] = k.get("BluetoothAddress", "")
    r["activation_state"] = k.get("ActivationState", "unknown")
    r["passcode_set"] = k.get("PasswordProtected", "unknown")
    sim = k.get("SIMStatus", "")
    r["sim"] = {"kCTSIMSupportSIMStatusNotInserted": "No SIM",
                "kCTSIMSupportSIMStatusReady": "SIM inserted",
                "kCTSIMSupportSIMStatusPINLocked": "SIM PIN locked"}.get(
        sim, sim.replace("kCTSIMSupportSIMStatus", ""))
    # storage
    rc, o, _ = run(["ideviceinfo", "-u", udid, "-q", "com.apple.disk_usage"],
                   15)
    dk = _kv(o)
    try:
        r["storage_gb"] = round(int(dk.get("TotalDiskCapacity", "0")) / 1e9)
    except ValueError:
        r["storage_gb"] = None
    cap, free = _gb(dk.get("TotalDataCapacity")), _gb(
        dk.get("TotalDataAvailable"))
    if cap is not None and free is not None:
        r["storage_free_gb"] = free
        r["storage_used_gb"] = round(cap - free, 1)
    # battery charge
    rc, o, _ = run(["ideviceinfo", "-u", udid, "-q",
                    "com.apple.mobile.battery"], 15)
    bk = _kv(o)
    r["battery_level"] = bk.get("BatteryCurrentCapacity", "")
    r["battery_charging"] = bk.get("BatteryIsCharging", "")
    # battery health from the battery controller
    r["battery_health_pct"] = None
    r["battery_cycles"] = None
    if have("idevicediagnostics"):
        rc, raw = run_bytes(["idevicediagnostics", "-u", udid, "ioregentry",
                             "AppleSmartBattery"], 20)
        try:
            i = raw.find(b"<?xml")
            pl = plistlib.loads(raw[i:]) if i >= 0 else {}
            reg = pl.get("IORegistry", pl) if isinstance(pl, dict) else {}
            cyc = reg.get("CycleCount")
            design = reg.get("DesignCapacity")
            full = (reg.get("AppleRawMaxCapacity") or
                    reg.get("NominalChargeCapacity"))
            if cyc is not None:
                r["battery_cycles"] = int(cyc)
            if design and full:
                r["battery_health_pct"] = min(100, round(100.0 * full /
                                                         design))
                r["battery_design_mah"] = int(design)
                r["battery_full_mah"] = int(full)
            if reg.get("Temperature") is not None:
                r["battery_temp_c"] = _num(reg.get("Temperature"), 100.0)
            if reg.get("Voltage"):
                r["battery_voltage"] = _num(reg.get("Voltage"), 1000.0, 2)
        except Exception:
            r["notes"].append("battery health not readable")
    r["details"] = details_list(r)
    return r


def ios_checks(udid, info):
    """Lock checks. Each: {name, result CLEAR/BLOCKED/CHECK, detail, how}"""
    kind = info.get("kind") or "iPhone"
    if kind == "iPhone / iPad":
        kind = "iPhone"
    checks = []
    # Find My / Activation Lock
    rc, o, _ = run(["ideviceinfo", "-u", udid, "-q", "com.apple.fmip"], 15)
    fk = _kv(o)
    fm = None
    for key in ("IsAssociated", "FMIPEnabled", "IsEnabled"):
        if key in fk:
            fm = fk[key].lower() in ("true", "1", "yes")
            break
    how_fm = ("On the iPhone: Settings > [name] > Find My > Find My "
              "iPhone must be OFF (the owner's Apple ID password is "
              "needed), or the owner removes it at icloud.com/find.")
    if fm is True:
        checks.append({"name": "Find My / Activation Lock",
                       "result": "BLOCKED",
                       "detail": "Find My is ON - the phone will be "
                                 "Activation Locked after a wipe",
                       "how": how_fm})
    elif fm is False:
        checks.append({"name": "Find My / Activation Lock",
                       "result": "CLEAR", "detail": "Find My is OFF",
                       "how": ""})
    else:
        checks.append({"name": "Find My / Activation Lock",
                       "result": "CHECK",
                       "detail": "this iPhone does not report Find My over "
                                 "USB - check it by hand",
                       "how": how_fm})
    # Supervision / MDM (company-managed)
    sup = None
    for dom in ("com.apple.mobile.chaperone", None):
        cmd = ["ideviceinfo", "-u", udid] + (["-q", dom] if dom else [])
        rc, o, _ = run(cmd, 15)
        for key, v in _kv(o).items():
            if "supervis" in key.lower():
                sup = v.lower() in ("true", "1", "yes")
        if sup is not None:
            break
    how_mdm = ("On the iPhone: Settings > General > VPN & Device Management "
               "must show no management profile, and Settings > General > "
               "About must not say 'This iPhone is supervised'. The "
               "customer releases it in Apple Business Manager (Devices > "
               "serial > Release Device) and removes it from their MDM.")
    if sup is True:
        checks.append({"name": "Supervised / MDM", "result": "BLOCKED",
                       "detail": "the iPhone is supervised (company "
                                 "managed)", "how": how_mdm})
    elif sup is False:
        checks.append({"name": "Supervised / MDM", "result": "CHECK",
                       "detail": "not supervised - check for a management "
                                 "profile by hand", "how": how_mdm})
    else:
        checks.append({"name": "Supervised / MDM", "result": "CHECK",
                       "detail": "not reported over USB - check by hand",
                       "how": how_mdm})
    # Carrier lock: never visible over USB
    checks.append({"name": "Carrier / SIM lock", "result": "CHECK",
                   "detail": "put in a SIM from another network: it must "
                             "not ask for a SIM unlock code",
                   "how": "Settings > General > About > Carrier Lock "
                          "should say 'No SIM restrictions'."})
    for c in checks:
        for k in ("detail", "how"):
            c[k] = c.get(k, "").replace("iPhone", kind)
    return checks


def ios_wipe_methods():
    """What this station can do to erase an iPhone, best first."""
    m = []
    rc, o, e = run(["idevicebackup2", "--help"], 10)
    if "erase" in (o + e).lower():
        m.append(("erase", "Erase All Content and Settings over USB"))
    if have("idevicerestore"):
        m.append(("restore", "Full erase-restore of iOS (downloads the "
                             "iOS firmware from Apple - needs internet)"))
    m.append(("manual", "Erase on the phone: Settings > General > Transfer "
                        "or Reset iPhone > Erase All Content and Settings"))
    return m


def ipsw_workdir(candidates):
    """Folder with the most free space for the iOS download (an iOS
    restore file is 5-9 GB). Returns (folder, free GB)."""
    best, free = "/tmp", 0.0
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            st = os.statvfs(d)
            f = st.f_bavail * st.f_frsize / 1e9
            if f > free:
                best, free = d, f
        except Exception:
            pass
    return best, round(free, 1)


def ios_wipe(udid, method, log=print, ecid="", workdir=None):
    """Run the wipe. Returns {ok, method, note}."""
    if method in ("restore", "restore_recovery"):
        cmd = ["idevicerestore", "-e", "-y"]
        if method == "restore":
            cmd += ["-u", udid]
        elif ecid:
            cmd += ["-i", ecid]
        log("Downloading iOS from Apple and restoring - this can take "
            "20-60 minutes. Do not unplug the device.")
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=7200, cwd=workdir or "/tmp")
            rc, o, e = p.returncode, p.stdout, p.stderr
        except Exception as ex:
            rc, o, e = 1, "", str(ex)
        return {"ok": rc == 0, "method": "Erase-restore of iOS / iPadOS "
                "(idevicerestore%s)" % (", from recovery mode" if method ==
                                        "restore_recovery" else ""),
                "note": (e or o).strip()[-200:]}
    if method == "erase":
        rc, o, e = run(["idevicebackup2", "-u", udid, "erase"], 600)
        return {"ok": rc == 0, "method": "Erase All Content and Settings "
                "(USB)", "note": (e or o).strip()[:200]}
    if method == "restore":
        log("Downloading iOS from Apple and restoring - this can take "
            "20-40 minutes. Do not unplug the phone.")
        rc, o, e = run(["idevicerestore", "-u", udid, "-e", "-y"], 7200)
        return {"ok": rc == 0, "method": "Erase-restore of iOS "
                "(idevicerestore)", "note": (e or o).strip()[-200:]}
    return {"ok": None, "method": "Erase All Content and Settings (on the "
            "phone, by technician)", "note": "technician confirmation "
            "needed"}


def ios_verify_wiped(udid, wait=600, log=print, serial=""):
    """After a wipe the iPhone restarts on the Hello / activation screen.
    It then shows ActivationState Unactivated and is no longer paired.
    udid None (wiped from recovery mode): the device with this serial
    (or the only device on the station) is checked."""
    end = time.time() + wait
    while time.time() < end:
        rc, o, _ = run(["idevice_id", "-l"], 10)
        ids = [l.strip() for l in o.splitlines() if l.strip()]
        if udid:
            ids = [i for i in ids if i == udid]
        for i in ids:
            b = ios_basic(i)
            if not udid and serial and b.get("SerialNumber") and \
                    b.get("SerialNumber") != serial:
                continue
            if not udid and not serial and len(ids) > 1:
                continue
            st = b.get("ActivationState", "")
            if st and st != "Activated":
                return True, "device restarted on the setup screen " \
                             "(ActivationState: %s)" % st
        time.sleep(5)
    return False, "device did not come back on the setup screen in time"


# =============================================================================
# Android
# =============================================================================
def adb(ser, *args, timeout=20):
    return run(["adb", "-s", ser] + list(args), timeout)


def prop(ser, name):
    rc, o, _ = adb(ser, "shell", "getprop", name)
    return o.strip()


def android_imei(ser):
    """IMEI if the phone lets adb read it (older Android only)."""
    for code in ("1", "4"):
        rc, o, _ = adb(ser, "shell", "service", "call", "iphonesubinfo",
                       code)
        digits = "".join(re.findall(r"'(.*?)'", o)).replace(".", "")
        digits = re.sub(r"\D", "", digits)
        if luhn_ok(digits[:15]):
            return digits[:15]
    return ""


# Amazon Fire model codes -> names (newer ones show their code)
FIRE_NAMES = {
    "KFTRWI": "Fire HD 10 (2021)", "KFTRPWI": "Fire HD 10 Plus (2021)",
    "KFMAWI": "Fire HD 10 (2019)", "KFSUWI": "Fire HD 10 (2017)",
    "KFTUWI": "Fire HD 10 (2023)", "KFONWI": "Fire HD 8 (2020)",
    "KFRAWI": "Fire HD 8 (2022)", "KFRAPWI": "Fire HD 8 Plus (2022)",
    "KFKAWI": "Fire HD 8 (2018)", "KFDOWI": "Fire HD 8 (2017)",
    "KFMUWI": "Fire 7 (2019)", "KFQUWI": "Fire 7 (2022)",
    "KFSNWI": "Fire Max 11 (2023)",
}

ANDROID_PROPS = {
    "make": "ro.product.manufacturer", "brand": "ro.product.brand",
    "marketname": "ro.product.marketname", "model_id": "ro.product.model",
    "device_code": "ro.product.device", "release": "ro.build.version.release",
    "build": "ro.build.display.id",
    "security_patch": "ro.build.version.security_patch",
    "serialno": "ro.serialno", "boot_serial": "ro.boot.serialno",
    "crypto": "ro.crypto.state", "crypto_type": "ro.crypto.type",
    "chars": "ro.build.characteristics", "baseband": "gsm.version.baseband",
    "sim_state": "gsm.sim.state", "sim_op": "gsm.sim.operator.alpha",
    "net_op": "gsm.operator.alpha", "csc": "ro.csc.sales_code",
    "csc2": "ril.official_cscver", "vb_state": "ro.boot.verifiedbootstate",
    "flash_locked": "ro.boot.flash.locked",
    "vbmeta": "ro.boot.vbmeta.device_state",
    "oem_unlock": "sys.oem_unlock_allowed", "soc": "ro.soc.model",
    "soc_maker": "ro.soc.manufacturer", "platform": "ro.board.platform",
    "hardware": "ro.hardware", "kg": "knox.kg.state",
    "samsung_market": "ril.product_code",
    "mkt_name2": "ro.vendor.oplus.market.name",
    "fireos": "ro.build.version.fireos",
    "mkt_name3": "ro.product.vendor.marketname",
}


def android_props(ser):
    """All the getprop values at once (one adb call)."""
    rc, o, _ = adb(ser, "shell", "getprop", timeout=20)
    allp = {}
    for m in re.finditer(r"^\[([^\]]+)\]: \[(.*)\]$", o, re.M):
        allp[m.group(1)] = m.group(2)
    return {k: allp.get(v, "").strip() for k, v in ANDROID_PROPS.items()}


def android_info(ser):
    r = {"platform": "android", "id": ser, "notes": []}
    rc, o, e = adb(ser, "get-state")
    if o.strip() != "device":
        r["error"] = "device not ready over USB (%s)" % (o or e).strip()
        return r
    P = android_props(ser)
    r["make"] = (P["make"] or P["brand"]).title() or "unknown"
    if r["make"].lower() == "amazon":
        r["kind"] = "Amazon Fire tablet"
    elif "tablet" in P["chars"]:
        r["kind"] = "Android tablet"
    else:
        r["kind"] = "Android phone"
    r["model"] = (P["marketname"] or P["mkt_name3"] or P["mkt_name2"] or
                  FIRE_NAMES.get(P["model_id"], "") or "")
    if not r["model"] and r["make"].lower() == "samsung":
        # Samsung keeps the sales name as the default device name
        rc, o, _ = adb(ser, "shell", "settings", "get", "global",
                       "device_name")
        if o.strip().startswith("Galaxy"):
            r["model"] = o.strip()
    r["model"] = r["model"] or P["model_id"] or "unknown"
    r["model_id"] = P["model_id"]
    r["device_code"] = P["device_code"]
    r["os"] = "Android %s" % (P["release"] or "?")
    if r["make"].lower() == "amazon":
        r["os"] = ("Fire OS %s (Android %s)" % (P["fireos"], P["release"])
                   if P["fireos"] else "Fire OS (Android %s)" % P["release"])
    r["build"] = P["build"]
    r["security_patch"] = P["security_patch"]
    r["baseband"] = P["baseband"].split(",")[0]
    r["csc"] = P["csc"] or P["samsung_market"]
    r["serial"] = P["serialno"] or P["boot_serial"] or ser
    imei = android_imei(ser)
    r["imei"] = [imei] if imei else []
    if not imei:
        r["notes"].append("IMEI not readable over USB on this Android "
                          "version - dial *#06# and type it in")
    r["encrypted"] = P["crypto"] or "unknown"
    r["encryption_type"] = P["crypto_type"]
    if P["crypto_type"]:
        r["encrypted"] += " (%s)" % P["crypto_type"]
    r["chip"] = " ".join(x for x in (P["soc_maker"], P["soc"] or
                                     P["platform"] or P["hardware"]) if x)
    # bootloader / root
    unlocked = P["vb_state"] in ("orange", "yellow") or \
        P["flash_locked"] == "0" or P["vbmeta"] == "unlocked"
    r["bootloader"] = ("UNLOCKED" if unlocked else "locked") + (
        " (verified boot %s)" % P["vb_state"] if P["vb_state"] else "")
    rc, o, _ = adb(ser, "shell", "command -v su || ls /system/xbin/su "
                   "/system/bin/su /sbin/su 2>/dev/null")
    r["rooted"] = bool(o.strip())
    if unlocked or r["rooted"]:
        r["notes"].append("bootloader unlocked or rooted - the system was "
                          "modified")
    r["oem_unlock_allowed"] = P["oem_unlock"]
    r["knox_guard"] = P["kg"]
    # SIM / carrier
    sims = [x for x in P["sim_state"].split(",") if x]
    if sims:
        r["sim"] = "SIM inserted" if any(x in ("READY", "LOADED")
                                         for x in sims) else \
            ("No SIM" if all(x in ("ABSENT", "NOT_READY", "UNKNOWN")
                             for x in sims) else ", ".join(sims))
    r["carrier"] = (P["sim_op"].strip(",") or P["net_op"].strip(","))
    # RAM
    rc, o, _ = adb(ser, "shell", "cat", "/proc/meminfo")
    m = re.search(r"MemTotal:\s+(\d+)", o)
    if m:
        kb = int(m.group(1))
        # shown like the box: 3.7 GB -> 4 GB
        r["ram_gb"] = min((x for x in (1, 1.5, 2, 3, 4, 6, 8, 12, 16, 18, 24,
                                       32) if x * 1024 * 1024 >= kb * 0.85),
                          default=round(kb / 1048576.0, 1))
    # storage (size, used, free) of the user data area
    rc, o, _ = adb(ser, "shell", "df", "-k", "/data")
    m = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+\d+%", o)
    if m:
        tot, used, free = (int(m.group(i)) * 1024 for i in (1, 2, 3))
        r["storage_used_gb"] = round(used / 1e9, 1)
        r["storage_free_gb"] = round(free / 1e9, 1)
        # sold size: the next 16/32/64/128... above the data area size
        r["storage_gb"] = min((x for x in (8, 16, 32, 64, 128, 256, 512,
                                           1024) if x * 1e9 >= tot),
                              default=round(tot / 1e9))
    else:
        r["storage_gb"] = None
    # screen
    rc, o, _ = adb(ser, "shell", "wm", "size")
    m = re.findall(r"(\d+x\d+)", o)
    if m:
        rc2, o2, _ = adb(ser, "shell", "wm", "density")
        d = re.findall(r"(\d+)", o2)
        r["screen"] = "%s pixels%s" % (m[-1], (", %s dpi" % d[-1]) if d
                                       else "")
    # Wi-Fi MAC (newer Android hides it: 02:00:00:00:00:00)
    rc, o, _ = adb(ser, "shell", "cat", "/sys/class/net/wlan0/address")
    mac = o.strip()
    if re.fullmatch(r"[0-9a-fA-F:]{17}", mac) and not mac.startswith(
            "02:00:00"):
        r["wifi_mac"] = mac
    # battery
    rc, o, _ = adb(ser, "shell", "dumpsys", "battery")
    bk = _kv(o)
    r["battery_level"] = bk.get("level", "")
    r["battery_charging"] = "true" if bk.get("status") == "2" else "false"
    r["battery_status"] = ANDROID_HEALTH.get(bk.get("health", ""), "unknown")
    r["battery_temp_c"] = _num(bk.get("temperature"), 10.0)
    r["battery_voltage"] = _num(bk.get("voltage"), 1000.0, 2)
    r["battery_tech"] = bk.get("technology", "")
    r["battery_health_pct"] = None
    r["battery_cycles"] = None
    for key in ("cycle count", "Cycle count", "cycle_count"):
        if bk.get(key, "").isdigit():
            r["battery_cycles"] = int(bk[key])
    for base in ("/sys/class/power_supply/battery",
                 "/sys/class/power_supply/bms"):
        rc, o, _ = adb(ser, "shell", "cat", base + "/cycle_count")
        if rc == 0 and o.strip().isdigit() and r["battery_cycles"] is None:
            r["battery_cycles"] = int(o.strip())
        rc1, full, _ = adb(ser, "shell", "cat", base + "/charge_full")
        rc2, des, _ = adb(ser, "shell", "cat", base + "/charge_full_design")
        if rc1 == 0 and rc2 == 0 and full.strip().isdigit() and \
                des.strip().isdigit() and int(des) > 0:
            r["battery_health_pct"] = min(100, round(100.0 * int(full) /
                                                     int(des)))
            r["battery_full_mah"] = int(full) // 1000
            r["battery_design_mah"] = int(des) // 1000
        if r["battery_cycles"] is not None or r["battery_health_pct"]:
            break
    # Android 14+: battery health % from the system (if the maker fills it)
    if r["battery_health_pct"] is None:
        rc, o, _ = adb(ser, "shell", "dumpsys", "batteryproperties")
        m = re.search(r"(?:state of health|soh)\D{0,5}(\d{1,3})", o, re.I)
        if m and 0 < int(m.group(1)) <= 100:
            r["battery_health_pct"] = int(m.group(1))
    r["details"] = details_list(r)
    return r


def _mask(acc):
    if "@" in acc:
        u, d = acc.split("@", 1)
        return (u[:2] + "***@" + d) if len(u) > 2 else "***@" + d
    return acc[:2] + "***"


def android_checks(ser, info):
    checks = []
    rc, o, _ = adb(ser, "shell", "dumpsys", "account", timeout=30)
    accs = re.findall(r"Account \{name=([^,]+), type=([^}]+)\}", o)
    google = sorted({n for n, t in accs if t.strip() == "com.google"})
    samsung = sorted({n for n, t in accs if "osp" in t or "samsung" in t})
    how_g = ("On the phone: Settings > Accounts (Passwords & accounts) > "
             "remove every Google account BEFORE the reset. Otherwise "
             "Factory Reset Protection (FRP) locks the phone to that "
             "account.")
    if rc != 0:
        checks.append({"name": "Google account (FRP)", "result": "CHECK",
                       "detail": "accounts could not be read", "how": how_g})
    elif google:
        checks.append({"name": "Google account (FRP)", "result": "BLOCKED",
                       "detail": "%d Google account(s) signed in: %s" % (
                           len(google), ", ".join(_mask(a) for a in google)),
                       "how": how_g})
    else:
        checks.append({"name": "Google account (FRP)", "result": "CLEAR",
                       "detail": "no Google account signed in", "how": ""})
    if samsung:
        checks.append({"name": "Samsung account (Reactivation lock)",
                       "result": "BLOCKED",
                       "detail": "Samsung account signed in",
                       "how": "Settings > Accounts and backup > Manage "
                              "accounts > remove the Samsung account."})
    checks += brand_account_checks(info.get("make", ""), accs)
    kg = (info.get("knox_guard") or "").strip()
    if kg:
        st = kg.lower()
        if st in ("active", "locked", "blink", "prenormal", "checking"):
            res = "BLOCKED"
        elif st in ("completed", "none", "disabled"):
            res = "CLEAR"
        else:
            res = "CHECK"
        checks.append({"name": "Samsung Knox Guard (finance / company lock)",
                       "result": res, "detail": "state: %s" % kg,
                       "how": "The phone is locked by a finance company or "
                              "business through Knox Guard. Only they can "
                              "release it (Knox Guard portal)."
                       if res != "CLEAR" else ""})
    rc, o, _ = adb(ser, "shell", "dpm", "list-owners")
    owners = [l.strip() for l in o.splitlines()
              if "owner" in l.lower() and "no owners" not in l.lower()]
    how_m = ("The customer removes the phone from their MDM (Intune, "
             "Workspace ONE, Knox, Google Workspace...) and from Android "
             "Zero-touch / Knox Mobile Enrollment, so it does not "
             "re-enrol after the reset.")
    if rc != 0:
        checks.append({"name": "MDM / device owner", "result": "CHECK",
                       "detail": "could not be read", "how": how_m})
    elif owners:
        checks.append({"name": "MDM / device owner", "result": "BLOCKED",
                       "detail": "; ".join(owners)[:160], "how": how_m})
    else:
        checks.append({"name": "MDM / device owner", "result": "CLEAR",
                       "detail": "no device or profile owner", "how": ""})
    checks.append({"name": "Zero-touch / Knox enrolment", "result": "CHECK",
                   "detail": "a cloud enrolment is not visible on the phone "
                             "- confirm with the customer",
                   "how": how_m})
    checks.append({"name": "Carrier / SIM lock", "result": "CHECK",
                   "detail": "put in a SIM from another network: it must "
                             "not ask for a network unlock code",
                   "how": ""})
    return checks


def android_wipe(ser, log=print):
    """Android does not allow a factory reset over adb without root.
    The station restarts the phone into recovery; the technician chooses
    'Wipe data / factory reset'."""
    rc, o, e = adb(ser, "reboot", "recovery", timeout=30)
    return {"ok": None if rc == 0 else False,
            "method": "Factory reset in recovery (encrypted storage: the "
                      "encryption keys are destroyed)",
            "note": "phone restarted into recovery - technician chooses "
                    "'Wipe data / factory reset'" if rc == 0 else
                    (e or o).strip()[:200]}


# =============================================================================
# brand accounts that lock an Android device after a reset
# =============================================================================
# (check name, makes it applies to, account-type words, where to remove it)
BRAND_ACCOUNTS = [
    ("Amazon account (registered Fire)", ("amazon",), ("amazon",),
     "On the tablet: Settings > My Account (or Accounts) > Deregister. "
     "A registered Fire stays linked to the owner's Amazon account."),
    ("Xiaomi Mi account (Find device lock)", ("xiaomi", "redmi", "poco"),
     ("xiaomi",),
     "Settings > Mi Account (Xiaomi account) > Sign out - needs the "
     "owner's password. Otherwise the phone stays locked to that account "
     "after the reset."),
    ("HUAWEI / HONOR ID (Activation lock)", ("huawei", "honor"),
     ("huawei", "hihonor", "honor"),
     "Settings > [name] > Log out of the HUAWEI ID / HONOR ID - needs the "
     "owner's password."),
    ("OPPO / realme / OnePlus account", ("oppo", "realme", "oneplus"),
     ("heytap", "oppo", "coloros", "oneplus", "realme"),
     "Settings > [name] > Sign out of the account (Find My Phone)."),
    ("vivo account", ("vivo", "iqoo"), ("vivo", "bbk"),
     "Settings > vivo account > Sign out (Find my phone)."),
]


def brand_account_checks(make, accs):
    """Brand lock checks for the brands that have one. accs = [(name, type)]"""
    out = []
    mk = (make or "").lower()
    for name, makes, words, how in BRAND_ACCOUNTS:
        if not any(m in mk for m in makes):
            continue
        found = sorted({n for n, t in accs
                        if any(w in t.lower() for w in words)})
        if found:
            out.append({"name": name, "result": "BLOCKED",
                        "detail": "signed in: %s" % ", ".join(
                            _mask(a) for a in found), "how": how})
        else:
            out.append({"name": name, "result": "CLEAR",
                        "detail": "no account of this brand signed in",
                        "how": ""})
    return out


# =============================================================================
# locked devices (passcode unknown) and devices added by hand
# =============================================================================
KINDS = ["iPhone", "iPad", "iPod touch", "Apple Watch", "Android phone",
         "Android tablet", "Amazon Fire tablet", "Other"]


def kind_platform(kind):
    if kind in ("iPhone", "iPad", "iPod touch", "Apple Watch",
                "iPhone / iPad"):
        return "ios"
    if kind.startswith(("Android", "Amazon")):
        return "android"
    return "manual"


def locked_info(p):
    """What is known about a device that cannot be unlocked."""
    kind = p.get("kind") or ("Android phone" if p["platform"] == "android"
                             else "iPhone / iPad" if p["platform"] == "ios"
                             else "Other")
    make = p.get("make") or ("Apple" if p["platform"] == "ios" else "")
    if make.lower() == "amazon":
        kind = "Amazon Fire tablet"
    if p["platform"] == "ios":
        model = apple_name(p.get("product", ""))
        model_id = p.get("product", "")
    else:
        model = p.get("model", "")
        model_id = p.get("model_id", "")
    info = {"platform": p["platform"], "id": p["id"], "kind": kind,
            "make": make, "model": model, "model_id": model_id,
            "serial": p.get("serial", ""),
            "os": ("iOS %s" % p["os"]) if p.get("os") else "",
            "ecid": p.get("ecid", ""), "bootloader": p.get("bootloader", ""),
            "imei": [], "notes": [], "passcode_known": False}
    if p["platform"] == "ios" and p.get("state") in ("ready", "trust",
                                                     "locked"):
        info["udid"] = p["id"]
    if p.get("serial"):
        info["notes"].append("serial read from the device over USB")
    return info


def merge_locked_info(info, p):
    """'Read again': fill the empty fields from a fresh look at the device
    (never overwrite what the technician typed)."""
    fresh = locked_info(p)
    filled = []
    for k in ("make", "model", "model_id", "serial", "os", "ecid",
              "bootloader", "udid"):
        if fresh.get(k) and not info.get(k):
            info[k] = fresh[k]
            filled.append(k)
    return filled


def locked_checks(kind):
    """Lock checks for a device whose passcode is unknown. They can only
    be seen on the setup screen AFTER the wipe, so all start as CHECK."""
    after = "check on the setup screen AFTER the wipe"
    if kind == "Apple Watch":
        return [{"name": "Activation Lock", "result": "CHECK",
                 "detail": after,
                 "how": "Pairing the erased watch with an iPhone must NOT ask "
                        "for the previous owner's Apple ID. If it does, the "
                        "owner removes it at icloud.com/find (Remove from "
                        "account)."}]
    if kind_platform(kind) == "ios":
        dev = kind if kind in ("iPad", "iPod touch") else "iPhone"
        return [
            {"name": "Find My / Activation Lock", "result": "CHECK",
             "detail": after,
             "how": "The setup screen must NOT show '%s Locked to Owner' / "
                    "Activation Lock. If it does, the owner removes it at "
                    "icloud.com/find (Remove from account), or the company "
                    "releases it in Apple Business Manager." % dev},
            {"name": "Remote Management (MDM)", "result": "CHECK",
             "detail": after,
             "how": "Setup must NOT show 'Remote Management - <organisation> "
                    "can automatically configure your %s'. If it does, the "
                    "company releases it in Apple Business Manager "
                    "(Devices > serial > Release Device)." % dev},
            {"name": "Carrier / SIM lock", "result": "CHECK",
             "detail": "put in a SIM from another network: it must not ask "
                       "for a SIM unlock code", "how": ""}]
    if kind_platform(kind) == "android":
        c = [{"name": "Google account (FRP)", "result": "CHECK",
              "detail": after,
              "how": "Setup must NOT ask 'Verify your account' / 'This "
                     "device was reset. To continue, sign in with a Google "
                     "account that was previously synced'. If it does, the "
                     "phone is FRP locked: the owner must remove it from "
                     "their Google account (myaccount.google.com > "
                     "Security > Your devices) or give the password."},
             {"name": "Brand account (Samsung / Mi / HUAWEI / Amazon...)",
              "result": "CHECK", "detail": after,
              "how": "Setup must NOT ask for a Samsung account "
                     "(Reactivation lock), Mi account, HUAWEI ID or Amazon "
                     "account."},
             {"name": "Work / organisation enrolment", "result": "CHECK",
              "detail": after,
              "how": "Setup must NOT say 'This device belongs to your "
                     "organisation' (Zero-touch / Knox enrolment). If it "
                     "does, the customer releases it from their MDM / "
                     "Zero-touch / Knox portal."},
             {"name": "Carrier / SIM lock", "result": "CHECK",
              "detail": "put in a SIM from another network: it must not ask "
                        "for a network unlock code", "how": ""}]
        return c
    return [{"name": "Accounts and locks", "result": "CHECK", "detail": after,
             "how": "After the reset the device must start like new without "
                    "asking for the previous owner's account or password."}]


def manual_checks(kind):
    """Lock checks for a device added by hand whose passcode IS known:
    the technician looks in its Settings."""
    if kind == "Apple Watch":
        return [{"name": "Activation Lock", "result": "CHECK",
                 "detail": "check on the watch's iPhone",
                 "how": "On the paired iPhone: Watch app > All Watches > (i) "
                        "> Unpair Apple Watch (this also removes Activation "
                        "Lock). Or the owner removes it at icloud.com/find."}]
    if kind_platform(kind) == "ios":
        dev = kind if kind in ("iPad", "iPod touch") else "iPhone"
        return [
            {"name": "Find My / Activation Lock", "result": "CHECK",
             "detail": "check in Settings",
             "how": "Settings > [name] > Find My > Find My %s must be OFF." %
                    dev},
            {"name": "Supervised / MDM", "result": "CHECK",
             "detail": "check in Settings",
             "how": "Settings > General > VPN & Device Management: no "
                    "management profile. Settings > General > About must "
                    "not say 'This %s is supervised'." % dev},
            {"name": "Carrier / SIM lock", "result": "CHECK",
             "detail": "check in Settings",
             "how": "Settings > General > About > Carrier Lock: 'No SIM "
                    "restrictions'."}]
    if kind_platform(kind) == "android":
        return [
            {"name": "Google account (FRP)", "result": "CHECK",
             "detail": "check in Settings",
             "how": "Settings > Accounts (Passwords & accounts): remove "
                    "every Google account BEFORE the reset."},
            {"name": "Brand account (Samsung / Mi / HUAWEI / Amazon...)",
             "result": "CHECK", "detail": "check in Settings",
             "how": "Settings > Accounts: sign out of the Samsung account, "
                    "Mi account, HUAWEI ID, OPPO/vivo account; on a Fire "
                    "tablet Settings > My Account > Deregister."},
            {"name": "MDM / work profile", "result": "CHECK",
             "detail": "check in Settings",
             "how": "Settings > Security > Device admin apps: none active; "
                    "no work profile."},
            {"name": "Carrier / SIM lock", "result": "CHECK",
             "detail": "SIM from another network", "how": ""}]
    return [{"name": "Accounts and locks", "result": "CHECK",
             "detail": "check in Settings",
             "how": "Sign out of every account and turn off any 'find my "
                    "device' before the reset."}]


def ios_recovery_steps(kind, model=""):
    """How to put an iPhone / iPad / iPod in recovery mode (cable in)."""
    m = model or ""
    if kind == "iPad":
        if "Pro 11" in m or "Pro 12.9-inch (3" in m or "Pro 12.9-inch (4" in \
                m or "Pro 12.9-inch (5" in m or "Pro 12.9-inch (6" in m or \
                "Air (4" in m or "Air (5" in m or "Air 1" in m or \
                "mini (6" in m or "mini (A" in m or "(10th" in m or \
                "(A16)" in m or "Pro 13" in m:
            return ("iPad without a Home button: press and release the volume "
                    "button nearest the top button, press and release the "
                    "other volume button, then hold the top button until "
                    "the recovery screen (computer and cable) appears.")
        return ("iPad with a Home button: hold the Home button and the top "
                "button together until the recovery screen (computer and "
                "cable) appears. (No Home button? Volume nearest the top "
                "button, then the other volume button, then hold the top "
                "button.)")
    if kind == "iPod touch" or "iPhone 7" in m:
        return ("Hold the Side (or Top) button and Volume Down together until "
                "the recovery screen (computer and cable) appears.")
    if "6s" in m or "SE (1st" in m:
        return ("Hold the Home button and the Side (or Top) button together "
                "until the recovery screen (computer and cable) appears.")
    return ("iPhone 8 and newer (also SE 2nd/3rd gen): press and release "
            "Volume Up, press and release Volume Down, then press and HOLD "
            "the Side button - keep holding past the Apple logo - until the "
            "recovery screen (computer and cable) appears.\n"
            "iPhone 7: hold Side + Volume Down.  iPhone 6s / SE 1st gen: "
            "hold Home + Side.")


ANDROID_RECOVERY = [
    ("samsung", "Samsung: switch it off. Keep the USB cable in this station. "
     "Hold Volume Up + Side (Power) until the Samsung logo, then let go - "
     "the recovery menu follows. (Older models: Volume Up + Home + Power, "
     "or Volume Up + Bixby + Power.)"),
    ("google", "Google Pixel: switch it off, hold Power + Volume Down until "
     "the bootloader screen. Volume keys to 'Recovery mode', Power to "
     "choose. At 'No command' hold Power and press Volume Up once."),
    ("motorola", "Motorola: switch it off, hold Power + Volume Down until "
     "the bootloader screen. Volume keys to 'Recovery mode', Power to "
     "choose. At 'No command' hold Power and press Volume Up once."),
    ("xiaomi", "Xiaomi / Redmi / POCO: switch it off, hold Volume Up + Power "
     "until the logo, then let go. In Mi-Recovery choose 'Wipe Data'."),
    ("oneplus", "OnePlus: switch it off, hold Power + Volume Down (older "
     "models: Volume Up) until the recovery menu."),
    ("huawei", "HUAWEI / HONOR: switch it off, hold Volume Up + Power until "
     "the logo (on some models the USB cable must be unplugged)."),
    ("honor", "HONOR: switch it off, hold Volume Up + Power until the logo."),
    ("amazon", "Amazon Fire: switch it off, hold Power and one Volume key "
     "(Down on most models, Up on some) until 'Amazon system recovery' "
     "appears."),
]


def android_recovery_steps(make):
    mk = (make or "").lower()
    for key, txt in ANDROID_RECOVERY:
        if key in mk:
            first = txt
            break
    else:
        first = ("Most Android devices: switch it off, then hold Volume Up "
                 "(or Volume Down) + Power until the recovery menu appears.")
    return (first + "\nThen: Volume keys to 'Wipe data / factory reset', "
            "Power to choose, confirm 'Factory data reset', then 'Reboot "
            "system now'.")


def wipe_methods(p, info, locked):
    """[(key, text)] best first, for any device."""
    kind = info.get("kind", "")
    st = p.get("state", "")
    if kind == "Apple Watch":
        return [("manual", "Erase on the watch: Settings > General > Reset > "
                 "Erase All Content and Settings (or unpair it in the Watch "
                 "app on its iPhone)")]
    if st == "manual":            # added by hand, no USB
        known = info.get("passcode_known")
        if kind_platform(kind) == "ios":
            return ([("manual", "Erase in Settings (by the technician)")]
                    if known else []) + [
                ("manual_restore", "Restore on a computer: Finder (Mac) or "
                 "Apple Devices / iTunes (Windows) > Restore")]
        if kind_platform(kind) == "android":
            return ([("settings", "Factory reset in Settings (by the "
                      "technician)")] if known else []) + [
                ("guided", "Factory reset from the recovery menu with the "
                 "device's buttons")]
        return [("manual", "Factory reset by the technician")]
    if p["platform"] == "ios" and st == "ready" and not locked:
        return ios_wipe_methods()
    if p["platform"] == "ios" and st in ("recovery", "dfu"):
        m = []
        if have("idevicerestore"):
            m.append(("restore_recovery", "Erase-restore iOS / iPadOS from "
                      "recovery mode (downloads it from Apple: needs "
                      "internet and 6-9 GB free on USB B)"))
        m.append(("manual_restore", "Restore on another computer: Finder "
                  "(Mac) or Apple Devices / iTunes (Windows) > Restore"))
        return m
    if p["platform"] == "ios":
        return [("to_recovery", "Put it in recovery mode first (passcode "
                 "unknown) - steps below"),
                ("manual_restore", "Restore on another computer: Finder "
                 "(Mac) or Apple Devices / iTunes (Windows) > Restore")]
    if p["platform"] == "android" and st == "ready" and not locked:
        return [("recovery", "Factory reset in recovery (the station restarts "
                 "the device into recovery; you choose 'Wipe data / factory "
                 "reset')")]
    if p["platform"] == "android":
        return [("guided", "Factory reset from the recovery menu with the "
                 "device's buttons (steps below)")]
    return [("manual", "Factory reset in the device's settings or recovery "
             "menu (by the technician)")]


def manual_wipe_steps(method, p, info):
    kind = info.get("kind", "")
    if method == "manual" and kind == "Apple Watch":
        return ("On the watch: Settings > General > Reset > Erase All Content "
                "and Settings. Or on its iPhone: Watch app > All Watches > "
                "(i) > Unpair Apple Watch.")
    if method == "manual" and kind_platform(kind) == "ios":
        dev = kind if kind in ("iPad", "iPod touch") else "iPhone"
        return ("On the device: Settings > General > Transfer or Reset %s > "
                "Erase All Content and Settings." % dev)
    if method == "manual_restore":
        return ("Connect it to a Mac (Finder) or Windows PC (Apple Devices "
                "or iTunes), put it in recovery mode, choose Restore.\n"
                + ios_recovery_steps(kind, info.get("model", "")))
    if method in ("guided", "manual") and kind_platform(kind) == "android":
        return android_recovery_steps(info.get("make", ""))
    if method == "settings":
        return ("On the device: Settings > System (or General management) > "
                "Reset options > Erase all data (factory reset). On a Fire "
                "tablet: Settings > Device Options > Reset to Factory "
                "Defaults.")
    if method == "recovery":
        return ("On the device (recovery menu): use the volume keys to "
                "choose 'Wipe data / factory reset', press Power, confirm, "
                "then 'Reboot system now'.")
    return ("Factory reset the device from its settings or recovery menu, "
            "then confirm below.")


# =============================================================================
# one call for everything (used by the window)
# =============================================================================
def read_phone(p):
    if p["platform"] == "ios":
        info = ios_info(p["id"])
        checks = [] if info.get("error") else ios_checks(p["id"], info)
    else:
        info = android_info(p["id"])
        checks = [] if info.get("error") else android_checks(p["id"], info)
    return info, checks


def overall_check(checks):
    res = [c["result"] for c in checks]
    if "BLOCKED" in res:
        return "BLOCKED"
    if "CHECK" in res:
        return "CHECK BY HAND"
    return "CLEAR"


if __name__ == "__main__":
    print("PhoneSeal core v%s" % VERSION)
    for p in list_phones():
        print("\n== %s %s (%s)" % (p["label"], p["id"], p["state"]))
        if p["state"] != "ready":
            print("   not ready: unlock the phone and tap Trust / allow "
                  "USB debugging")
            continue
        info, checks = read_phone(p)
        print(json.dumps({"info": info, "checks": checks}, indent=2))
        print("   overall:", overall_check(checks))
