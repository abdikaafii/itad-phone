#!/bin/bash
# itad_storage.sh - find (or make) a place to SAVE reports (v1.2.0)
#
# v1.2.0: Ventoy stick found even when renamed, opened through a loop
#         device when Ventoy keeps it busy; the small VTOYEFI boot
#         partition is never used for reports. Same file in LaptopSeal
#         and PhoneSeal.
# v1.1.0: a separate ITAD_DATA stick ("USB B", shared with SwitchSeal) is
#         always used first, before the ITAD_DATA part of the boot USB.
#         Every place is checked with a real write (1 MB, synced, read
#         back) before it is used, so a stick that gives write errors is
#         skipped instead of failing later.
#
# Run as root by launch.sh at every boot. Prints ONE line:
#     <folder> <persistent 0|1> <description>
#
# Order:
#   1. A partition labelled ITAD_DATA on any USB stick (also on the boot
#      USB itself) - mounted at /mnt/itad.
#   1b. Any other USB stick (FAT32 / exFAT / NTFS) that is plugged in:
#      reports go into its ITAD_REPORTS folder.
#   2. The boot USB is a normal writable stick (written with Rufus in
#      "ISO mode", or Ventoy): the reports go into its ITAD_REPORTS folder.
#   3. The boot USB was written as an image (Rufus DD / Etcher / Win32
#      Disk Imager) with a classic MBR table: a FAT32 partition
#      "ITAD_DATA" is created ONCE in the free space at the end of the
#      BOOT USB, then mounted. Windows shows it as a separate drive. Only
#      the free space is used: the system part and every other disk are
#      never touched. (Not done on a GPT layout: changing it could stop
#      the stick from booting.)
#   4. Nothing possible: memory only (/tmp/itad-reports, lost at power
#      off) - the window then shows a warning.
#
# Log: /tmp/itad-storage.log
LOG=/tmp/itad-storage.log
MNT=/mnt/itad
LABEL=ITAD_DATA
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
say() { echo "$1 $2 $3"; exit 0; }
mkdir -p "$MNT"

mount_it() {               # $1 = device
    mountpoint -q "$MNT" && umount "$MNT" 2>/dev/null
    mount -o rw,uid=1000,gid=1000,umask=000 "$1" "$MNT" 2>>"$LOG" \
        || mount -o rw "$1" "$MNT" 2>>"$LOG" || return 1
    write_ok "$MNT" || { umount "$MNT" 2>/dev/null; return 1; }
    return 0
}

write_ok() {               # real write test: 1 MB, synced, read back
    local t="$1/.itad_write_test"
    dd if=/dev/urandom of="$t" bs=64k count=16 conv=fsync 2>>"$LOG" \
        || { log "write test FAILED on $1"; rm -f "$t"; return 1; }
    cat "$t" > /dev/null 2>>"$LOG" || { rm -f "$t"; return 1; }
    rm -f "$t"; sync
    return 0
}

# ---- find the boot USB ---------------------------------------------------
MED=/run/live/medium
src="$(findmnt -no SOURCE "$MED" 2>/dev/null)"
fstype="$(findmnt -no FSTYPE "$MED" 2>/dev/null)"
log "boot medium: $src ($fstype)"
bootdisk="$(lsblk -no PKNAME "$src" 2>/dev/null | head -n1)"
[ -z "$bootdisk" ] && bootdisk="$(basename "$src")"

# ---- 1. a partition called ITAD_DATA: separate stick first ---------------
other=""; onboot=""
for dev in $(blkid -t LABEL="$LABEL" -o device 2>/dev/null); do
    pk="$(lsblk -no PKNAME "$dev" 2>/dev/null | head -n1)"
    if [ "$pk" = "$bootdisk" ]; then onboot="$onboot $dev"
    else other="$other $dev"; fi
done
for dev in $other; do
    if mount_it "$dev"; then
        log "using ITAD_DATA stick $dev"
        say "$MNT" 1 "ITAD_DATA_stick_$dev"
    fi
