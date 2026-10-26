# ITAD PhoneSeal

Phone lock checks, secure erase, component tests and a signed certificate,
from one station. Part of the ITAD tools (LaptopSeal, SwitchSeal).

## How it works

The **station** is any PC or laptop booted from the PhoneSeal USB.
Phones are plugged into the station by USB cable.

1. **Sign in**: technician from `technicians.txt` on the ITAD_DATA stick
   (USB B), the same file as LaptopSeal and SwitchSeal.
2. **Job and phone**: Job ID, Asset ID, then plug in the phone.
   * iPhone: unlock it and tap *Trust This Computer*.
   * Android: *Settings > Developer options > USB debugging* ON, tap *Allow*.
3. **Lock checks**: Find My / Activation Lock, supervision / MDM (iPhone);
   Google account (FRP), Samsung account, MDM device owner (Android);
   carrier lock. Anything the phone does not report over USB is shown as
   **CHECK BY HAND** with the exact place to look. Never assumed clear.
   A locked phone gets a customer **removal request** saved automatically.
4. **Tests**: the phone joins the same Wi-Fi as the station and scans a
   QR code. The test page runs in the phone's own browser (no app):
   touch screen, multi-touch, display, speakers, microphone, both cameras,
   vibration, motion sensors, buttons & ports. Battery health and charging
   are read by the station. The technician can change any result.
5. **Wipe**: phones are encrypted, so an erase destroys the keys
   (cryptographic erase). iPhone: erase over USB if the tools support it,
   or a full erase-restore of iOS (needs internet), or on the phone.
   Android: the station restarts the phone into recovery and the
   technician picks *Wipe data / factory reset*. The station then checks
   the phone is on the Hello / Welcome screen.
6. **Report**: grade and notes, then a digitally signed PDF certificate
   (same design as LaptopSeal) in the `reports` folder of the ITAD_DATA
   stick.

Order is **checks, tests, wipe, report**: after the wipe the phone is back on
the setup screen and cannot open the test page.

## Files

`build/config/includes.chroot/opt/itad-phone/`

| File | What it does |
|---|---|
| `phone_window.py` | The station window |
| `phone_core.py` | Finds phones, reads them, lock checks, wipe |
| `test_server.py` | HTTPS test page server + QR code |
| `web/index.html` | The test page that runs on the phone |
| `phone_report.py` | Result rules and the signed PDF certificate |
| `itad_common.py` | Logins, storage and signing (shared with LaptopSeal) |
| `itad_storage.sh` | Finds the ITAD_DATA stick (USB B) for reports |
| `verify_report.py` | Checks that a report was not changed |

Build: GitHub > Actions > *Build ITAD PhoneSeal ISO* > Run workflow.
