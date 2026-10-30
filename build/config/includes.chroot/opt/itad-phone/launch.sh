#!/bin/bash
# launch.sh - starts the ITAD phone station (PhoneSeal)
# Finds its own folder automatically (works in /opt or /opt/itad-phone).
# 1) Tests that the new window can open. 2) Opens it.
# 3) If it cannot open, shows the old text screen and says why.

SELF="$(readlink -f "$0")"
APP_DIR="$(dirname "$SELF")"
APP="$APP_DIR/phone_core.py"
WINDOW="$APP_DIR/phone_window.py"
LOG="/tmp/itad-launch.log"
WINLOG="/tmp/itad-window.log"
DATA_LABEL="ITAD_DATA"
DATA_MNT="/mnt/itad"

log() { echo "$(date '+%F %T') $*" >> "$LOG" 2>/dev/null; }

# ------------------------------------------------------------
# INNER MODE: menu / old text screen, runs inside xterm
# Usage: launch.sh --inner [--menu]
#   --menu = show the menu first (do not start the old tool)
# ------------------------------------------------------------
if [ "${1:-}" = "--inner" ]; then
    export TERM="${TERM:-xterm-256color}"
    clear

    CONTINUE_FLAG=""
    SKIP_RUN="0"
    [ "${2:-}" = "--menu" ] && SKIP_RUN="1"

    while true; do
        if [ -n "${WINDOW_PROBLEM:-}" ]; then
            echo "NOTE: the new window did not start."
            echo "Reason: $WINDOW_PROBLEM"
            echo "More details: cat $WINLOG"
            echo
            WINDOW_PROBLEM=""
        fi

        if [ "$SKIP_RUN" = "1" ]; then
            SKIP_RUN="0"
        elif ! command -v python3 >/dev/null 2>&1; then
            echo "ERROR: python3 is not installed on this USB."
        elif [ ! -f "$APP" ]; then
            echo "ERROR: $APP not found."
            echo "Files in $APP_DIR:"
            ls -1 "$APP_DIR" 2>/dev/null
        else
            cd "$APP_DIR" || true
            log "starting phone_core.py with flags: $CONTINUE_FLAG"
            sudo ITAD_DATA="$ITAD_DATA" python3 "$APP" $CONTINUE_FLAG
            log "phone_core.py exited with code $?"
        fi

        echo
        echo "=============================================="
        echo "  ITAD tool has stopped. What now?"
        echo "=============================================="
        echo "  [W] Open the new PhoneSeal window"
        echo "  [R] List the connected phones (text)"
        echo "  [N] Wi-Fi / network settings"
        echo "  [S] Open a shell (for technicians)"
        echo "  [B] Reboot"
        echo "  [P] Power off"
        echo
        read -r -n1 -p "  Choose W / R / N / S / B / P: " choice
        echo
        case "${choice,,}" in
            w) cd "$APP_DIR" || true
               sudo -E ITAD_DATA="$ITAD_DATA" python3 "$WINDOW" 2>&1 | tee "$WINLOG"
               SKIP_RUN="1" ;;
            r) CONTINUE_FLAG=""; clear ;;
            n) clear; sudo nmtui; clear ;;
            s) clear; echo "Type 'exit' to come back to this menu."; bash ;;
            b) sync; sudo reboot ;;
            p) sync; sudo poweroff ;;
            *) SKIP_RUN="1"; clear ;;
        esac
    done
    exit 0
fi

# ------------------------------------------------------------
# OUTER MODE: prepare the system, then open the tool
# ------------------------------------------------------------
touch "$LOG"
: > "$WINLOG"
log "launch.sh started from $APP_DIR"

# 1. Never let the screen go blank or sleep
sudo setterm -blank 0 -powerdown 0 2>/dev/null || true

# 1b. Wi-Fi: switch it on and fix cards that find no networks (e.g. the
#     Realtek RTL8723BE in HP laptops). Runs in the background, about 1
#     minute at most, log in /tmp/itad-wifi.log (see wifi_fix.sh).
if [ -f "$APP_DIR/wifi_fix.sh" ]; then
    sudo bash "$APP_DIR/wifi_fix.sh" >/dev/null 2>&1 &
fi

