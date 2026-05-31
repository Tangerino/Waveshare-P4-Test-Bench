# serial/diag.py
#
# Raw UART loopback test for the 4 protocol UARTs — pure hardware, no protocol.
# Jumper TX<->RX on each port, then this writes a pattern and verifies it comes
# back. Runs all 4 ports concurrently and sweeps baud to find the max that
# passes per port.
#
# UART0 (the boot/console UART) is intentionally NOT used, to avoid future
# conflicts (boot logs, serial console, ROM download). probe() still reports it.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# Jumper these header pins (TX<->RX) before testing:
#   UART1 GPIO20<->21   UART2 GPIO23<->22
#   UART3 GPIO32<->33   UART4 GPIO26<->27
# (GPIO24/25 are the USB-Serial-JTAG D-/D+ pins — unusable as UART.)
#
# Usage (REPL):
#   from serial import echo, max_speed, report, probe, monitor
#   probe()          # which UART controllers (1..4) this firmware exposes
#   echo(921600)     # all jumpered ports, one baud (per-port KB/s)
#   max_speed()      # sweep -> highest passing baud per port
#   monitor()        # live ON/off-line per port as you fit/remove jumpers
#   report()

import time

import machine

# (label, uart_id, tx, rx) — the 4 testable UARTs, on confirmed free header
# GPIOs. UART0 is deliberately left out (reserved for the boot/console UART);
# GPIO37/38 (TXD/RXD) stay free for it.
PORTS = (
    ('UART1', 1, 20, 21),
    ('UART2', 2, 23, 22),
    ('UART3', 3, 32, 33),  # NOT 24/25 — those are USB-JTAG D-/D+ (the REPL link)
    ('UART4', 4, 26, 27),
)

# Scratch pins used by probe() to test controller availability.
_SCRATCH = (47, 48)

# Baud ladder for the max-speed sweep (low -> high). Kept short for speed.
BAUDS = (115200, 460800, 921600, 2000000, 3000000, 5000000)

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
    """Report which UART controllers (1..4) this firmware can open.

    Uses scratch pins, so it needs no jumpers. UART0 (console) and UART5 are not
    probed — opening them logs noisy ESP-IDF errors and they aren't used here.
    """
    if show:
        print('  Probing UART1..4 (scratch pins {}/{})...'.format(*_SCRATCH))
    avail = []
    for uid in (1, 2, 3, 4):
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
        print('    UART0: reserved (console, not tested)')
        print('  -> usable: {}'.format(avail))
    return avail


