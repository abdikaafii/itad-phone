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
4. **Tests**: Android with USB debugging opens the test page over the USB
   cable (no Wi-Fi). Other phones scan a QR code: on the same Wi-Fi, or on
   the **station Wi-Fi** (press *Network > Start station Wi-Fi*, the phone
   joins it with a second QR code). The test page runs in the phone's own browser (no app):
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

### Which devices

* **iPhone, iPad, iPod touch**: everything over USB (names for all models
  from iPhone 6s / iPad 5th gen; newer models show their model code).
* **Android phones and tablets, Amazon Fire**: over USB with USB debugging.
  Brand locks checked too: Samsung, Amazon (registered Fire), Xiaomi Mi
  account, HUAWEI / HONOR ID, OPPO / realme / OnePlus, vivo.
* **Apple Watch and devices with no USB**: *Add a device by hand* on the
  Job page. Details are typed in, checks are confirmed by the technician,
  tests can still run in the device's browser if it has one.

### Passcode unknown (locked devices)

Press **Passcode unknown** on the device's row. The station shows it even
when it is locked, in recovery / DFU mode, in bootloader mode, or has USB
debugging off.

1. Device details: type the serial / IMEI.
2. Wipe:
   * iPhone / iPad: the station shows how to put it in **recovery mode**,
     finds it, and erase-restores iOS (downloads iOS from Apple: needs
     internet and 6-9 GB free on USB B), or restore on another computer.
   * Android / Fire: step-by-step **recovery menu** buttons for the brand
     (Samsung, Pixel, Motorola, Xiaomi, OnePlus, HUAWEI, Fire...).
3. Lock checks **on the setup screen after the wipe** (Activation Lock,
   Remote Management, Google FRP "Verify your account", brand accounts,
   "This device belongs to your organisation"). A lock found = removal
   request saved for the customer.
4. Report: tests show **NOT TESTED - passcode unknown**; a wiped,
   lock-free device gets the result **WIPED - NOT TESTED**.

Order is **checks, tests, wipe, report**: after the wipe the phone is back on
the setup screen and cannot open the test page.

## Files

`build/config/includes.chroot/opt/itad-phone/`

| File | What it does |
|---|---|
| `phone_window.py` | The station window |
| `phone_core.py` | Finds phones, reads everything (model, IMEI, battery, storage, RAM, chip, bootloader...), lock checks, wipe |
| `net.py` | Network: Wi-Fi list, station Wi-Fi hotspot, Android test page over USB |
| `test_server.py` | HTTPS test page server + QR code |
| `web/index.html` | The test page that runs on the phone |
| `phone_report.py` | Result rules and the signed PDF certificate |
| `itad_common.py` | Logins, storage and signing (shared with LaptopSeal) |
| `itad_storage.sh` | Finds the ITAD_DATA stick (USB B) for reports |
| `verify_report.py` | Checks that a report was not changed |

Build: GitHub > Actions > *Build ITAD PhoneSeal ISO* > Run workflow.
