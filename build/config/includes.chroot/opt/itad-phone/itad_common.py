#!/usr/bin/env python3
"""
itad_common.py - pieces shared with LaptopSeal (v0.1.0)

Copied from LaptopSeal laptop_window.py so both tools behave the same:
technician logins (technicians.txt on the ITAD_DATA stick / USB B, also
SwitchSeal "Name:password" lines), where reports are saved, and the
Ed25519 report signature (keys folder on the ITAD_DATA stick).
"""
import hashlib
import hmac
import json
import os
import re
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Dublin")
except Exception:
    TZ = None

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
TECH_FILE = "technicians.txt"


PBKDF_ITER = 200000


MAX_TRIES = 5          # wrong passwords before a short lock


LOCK_SECONDS = 30


BAD_SERIALS = {
    "", "none", "default string", "to be filled by o.e.m.",
    "to be filled by o.e.m", "system serial number", "not specified",
    "0", "n/a", "unknown", "o.e.m.", "oem", "chassis serial number",
    "0123456789", "1234567890",
}


STORE_NAMES = {
    "ITAD_DATA_created_on_boot_USB": "the ITAD_DATA part of the boot USB",
    "boot_stick_folder": "the boot USB (ITAD_REPORTS folder)",
    "USB_stick_folder": "the USB stick (ITAD_REPORTS folder)",
    "Ventoy_stick_folder": "the Ventoy USB (ITAD_REPORTS folder)",
}


SIGN_FIELDS = ("integrity",)


def now():
    return datetime.now(TZ) if TZ else datetime.now()


def fmt_time(t):
    return t.strftime("%Y-%m-%d %H:%M:%S") if t else ""


def fmt_dur(a, b):
    """'1 h 05 min' style duration between two times ('' if unknown)."""
    if not a or not b:
        return ""
    sec = max(0, int((b - a).total_seconds()))
    h, rem = divmod(sec, 3600)
    m, s_ = divmod(rem, 60)
    if h:
        return "%d h %02d min" % (h, m)
    if m:
        return "%d min %02d s" % (m, s_)
    return "%d s" % s_


def valid_serial(s):
    return bool(s) and str(s).strip().lower() not in BAD_SERIALS


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s)) or "UNKNOWN"


def store_name():
    w = os.environ.get("ITAD_DATA_WHERE", "")
    if w.startswith("ITAD_DATA_stick_"):
        return "the ITAD_DATA stick (USB B)"
    if w.startswith("ITAD_DATA_on_"):
        return "the ITAD_DATA drive (%s)" % w[len("ITAD_DATA_on_"):]
    return STORE_NAMES.get(w, "")


def pick_out_dir():
    env = os.environ.get("ITAD_DATA")
    if env and os.path.isdir(env) and os.access(env, os.W_OK):
        # launch.sh says whether this folder is on a stick (kept) or only
        # in memory; without that, only a mounted drive counts as kept
        flag = os.environ.get("ITAD_DATA_PERSIST")
        if flag in ("0", "1"):
            return env, flag == "1"
        real = os.path.realpath(env)
        on_disk = not real.startswith(("/tmp", "/run/user", "/dev/shm"))
        return env, on_disk
    for c in ("/mnt/itad", "/media/ITAD_DATA", "/mnt/ITAD_DATA"):
        if os.path.ismount(c) and os.access(c, os.W_OK):
            return c, True
    d = "/tmp/itad-reports"
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = os.path.expanduser("~/itad-reports")
        os.makedirs(d, exist_ok=True)
    return d, False


def tech_files(out_dir):
    seen, files = set(), []
    for base in (out_dir, "/mnt/itad", TOOLS_DIR):
        p = os.path.join(base, TECH_FILE)
        rp = os.path.realpath(p)
        if rp not in seen and os.path.isfile(p):
            seen.add(rp)
            files.append(p)
    return files


