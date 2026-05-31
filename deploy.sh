#!/usr/bin/env bash
# deploy.sh — copy the ESP32-P4 hardware tests to the board and (re)start.
#
# Usage:
#   ./deploy.sh                 # copy files, reset, open REPL (interactive menu)
#   ./deploy.sh --no-repl       # copy + reset, don't open the REPL
#   ./deploy.sh --wifi          # copy, then WiFi connect + one-shot report
#   ./deploy.sh --eth           # copy, then Ethernet up + one-shot report
#   ./deploy.sh --system        # copy, then CPU/memory/flash one-shot report
#   ./deploy.sh --sd            # copy, then microSD mount + speed one-shot report
#   ./deploy.sh --i2c           # copy, then I2C bus scan
#   ./deploy.sh --sleep         # copy, then sleep info + light-sleep test
#   ./deploy.sh --audio         # copy, then ES8311 probe + test tone
#   ./deploy.sh --gpio          # copy, then GPIO test info (interactive for pins)
#   ./deploy.sh --serial        # copy, then 4-UART loopback + max-baud sweep
#   PORT=/dev/tty.usbmodemXXX ./deploy.sh    # override the port
#
# Override the default port with the PORT env var, or edit it below.

set -euo pipefail

PORT="${PORT:-/dev/tty.usbmodem5B610378241}"
# Root files copied as-is, plus package directories copied recursively.
FILES=(main.py netutils.py)
PKGS=(wifi eth system sdcard i2c sleep audio gpio serial)

# Best-effort: nudge the board out of any running menu/loop to the REPL so the
# upload can always grab it — send a few Ctrl-C straight to the serial port
# (no pyserial needed). The P4 console is native USB-CDC, so writing to the
# port doesn't toggle a reset line. No-op if the port is held by another
# program. macOS uses 'stty -f'; Linux uses 'stty -F'.
wake_repl() {
    { stty -f "$PORT" 115200 clocal 2>/dev/null \
        || stty -F "$PORT" 115200 clocal 2>/dev/null; } || true
    # Hold the port open (fd 3) for the whole burst so tty settings persist.
    # Runs in a subshell so a failed open can't exit deploy.sh.
    (
        exec 3>"$PORT" 2>/dev/null || exit 0
        for _ in 1 2 3 4; do
            printf '\r\003' >&3   # Ctrl-C -> drop a running menu/loop to the REPL
            sleep 0.1
        done
        printf '\r\002\r' >&3     # Ctrl-B: leave raw mode if we landed in it
    ) 2>/dev/null || true
    sleep 0.3
}

