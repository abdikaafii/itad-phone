#!/usr/bin/env python3
"""
phone_report.py - PhoneSeal result and signed PDF certificate (v0.2.0)

Same look as the LaptopSeal certificate: dark-blue ITAD header, result
badge, QR code + Ed25519 signature on page 1, coloured results.
"""
import json
import os

from itad_common import sign_report

VERSION = "0.2.0"
NOT_FITTED = "N/A"
NOT_TESTED = "NOT TESTED"      # passcode unknown


def compute_overall(rep):
    """PASS only when everything needed was done and passed."""
    reasons, fail = [], False
    for c in rep.get("checks", []):
        if c["result"] == "BLOCKED":
            fail = True
            reasons.append("%s: LOCKED" % c["name"])
    w = rep.get("wipe", {})
    if w.get("state") == "FAILED":
        fail = True
        reasons.append("Wipe failed")
    for t in rep.get("tests", []):
        if t.get("status") == "FAIL":
            fail = True
            reasons.append("%s failed" % t["component"])
    if fail:
        return "FAIL", reasons
    for c in rep.get("checks", []):
        if c["result"] == "CHECK":
            reasons.append("%s not confirmed" % c["name"])
    if w.get("state") != "WIPED":
        reasons.append("Wipe not done (%s)" % (w.get("state") or
                                               "not started").lower())
    nt = [t for t in rep.get("tests", []) if t.get("status") == NOT_TESTED]
    for t in rep.get("tests", []):
        if t.get("status") not in ("PASS", NOT_FITTED, NOT_TESTED):
            notes = " ".join(t.get("notes") or [])
            reasons.append("%s %s" % (t["component"], "not tested" if
                                      "Not tested" in notes or not notes
                                      else "needs attention: " + notes[:60]))
    if rep.get("test_mode"):
        reasons.insert(0, "TEST MODE - not for customer devices")
    if nt:
        why = "%d component tests not done - passcode unknown" % len(nt)
        if not reasons:
            # wiped and lock-free, but could not be tested
            return "WIPED - NOT TESTED", [why]
        reasons.append(why)
    return ("INCOMPLETE" if reasons else "PASS"), reasons


def render_txt(rep):
    L = ["ITAD PHONE REPORT", "RESULT: %s" % rep["overall"]]
    L += ["  - %s" % r for r in rep["reasons"]]
    L.append("=" * 60)
    d = rep["device"]
    for k, v in (("Job ID", rep["job_id"]), ("Asset ID", rep["asset_id"]),
                 ("Technician", rep["technician"]),
                 ("Location", rep["location"]),
                 ("Started", rep["started"]), ("Finished", rep["finished"]),
                 ("Duration", rep["duration"]),
                 ("Make / model", "%s %s" % (d.get("make", ""),
                                             d.get("model", ""))),
                 ("Model ID", d.get("model_id")), ("Serial", d.get("serial")),
                 ("IMEI", ", ".join(d.get("imei") or []) or "-"),
                 ("OS", d.get("os")), ("Storage", "%s GB" % (
                     d.get("storage_gb") or "?")),
                 ("Battery", battery_text(d))):
        L.append("%-14s: %s" % (k, v or "-"))
    L += ["", "LOCK CHECKS"]
    for c in rep["checks"]:
        L.append("%-28s %-8s %s" % (c["name"], c["result"], c.get("detail",
                                                                  "")))
    w = rep["wipe"]
    L += ["", "WIPE", "%-14s: %s" % ("State", w.get("state")),
          "%-14s: %s" % ("Method", w.get("method", "-")),
          "%-14s: %s" % ("Verification", w.get("verify_note", "-")),
          "%-14s: %s - %s (%s)" % ("Time", w.get("started", "-"),
                                   w.get("finished", "-"),
                                   w.get("duration", "-"))]
    L += ["", "COMPONENTS"]
    for t in rep["tests"]:
        L.append("%-18s %-6s %s" % (t["component"], t["status"],
                                    "; ".join(t.get("notes") or [])))
    o = rep.get("observations", {})
    L += ["", "OBSERVATIONS", "%-14s: %s" % ("Grade", o.get("grade") or "-"),
          "%-14s: %s" % ("Notes", o.get("notes") or "-")]
    integ = rep.get("integrity") or {}
    if integ:
        L += ["", "INTEGRITY", "%-14s: %s" % ("SHA-256", integ.get("sha256")),
              "%-14s: %s" % ("Signed", ("Ed25519, key ID %s" %
                                        integ.get("key_id"))
                             if integ.get("signed") else "NOT signed")]
    L.append("Tool: ITAD PhoneSeal v%s" % rep.get("version", VERSION))
    return "\n".join(L) + "\n"


