#!/bin/bash
# build.sh - builds the ITAD PhoneSeal station boot ISO.
# Output: build/itad-phone.iso
#
# The station is any PC / laptop booted from this USB. Phones are plugged
# into it by USB cable (iPhone: libimobiledevice, Android: adb) and run
# their tests in their own browser through a QR code.
#
# Same base as PhoneSeal: Debian 13, animated boot screen, green boot
# text, fast boot (zstd), extra packages installed one by one (a missing
# one never breaks the build), and a 300 MB ITAD_DATA partition in the
# ISO for reports.
set -euo pipefail
cd "$(dirname "$0")"
CFG="config"; INC="$CFG/includes.chroot"; HOOKS="$CFG/hooks/normal"

echo "== 1. Clean =="
lb clean --purge 2>/dev/null || true
rm -rf "$CFG/bootloaders/isolinux"

echo "== 2. Configure =="
lb config --distribution trixie --architectures amd64 \
  --archive-areas "main contrib non-free non-free-firmware" \
  --firmware-chroot true --firmware-binary true \
  --uefi-secure-boot auto \
  --chroot-squashfs-compression-type zstd \
  --binary-images iso-hybrid --bootloaders "syslinux,grub-efi" \
  --debian-installer none --memtest none \
  --iso-application "ITAD PhoneSeal" --iso-volume "ITAD_PHONE" \
  --bootappend-live "boot=live components splash loglevel=6 rd.systemd.show_status=false systemd.show_status=false rd.udev.log_level=3 udev.log_level=3 vt.global_cursor_default=0 plymouth.ignore-serial-consoles vt.default_red=0,170,0,170,0,170,0,40,85,255,85,255,85,255,85,90 vt.default_grn=0,0,170,85,0,0,170,220,85,85,255,255,85,85,255,255 vt.default_blu=0,0,0,0,170,170,170,90,85,85,85,85,255,255,255,140"

echo "== 2b. Packages =="
# MUST-HAVE packages (all exist in Debian 13). If one of these is missing
# the build stops, because the tool cannot work without them.
mkdir -p "$CFG/package-lists"
rm -f "$CFG"/package-lists/repo-*.list.chroot
printf '%s\n' plymouth plymouth-themes xorg xinit openbox xterm python3 \
  python3-tk python3-reportlab python3-pil python3-cryptography sudo \
  util-linux x11-xserver-utils network-manager iw rfkill openssl \
  libimobiledevice-utils usbmuxd fonts-dejavu-core zstd dosfstools \
  exfatprogs pciutils usbutils iproute2 \
  > "$CFG/package-lists/itad.list.chroot"

# NICE-TO-HAVE packages: installed one by one by a hook (step 4).
# A name that does not exist is skipped, never fatal.
mkdir -p "$INC/etc"
OPT="$INC/etc/itad-optional-packages.txt"
printf '%s\n' \
  adb fastboot android-sdk-platform-tools-common idevicerestore \
  ideviceinstaller libimobiledevice-utils python3-qrcode python3-imobiledevice \
  firmware-linux firmware-linux-nonfree firmware-misc-nonfree \
  firmware-iwlwifi firmware-realtek firmware-atheros firmware-brcm80211 \
  firmware-mediatek firmware-intel-graphics firmware-amd-graphics \
  intel-microcode amd64-microcode \
  xserver-xorg-video-all xserver-xorg-input-all xserver-xorg-input-libinput \
  xserver-xorg-video-fbdev xserver-xorg-video-vesa libgl1-mesa-dri \
  network-manager-gnome jq unclutter \
  > "$OPT"