def echo(baud=921600, total=2048, show=True):
    """Loop back bytes through the jumpered ports concurrently at `baud`.

    Ports that fail the FIRST round (no jumper) are dropped, so a dead port
    costs one round instead of all of them. Per-port KB/s is measured from each
    port's own receive time, so one port's timeout doesn't skew another's rate.
    """
    if show:
        print('  Echo @ {} baud...'.format(baud))
    chans = []  # [label, uart_or_None, active]
    res = {}
    for label, uid, tx, rx in PORTS:
        res[label] = {
            'opened': False,
            'pass': False,
            'ok': 0,
            'err': 0,
            'kbps': 0,
            '_us': 0,
        }
        try:
            chans.append([label, _open(uid, tx, rx, baud), True])
            res[label]['opened'] = True
        except Exception as e:  # noqa: BLE001
            chans.append([label, None, False])
            res[label]['err_open'] = str(e)

    rounds = max(1, total // CHUNK)
    rt = max(20, int(CHUNK * 14000 / baud) + 8)  # read budget, generous margin
    for rnd in range(rounds):
        for ch in chans:
            if ch[1] and ch[2]:
                ch[1].read()
                ch[1].write(_PATTERN)
        for ch in chans:
            if not (ch[1] and ch[2]):
                continue
            t0 = time.ticks_us()
            got = _read_exact(ch[1], CHUNK, rt)
            r = res[ch[0]]
            if got == _PATTERN:
                r['ok'] += CHUNK
                r['_us'] += time.ticks_diff(time.ticks_us(), t0)
            else:
                r['err'] += 1
        if rnd == 0:  # drop ports with no jumper so the rest stays fast
            for ch in chans:
                if ch[1] and res[ch[0]]['ok'] == 0:
                    ch[2] = False

    for ch in chans:
        if ch[1]:
            ch[1].deinit()
    for label, *_ in PORTS:
        r = res[label]
        r['pass'] = r['opened'] and r['err'] == 0 and r['ok'] > 0
        r['kbps'] = round(r['ok'] / (r['_us'] / 1e6) / 1024, 1) if r['_us'] else 0

    if show:
        for label, *_ in PORTS:
            r = res[label]
            if not r['opened']:
                state = 'UART open FAILED'
            elif r['pass']:
                state = 'ON line   {} KB/s'.format(r['kbps'])
            else:
                state = 'off line  (no jumper)'
            print('    {}: {}'.format(label, state))
    return res


def max_speed(show=True):
    """Sweep the baud ladder; print progress and the highest baud per port."""
    if show:
        print('  Max-speed sweep (jumpered ports only):')
    best = {label: None for label, *_ in PORTS}
    for baud in BAUDS:
        res = echo(baud, total=1024, show=False)
        passed = [label for label in best if res[label]['pass']]
        for label in passed:
            best[label] = baud
        if show:
            print(
                '    {:>7}: {}'.format(baud, ' '.join(p.strip() for p in passed) or '-')
            )
    if show:
        print('  Highest per port:')
        for label, *_ in PORTS:
            b = best[label]
            print(
                '    {}: {}'.format(label, '{} baud'.format(b) if b else 'no loopback')
            )
    return best


def monitor(baud=115200, interval_ms=400):
    """Continuously loopback-test each port; print ON/off-line transitions.

    Install or remove a TX<->RX jumper and watch the status update live. A port
    with no jumper reads back nothing -> 'off line'; fit the jumper -> 'ON line'.
    Ctrl-C stops.
    """
    chans = []
    for label, uid, tx, rx in PORTS:
        try:
            chans.append([label, _open(uid, tx, rx, baud), None])
        except Exception as e:  # noqa: BLE001
            chans.append([label, None, False])
            print('  {}: UART open FAILED ({})'.format(label, e))
    print('Live loopback monitor @ {} baud — fit/remove TX<->RX jumpers.'.format(baud))
    print('Pins: UART1 20<->21  UART2 23<->22  UART3 32<->33  UART4 26<->27')
    print('(Ctrl-C to stop)')
    pat = _PATTERN[:16]
    try:
        while True:
            for ch in chans:
                label, u, prev = ch
                if u is None:
                    continue
                u.read()
                u.write(pat)
                online = _read_exact(u, len(pat), 60) == pat
                if online != prev:
                    print('  {}  {} line'.format(label, 'ON ' if online else 'off'))
                    ch[2] = online
            time.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        print('\n  monitor stopped.')
    finally:
        for label, u, _state in chans:
            if u:
                u.deinit()


def report():
    print('=' * 78)
    print('Serial loopback — 4 UARTs (jumper TX<->RX on each port)')
    print('=' * 78)
    print('Pins: 20<->21  23<->22  32<->33  26<->27   (UART0 reserved — console)')
    print('\nUART controllers:')
    probe(show=True)
    print('\nLoopback @ 921600:')
    echo(921600, show=True)
    print('\nMax baud per port:')
    max_speed(show=True)
    print('=' * 78)
    print('Done.')


# -- interactive menu ----------------------------------------------------

MENU = """
--- Serial loopback (ESP32-P4, 4 UARTs) ---
 1) Full report          4) Probe UART controllers
 2) Max-speed sweep       5) Live ON/off-line monitor
 3) Echo at custom baud   0) Exit
Choose: """


def main(_=None):
    import netutils

    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
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
        elif choice == '5':
            netutils.run_action(monitor)
        elif choice == '0':
            return
        else:
            print('?')
