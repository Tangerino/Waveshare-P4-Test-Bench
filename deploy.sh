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
#   ./deploy.sh --ble           # copy, then BLE probe + scan
#   ./deploy.sh --thread        # copy, then threading/IPC/perf report
#   PORT=/dev/tty.usbmodemXXX ./deploy.sh    # override the port
#
# Override the default port with the PORT env var, or edit it below.

set -euo pipefail

PORT="${PORT:-/dev/tty.usbmodem5B610378241}"
# Root files copied as-is, plus package directories copied recursively.
FILES=(main.py netutils.py)
PKGS=(wifi eth system sdcard i2c sleep audio gpio serial ble thread)

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
  --ble         Copy, then BLE availability probe + scan.
  --thread      Copy, then threading + message-passing + perf report.
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

echo ">> Uploading ${FILES[*]} + ${PKGS[*]}/ to $PORT"
# Capture mpremote's output so its Python traceback never reaches the user.
# On success show the cp progress; on failure show only a clean one-line reason.
if out=$(mpremote connect "$PORT" "${cp_args[@]}" 2>&1); then
    [ -n "$out" ] && printf '%s\n' "$out"
    echo ">> Upload OK"
else
    reason=$(printf '%s\n' "$out" \
        | grep -ioE 'could not enter raw repl|no device|permission denied|[A-Za-z]*Error[^"]*' \
        | tail -1)
    echo >&2
    echo "!! Upload failed: ${reason:-could not access the board on $PORT}" >&2
    echo "   The board is busy — mpremote couldn't interrupt it to upload. Try:" >&2
    echo "     1. Close any open REPL / serial monitor holding $PORT." >&2
    echo "     2. Tap the board's RST/EN button (or unplug/replug), then re-run." >&2
    echo "     3. Or: mpremote connect $PORT repl  ->  press 0 to reach >>> " >&2
    echo "        ->  Ctrl-]  ->  ./deploy.sh" >&2
    echo "   (One-time only: once this build is on the board, Ctrl-C drops to the" >&2
    echo "    REPL, so future deploys interrupt the menu automatically.)" >&2
    exit 1
fi

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
    --ble)
        echo ">> BLE availability probe + scan"
        exec mpremote connect "$PORT" exec \
            "from ble import BLEDiagnostics; BLEDiagnostics().report()"
        ;;
    --thread)
        echo ">> Threading + message-passing + parallel-perf report"
        exec mpremote connect "$PORT" exec \
            "from thread import ThreadDiagnostics; ThreadDiagnostics().report()"
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