# Packages in the repo files build/package-lists/*.list.chroot are added
# to the nice-to-have list too (so they can never break the build).
for f in package-lists/*.list.chroot; do
  [ -f "$f" ] && grep -v '^[[:space:]]*#' "$f" | tr -s ' \t' '\n' >> "$OPT"
done
sort -u "$OPT" | sed '/^[[:space:]]*$/d' > "$OPT.tmp"
mv -f "$OPT.tmp" "$OPT"
echo "Nice-to-have packages: $(wc -l < "$OPT")"

echo "== 3. Boot splash =="
# Animated boot screen in the PhoneSeal colours (dark blue):
# glowing logo, spinning comet ring, smooth progress bar, changing text.
T="$INC/usr/share/plymouth/themes/itad"; rm -rf "$T"; mkdir -p "$T"
FB=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
FR=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
TMP="$(mktemp -d)"

# Logo: "IT" white + "AD" blue, then PHONESEAL and the tagline
convert -background none -font "$FB" -pointsize 120 -fill white label:IT "PNG32:$TMP/it.png"
convert -background none -font "$FB" -pointsize 120 -fill "#2E9BFF" label:AD "PNG32:$TMP/ad.png"
convert "$TMP/it.png" "$TMP/ad.png" -background none +append "PNG32:$TMP/itad.png"
convert -background none -font "$FR" -pointsize 30 -kerning 12 -fill "#38BDF8" \
  label:"PHONESEAL" "PNG32:$TMP/sub.png"
convert -background none -font "$FR" -pointsize 18 -kerning 6 -fill "#8EA6C8" \
  label:"SECURE  •  TEST  •  CERTIFY" "PNG32:$TMP/tag.png"
convert "$TMP/itad.png" "$TMP/sub.png" "$TMP/tag.png" -background none \
  -gravity center -smush 14 "PNG32:$T/logo.png"

# Soft glow behind the logo and the spinner (it pulses)
convert -size 520x520 radial-gradient:"rgba(30,123,255,0.30)-rgba(30,123,255,0)" \
  "PNG32:$T/glow.png"

# Spinner: a comet-shaped ring of dots, drawn at 2x and shrunk (smooth edges),
# turned into 48 frames.
DRAW=""
for k in $(seq 0 59); do
  DRAW="$DRAW $(awk -v k="$k" 'BEGIN{
    pi=3.14159265; a=(k*4.5-90)*pi/180; t=k/59;
    x=96+70*cos(a); y=96+70*sin(a); r=3+6*t; al=0.08+0.92*t*t;
    g=int(123+66*t); b=255;
    printf "-fill \"rgba(%d,%d,%d,%.3f)\" -draw \"circle %.1f,%.1f %.1f,%.1f\" ", 30+26*t, g, b, al, x, y, x+r, y }')"
done
eval convert -size 192x192 xc:none $DRAW "PNG32:$TMP/comet.png"
for i in $(seq 0 47); do
  convert "$TMP/comet.png" -background none -virtual-pixel transparent \
    -distort SRT "$(awk -v i="$i" 'BEGIN{printf "%.2f", i*7.5}')" \
    -resize 50% "PNG32:$T/spin-$i.png"
done

# Progress bar: dark track + blue gradient fill (rounded ends)
convert -size 520x10 xc:none -fill "#1A3966" -draw "roundrectangle 0,0 519,9 5,5" \
  "PNG32:$T/track.png"
convert -size 10x520 gradient:"#38BDF8"-"#1E7BFF" -rotate 90 "PNG32:$TMP/grad.png"
convert -size 520x10 xc:none -fill white -draw "roundrectangle 0,0 519,9 5,5" \
  "PNG32:$TMP/mask.png"
convert "$TMP/grad.png" "$TMP/mask.png" -compose DstIn -composite "PNG32:$T/fill.png"

# Status messages (shown one after another) and the footer
n=0
for m in "Starting up" "Loading drivers" "Detecting hardware" \
         "Preparing PhoneSeal" "Opening PhoneSeal"; do
  convert -size 700x44 xc:none -font "$FR" -pointsize 22 -fill "#8EA6C8" \
    -gravity center -annotate 0 "$m" "PNG32:$T/msg-$n.png"
  n=$((n+1))
done
convert -size 900x36 xc:none -font "$FR" -pointsize 15 -fill "#4F6A92" \
  -gravity center -annotate 0 "Do not remove the USB stick   •   Better devices. A cleaner planet." \
  "PNG32:$T/footer.png"
rm -rf "$TMP"

printf '%s\n' "[Plymouth Theme]" "Name=ITAD" "Description=PhoneSeal boot screen" \
  "ModuleName=script" "" "[script]" \
  "ImageDir=/usr/share/plymouth/themes/itad" \
  "ScriptFile=/usr/share/plymouth/themes/itad/itad.script" > "$T/itad.plymouth"
cat > "$T/itad.script" <<'EOF'
# PhoneSeal boot screen (Plymouth script)
Window.SetBackgroundTopColor(0.020, 0.059, 0.133);
Window.SetBackgroundBottomColor(0.031, 0.094, 0.192);
W = Window.GetWidth();
H = Window.GetHeight();
f = Math.Clamp(Math.Min(W / 1600, H / 900), 0.55, 1.8);

fun load(name) {
  img = Image(name);
  return img.Scale(Math.Int(img.GetWidth() * global.f + 0.5),
                   Math.Int(img.GetHeight() * global.f + 0.5));
}

fun place(sprite, img, cx, cy, z) {
  sprite.SetPosition(Math.Int(cx - img.GetWidth() / 2),
                     Math.Int(cy - img.GetHeight() / 2), z);
}

# glow + logo
glow = load("glow.png");
glow_s = Sprite(glow);
place(glow_s, glow, W / 2, H * 0.40, 1);
logo = load("logo.png");
logo_s = Sprite(logo);
place(logo_s, logo, W / 2, H * 0.40, 10);
logo_s.SetOpacity(0);

# spinner
NS = 48;
for (i = 0; i < NS; i++) spin[i] = load("spin-" + i + ".png");
spin_s = Sprite(spin[0]);
spin_y = H * 0.40 + logo.GetHeight() / 2 + 70 * f;
place(spin_s, spin[0], W / 2, spin_y, 10);

# progress bar
track = load("track.png");
track_s = Sprite(track);
bar_y = spin_y + 70 * f;
place(track_s, track, W / 2, bar_y, 10);
fill = Image("fill.png");
fill_w = Math.Int(fill.GetWidth() * f);
fill_h = Math.Int(fill.GetHeight() * f);
fill_x = Math.Int(W / 2 - track.GetWidth() / 2);
fill_s = Sprite();
fill_s.SetPosition(fill_x, Math.Int(bar_y - fill_h / 2), 11);
last_w = -1;

# status text
NM = 5;
for (i = 0; i < NM; i++) msg[i] = load("msg-" + i + ".png");
msg_s = Sprite(msg[0]);
place(msg_s, msg[0], W / 2, bar_y + 40 * f, 10);
cur_msg = 0;
msg_t = 0;

# footer
foot = load("footer.png");
foot_s = Sprite(foot);
place(foot_s, foot, W / 2, H - 40 * f, 10);

t = 0;
frame = 0;
sys_p = 0;
shown_p = 0;
quitting = 0;

fun progress_cb(duration, progress) {
  if (progress > global.sys_p) global.sys_p = progress;
}
Plymouth.SetBootProgressFunction(progress_cb);

fun set_fill(p) {
  w = Math.Int(global.fill_w * p);
  if (w < global.fill_h) w = global.fill_h;
  if (w != global.last_w) {
    global.fill_s.SetImage(global.fill.Scale(w, global.fill_h));
    global.last_w = w;
  }
}

fun refresh_cb() {
  global.t = global.t + 0.02;
  global.frame = global.frame + 1;

  # logo fades in, glow pulses
  if (global.t < 1) global.logo_s.SetOpacity(global.t);
  else global.logo_s.SetOpacity(1);
  global.glow_s.SetOpacity(0.55 + 0.45 * Math.Sin(global.t * 2.2));

  # spinner: one turn every ~1.2 s
  global.spin_s.SetImage(global.spin[Math.Int(global.frame / 1.25) % global.NS]);

  # progress: never stops moving, follows the real boot when it is ahead
  tp = 0.94 * global.t / (global.t + 7);
  target = Math.Max(tp, global.sys_p * 0.97);
  if (global.quitting) target = 1;
  global.shown_p = global.shown_p + (target - global.shown_p) * 0.06;
  set_fill(global.shown_p);

  # status text changes as the boot goes on
  want = 0;
  if (global.shown_p > 0.18) want = 1;
  if (global.shown_p > 0.38) want = 2;
  if (global.shown_p > 0.58) want = 3;
  if (global.quitting) want = 4;
  if (want != global.cur_msg) {
    global.cur_msg = want;
    global.msg_s.SetImage(global.msg[want]);
    global.msg_t = 0;
  }
  global.msg_t = global.msg_t + 0.02;
  global.msg_s.SetOpacity(Math.Min(1, global.msg_t * 3));
}
Plymouth.SetRefreshFunction(refresh_cb);

fun quit_cb() {
  global.quitting = 1;
  global.shown_p = 1;
  set_fill(1);
  global.msg_s.SetImage(global.msg[4]);
  global.msg_s.SetOpacity(1);
}
Plymouth.SetQuitFunction(quit_cb);
EOF

echo "== 4. Hooks (extra packages + splash) =="
mkdir -p "$HOOKS"
cat > "$HOOKS/0050-itad-optional-packages.hook.chroot" <<'EOF'
#!/bin/sh
# Install every nice-to-have package on its own. Missing ones are skipped.
L=/etc/itad-optional-packages.txt
[ -f "$L" ] || exit 0
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null 2>&1 || true
OK=""; SKIP=""
for p in $(cat "$L"); do
  if apt-get install -y --no-install-recommends "$p" >/dev/null 2>&1; then
    OK="$OK $p"
  else
    SKIP="$SKIP $p"
  fi
done
echo "ITAD extra packages installed:$OK"
echo "ITAD extra packages SKIPPED (not found):$SKIP"
echo "skipped:$SKIP" > /etc/itad-optional-skipped.txt
apt-get clean
exit 0
EOF

cat > "$HOOKS/0100-itad-plymouth.hook.chroot" <<'EOF'
#!/bin/sh
plymouth-set-default-theme itad 2>/dev/null || true
P=/usr/share/plymouth/themes
update-alternatives --install $P/default.plymouth default.plymouth $P/itad/itad.plymouth 100 2>/dev/null || true
update-alternatives --set default.plymouth $P/itad/itad.plymouth 2>/dev/null || true
# Show the boot screen early (graphics drivers in the initramfs) and make
# the initramfs fast to unpack (zstd).
mkdir -p /etc/initramfs-tools/conf.d
printf 'FRAMEBUFFER=y\nCOMPRESS=zstd\n' > /etc/initramfs-tools/conf.d/itad
update-initramfs -u -k all 2>/dev/null || true
exit 0
EOF

# Faster boot: switch off things the tool never uses, and keep the boot
# screen up until the PhoneSeal window is ready (no black gap, no text).
cat > "$HOOKS/0150-itad-fast-boot.hook.chroot" <<'EOF'
#!/bin/sh
for u in NetworkManager-wait-online.service systemd-networkd-wait-online.service \
         ModemManager.service cups.service cups-browsed.service \
         avahi-daemon.service avahi-daemon.socket apt-daily.timer \
         apt-daily-upgrade.timer man-db.timer e2scrub_all.timer \
         e2scrub_reap.service fstrim.timer anacron.timer anacron.service \
         unattended-upgrades.service; do
  systemctl mask "$u" >/dev/null 2>&1 || true
done
systemctl unmask plymouth-quit.service plymouth-quit-wait.service >/dev/null 2>&1 || true
systemctl enable itad-splash-timeout.service >/dev/null 2>&1 || true
exit 0
EOF
# Plymouth quits when the system is ready, but keeps its last picture on
# screen (--retain-splash) until the PhoneSeal window opens on top.
# (v3 kept plymouth running until X started: on some laptops plymouth
# and X then fought over the screen = freeze and glitching.)
PQ="$INC/etc/systemd/system/plymouth-quit.service.d"; mkdir -p "$PQ"
printf '%s\n' "[Service]" "ExecStart=" \
  "ExecStart=-/usr/bin/plymouth quit --retain-splash" > "$PQ/itad.conf"
# Safety net: if the boot screen is still up after 1 minute, remove it so
# the technician can see what is wrong.
mkdir -p "$INC/etc/systemd/system"
printf '%s\n' "[Unit]" "Description=ITAD: remove boot screen if the window never starts" \
  "[Service]" "Type=simple" \
  "ExecStart=/bin/sh -c 'sleep 60; /usr/bin/plymouth quit || true'" \
  "[Install]" "WantedBy=multi-user.target" \
  > "$INC/etc/systemd/system/itad-splash-timeout.service"

echo "== 4a. sudo + tool files =="
mkdir -p "$INC/etc/sudoers.d"
echo "user ALL=(ALL) NOPASSWD: ALL" > "$INC/etc/sudoers.d/live-nopasswd"
chmod 0440 "$INC/etc/sudoers.d/live-nopasswd"
A="$INC/opt/itad-phone"; mkdir -p "$A"
for f in "$INC"/opt/*.py "$INC"/opt/*.sh; do [ -f "$f" ] && cp -f "$f" "$A/"; done
ls -1 "$A"
for n in phone_window.py phone_core.py phone_report.py test_server.py itad_common.py launch.sh itad_storage.sh web/index.html; do
  [ -f "$A/$n" ] || { echo "ERROR: $n missing" >&2; exit 1; }
done
chmod +x "$A"/*.sh "$A"/*.py

echo "== 4b. Autostart, autologin, menu =="
OB="$INC/etc/xdg/openbox"; mkdir -p "$OB"
cat > "$OB/autostart" <<'EOF'
#!/bin/bash
# No xsetroot here: the last boot-screen picture stays visible until the
# PhoneSeal window opens on top of it (no black flash).
xhost +local:root >/dev/null 2>&1
/opt/itad-phone/launch.sh >/tmp/launch-out.log 2>&1 &
EOF
: > "$INC/etc/issue"; : > "$INC/etc/issue.net"; : > "$INC/etc/motd"
G="$INC/etc/systemd/system/getty@tty1.service.d"; mkdir -p "$G"
printf '%s\n' "[Service]" "ExecStart=" \
  'ExecStart=-/sbin/agetty --autologin user --skip-login --nonewline --noissue --nohostname --noclear %I $TERM' \
  > "$G/zz-itad-autologin.conf"
K="$INC/etc/skel"; mkdir -p "$K"; : > "$K/.hushlogin"
printf '#!/bin/sh\nexec openbox-session\n' > "$K/.xinitrc"
# Hand over from the boot screen to the window: plymouth leaves its last
# picture on screen (--retain-splash) and Xorg starts without painting it
# black (-background none), so the window appears straight on top.
X='if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then sudo -n /usr/bin/plymouth quit --retain-splash >/dev/null 2>&1; startx -- -keeptty -background none >/tmp/startx.log 2>&1; clear; fi'
echo "$X" > "$K/.bash_profile"; echo "$X" > "$K/.profile"
cat > "$OB/menu.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
<menu id="root-menu" label="Openbox 3">
<item label="Launch PhoneSeal (window)"><action name="Execute"><command>/opt/itad-phone/launch.sh</command></action></item>
<item label="Wi-Fi / network settings"><action name="Execute"><command>xterm -e sudo nmtui</command></action></item>
<item label="List phones (text)"><action name="Execute"><command>xterm -hold -e sudo python3 /opt/itad-phone/phone_core.py</command></action></item>
<item label="Terminal"><action name="Execute"><command>xterm</command></action></item>
<item label="Exit"><action name="Exit" /></item>
</menu>
</openbox_menu>
EOF
chmod +x "$OB/autostart" "$K/.xinitrc" "$HOOKS"/*.hook.chroot

echo "== 4c. Hide boot menus =="
B="$CFG/includes.binary/isolinux"; mkdir -p "$B"
# Force true RGB PNGs (colour type 2). Plain black can otherwise be saved
# as a grey-scale PNG, which GRUB and syslinux refuse.
convert -size 800x600 xc:black -define png:color-type=2 -depth 8 "PNG24:$B/splash800x600.png"
convert -size 640x480 xc:black -define png:color-type=2 -depth 8 "PNG24:$B/splash.png"
cat > "$HOOKS/0900-itad-hide-boot-menu.hook.binary" <<'EOF'
#!/bin/sh
B="."; [ ! -d boot/grub ] && [ -d binary/boot/grub ] && B="binary"
G="$B/boot/grub"
if [ -d "$G" ]; then
  # No background picture: GRUB cannot read some PNG types and then shows
  # "png: color type not supported / Press any key to continue".
  for f in "$G"/*.cfg; do
    [ -f "$f" ] || continue
    sed -i -e '/background_image/d' -e '/insmod png/d' -e '/^[[:space:]]*set theme=/d' "$f"
  done
  rm -f "$G"/*.png
  printf 'set color_normal=light-green/black\nset color_highlight=black/black\nset menu_color_normal=black/black\nset menu_color_highlight=black/black\n' > "$G/theme.cfg"
  # Green progress lines while GRUB loads the system from the USB stick
  for f in "$G"/*.cfg; do
    [ -f "$f" ] || continue
    sed -i \
      -e 's/^\([[:space:]]*\)linux\([[:space:]]\)/\1set color_normal=light-green\/black\n\1echo "  > ITAD PhoneSeal"\n\1echo "  > Loading Linux kernel..."\n\1linux\2/' \
      -e 's/^\([[:space:]]*\)initrd\([[:space:]]\)/\1echo "  > Loading drivers and firmware (a few seconds)..."\n\1initrd\2/' \
      "$f"
  done
  for f in "$G"/*.cfg; do sed -i 's/^\([[:space:]]*\)set timeout=.*/\1set timeout=0/' "$f"; done
  [ -f "$G/config.cfg" ] && printf '\nset default=0\nset timeout=0\nset timeout_style=hidden\n' >> "$G/config.cfg"
  if [ -f "$G/grub.cfg" ]; then
    { printf 'set default=0\nset timeout=0\nset timeout_style=hidden\n'; cat "$G/grub.cfg"; } > "$G/g.new"
    mv -f "$G/g.new" "$G/grub.cfg"
  fi
