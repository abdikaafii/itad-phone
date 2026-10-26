#!/usr/bin/env python3
"""
phone_core.py - ITAD PhoneSeal: find phones, read them, lock checks, wipe
(v0.1.0)

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

VERSION = "0.1.0"


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
}

ANDROID_HEALTH = {"1": "Unknown", "2": "Good", "3": "Overheat", "4": "Dead",
                  "5": "Over voltage", "6": "Failure", "7": "Cold"}


# =============================================================================
# finding phones
# =============================================================================
def list_phones():
    """All phones on USB: [{platform, id, state, label}]"""
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
            out.append({"platform": "ios", "id": udid, "state": st,
                        "label": "iPhone / iPad"})
    if have("adb"):
        rc, o, _ = run(["adb", "devices", "-l"], 15)
        for ln in o.splitlines()[1:]:
            parts = ln.split()
            if len(parts) < 2:
                continue
            ser, st = parts[0], parts[1]
            model = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p[6:].replace("_", " ")
            state = {"device": "ready", "unauthorized": "trust",
                     "offline": "offline"}.get(st, st)
            out.append({"platform": "android", "id": ser, "state": state,
                        "label": model or "Android phone"})
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


def ios_info(udid):
    r = {"platform": "ios", "id": udid, "notes": []}
    rc, o, e = run(["ideviceinfo", "-u", udid], 20)
    if rc != 0:
        r["error"] = (e or o).strip()[:200] or "could not read the iPhone"
        return r
    k = _kv(o)
    r["raw_keys"] = sorted(k.keys())
    pt = k.get("ProductType", "")
    r["make"] = "Apple"
    r["model"] = IPHONE_NAMES.get(pt, pt or "unknown")
    r["model_id"] = pt
    r["model_number"] = (k.get("ModelNumber", "") +
                         k.get("RegionInfo", "")).strip()
    r["os"] = "iOS %s" % k.get("ProductVersion", "?")
    r["serial"] = k.get("SerialNumber", "")
    imeis = [k.get("InternationalMobileEquipmentIdentity", ""),
             k.get("InternationalMobileEquipmentIdentity2", "")]
    r["imei"] = [i for i in imeis if i]
    r["colour"] = k.get("DeviceColor", "")
    r["activation_state"] = k.get("ActivationState", "unknown")
    r["passcode_set"] = k.get("PasswordProtected", "unknown")
    # storage
    rc, o, _ = run(["ideviceinfo", "-u", udid, "-q", "com.apple.disk_usage"],
                   15)
    dk = _kv(o)
    try:
        r["storage_gb"] = round(int(dk.get("TotalDiskCapacity", "0")) / 1e9)
    except ValueError:
        r["storage_gb"] = None
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
        except Exception:
            r["notes"].append("battery health not readable")
    return r


def ios_checks(udid, info):
    """Lock checks. Each: {name, result CLEAR/BLOCKED/CHECK, detail, how}"""
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


def ios_wipe(udid, method, log=print):
    """Run the wipe. Returns {ok, method, note}."""
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


def ios_verify_wiped(udid, wait=600, log=print):
    """After a wipe the iPhone restarts on the Hello / activation screen.
    It then shows ActivationState Unactivated and is no longer paired."""
    end = time.time() + wait
    while time.time() < end:
        rc, o, _ = run(["idevice_id", "-l"], 10)
        if udid in o:
            rc2, o2, _ = run(["ideviceinfo", "-u", udid, "-s", "-k",
                              "ActivationState"], 15)
            st = o2.strip()
            if st and st != "Activated":
                return True, "phone restarted on the setup screen " \
                             "(ActivationState: %s)" % st
        time.sleep(5)
    return False, "phone did not come back on the setup screen in time"


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


def android_info(ser):
    r = {"platform": "android", "id": ser, "notes": []}
    rc, o, e = adb(ser, "get-state")
    if o.strip() != "device":
        r["error"] = "phone not ready over USB (%s)" % (o or e).strip()
        return r
    r["make"] = prop(ser, "ro.product.manufacturer").title() or "unknown"
    r["model"] = (prop(ser, "ro.product.marketname") or
                  prop(ser, "ro.product.model") or "unknown")
    r["model_id"] = prop(ser, "ro.product.model")
    r["os"] = "Android %s" % (prop(ser, "ro.build.version.release") or "?")
    r["serial"] = prop(ser, "ro.serialno") or ser
    imei = android_imei(ser)
    r["imei"] = [imei] if imei else []
    if not imei:
        r["notes"].append("IMEI not readable over USB on this Android "
                          "version - dial *#06# and type it in")
    r["encrypted"] = prop(ser, "ro.crypto.state") or "unknown"
    r["encryption_type"] = prop(ser, "ro.crypto.type") or ""
    rc, o, _ = adb(ser, "shell", "df", "/data")
    m = re.search(r"\s(\d+)\s+\d+\s+\d+\s+\d+%", o)
    r["storage_gb"] = round(int(m.group(1)) * 1024 / 1e9) if m else None
    rc, o, _ = adb(ser, "shell", "dumpsys", "battery")
    bk = _kv(o)
    r["battery_level"] = bk.get("level", "")
    r["battery_charging"] = "true" if bk.get("status") == "2" else "false"
    r["battery_status"] = ANDROID_HEALTH.get(bk.get("health", ""), "unknown")
    r["battery_health_pct"] = None
    r["battery_cycles"] = None
    for base in ("/sys/class/power_supply/battery",
                 "/sys/class/power_supply/bms"):
        rc, o, _ = adb(ser, "shell", "cat", base + "/cycle_count")
        if rc == 0 and o.strip().isdigit():
            r["battery_cycles"] = int(o.strip())
        rc1, full, _ = adb(ser, "shell", "cat", base + "/charge_full")
        rc2, des, _ = adb(ser, "shell", "cat", base + "/charge_full_design")
        if rc1 == 0 and rc2 == 0 and full.strip().isdigit() and \
                des.strip().isdigit() and int(des) > 0:
            r["battery_health_pct"] = min(100, round(100.0 * int(full) /
                                                     int(des)))
        if r["battery_cycles"] is not None or r["battery_health_pct"]:
            break
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