def parse_tech_line(ln):
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        return None, ""
    if ":" in ln:
        name, rest = ln.split(":", 1)
    else:
        name, rest = re.split(r",", ln, 1)[0], ""
    name = name.strip()
    rest = rest.strip()
    # LaptopSeal stores "pbkdf2_sha256$..." hashes; SwitchSeal stores the
    # password itself ("Name:password"). Both are accepted for sign-in.
    return (name or None), rest


def load_accounts(out_dir):
    """Returns {lower name: {"name": Name, "hash": stored hash or ""}}."""
    acc = {}
    for p in tech_files(out_dir):
        try:
            with open(p) as f:
                for ln in f:
                    name, h = parse_tech_line(ln)
                    if not name:
                        continue
                    key = name.lower()
                    if key not in acc or (h and not acc[key]["hash"]):
                        acc[key] = {"name": name, "hash": h, "file": p}
        except Exception:
            pass
    return acc


def hash_password(password, salt=None, iterations=PBKDF_ITER):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                             iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt.hex(), dk.hex())


def verify_password(password, stored):
    if stored and not stored.startswith("pbkdf2_sha256$"):
        # SwitchSeal-style line (password as written in technicians.txt)
        return hmac.compare_digest(stored.encode("utf-8"),
                                   password.encode("utf-8"))
    try:
        algo, it, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), int(it))
        return hmac.compare_digest(dk.hex(), want)
    except Exception:
        return False


def save_account(out_dir, name, password):
    """Adds or updates one technician. Returns the file path used."""
    path = os.path.join(out_dir, TECH_FILE)
    lines = []
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except Exception:
        lines = ["# LaptopSeal technicians. Passwords are stored as hashes only.",
                 "# Add technicians from the sign-in screen."]
    new_line = "%s:%s" % (name, hash_password(password))
    done = False
    for i, ln in enumerate(lines):
        n, _ = parse_tech_line(ln)
        if n and n.lower() == name.lower():
            lines[i] = new_line
            done = True
    if not done:
        lines.append(new_line)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def report_fingerprint(rep):
    """SHA-256 of the report content (everything except the signature)."""
    body = dict((k, v) for k, v in rep.items() if k not in SIGN_FIELDS)
    data = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sign_report(rep, out_dir, persistent):
    """Add rep["integrity"]: fingerprint + Ed25519 signature.
    The private key lives on the ITAD_DATA stick (keys/), never in the ISO.
    Without the stick the report gets a fingerprint but no signature."""
    fp = report_fingerprint(rep)
    integ = {"algorithm": "SHA-256 + Ed25519", "sha256": fp,
             "signature": "", "key_id": "", "signed": False}
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
    except Exception:
        integ["note"] = "cryptography module missing - not signed"
        rep["integrity"] = integ
        return integ
    if not persistent:
        integ["note"] = "no ITAD_DATA stick - not signed"
        rep["integrity"] = integ
        return integ
    kdir = os.path.join(out_dir, "keys")
    kpriv = os.path.join(kdir, "itad_signing_key.pem")
    kpub = os.path.join(kdir, "itad_signing_public.pem")
    try:
        os.makedirs(kdir, exist_ok=True)
        if os.path.exists(kpriv):
            with open(kpriv, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), None)
        else:
            key = Ed25519PrivateKey.generate()
            with open(kpriv, "wb") as f:
                f.write(key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption()))
            os.chmod(kpriv, 0o600)
        pub = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        if not os.path.exists(kpub):
            with open(kpub, "wb") as f:
                f.write(key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo))
        integ["signature"] = key.sign(fp.encode("ascii")).hex()
        integ["key_id"] = hashlib.sha256(pub).hexdigest()[:16]
        integ["public_key"] = pub.hex()
        integ["signed"] = True
    except Exception as ex:
        integ["note"] = "signing failed: %s" % str(ex)[:80]
    rep["integrity"] = integ
    return integ