fi
I="$B/isolinux"
if [ -f "$I/live.cfg" ]; then
  L="$(awk 'tolower($1)=="label" {print $2; exit}' "$I/live.cfg")"
  [ -n "$L" ] && printf 'include live.cfg\ndefault %s\nprompt 0\ntimeout 1\n' "$L" > "$I/isolinux.cfg"
fi
exit 0
EOF
chmod +x "$HOOKS/0900-itad-hide-boot-menu.hook.binary"

echo "== 5. Build =="
lb build
ISO="$(ls -1t live-image-*.hybrid.iso binary.hybrid.iso 2>/dev/null | head -n1 || true)"
[ -n "$ISO" ] || { echo "ERROR: no ISO produced" >&2; exit 1; }
mv -f "$ISO" itad-phone.iso
ls -lh itad-phone.iso

echo "== 6. Add an empty ITAD_DATA partition for reports =="
# A 300 MB FAT32 partition called ITAD_DATA is added to the image, so
# every USB written from this ISO has a place to save reports (shown as a
# separate drive in Windows). If this step fails, the normal ISO is kept.
if command -v xorriso >/dev/null && command -v mkfs.vfat >/dev/null; then
  rm -f itad_data.img itad-phone-data.iso
  truncate -s 300M itad_data.img
  mkfs.vfat -F 32 -n ITAD_DATA itad_data.img >/dev/null
  if xorriso -indev itad-phone.iso -outdev itad-phone-data.iso \
       -boot_image any replay \
       -append_partition 3 0x0c itad_data.img 2>&1 | tail -n 5; then
    if [ -s itad-phone-data.iso ]; then
      mv -f itad-phone-data.iso itad-phone.iso
      echo "ITAD_DATA partition added"
    fi
  else
    echo "WARNING: could not add the ITAD_DATA partition (ISO kept as is)"
  fi
  rm -f itad_data.img itad-phone-data.iso
fi
ls -lh itad-phone.iso