done
for dev in $onboot; do
    if mount_it "$dev"; then
        log "using ITAD_DATA part of the boot USB $dev"
        say "$MNT" 1 "ITAD_DATA_created_on_boot_USB"
    fi
done

# ---- 1a. Ventoy stick: its own data partition ----------------------------
# v1.2.0: the data partition is found even if it was renamed in Windows
# (it is partition 1 of the disk that has the small VTOYEFI partition).
# Ventoy keeps that partition busy while an ISO runs, so a normal mount
# can fail with "busy". Then it is opened through a loop device instead
# (only the free space is written; the ISO files are never touched).
# Setting VTOY_LINUX_REMOUNT=1 in ventoy/ventoy.json also helps.
ventoy_parts() {
    blkid -L Ventoy 2>/dev/null
    for efi in $(blkid -t LABEL=VTOYEFI -o device 2>/dev/null); do
        d="$(lsblk -no PKNAME "$efi" 2>/dev/null | head -n1)"
        [ -z "$d" ] && continue
        lsblk -nlo NAME,TYPE "/dev/$d" 2>/dev/null | \
            awk '$2=="part"{print "/dev/"$1; exit}'
    done
}
modprobe exfat 2>/dev/null
for vdev in $(ventoy_parts | awk '!seen[$0]++'); do
    [ -b "$vdev" ] || continue
    log "Ventoy data partition: $vdev ($(blkid -o value -s TYPE "$vdev"))"
    if mount_it "$vdev"; then
        mkdir -p "$MNT/ITAD_REPORTS"
        log "using Ventoy partition $vdev"
        say "$MNT/ITAD_REPORTS" 1 "Ventoy_stick_folder"
    fi
    log "normal mount of $vdev failed - trying through a loop device"
    lo="$(losetup -f --show "$vdev" 2>>"$LOG")"
    if [ -n "$lo" ]; then
        if mount_it "$lo"; then
            mkdir -p "$MNT/ITAD_REPORTS"
            log "using Ventoy partition $vdev through $lo"
            say "$MNT/ITAD_REPORTS" 1 "Ventoy_stick_folder"
        fi
        losetup -d "$lo" 2>/dev/null
    fi
    log "Ventoy partition $vdev could not be opened"
done

# ---- 1b. any other USB stick that is plugged in --------------------------
while read -r name pk tran fs; do
    [ -z "$name" ] && continue
    d="${pk:-$name}"
    [ "$d" = "$bootdisk" ] && continue
    dt="$(lsblk -dno TRAN "/dev/$d" 2>/dev/null)"
    [ "$dt" = "usb" ] || continue
    case "$fs" in vfat|exfat|ntfs) ;; *) continue ;; esac
    [ "$(blkid -o value -s LABEL "/dev/$name" 2>/dev/null)" = "VTOYEFI" ] \
        && continue                   # Ventoy's own boot files: never
    if mount_it "/dev/$name"; then
        mkdir -p "$MNT/ITAD_REPORTS"
        log "using USB stick /dev/$name ($fs)"
        say "$MNT/ITAD_REPORTS" 1 "USB_stick_folder"
    fi
done <<EOF3
$(lsblk -nlo NAME,PKNAME,TRAN,FSTYPE 2>/dev/null | awk 'NF>=2')
EOF3
case "$src" in
    /dev/loop*)          # Ventoy / ISO file on a stick: use the stick's
        back="$(losetup -no BACK-FILE "$src" 2>/dev/null)"   # data part
        hostmnt="$(df --output=target "$back" 2>/dev/null | tail -n1)"
        if [ -n "$hostmnt" ] && [ -w "$hostmnt" ]; then
            mkdir -p "$hostmnt/ITAD_REPORTS"
            log "using the stick that holds the ISO file: $hostmnt"
            say "$hostmnt/ITAD_REPORTS" 1 "boot_stick_folder"
        fi
        hostdev="$(df --output=source "$back" 2>/dev/null | tail -n1)"
        if [ -n "$hostdev" ] && mount -o remount,rw "$hostdev" \
                "$hostmnt" 2>>"$LOG"; then
            mkdir -p "$hostmnt/ITAD_REPORTS"
            say "$hostmnt/ITAD_REPORTS" 1 "boot_stick_folder"
        fi
        ;;
