#!/bin/bash
# wifi_fix.sh - makes the Wi-Fi card find networks (v1.0.0)
#
# Shared by LaptopSeal and PhoneSeal. Run as root by launch.sh at every
# boot, in the background (it never delays the window).
#
# Why: some Wi-Fi cards work on Linux but find NO networks until a
# setting is changed. The best known one is the Realtek RTL8723BE in many
# HP laptops (EliteBook / ProBook / 250 / 255 / 455): Linux listens on the
# wrong antenna. The fix is the driver option ant_sel=1 or ant_sel=2,
# and which one is right depends on the laptop.
#
# What it does:
#   1. Switches Wi-Fi on (rfkill + NetworkManager).
#   2. If the card is an RTL8723BE and it finds no networks, it tries
#      ant_sel=2, then ant_sel=1, and keeps the first one that finds
#      networks. If none finds anything (no Wi-Fi nearby) it goes back to
#      the normal setting.
#   3. Never touches a Wi-Fi that is already connected or is running the
#      station hotspot.
#
# Log: /tmp/itad-wifi.log

LOG=/tmp/itad-wifi.log
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

[ "$(id -u)" = "0" ] || { echo "run as root"; exit 1; }
log "wifi_fix.sh started"
# The windows read this: "working" = still setting up Wi-Fi (about 1 min)
STATE=/tmp/itad-wifi.state
echo working > "$STATE"; chmod 644 "$STATE" 2>/dev/null
trap 'echo done > "$STATE"' EXIT

# ---- wait for NetworkManager (up to 40 s) --------------------------------
for i in $(seq 1 40); do
    nmcli -t -f RUNNING general 2>/dev/null | grep -q running && break
    sleep 1
done

# ---- 1. Wi-Fi switched on ------------------------------------------------
command -v rfkill >/dev/null && rfkill unblock wifi 2>>"$LOG"
command -v rfkill >/dev/null && rfkill unblock all 2>>"$LOG"
nmcli radio wifi on 2>>"$LOG"

wifi_dev() {
    nmcli -t -f DEVICE,TYPE device 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}'
}

wifi_busy() {         # connected, or running the station hotspot
    nmcli -t -f TYPE,STATE device 2>/dev/null | \
        awk -F: '$1=="wifi" && $2 ~ /^connected/ {f=1} END {exit !f}'
}

count_nets() {        # number of Wi-Fi networks seen
    local dev
    for i in $(seq 1 15); do        # the card can take a moment to appear
        dev="$(wifi_dev)"; [ -n "$dev" ] && break; sleep 1
    done
    [ -z "$dev" ] && { echo 0; return; }
    nmcli radio wifi on 2>/dev/null
    nmcli device set "$dev" managed yes 2>/dev/null
    local best=0 n
    for try in 1 2 3; do
        nmcli device wifi rescan ifname "$dev" >/dev/null 2>&1
        sleep 6
        n="$(nmcli -t -f SSID device wifi list ifname "$dev" --rescan no \
             2>/dev/null | grep -c .)"
        [ "${n:-0}" -gt "$best" ] && best="$n"
        [ "$best" -gt 0 ] && break
    done
    echo "$best"
}

uses_driver() {       # $1 = driver name
    [ -d "/sys/module/$1" ] && return 0
    lspci -k 2>/dev/null | grep -q "Kernel driver in use: $1"
}

load_with() {         # $1 = driver, $2 = options (may be empty)
    modprobe -r "$1" 2>>"$LOG"
    sleep 1
    # shellcheck disable=SC2086
    modprobe "$1" $2 2>>"$LOG"
    sleep 4
    command -v rfkill >/dev/null && rfkill unblock wifi 2>/dev/null
    nmcli radio wifi on 2>/dev/null
}

if [ -z "$(wifi_dev)" ]; then
    log "no Wi-Fi card found (or no driver for it)"
    lspci -nnk 2>/dev/null | grep -iA3 'network' >> "$LOG"
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
    for sel in 2 1; do
        wifi_busy && { log "Wi-Fi got busy - stop"; exit 0; }
        log "$DRV: trying ant_sel=$sel"
        load_with "$DRV" "ant_sel=$sel"
        n="$(count_nets)"
        log "$DRV ant_sel=$sel: $n networks"
        if [ "$n" -gt 0 ]; then
            mkdir -p /etc/modprobe.d
            echo "options $DRV ant_sel=$sel" > /etc/modprobe.d/itad-wifi.conf
            log "keeping ant_sel=$sel"
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
exit 0