usage() {
    cat <<EOF
deploy.sh — upload the ESP32-P4 hardware tests and (re)start.

Usage: ./deploy.sh [option]

Options:
  (none)        Copy files, reset, open the REPL (interactive menu).
  --wifi        Copy, then WiFi connect (default creds) + one-shot report.
  --eth         Copy, then Ethernet up + one-shot report.
  --system      Copy, then CPU/memory/flash one-shot report.
  --sd          Copy, then microSD mount + speed one-shot report.
  --i2c         Copy, then I2C bus scan.
  --sleep       Copy, then sleep info + light-sleep test (non-destructive).
  --audio       Copy, then ES8311 codec probe + a test tone.
  --gpio        Copy, then GPIO test summary (use the menu for live pins).
  --serial      Copy, then 4-UART loopback + max-baud sweep (jumper TX<->RX).
  --no-repl     Copy + reset, but don't open the REPL.
  -h, --help    Show this help and exit.

Environment:
  PORT          Serial device (default: $PORT).
                e.g.  PORT=/dev/tty.usbmodemXXXX ./deploy.sh

Uploaded: ${FILES[*]} + packages: ${PKGS[*]}
EOF
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
esac

cd "$(dirname "$0")"

# Sanity: make sure everything exists before touching the board.
for f in "${FILES[@]}"; do
    [ -f "$f" ] || { echo "error: file $f not found in $(pwd)" >&2; exit 1; }
done
for p in "${PKGS[@]}"; do
    [ -d "$p" ] || { echo "error: package dir $p not found in $(pwd)" >&2; exit 1; }
done

# Build one chained command: fs cp main.py :main.py + fs cp -r wifi :
cp_args=()
add() { [ "${#cp_args[@]}" -gt 0 ] && cp_args+=("+"); cp_args+=("$@"); }
for f in "${FILES[@]}"; do
    add fs cp "$f" ":$f"
done
# secrets.py holds credentials (gitignored). Upload it if present.
if [ -f secrets.py ]; then
    add fs cp secrets.py ":secrets.py"
else
    echo "warning: secrets.py not found — copy secrets_example.py to secrets.py" >&2
    echo "         and add your WiFi creds (defaults will be blank otherwise)." >&2
fi
for p in "${PKGS[@]}"; do
    add fs cp -r "$p" ":"   # recursive: creates :$p/ on the board
done

echo ">> Nudging board to the REPL (Ctrl-C) ..."
wake_repl
echo ">> Uploading ${FILES[*]} + ${PKGS[*]}/ to $PORT"
if ! mpremote connect "$PORT" "${cp_args[@]}"; then
    echo >&2
    echo "!! Upload failed ('could not enter raw repl' usually means the board" >&2
    echo "   is busy or a serial monitor is attached). Try:" >&2
    echo "     - close any open REPL / serial terminal on $PORT" >&2
    echo "     - press Ctrl-C in the board's menu to drop to the REPL, then retry" >&2
    echo "     - or unplug/replug the board and run ./deploy.sh again" >&2
    exit 1
fi
echo ">> Upload OK"

case "${1:-}" in
    --wifi|--scan)
        echo ">> WiFi connect (default creds) + one-shot report (non-interactive)"
        exec mpremote connect "$PORT" exec \
            "from wifi import WiFiDiagnostics; d = WiFiDiagnostics(); d.connect(); d.report()"
        ;;
    --eth)
        echo ">> Ethernet up + one-shot report (non-interactive)"
        exec mpremote connect "$PORT" exec \
            "from eth import EthernetDiagnostics; e = EthernetDiagnostics(); e.report()"
        ;;
    --system)
        echo ">> System (CPU/memory/flash) one-shot report (non-interactive)"
        exec mpremote connect "$PORT" exec \
            "from system import SystemDiagnostics; s = SystemDiagnostics(); s.report()"
        ;;
    --sd)
        echo ">> microSD mount + speed one-shot report (non-interactive)"
        exec mpremote connect "$PORT" exec \
            "from sdcard import SDCardDiagnostics; SDCardDiagnostics().report()"
        ;;
    --i2c)
        echo ">> I2C bus scan (non-interactive)"
        exec mpremote connect "$PORT" exec \
            "from i2c import I2CDiagnostics; I2CDiagnostics().report()"
        ;;
    --sleep)
        echo ">> Sleep info + light-sleep test (non-destructive)"
        exec mpremote connect "$PORT" exec \
            "from sleep import SleepDiagnostics; SleepDiagnostics().report()"
        ;;
    --audio)
        echo ">> ES8311 codec probe + test tone"
        exec mpremote connect "$PORT" exec \
            "from audio import AudioDiagnostics; AudioDiagnostics().report()"
        ;;
    --gpio)
        echo ">> GPIO test summary (use the menu for live pin control)"
        exec mpremote connect "$PORT" exec \
            "from gpio import GPIODiagnostics; GPIODiagnostics().report()"
        ;;
    --serial)
        echo ">> 4-UART loopback + max-baud sweep (jumper TX<->RX on each port)"
        exec mpremote connect "$PORT" exec \
            "from serial import report; report()"
        ;;
    --no-repl)
        echo ">> Resetting board"
        mpremote connect "$PORT" reset
        ;;
    "")
        echo ">> Resetting board and opening REPL (Ctrl-] to exit)"
        mpremote connect "$PORT" reset
        exec mpremote connect "$PORT" repl
        ;;
    *)
        echo "error: unknown option '$1'" >&2
        echo >&2
        usage >&2
        exit 1
        ;;
esac