def battery_text(d):
    parts = []
    if d.get("battery_health_pct") is not None:
        parts.append("health %s%%" % d["battery_health_pct"])
    if d.get("battery_cycles") is not None:
        parts.append("%s cycles" % d["battery_cycles"])
    if d.get("battery_level"):
        parts.append("charge %s%%" % d["battery_level"])
    if d.get("battery_status"):
        parts.append(d["battery_status"])
    return ", ".join(parts) or "not readable"


def qr_text(rep):
    integ = rep.get("integrity") or {}
    d = rep["device"]
    return "ITAD-PHONE|%s|%s|%s|%s|%s|%s|%s" % (
        rep["job_id"], rep["asset_id"], d.get("serial", ""),
        (d.get("imei") or [""])[0], rep["overall"],
        integ.get("sha256", "")[:32], integ.get("key_id", "") or "unsigned")


def write_pdf(path, rep):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, Paragraph,
                                    SimpleDocTemplate, Spacer, Table,
                                    TableStyle)
    W, H = A4
    NAVY_C = colors.HexColor("#050F22")
    BLUE_C = colors.HexColor("#2E9BFF")
    CYAN_C = colors.HexColor("#38BDF8")
    INK = colors.HexColor("#0B1F40")
    GREY = colors.HexColor("#5B6B84")
    LINE = colors.HexColor("#D5DEEA")
    SOFT = colors.HexColor("#F3F6FB")
    BG = {"PASS": "#DDF5EA", "CLEAR": "#DDF5EA", "FAIL": "#FBE1E1",
          "BLOCKED": "#FBE1E1", "CHECK": "#FFF3D1", "WARN": "#FFF3D1",
          NOT_FITTED: "#ECEFF4", NOT_TESTED: "#ECEFF4"}
    FG = {"PASS": "#13774D", "CLEAR": "#13774D", "FAIL": "#B3261E",
          "BLOCKED": "#B3261E", "CHECK": "#8A5A00", "WARN": "#8A5A00",
          NOT_FITTED: "#5B6B84", NOT_TESTED: "#5B6B84"}
    RC = {"PASS": "#1FA971", "FAIL": "#C62F2F"}.get(rep["overall"], "#D9A21B")
    integ = rep.get("integrity") or {}
    d = rep["device"]

    def ps(n, size=9, bold=False, color=INK, align=0):
        return ParagraphStyle(n, fontName="Helvetica-Bold" if bold else
                              "Helvetica", fontSize=size, leading=size * 1.3,
                              textColor=color, alignment=align)
    s_txt, s_small = ps("t", 8.6), ps("s", 7.2, color=GREY)
    s_key, s_val, s_h = ps("k", 7.6, True, GREY), ps("v", 9, True), \
        ps("h", 11, True)

    def esc(v):
        return (str(v if v not in (None, "") else "-").replace("&", "&amp;")
                .replace("<", "&lt;").replace(">", "&gt;"))

    def deco(c, doc):
        c.saveState()
        c.setFillColor(NAVY_C)
        c.rect(0, H - 30 * mm, W, 30 * mm, stroke=0, fill=1)
        c.setFillColor(BLUE_C)
        c.rect(0, H - 30 * mm, W, 1.2 * mm, stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 26)
        c.setFillColor(colors.white)
        c.drawString(16 * mm, H - 17 * mm, "IT")
        c.setFillColor(BLUE_C)
        c.drawString(16 * mm + c.stringWidth("IT", "Helvetica-Bold", 26),
                     H - 17 * mm, "AD")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(CYAN_C)
        c.drawString(16.5 * mm, H - 23 * mm, "P H O N E S E A L   -   "
                     "S E C U R E  •  T E S T  •  C E R T I F Y")
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(W - 16 * mm, H - 15 * mm,
                          "Certificate of Data Erasure")
        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#B9C8DE"))
        c.drawRightString(W - 16 * mm, H - 20.5 * mm, "and Phone Test Report")
        c.drawRightString(W - 16 * mm, H - 25 * mm, "Job %s   •   IMEI %s" % (
            rep["job_id"], (d.get("imei") or ["-"])[0]))
        c.setStrokeColor(LINE)
        c.line(16 * mm, 14 * mm, W - 16 * mm, 14 * mm)
        c.setFont("Helvetica", 7)
        c.setFillColor(GREY)
        fp = integ.get("sha256", "")
        c.drawString(16 * mm, 9.5 * mm, "ITAD PhoneSeal v%s%s" % (
            rep.get("version", VERSION),
            ("   •   Fingerprint %s..." % fp[:24]) if fp else ""))
        c.drawRightString(W - 16 * mm, 9.5 * mm, "Page %d" % doc.page)
        if rep.get("test_mode"):
            c.setFont("Helvetica-Bold", 60)
            c.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.12))
            c.translate(W / 2, H / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, "TEST MODE")
        c.restoreState()

    doc = SimpleDocTemplate(path, pagesize=A4, title="ITAD Phone report",
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=36 * mm, bottomMargin=20 * mm)
    FW = W - 32 * mm
    el = []
    badge = Table([[Paragraph("RESULT", ps("rb", 8, True, colors.white,
                                           1))],
                   [Paragraph(esc(rep["overall"]),
                              ps("rv", 22 if len(rep["overall"]) <= 6
                                 else 14, True, colors.white, 1))]],
                  colWidths=[42 * mm], rowHeights=[6 * mm, 13 * mm])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1),
                                colors.HexColor(RC)),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    reasons = rep["reasons"] or ["All lock checks, the wipe and every "
                                 "component test passed."]
    try:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        qw = QrCodeWidget(qr_text(rep))
        x1, y1, x2, y2 = qw.getBounds()
        sz = 30 * mm
        qr = Drawing(sz, sz, transform=[sz / (x2 - x1), 0, 0,
                                        sz / (y2 - y1), 0, 0])
        qr.add(qw)
    except Exception:
        qr = Paragraph("QR unavailable", s_small)
    top = Table([[badge, Paragraph("<br/>".join("•  " + esc(r) for r in
                                                 reasons[:6]), s_txt),
                  [qr, Paragraph("Digitally signed • key %s" %
                                 integ.get("key_id") if integ.get("signed")
                                 else "Not signed", ps("q", 6.5, color=GREY,
                                                       align=1))]]],
                colWidths=[46 * mm, FW - 80 * mm, 34 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("LEFTPADDING", (0, 0), (0, 0), 0),
                             ("ALIGN", (2, 0), (2, 0), "CENTER")]))
    el += [top, Spacer(1, 5 * mm)]

    def kv(pairs, cols=2):
        cells, row = [], []
        for k, v in pairs:
            row.append([Paragraph(k.upper(), s_key), Paragraph(esc(v),
                                                               s_val)])
            if len(row) == cols:
                cells.append(row)
                row = []
        if row:
            cells.append(row + [""] * (cols - len(row)))
        t = Table(cells, colWidths=[FW / cols] * cols)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT),
                               ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                               ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t
    el += [Paragraph("Device and job", s_h), Spacer(1, 2 * mm),
           kv([("Make / model", "%s %s" % (d.get("make", ""),
                                           d.get("model", ""))),
               ("Serial number", d.get("serial")),
               ("IMEI", ", ".join(d.get("imei") or []) or "-"),
               ("Model ID", d.get("model_id")),
               ("Operating system", d.get("os")),
               ("Storage", "%s GB" % (d.get("storage_gb") or "?")),
               ("Battery", battery_text(d)), ("Colour", d.get("colour")),
               ("Job ID", rep["job_id"]), ("Asset ID", rep["asset_id"]),
               ("Technician", rep["technician"]),
               ("Location", rep["location"]),
               ("Started", rep["started"]), ("Finished", rep["finished"]),
               ("Total time", rep["duration"])]), Spacer(1, 5 * mm)]

    def table(head, rows, widths):
        data = [[Paragraph(h, s_key) for h in head]]
        st = [("BOX", (0, 0), (-1, -1), 0.6, LINE),
              ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
              ("BACKGROUND", (0, 0), (-1, 0), SOFT),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("ALIGN", (1, 0), (1, -1), "CENTER")]
        for i, (a, s, n) in enumerate(rows, start=1):
            data.append([Paragraph("<b>%s</b>" % esc(a), s_txt),
                         Paragraph('<font color="%s"><b>%s</b></font>' % (
                             FG.get(s, "#5B6B84"), esc(s)),
                             ps("x", 8.2, True, align=1)),
                         Paragraph(esc(n), s_txt)])
            st.append(("BACKGROUND", (1, i), (1, i),
                       colors.HexColor(BG.get(s, "#ECEFF4"))))
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(st))
        return t
    el += [Paragraph("Lock checks", s_h), Spacer(1, 2 * mm),
           table(["CHECK", "RESULT", "DETAILS"],
                 [(c["name"], c["result"], c.get("detail", "") +
                   (" (confirmed by %s)" % c["confirmed_by"]
                    if c.get("confirmed_by") else ""))
                  for c in rep["checks"]],
                 [44 * mm, 22 * mm, FW - 66 * mm]), Spacer(1, 5 * mm)]
    w = rep["wipe"]
    el += [Paragraph("Data erasure", s_h), Spacer(1, 2 * mm),
           kv([("State", w.get("state")), ("Method", w.get("method")),
               ("Verification", w.get("verify_note")),
               ("Time", "%s - %s (%s)" % (w.get("started", "-"),
                                          w.get("finished", "-"),
                                          w.get("duration", "-")))]),
           Paragraph("Phones store data encrypted. A factory reset / erase "
                     "destroys the encryption keys, so the data cannot be "
                     "read (cryptographic erase, NIST SP 800-88).", s_small),
           Spacer(1, 5 * mm)]
    tests = rep["tests"]
    fitted = [t for t in tests if t["status"] not in (NOT_FITTED,
                                                      NOT_TESTED)]
    good = sum(1 for t in fitted if t["status"] == "PASS")
    el += [Paragraph("Component tests  -  %d of %d passed" % (good,
                                                             len(fitted)),
                     s_h), Spacer(1, 2 * mm),
           table(["COMPONENT", "RESULT", "DETAILS"],
                 [(t["component"], t["status"],
                   "; ".join(t.get("notes") or [])) for t in tests],
                 [34 * mm, 20 * mm, FW - 54 * mm]), Spacer(1, 5 * mm)]
    o = rep.get("observations", {})
    el.append(KeepTogether([Paragraph("Observations", s_h),
                            Spacer(1, 2 * mm),
                            kv([("Cosmetic grade", o.get("grade")),
                                ("Notes", o.get("notes"))])]))
    itxt = "Fingerprint (SHA-256): %s" % esc(integ.get("sha256", "-"))
    if integ.get("signed"):
        itxt += ("<br/>Digitally signed with Ed25519, key ID %s.<br/>"
                 "Signature: %s" % (esc(integ.get("key_id")),
                                    esc(integ.get("signature", ""))))
    else:
        itxt += "<br/>NOT signed (%s)." % esc(integ.get("note", "no key"))
    sign = Table([[Paragraph("Technician: <b>%s</b>" % esc(
        rep["technician"]), s_txt),
        Paragraph("Signature: ________________________", s_txt),
        Paragraph("Date: %s" % esc(rep["finished"][:10]), s_txt)]],
        colWidths=[FW * 0.33, FW * 0.42, FW * 0.25])
    el.append(KeepTogether([Spacer(1, 6 * mm),
                            Paragraph("Report integrity", s_h),
                            Paragraph(itxt, ps("i", 6.8, color=GREY)),
                            Spacer(1, 8 * mm), sign]))
    doc.build(el, onFirstPage=deco, onLaterPages=deco)


