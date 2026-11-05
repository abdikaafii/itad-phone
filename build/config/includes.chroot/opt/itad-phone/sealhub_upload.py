#!/usr/bin/env python3
"""
sealhub_upload.py - send finished reports to SealHub (v1.1.0)

Used by LaptopSeal, PhoneSeal and SwitchSeal (the same file in all three). Plain Python 3, no extra packages.
Nothing in here may ever stop a report from being saved: every public
function catches its own errors and returns a result instead.

How it works
  1. The report is always saved on the USB first (TXT, JSON, PDF, LOG).
  2. queue_report() also writes  <report>.sealhub.json  next to them. That small
     file is the SealHub version of the report.
  3. send_pending() sends every .sealhub.json that has not been sent yet,
     together with the PDF, TXT and JSON of the same report. When SealHub says
     OK, a marker file  <report>.sealhub.json.sent  is written, so the same
     report is never sent twice. (If it were, SealHub recognises it and does not
     make a copy.)
  4. No network? Nothing is lost. The report stays queued on the USB and goes
     out the next time a report is finished with a network connection.

Settings: a file called  sealhub.conf  on the USB, in the same place as
technicians.txt:
    {
      "url": "https://sealhub.onrender.com",
      "token": "sh_..."
    }
(or the environment variables SEALHUB_URL and SEALHUB_TOKEN).

Check it by hand on the boot USB:   python3 sealhub_upload.py --check
"""
import base64
import hashlib
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

VERSION = "1.1.0"
CONF_NAME = "sealhub.conf"
QUEUE_SUFFIX = ".sealhub.json"
ATTACH_EXT = (".pdf", ".txt", ".json")
MAX_ATTACH = 10 * 1024 * 1024
TIMEOUT = 60
UA = "Seal-SealHub/" + VERSION


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------
def config_dirs(out_dir, extra=()):
    """Same places as technicians.txt, plus the top of the Ventoy partition
    (out_dir is its ITAD_REPORTS folder)."""
    dirs = []
    if out_dir:
        dirs.append(out_dir)
        if os.path.basename(os.path.normpath(out_dir)) == "ITAD_REPORTS":
            dirs.append(os.path.dirname(os.path.normpath(out_dir)))
    dirs += ["/mnt/itad", "/media/ITAD_DATA", "/mnt/ITAD_DATA"]
    dirs += list(extra)
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def load_config(out_dir, extra=()):
    """Returns (url, token, problem). problem is '' when all is fine and
    'missing' when SealHub simply is not set up on this USB."""
    url = os.environ.get("SEALHUB_URL", "").strip()
    token = os.environ.get("SEALHUB_TOKEN", "").strip()
    problem = ""
    if not (url and token):
        for d in config_dirs(out_dir, extra):
            path = os.path.join(d, CONF_NAME)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    conf = json.load(fh)
                url = url or str(conf.get("url", "")).strip()
                token = token or str(conf.get("token", "")).strip()
            except Exception as e:
                problem = "%s is not valid (%s)" % (path, str(e)[:80])
                continue
            if url and token:
                problem = ""
                break
    if not (url and token):
        return "", "", problem or "missing"
    if "://" not in url:
        url = "https://" + url
    return url.rstrip("/"), token, ""


# --------------------------------------------------------------------------
# turn a Seal report (laptop, phone or switch) into a SealHub report
# --------------------------------------------------------------------------
def _clean(v, n=300):
    return str(v if v is not None else "").replace("\r", " ").replace("\n", "; ").strip()[:n]


def _put(d, key, value, n=300):
    value = _clean(value, n)
    if value and value != "-":
        d[key] = value


def _tested_at(rep):
    """Report time as UTC ISO text. The report keeps local Dublin time."""
    text = str(rep.get("finished") or "").strip()
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        try:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Dublin"))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uid(rep, serial):
    """Stable id: saving the same finished report again must never make a second one."""
    return hashlib.sha256(("%s|%s|%s|%s" % (
        serial, rep.get("job_id"), rep.get("started"), rep.get("finished"))).encode()).hexdigest()[:40]


