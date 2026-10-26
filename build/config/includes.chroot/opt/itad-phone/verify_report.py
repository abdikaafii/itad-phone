#!/usr/bin/env python3
"""
verify_report.py - check that an ITAD Laptop report was not changed (v1.0.0)

Usage:
    python3 verify_report.py SN_ABC123_20261026-101500.json
    python3 verify_report.py REPORT.json --public-key itad_signing_public.pem

What it checks:
  1. The fingerprint (SHA-256) of the report content still matches.
     If anyone edited the JSON (result, serial, wipe...), it will not.
  2. The Ed25519 digital signature is valid for that fingerprint.
  3. With --public-key: the report was signed by YOUR key (the public key
     file from the keys folder on the ITAD_DATA stick), not some other key.

Works on Windows, Mac or Linux with Python 3 and the "cryptography"
module (pip install cryptography).

Exit codes: 0 = valid, 1 = NOT valid, 2 = could not check.
"""
import argparse
import hashlib
import json
import sys

SIGN_FIELDS = ("integrity",)


def fingerprint(rep):
    body = dict((k, v) for k, v in rep.items() if k not in SIGN_FIELDS)
    data = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Verify an ITAD Laptop report")
    ap.add_argument("report", help="the report .json file")
    ap.add_argument("--public-key", default="",
                    help="itad_signing_public.pem from the ITAD_DATA stick")
    a = ap.parse_args()
    try:
        with open(a.report, encoding="utf-8") as f:
            rep = json.load(f)
    except Exception as ex:
        print("Cannot read the report: %s" % ex)
        return 2
    integ = rep.get("integrity") or {}
    if not integ:
        print("NOT VALID: the report has no integrity section.")
        return 1
    fp = fingerprint(rep)
    print("Report      : %s" % a.report)
    print("Job / Asset : %s / %s" % (rep.get("job_id"), rep.get("asset_id")))
    print("Serial      : %s" % rep.get("serial"))
    print("Result      : %s" % rep.get("overall"))
    if fp != integ.get("sha256"):
        print("NOT VALID: the report content was CHANGED after it was made.")
        return 1
    print("Fingerprint : OK (content not changed)")
    if not integ.get("signed"):
        print("Signature   : none (%s)" % integ.get("note", "not signed"))
        print("RESULT      : content unchanged, but NOT signed")
        return 1
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        from cryptography.exceptions import InvalidSignature
    except Exception:
        print("Install the cryptography module: pip install cryptography")
        return 2
    pub_raw = bytes.fromhex(integ.get("public_key", ""))
    if a.public_key:
        with open(a.public_key, "rb") as f:
            trusted = serialization.load_pem_public_key(f.read())
        trusted_raw = trusted.public_bytes(serialization.Encoding.Raw,
                                           serialization.PublicFormat.Raw)
        if trusted_raw != pub_raw:
            print("NOT VALID: signed with a DIFFERENT key than yours.")
            return 1
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(
            bytes.fromhex(integ.get("signature", "")),
            fp.encode("ascii"))
    except InvalidSignature:
        print("NOT VALID: the signature is wrong.")
        return 1
    except Exception as ex:
        print("Could not check the signature: %s" % ex)
        return 2
    print("Signature   : OK (key ID %s)%s" % (
        integ.get("key_id"), "" if a.public_key else
        "  - add --public-key to confirm it is YOUR key"))
    print("RESULT      : VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
