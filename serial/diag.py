# serial/diag.py
#
# Raw UART loopback test for all 5 UARTs — pure hardware, no protocol.
# Jumper TX<->RX on each port, then this writes a pattern and verifies it comes
# back. Runs all 5 ports concurrently and sweeps baud to find the max that
# passes per port.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# Jumper these header pins (TX<->RX) before testing:
#   RS485#1 GPIO20<->21   RS485#2 GPIO23<->22
#   RS232   GPIO24<->25   Modem   GPIO26<->27   UART0 GPIO37<->38
#
# Usage (REPL):
#   from serial import echo, max_speed, report, probe
#   probe()          # which UART controllers (0..5) this firmware exposes
#   echo(921600)     # all 5 ports, one baud
#   max_speed()      # sweep -> highest passing baud per port
#   report()

import time

import machine

# (label, uart_id, tx, rx) — the 5 ports, on confirmed free header GPIOs.
# UART0 (GPIO37/38) is the board's boot/console UART; usable here because the
# REPL is on USB-Serial-JTAG, but it may print boot logs — see probe().
PORTS = (
    ('RS485#1', 1, 20, 21),
    ('RS485#2', 2, 23, 22),
    ('RS232  ', 3, 24, 25),
    ('Modem  ', 4, 26, 27),
    ('UART0  ', 0, 37, 38),  # spare header UART (TXD/RXD pins)
)

# Scratch pins used by probe() to test controller availability.
_SCRATCH = (47, 48)

# Baud ladder for the max-speed sweep (low -> high).
BAUDS = (115200, 460800, 921600, 1500000, 2000000, 3000000, 4000000, 5000000)

CHUNK = 64  # bytes per round (<= rxbuf to avoid overflow before readback)
_PATTERN = bytes(((i * 7 + 13) & 0xFF) for i in range(CHUNK))


def _open(uart_id, tx, rx, baud):
    return machine.UART(
        uart_id,
        baudrate=baud,
        tx=machine.Pin(tx),
        rx=machine.Pin(rx),
        bits=8,
        parity=None,
        stop=1,
        timeout=50,
        timeout_char=5,
        rxbuf=256,
        txbuf=256,
    )


def _read_exact(u, n, timeout_ms):
    buf = b''
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while len(buf) < n and time.ticks_diff(deadline, time.ticks_ms()) > 0:
        c = u.read(n - len(buf))
        if c:
            buf += c
    return buf


def probe(show=True):
    """Report which UART controller ids (0..5) this firmware can open.

    Uses scratch pins, so it needs no jumpers. UART0 is the boot/console UART;
    opening it is fine when the REPL is on USB-Serial-JTAG.
    """
    if show:
        print('  Probing UART controllers (scratch pins {}/{})...'.format(*_SCRATCH))
    avail = []
    for uid in range(6):
        try:
            u = machine.UART(
                uid,
                baudrate=115200,
                tx=machine.Pin(_SCRATCH[0]),
                rx=machine.Pin(_SCRATCH[1]),
            )
            u.deinit()
            avail.append(uid)
            if show:
                print('    UART{}: available'.format(uid))
        except Exception as e:  # noqa: BLE001
            if show:
                print('    UART{}: no ({})'.format(uid, e))
    if show:
        print('  -> {} UART controller(s): {}'.format(len(avail), avail))
    return avail


def echo(baud=921600, total=4096, show=True):
    """Loop back `total` bytes through all 5 ports concurrently at `baud`.

    Returns {label: {'ok_bytes', 'errors', 'opened', 'kbps', 'pass'}}.
    """
    if show:
        print('  Echo all ports @ {} baud ({} bytes each)...'.format(baud, total))
    chans = []
    res = {}
    for label, uid, tx, rx in PORTS:
        res[label] = {
            'ok_bytes': 0,
            'errors': 0,
            'opened': False,
            'kbps': 0,
            'pass': False,
        }
        try:
            chans.append((label, _open(uid, tx, rx, baud)))
            res[label]['opened'] = True
        except Exception as e:  # noqa: BLE001
            chans.append((label, None))
            res[label]['err_open'] = str(e)

    rounds = max(1, total // CHUNK)
    # per-byte timeout budget grows for slow baud
    rt = max(50, int(CHUNK * 12000 / baud) + 20)
    t0 = time.ticks_ms()
    for _ in range(rounds):
        for label, u in chans:
            if u:
                u.read()  # clear stale
                u.write(_PATTERN)
        for label, u in chans:
            if not u:
                continue
            got = _read_exact(u, CHUNK, rt)
            if got == _PATTERN:
                res[label]['ok_bytes'] += CHUNK
            else:
                res[label]['errors'] += 1
    dt = max(1, time.ticks_diff(time.ticks_ms(), t0))

    for label, u in chans:
        if u:
            u.deinit()
        r = res[label]
        r['pass'] = r['opened'] and r['errors'] == 0 and r['ok_bytes'] > 0
        r['kbps'] = round(r['ok_bytes'] * 1000 / dt / 1024, 1)

    if show:
        for label, _uid, _tx, _rx in PORTS:
            r = res[label]
            if not r['opened']:
                state = 'UART open FAILED'
            elif r['pass']:
                state = 'PASS  {} KB/s'.format(r['kbps'])
            else:
                state = 'FAIL  ({} err) — jumper TX<->RX?'.format(r['errors'])
            print('    {}: {}'.format(label, state))
    return res


def max_speed(show=True):
    """Sweep the baud ladder; report the highest passing baud per port."""
    if show:
        print('  Max-speed sweep ({}..{} baud)...'.format(BAUDS[0], BAUDS[-1]))
    best = {label: None for label, *_ in PORTS}
    for baud in BAUDS:
        res = echo(baud, total=2048, show=False)
        for label in best:
            if res[label]['pass']:
                best[label] = baud
    if show:
        for label, *_ in PORTS:
            b = best[label]
            print(
                '    {}: {}'.format(
                    label, '{} baud'.format(b) if b else 'no loopback (jumper?)'
                )
            )
    return best


def report():
    print('=' * 78)
    print('Serial loopback — 5 UARTs (jumper TX<->RX on each port)')
    print('=' * 78)
    print('Pins: 20<->21  23<->22  24<->25  26<->27  37<->38')
    print('\nUART controllers:')
    probe(show=True)
    print('\nConcurrent echo @ 921600:')
    echo(921600, show=True)
    print('\nPer-port maximum baud:')
    best = max_speed(show=True)
    ok = [b for b in best.values() if b]
    if ok:
        common = min(ok)
        print('\nAll-ports concurrent @ {} (min of the maxes):'.format(common))
        echo(common, show=True)
    print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Serial loopback (ESP32-P4, 5 UARTs) ---
 1) Full report          3) Echo at custom baud
 2) Max-speed sweep       4) Probe UART controllers
 0) Exit
Choose: """


def main(_=None):
    import netutils

    while True:
        try:
            choice = input(MENU).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(report)
        elif choice == '2':
            netutils.run_action(max_speed)
        elif choice == '3':
            b = int(input('baud [921600]: ').strip() or '921600')
            netutils.run_action(lambda: echo(b))
        elif choice == '4':
            netutils.run_action(probe)
        elif choice == '0':
            return
        else:
            print('?')