def detect_kind(rep):
    if isinstance(rep.get("device"), dict) and "ios" in rep["device"]:
        return "switch"
    if isinstance(rep.get("device"), dict):
        return "phone"
    return "laptop"


def build_payload(rep, kind=None):
    """SealHub version of one report (a dict, ready for JSON)."""
    kind = kind or detect_kind(rep)
    if kind == "phone":
        return _payload_phone(rep)
    if kind == "switch":
        return _payload_switch(rep)
    return _payload_laptop(rep)


def _payload_phone(rep):
    d = rep.get("device") or {}
    overall = str(rep.get("overall") or "").upper()
    result = overall if overall in ("PASS", "FAIL") else "REVIEW"
    imeis = [str(x) for x in (d.get("imei") or []) if x]
    serial = _clean(d.get("serial") or (imeis[0] if imeis else "") or rep.get("asset_id") or "UNKNOWN", 80)
    summary = "; ".join(str(r) for r in (rep.get("reasons") or []))[:380]
    if overall and result == "REVIEW":
        summary = ("%s. %s" % (overall.capitalize(), summary)).strip()
    if rep.get("test_mode"):
        summary = ("TEST MODE - not for customer use. " + summary).strip()
    if not summary and result == "PASS":
        summary = "All checks and tests passed."

    hardware = {}
    _put(hardware, "Make and model", "%s %s" % (d.get("make") or "", d.get("model") or ""))
    _put(hardware, "Model ID", d.get("model_id"))
    _put(hardware, "Serial", d.get("serial"))
    _put(hardware, "IMEI", ", ".join(imeis))
    _put(hardware, "OS", d.get("os"))
    if d.get("storage_gb"):
        hardware["Storage"] = "%s GB" % d.get("storage_gb")
    bat = []
    if d.get("battery_health_pct") is not None:
        bat.append("health %s%%" % d["battery_health_pct"])
    if d.get("battery_cycles") is not None:
        bat.append("%s cycles" % d["battery_cycles"])
    if d.get("battery_level"):
        bat.append("charge %s%%" % d["battery_level"])
    _put(hardware, "Battery", ", ".join(bat))
    for item in d.get("details") or []:
        try:
            _sec, lab, val = item
        except (TypeError, ValueError):
            continue
        if _clean(lab, 60) and _clean(lab, 60) not in hardware:
            _put(hardware, _clean(lab, 60), val)
        if len(hardware) >= 40:
            break

    checks = {}
    for c in rep.get("checks") or []:
        line = _clean(c.get("result"), 20)
        if c.get("detail"):
            line += " - " + _clean(c.get("detail"), 160)
        _put(checks, _clean(c.get("name"), 60) or "Check", line)
    if rep.get("passcode_unknown"):
        checks["Passcode"] = "Unknown - component tests could not be done"

    w = rep.get("wipe") or {}
    wipe = {}
    _put(wipe, "Status", w.get("state"))
    _put(wipe, "Method", w.get("method"))
    _put(wipe, "Verification", w.get("verify_note"))
    _put(wipe, "Started", w.get("started"))
    _put(wipe, "Finished", w.get("finished"))
    _put(wipe, "Duration", w.get("duration"))

    tests = []
    for t in rep.get("tests") or []:
        item = {"name": _clean(t.get("component") or "-", 60), "result": _clean(t.get("status"), 20)}
        note = _clean("; ".join(str(n) for n in (t.get("notes") or [])), 200)
        if note:
            item["note"] = note
        tests.append(item)

    obs = rep.get("observations") or {}
    bits = []
    if obs.get("grade"):
        bits.append("Cosmetic grade: %s." % obs.get("grade"))
    if str(obs.get("notes") or "").strip():
        bits.append("Notes: %s" % str(obs.get("notes")).strip())

    data = {}
    for key, val in (("hardware", hardware), ("checks", checks), ("wipe", wipe)):
        if val:
            data[key] = val
    if tests:
        data["tests"] = tests
    if bits:
        data["observations"] = " ".join(bits)[:1500]
    _put(data, "Location", rep.get("location"))
    _put(data, "Company", rep.get("company"))
    _put(data, "Job started", rep.get("started"))
    _put(data, "Job duration", rep.get("duration"))
    _put(data, "Erasure ID", rep.get("erasure_id"))
    _put(data, "Tool", "PhoneSeal %s" % (rep.get("version") or ""))
    if (rep.get("integrity") or {}).get("signed"):
        data["Digitally signed"] = "Yes (see the attached .json file)"
    return {"uid": _uid(rep, serial), "device_type": "phone", "serial": serial,
            "asset_id": _clean(rep.get("asset_id"), 80), "job_id": _clean(rep.get("job_id"), 80),
            "technician": _clean(rep.get("technician"), 80), "result": result, "summary": summary,
            "tested_at": _tested_at(rep), "data": data}