esac

# ---- 2. writable boot stick (Rufus ISO mode = FAT32 / NTFS / exFAT) ------
case "$fstype" in
    vfat|exfat|ntfs|ntfs3|fuseblk|ext4)
        if mount -o remount,rw "$MED" 2>>"$LOG" && \
                mkdir -p "$MED/ITAD_REPORTS" 2>>"$LOG" && \
                write_ok "$MED/ITAD_REPORTS"; then
            log "boot stick is writable ($fstype): $MED/ITAD_REPORTS"
            say "$MED/ITAD_REPORTS" 1 "boot_stick_folder"
        fi
        ;;
esac

# ---- 3. image-written boot stick: make ITAD_DATA in its free space -------
part="${src#/dev/}"
disk="$(lsblk -no PKNAME "/dev/$part" 2>/dev/null | head -n1)"
[ -z "$disk" ] && [ -b "/dev/$part" ] && \
    [ "$(lsblk -no TYPE "/dev/$part" | head -n1)" = "disk" ] && disk="$part"
tran="$(lsblk -dno TRAN "/dev/$disk" 2>/dev/null)"
rm_="$(lsblk -dno RM "/dev/$disk" 2>/dev/null | tr -d ' ')"
log "boot disk: /dev/$disk tran=$tran rm=$rm_"
if [ -n "$disk" ] && { [ "$tran" = "usb" ] || [ "$rm_" = "1" ]; } && \
        command -v sfdisk >/dev/null && command -v mkfs.vfat >/dev/null; then
    D="/dev/$disk"
    # largest free area (in 512-byte sectors)
    read -r fs fe fn <<EOF2
$(sfdisk -F "$D" 2>/dev/null | awk '$1 ~ /^[0-9]+$/ {print $1, $2, $3}' |
  sort -k3 -n | tail -n1)
EOF2
    label="$(sfdisk -d "$D" 2>/dev/null | awk -F': ' '/^label:/ {print $2}')"
    log "free space on $D: start=$fs end=$fe sectors=$fn label=$label"
    if [ "$label" != "dos" ]; then
        log "boot USB layout is '$label', not MBR - not changed (safety)"
    elif [ -n "$fn" ] && [ "$fn" -gt 1048576 ]; then      # more than 512 MB
        start=$(( (fs + 2047) / 2048 * 2048 ))
        typ="c"
        before="$(lsblk -nlo NAME "$D" | sort)"
        if echo "start=$start, type=$typ" | \
                sfdisk --append --no-reread --no-tell-kernel "$D" \
                >>"$LOG" 2>&1; then
            partx -a "$D" >>"$LOG" 2>&1 || partx -u "$D" >>"$LOG" 2>&1
            udevadm settle 2>/dev/null; sleep 1
            new="$(comm -13 <(echo "$before") \
                   <(lsblk -nlo NAME "$D" | sort) | tail -n1)"
            log "new partition: $new"
            if [ -n "$new" ] && mkfs.vfat -F 32 -n "$LABEL" "/dev/$new" \
                    >>"$LOG" 2>&1 && mount_it "/dev/$new"; then
                log "created and mounted ITAD_DATA on /dev/$new"
                say "$MNT" 1 "ITAD_DATA_created_on_boot_USB"
            fi
        else
            log "sfdisk could not add a partition"
        fi
    else
        log "not enough free space on the boot USB"
    fi
fi

# ---- 4. memory only ------------------------------------------------------
mkdir -p /tmp/itad-reports
log "no place to save on a stick - memory only"
say /tmp/itad-reports 0 "memory_only"
