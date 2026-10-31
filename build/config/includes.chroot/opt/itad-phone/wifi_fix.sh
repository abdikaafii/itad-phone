#!/bin/bash
# wifi_fix.sh - makes the Wi-Fi card find networks (v1.1.0)
#
# Shared by LaptopSeal and PhoneSeal. Run as root by launch.sh at every
# boot, in the background (it never delays the window).
#
# v1.1.0: it can never hang any more. Every command has a time limit and
#   the whole script stops after 2 minutes at most, so the window can no
#   longer stay on "The Wi-Fi is still being set up". Only one copy runs
#   at a time. It now writes the Wi-Fi card name and driver into the log
#   (/tmp/itad-wifi.card) so the window can show them. Wi-Fi power saving
#   is switched off (it stops some cards from finding networks). For the
#   Realtek RTL8723BE it now also tries the power-saving-off options
#   (fwlps=0 ips=0) together with each antenna setting.
#
# Why: some Wi-Fi cards work on Linux but find NO networks until a
# setting is changed. The best known one is the Realtek RTL8723BE in many
# HP laptops (EliteBook / ProBook / 250 / 255 / 450 / 455): Linux listens
# on the wrong antenna. The fix is the driver option ant_sel=1 or
# ant_sel=2, and which one is right depends on the laptop.
#
# What it does:
#   1. Switches Wi-Fi on (rfkill + NetworkManager).
#   2. If the card is an RTL8723BE and it finds no networks, it tries
#      ant_sel=2, then ant_sel=1 (with power saving off), and keeps the
#      first one that finds networks. If none finds anything (no Wi-Fi
#      nearby) it goes back to the normal setting.
#   3. Never touches a Wi-Fi that is already connected or is running the
#      station hotspot.
#
# Files:  /tmp/itad-wifi.log    what it did
#         /tmp/itad-wifi.state  "working" while busy, "done" when finished
#         /tmp/itad-wifi.card   the Wi-Fi card name and driver

LOG=/tmp/itad-wifi.log
STATE=/tmp/itad-wifi.state
CARD=/tmp/itad-wifi.card
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

[ "$(id -u)" = "0" ] || { echo "run as root"; exit 1; }

# ---- only one copy at a time ---------------------------------------------
exec 9>/tmp/itad-wifi.lock
if ! flock -n 9; then
    log "wifi_fix.sh already running - this copy stops"
    exit 0
fi

log "wifi_fix.sh v1.1.0 started"
# The windows read this: "working" = still setting up Wi-Fi
echo working > "$STATE"; chmod 644 "$STATE" 2>/dev/null
finish() { echo done > "$STATE"; chmod 644 "$STATE" 2>/dev/null; }
trap finish EXIT
trap 'log "stopped (signal)"; exit 0' TERM INT HUP

# ---- safety net: stop after 120 seconds whatever happens ------------------
MAIN_PID=$$
( exec 9>&-
  sleep 120
  if kill -0 "$MAIN_PID" 2>/dev/null; then
      echo "$(date '+%F %T') time limit (2 min) reached - stopping" >> "$LOG"
      echo done > "$STATE"
      kill -TERM "$MAIN_PID" 2>/dev/null
  fi ) &
WATCH_PID=$!
trap 'finish; kill "$WATCH_PID" 2>/dev/null' EXIT

T() { timeout "$@"; }   # short name: T <seconds> command...

# ---- wait for NetworkManager (up to 40 s) --------------------------------
for i in $(seq 1 40); do
    T 5 nmcli -t -f RUNNING general 2>/dev/null | grep -q running && break
    sleep 1
done

# ---- 1. Wi-Fi switched on ------------------------------------------------
command -v rfkill >/dev/null && T 5 rfkill unblock wifi 2>>"$LOG"
command -v rfkill >/dev/null && T 5 rfkill unblock all 2>>"$LOG"
T 10 nmcli radio wifi on 2>>"$LOG"