def _payload_switch(rep):
    d = rep.get("device") or {}
    result = "PASS" if str(rep.get("overall") or "").upper() == "PASS" else "FAIL"
    serial = _clean(d.get("serial") or "UNKNOWN", 80)
    summary = "; ".join(str(r) for r in (rep.get("reasons") or []))[:380]
    if not summary and result == "PASS":
        summary = "Switch wiped to factory defaults and verified."

    hardware = {}
    _put(hardware, "Make and model", "%s %s" % (d.get("make") or "", d.get("model") or ""))
    _put(hardware, "IOS version", d.get("ios"))
    if d.get("ports") is not None:
        hardware["Ports"] = "%s detected, %s with link" % (d.get("ports"), d.get("linked"))
    for i, line in enumerate(d.get("port_lines") or [], start=1):
        _put(hardware, "Port type %d" % i, line)

    wipe = {}
    wipe["Status"] = "Wiped" if rep.get("boot_ok") else "Switch did not come back after reload"
    _put(wipe, "Started", rep.get("wipe_started"))
    _put(wipe, "Finished", rep.get("wipe_finished"))
    for i, step in enumerate(rep.get("sanitisation") or [], start=1):
        _put(wipe, "Step %d" % i, step)
    _put(wipe, "Console log SHA-256", rep.get("console_log_sha256"), 80)

    checks = {"Switch came back after reload": "PASS" if rep.get("boot_ok") else "FAIL"}
    for c in rep.get("checks") or []:
        _put(checks, _clean(c.get("name"), 90) or "Check", c.get("result"))

    data = {"hardware": hardware, "checks": checks, "wipe": wipe}
    if str(rep.get("observation") or "").strip():
        data["observations"] = _clean(rep.get("observation"), 1500)
    _put(data, "Location", rep.get("location"))
    _put(data, "Company", rep.get("company"))
    _put(data, "Job started", rep.get("started"))
    _put(data, "Erasure ID", rep.get("erasure_id"))
    _put(data, "Tool", "SwitchSeal %s" % (rep.get("version") or ""))
    if (rep.get("integrity") or {}).get("signed"):
        data["Digitally signed"] = "Yes (see the attached .json file)"
    return {"uid": _uid(rep, serial), "device_type": "switch", "serial": serial,
            "asset_id": _clean(rep.get("asset_id"), 80), "job_id": _clean(rep.get("job_id"), 80),
            "technician": _clean(rep.get("technician"), 80), "result": result, "summary": summary,
            "tested_at": _tested_at(rep), "data": data}