def save_all(rep, out_dir, persistent, log_lines=(), errors=None):
    """Sign, then write TXT, JSON, PDF and log into out_dir/reports.
    Always saves, whatever the result. If the stick can't be written it
    tries its top folder, then memory; errors gets the real reasons."""
    errors = errors if errors is not None else []
    d = rep["device"]
    key = (d.get("imei") or [""])[0] or d.get("serial") or rep["asset_id"]
    name = "PHONE_%s_%s" % (
        "".join(c for c in key if c.isalnum()) or "UNKNOWN",
        rep["finished"].replace("-", "").replace(":", "").replace(" ", "-"))
    try:
        sign_report(rep, out_dir, persistent)
    except Exception as e:
        errors.append("signing: %s" % e)
        rep.setdefault("integrity", {"signed": False,
                                     "note": "signing failed: %s" % e})

    def wtxt(p, text):
        with open(p, "w") as f:
            f.write(text)

    def wjson(p):
        with open(p, "w") as f:
            json.dump(rep, f, indent=2, default=str)

    for rdir in (os.path.join(out_dir, "reports"), out_dir,
                 "/tmp/itad-reports"):
        try:
            os.makedirs(rdir, exist_ok=True)
        except Exception as e:
            errors.append("%s: %s" % (rdir, e))
            continue
        base = os.path.join(rdir, name)
        saved = []
        for ext, fn in (("txt", lambda p: wtxt(p, render_txt(rep))),
                        ("json", wjson),
                        ("pdf", lambda p: write_pdf(p, rep)),
                        ("log", lambda p: wtxt(p, "\n".join(log_lines) +
                                               "\n"))):
            try:
                fn(base + "." + ext)
                saved.append(base + "." + ext)
            except Exception as e:
                errors.append("%s %s: %s" % (ext.upper(), rdir, e))
        if any(x.endswith((".txt", ".pdf")) for x in saved):
            try:
                os.sync()
            except Exception:
                pass
            return saved
    return []