# ---- the card name and driver, for the log and the window ------------------
{
    T 10 lspci -nnk 2>/dev/null | grep -iA3 'network controller' | \
        grep -iE 'network controller|kernel driver in use'
    T 10 lsusb 2>/dev/null | grep -iE 'wireless|wi-?fi|802\.11|wlan'
} > "$CARD" 2>/dev/null
chmod 644 "$CARD" 2>/dev/null
log "card: $(tr '\n' ' ' < "$CARD")"
T 5 rfkill list >> "$LOG" 2>&1

wifi_dev() {
    T 10 nmcli -t -f DEVICE,TYPE device 2>/dev/null | \
        awk -F: '$2=="wifi"{print $1; exit}'
}

wifi_busy() {         # connected, or running the station hotspot
    T 10 nmcli -t -f TYPE,STATE device 2>/dev/null | \
        awk -F: '$1=="wifi" && $2 ~ /^connected/ {f=1} END {exit !f}'
}

powersave_off() {     # $1 = Wi-Fi device
    command -v iw >/dev/null && T 5 iw dev "$1" set power_save off 2>/dev/null
}

count_nets() {        # number of Wi-Fi networks seen
    local dev=""
    for i in $(seq 1 15); do        # the card can take a moment to appear
        dev="$(wifi_dev)"; [ -n "$dev" ] && break; sleep 1
    done
    [ -z "$dev" ] && { echo 0; return; }
    T 10 nmcli radio wifi on 2>/dev/null
    T 10 nmcli device set "$dev" managed yes 2>/dev/null
    powersave_off "$dev"
    local best=0 n
    for try in 1 2 3; do
        T 15 nmcli device wifi rescan ifname "$dev" >/dev/null 2>&1
        sleep 5
        n="$(T 15 nmcli -t -f SSID device wifi list ifname "$dev" \
             --rescan no 2>/dev/null | grep -c .)"
        [ "${n:-0}" -gt "$best" ] && best="$n"
        [ "$best" -gt 0 ] && break
    done
    echo "$best"
}

uses_driver() {       # $1 = driver name
    [ -d "/sys/module/$1" ] && return 0
    T 10 lspci -k 2>/dev/null | grep -q "Kernel driver in use: $1"
}

load_with() {         # $1 = driver, $2 = options (may be empty)
    T 20 modprobe -r "$1" 2>>"$LOG"
    sleep 1
    # shellcheck disable=SC2086
    T 20 modprobe "$1" $2 2>>"$LOG"
    sleep 4
    command -v rfkill >/dev/null && T 5 rfkill unblock wifi 2>/dev/null
    T 10 nmcli radio wifi on 2>/dev/null
}

if [ -z "$(wifi_dev)" ]; then
    log "no Wi-Fi card found by NetworkManager (or no driver for it)"
    T 10 nmcli device >> "$LOG" 2>&1
    T 10 dmesg 2>/dev/null | grep -iE 'firmware|wlan|wifi|iwl|rtl|ath|brcm|mt7' | \
        tail -n 15 >> "$LOG"
    exit 0
fi

if wifi_busy; then
    log "Wi-Fi already connected / hotspot on - nothing to do"
    exit 0
fi

# ---- 2. Realtek RTL8723BE: pick the antenna that works -------------------
DRV=rtl8723be
if uses_driver "$DRV"; then
    n="$(count_nets)"
    log "$DRV with the normal setting: $n networks"
    if [ "$n" -gt 0 ]; then
        exit 0
    fi
    for opts in "ant_sel=2 fwlps=0 ips=0" "ant_sel=1 fwlps=0 ips=0"; do
        wifi_busy && { log "Wi-Fi got busy - stop"; exit 0; }
        log "$DRV: trying $opts"
        load_with "$DRV" "$opts"
        n="$(count_nets)"
        log "$DRV $opts: $n networks"
        if [ "$n" -gt 0 ]; then
            mkdir -p /etc/modprobe.d
            echo "options $DRV $opts" > /etc/modprobe.d/itad-wifi.conf
            log "keeping $opts"
            exit 0
        fi
    done
    log "$DRV: no networks with any setting (no Wi-Fi nearby?) - back to normal"
    rm -f /etc/modprobe.d/itad-wifi.conf
    load_with "$DRV" ""
    exit 0
fi

n="$(count_nets)"
log "Wi-Fi card ok, $n networks seen"
T 10 nmcli device >> "$LOG" 2>&1
exit 0