def _payload_laptop(rep):
    """SealHub version of one LaptopSeal report."""
    overall = str(rep.get("overall") or "").upper()
    result = overall if overall in ("PASS", "FAIL") else "REVIEW"
    reasons = [str(r).split(":")[0] for r in (rep.get("reasons") or [])]
    summary = "; ".join(reasons)[:380]
    if rep.get("test_mode"):
        summary = ("TEST MODE - not for customer use. " + summary).strip()
    if not summary and result == "PASS":
        summary = "All checks and tests passed."

    hardware = {}
    _put(hardware, "Make and model", rep.get("make_model"))
    _put(hardware, "CPU", rep.get("cpu"))
    _put(hardware, "RAM", rep.get("ram"))
    _put(hardware, "Screen", rep.get("screen"))
    _put(hardware, "Storage", rep.get("storage"), 400)
    _put(hardware, "GPU", rep.get("gpu"))
    _put(hardware, "BIOS", rep.get("bios"))
    _put(hardware, "Boot mode", rep.get("boot_mode"))
    _put(hardware, "Chassis", rep.get("chassis"))

    checks = {}
    _put(checks, "Absolute lock", rep.get("absolute"))
    _put(checks, "Enrolment (MDM / Autopilot)", rep.get("enrolment"))
    _put(checks, "Pre-wipe check", rep.get("check_result"))
    if rep.get("test_mode"):
        checks["Test mode"] = "YES - check and wipe were skipped"

    wipe = {}
    _put(wipe, "Status", rep.get("wipe_state"))
    _put(wipe, "Started", rep.get("wipe_started"))
    _put(wipe, "Finished", rep.get("wipe_finished"))
    _put(wipe, "Duration", rep.get("wipe_duration"))
    for i, e in enumerate(rep.get("erasures") or [], start=1):
        label = " ".join(x for x in (_clean(e.get("model"), 60),
                                     ("%s GB" % e.get("capacity_gb")) if e.get("capacity_gb") else "") if x)
        line = "%s - %s - %s" % (label or "Drive", _clean(e.get("method"), 80) or "-", _clean(e.get("status"), 40) or "-")
        if e.get("serial"):
            line += " (drive serial %s)" % _clean(e.get("serial"), 40)
        wipe["Drive %d" % i] = line
    _put(wipe, "Certificate SHA-256", rep.get("certificate"), 80)
    if not rep.get("wipe_state") and not rep.get("erasures"):
        wipe = {}

    tests = []
    for t in rep.get("tests") or []:
        item = {"name": _clean(t.get("component") or t.get("name") or "-", 60),
                "result": _clean(t.get("status") or "", 20)}
        note = _clean("; ".join(str(n) for n in (t.get("notes") or [])), 200)
        if note:
            item["note"] = note
        tests.append(item)

    obs = rep.get("observations") or {}
    obs_bits = []
    if obs.get("grade"):
        obs_bits.append("Cosmetic grade: %s." % obs.get("grade"))
    if obs.get("issues"):
        obs_bits.append("Issues: %s." % ", ".join(str(x) for x in obs.get("issues")))
    if str(obs.get("notes") or "").strip():
        obs_bits.append("Notes: %s" % str(obs.get("notes")).strip())

    data = {}
    if hardware:
        data["hardware"] = hardware
    if checks:
        data["checks"] = checks
    if wipe:
        data["wipe"] = wipe
    if tests:
        data["tests"] = tests
    if obs_bits:
        data["observations"] = " ".join(obs_bits)[:1500]
    extra = {}
    _put(extra, "Location", rep.get("location"))
    _put(extra, "Company", rep.get("company"))
    _put(extra, "Job started", rep.get("started"))
    _put(extra, "Job duration", rep.get("duration"))
    _put(extra, "Tool", "LaptopSeal %s" % (rep.get("version") or ""))
    if (rep.get("integrity") or {}).get("signed"):
        extra["Digitally signed"] = "Yes (see the attached .json file)"
    data.update(extra)

    # Stable id: saving the same finished report again must never make a second one.
    uid = _uid(rep, rep.get("serial"))
    return {
        "uid": uid, "device_type": "laptop",
        "serial": _clean(rep.get("serial") or "UNKNOWN", 80),
        "asset_id": _clean(rep.get("asset_id"), 80), "job_id": _clean(rep.get("job_id"), 80),
        "technician": _clean(rep.get("technician"), 80),
        "result": result, "summary": summary, "tested_at": _tested_at(rep), "data": data,
    }