# 2. Find (or make) a place to save reports: ITAD_DATA partition,
#    another USB stick, or the boot stick itself (see itad_storage.sh)
read -r ITAD_DATA ITAD_DATA_PERSIST ITAD_DATA_WHERE <<EOF_ST
$(sudo bash "$APP_DIR/itad_storage.sh" 2>>"$LOG")
EOF_ST
if [ -z "$ITAD_DATA" ] || [ ! -d "$ITAD_DATA" ]; then
    mkdir -p /tmp/itad-reports
    ITAD_DATA=/tmp/itad-reports; ITAD_DATA_PERSIST=0; ITAD_DATA_WHERE=memory_only
fi
sudo chmod 777 "$ITAD_DATA" 2>/dev/null
export ITAD_DATA ITAD_DATA_PERSIST ITAD_DATA_WHERE
log "reports go to $ITAD_DATA (persistent=$ITAD_DATA_PERSIST, $ITAD_DATA_WHERE)"

# 3. Wait for the graphical screen (up to 30 seconds)
if [ -z "${DISPLAY:-}" ] && [ -S /tmp/.X11-unix/X0 ]; then
    export DISPLAY=":0"
fi
for i in $(seq 1 30); do
    if [ -n "${DISPLAY:-}" ] && command -v xset >/dev/null 2>&1 && xset q >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# 4. Screen settings and hidden mouse pointer
if command -v xset >/dev/null 2>&1; then
    xset s off 2>/dev/null
    xset -dpms 2>/dev/null
    xset s noblank 2>/dev/null
fi
if command -v unclutter >/dev/null 2>&1; then
    unclutter -idle 0.5 -root >/dev/null 2>&1 &
fi

# 5. Test that the new window CAN open (before starting it)
PROBLEM=""
if [ -z "${DISPLAY:-}" ]; then
    PROBLEM="no graphical screen found"
elif ! command -v python3 >/dev/null 2>&1; then
    PROBLEM="python3 is not installed"
elif [ ! -f "$WINDOW" ]; then
    PROBLEM="phone_window.py not found in $APP_DIR"
elif ! sudo -E python3 -c "import tkinter" >>"$WINLOG" 2>&1; then
    PROBLEM="Tkinter is not installed (add python3-tk to the package list)"
elif ! sudo -E DISPLAY="$DISPLAY" python3 -c "import tkinter; tkinter.Tk().destroy()" >>"$WINLOG" 2>&1; then
    PROBLEM="Tkinter cannot open a window on screen $DISPLAY"
fi

# 6. Open the new window, or fall back
if [ -z "$PROBLEM" ]; then
    log "starting phone_window.py on $DISPLAY"
    cd "$APP_DIR" || true
    sudo -E ITAD_DATA="$ITAD_DATA" ITAD_DATA_PERSIST="$ITAD_DATA_PERSIST" ITAD_DATA_WHERE="$ITAD_DATA_WHERE" DISPLAY="$DISPLAY" python3 "$WINDOW" >>"$WINLOG" 2>&1
    code=$?
    log "phone_window.py exited with code $code (details in $WINLOG)"
    if [ "$code" -ne 0 ]; then
        export WINDOW_PROBLEM="the window stopped with an error (code $code)"
    fi
    # After the window closes: show the menu (not the old tool)
    if command -v xterm >/dev/null 2>&1; then
        exec xterm -fullscreen +sb -title "ITAD PhoneSeal" \
            -fa "DejaVu Sans Mono" -fs 13 -bg "#050a14" -fg "#e6f1ff" \
            -e bash "$SELF" --inner --menu
    else
        exec bash "$SELF" --inner --menu
    fi
fi

# 7. FALLBACK: old text screen, and say why
log "window not started: $PROBLEM"
export WINDOW_PROBLEM="$PROBLEM"
if [ -n "${DISPLAY:-}" ] && command -v xterm >/dev/null 2>&1 && xset q >/dev/null 2>&1; then
    exec xterm -fullscreen +sb \
        -title "ITAD PhoneSeal" \
        -fa "DejaVu Sans Mono" -fs 13 \
        -bg "#050a14" -fg "#e6f1ff" \
        -e bash "$SELF" --inner --menu
else
    exec bash "$SELF" --inner --menu
fi