# --------------------------------------------------------------------------
# queue folder handling
# --------------------------------------------------------------------------
def _queue_files(report_dir):
    try:
        names = sorted(n for n in os.listdir(report_dir) if n.endswith(QUEUE_SUFFIX))
    except OSError:
        return []
    return [os.path.join(report_dir, n) for n in names]


def _done(path):
    return os.path.exists(path + ".sent") or os.path.exists(path + ".rejected")


def queue_report(rep, report_dir, base, kind=None):
    """Write <base>.sealhub.json next to the report. Returns its path, or ''.
    Saving the same report again (same id) does not queue a second copy."""
    try:
        payload = build_payload(rep, kind)
        for old in _queue_files(report_dir):
            try:
                with open(old, encoding="utf-8") as fh:
                    if json.load(fh).get("uid") == payload["uid"]:
                        return old
            except Exception:
                continue
        path = os.path.join(report_dir, base + QUEUE_SUFFIX)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        return path
    except Exception:
        return ""


def _attachments(queue_path):
    stem = queue_path[:-len(QUEUE_SUFFIX)]
    out = []
    for ext in ATTACH_EXT:
        p = stem + ext
        try:
            if os.path.isfile(p) and 0 < os.path.getsize(p) <= MAX_ATTACH:
                with open(p, "rb") as fh:
                    out.append({"name": os.path.basename(p),
                                "content_b64": base64.b64encode(fh.read()).decode("ascii")})
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------
# talking to SealHub
# --------------------------------------------------------------------------
def _request(method, url, token, payload=None):
    """Returns (status, body_dict). Raises URLError/OSError when there is no connection."""
    data = None
    headers = {"Authorization": "Bearer " + token, "User-Agent": UA}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            body = {"error": str(e.reason)}
        return e.code, body


def _connection_text(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY" in str(reason):
        return "secure connection failed - check the laptop clock and date"
    if isinstance(reason, socket.timeout) or "timed out" in str(reason):
        return "SealHub did not answer in time"
    return "no network connection"


def send_report(rep, saved, out_dir, report_dir, kind=None):
    """Queue this report and send everything that is waiting. Never raises.

    Returns {"state": ..., "text": ...} where state is one of
    sent, duplicate, not_set_up, offline, refused, error.
    """
    try:
        base = None
        for p in saved or []:
            if p.endswith(".txt") or p.endswith(".pdf"):
                base = os.path.splitext(os.path.basename(p))[0]
                break
        if not base:
            base = "SN_%s_%s" % (_clean(build_payload(rep, kind)["serial"], 40).replace("/", "_"),
                                 datetime.now().strftime("%Y%m%d-%H%M%S"))
        queued = queue_report(rep, report_dir, base, kind)
        url, token, problem = load_config(out_dir, extra=[report_dir])
        if problem == "missing":
            return {"state": "not_set_up",
                    "text": "SealHub: not set up - put sealhub.conf on the USB next to technicians.txt. "
                            "The report is saved on the USB and can be sent later."}
        if problem or not url:
            return {"state": "error", "text": "SealHub: " + (problem or "settings missing")}
        if not queued:
            return {"state": "error", "text": "SealHub: could not prepare the report for sending"}
        return send_pending(url, token, report_dir, first=queued)
    except Exception as e:  # never let SealHub trouble reach the technician's flow
        return {"state": "error", "text": "SealHub: unexpected problem (%s). The report is saved on the USB." % str(e)[:80]}


def send_pending(url, token, report_dir, first=None):
    """Send every unsent .sealhub.json in report_dir ('first' goes first)."""
    todo = [p for p in _queue_files(report_dir) if not _done(p)]
    if first and first in todo:
        todo.remove(first)
        todo.insert(0, first)
    first_state, first_id, first_why = None, "", ""
    others = 0            # earlier reports that went out in this round
    handled = 0
    for path in todo:
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            files = _attachments(path)
            if files:
                payload["files"] = files
            status, body = _request("POST", url + "/api/reports", token, payload)
        except (urllib.error.URLError, OSError) as e:
            left = len(todo) - handled
            return {"state": "offline", "sent": others,
                    "text": "SealHub: %s. %d report%s saved on the USB, will be sent next time." % (
                        _connection_text(e), left, "" if left == 1 else "s")}
        except ValueError as e:
            status, body = 400, {"error": "unreadable report file (%s)" % str(e)[:60]}
        handled += 1
        if status in (200, 201) and body.get("ok"):
            dup = bool(body.get("duplicate"))
            _mark(path, ".sent", "%s%s" % (body.get("certificate_id"), " (already there)" if dup else ""))
            if path == first:
                first_state = "duplicate" if dup else "sent"
                first_id = body.get("certificate_id") or ""
            elif not dup:
                others += 1
        elif status in (401, 403):
            return {"state": "refused",
                    "text": "SealHub: the token was not accepted. Ask your supervisor for a new token "
                            "(Settings > API tokens). The report is saved on the USB."}
        elif status == 400:
            why = str(body.get("error"))[:80]
            _mark(path, ".rejected", why)
            if path == first:
                first_state, first_why = "refused", why
        else:
            return {"state": "error",
                    "text": "SealHub answered %s: %s. The report is saved on the USB and will be sent "
                            "next time." % (status, str(body.get("error", ""))[:80])}
    tail = (" + %d earlier report%s" % (others, "" if others == 1 else "s")) if others else ""
    if first_state == "sent":
        return {"state": "sent", "sent": 1 + others, "text": "SealHub: report sent (%s)%s" % (first_id, tail)}
    if first_state == "duplicate":
        return {"state": "duplicate", "sent": others,
                "text": "SealHub: this report was already on SealHub (%s)%s" % (first_id, tail)}
    if first_state == "refused":
        return {"state": "refused", "sent": others,
                "text": "SealHub refused the report (%s). It is saved on the USB.%s" % (first_why, tail)}
    if others:
        return {"state": "sent", "sent": others,
                "text": "SealHub: %d earlier report%s sent" % (others, "" if others == 1 else "s")}
    return {"state": "sent", "sent": 0, "text": "SealHub: nothing waiting to send."}


def _mark(path, suffix, text):
    try:
        with open(path + suffix, "w", encoding="utf-8") as fh:
            fh.write("%s\n%s\n" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), text))
    except OSError:
        pass


# --------------------------------------------------------------------------
# check by hand
# --------------------------------------------------------------------------
def main():
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ITAD_DATA", "/mnt/itad/ITAD_REPORTS")
    url, token, problem = load_config(out_dir)
    print("Looked for %s in: %s" % (CONF_NAME, ", ".join(config_dirs(out_dir))))
    if problem:
        print("Problem: %s" % ("sealhub.conf not found" if problem == "missing" else problem))
        return 1
    print("Address: %s   Token: %s..." % (url, token[:9]))
    try:
        status, body = _request("GET", url + "/api/ping", token)
    except (urllib.error.URLError, OSError) as e:
        print("Could not connect: %s" % _connection_text(e))
        return 1
    if status == 200:
        print("OK - connected to SealHub (token name: %s)" % body.get("token"))
        return 0
    print("SealHub answered %s: %s" % (status, body.get("error", body)))
    return 1


if __name__ == "__main__":
    sys.exit(main() if (len(sys.argv) > 1 and sys.argv[1] == "--check") else
             (print(__doc__) or 0))
