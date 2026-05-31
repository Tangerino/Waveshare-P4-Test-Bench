# ble/diag.py
#
# BLE diagnostics for the ESP32-P4 (BLE comes from the on-board ESP32-C6 over
# the esp-hosted link — the P4 has no radio of its own).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# IMPORTANT: BLE over the hosted C6 link is NOT guaranteed on every build. The
# 'C6_WIFI' firmware may expose only WiFi. probe() checks whether the
# `bluetooth` module exists and the controller activates; if not, it says so.
#
# Usage (REPL):
#   from ble import BLEDiagnostics, main
#   b = BLEDiagnostics()
#   b.probe()          # is BLE available on this firmware?
#   b.scan(5000)       # passive/active scan: list nearby BLE advertisers
#   b.advertise('P4-TEST')       # advertise until Ctrl-C (phone can see it)
#   b.report(); main()

import time

try:
    import bluetooth
except ImportError:  # pragma: no cover
    bluetooth = None

_IRQ_SCAN_RESULT = 5
_IRQ_SCAN_DONE = 6

# GAP advertising data AD types.
_AD_FLAGS = 0x01
_AD_NAME_SHORT = 0x08
_AD_NAME_COMPLETE = 0x09


def _fmt_addr(addr):
    return ':'.join('{:02x}'.format(b) for b in addr)


def _decode_name(payload):
    """Pull a device name out of advertising data (AD type 0x08/0x09)."""
    i = 0
    n = len(payload)
    while i + 1 < n:
        length = payload[i]
        if length == 0:
            break
        atype = payload[i + 1]
        if atype in (_AD_NAME_SHORT, _AD_NAME_COMPLETE):
            try:
                return bytes(payload[i + 2 : i + 1 + length]).decode()
            except Exception:  # noqa: BLE001
                return '?'
        i += 1 + length
    return ''


class BLEDiagnostics:
    def __init__(self):
        self.ble = None
        self._found = {}
        self._done = True

    # -- availability ----------------------------------------------------

    def _get(self):
        if self.ble is None:
            if bluetooth is None:
                raise OSError('bluetooth module not in this firmware')
            self.ble = bluetooth.BLE()
        return self.ble

    def probe(self, show=True):
        """Check whether BLE is usable on this build/firmware."""
        info = {'module': bluetooth is not None, 'active': False}
        if bluetooth is None:
            if show:
                print('  bluetooth module: NOT present in this firmware')
                print('  -> BLE not available (C6_WIFI build is WiFi-only?)')
            return info
        try:
            ble = self._get()
            ble.active(True)
            info['active'] = bool(ble.active())
            try:
                info['mac'] = _fmt_addr(ble.config('mac')[1])
            except (OSError, ValueError, TypeError):
                pass
        except Exception as e:  # noqa: BLE001
            info['error'] = str(e)
        if show:
            print('  bluetooth module: present')
            if info['active']:
                print('  BLE controller  : ACTIVE')
                if 'mac' in info:
                    print('  BLE address     : {}'.format(info['mac']))
                print('  -> BLE works over the hosted C6 link.')
            else:
                print(
                    '  BLE controller  : FAILED to activate ({})'.format(
                        info.get('error', 'no error')
                    )
                )
                print('  -> the hosted C6 link likely does not bridge BLE.')
        return info

    # -- scan ------------------------------------------------------------

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            key = bytes(addr)
            name = _decode_name(adv_data)
            prev = self._found.get(key)
            # keep the strongest sighting, prefer one that has a name
            if prev is None or rssi > prev['rssi'] or (name and not prev['name']):
                self._found[key] = {
                    'addr': _fmt_addr(addr),
                    'rssi': rssi,
                    'name': name,
                    'type': addr_type,
                    'adv': adv_type,
                }
        elif event == _IRQ_SCAN_DONE:
            self._done = True

    def scan(self, duration_ms=5000, active=True, show=True):
        """Scan for advertising BLE devices. Returns a list sorted by RSSI."""
        ble = self._get()
        ble.active(True)
        ble.irq(self._irq)
        self._found = {}
        self._done = False
        if show:
            print('  Scanning {} s...'.format(duration_ms // 1000))
        # interval/window in us; active=True sends scan reqs (gets names)
        ble.gap_scan(duration_ms, 30000, 30000, active)
        deadline = time.ticks_add(time.ticks_ms(), duration_ms + 1000)
        while not self._done and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(50)
        try:
            ble.gap_scan(None)  # ensure stopped
        except Exception:  # noqa: BLE001
            pass
        devices = sorted(self._found.values(), key=lambda d: d['rssi'], reverse=True)
        if show:
            print('\n  {} BLE device(s):'.format(len(devices)))
            print('  ' + '-' * 60)
            print('  {:<18} {:>5} {:<4} {}'.format('ADDR', 'RSSI', 'TYP', 'NAME'))
            print('  ' + '-' * 60)
            for d in devices:
                print(
                    '  {:<18} {:>5} {:<4} {}'.format(
                        d['addr'],
                        d['rssi'],
                        'rnd' if d['type'] else 'pub',
                        d['name'] or '<no name>',
                    )
                )
            print('  ' + '-' * 60)
        return devices

    # -- advertise -------------------------------------------------------

    def advertise(self, name='P4-TEST', secs=0, show=True):
        """Advertise a named beacon (find it in a phone BLE app).

        secs<=0 (default) advertises until Ctrl-C; otherwise for `secs` seconds.
        """
        ble = self._get()
        ble.active(True)
        payload = bytes((2, _AD_FLAGS, 0x06))  # general discoverable, BR/EDR off
        nm = name.encode()
        payload += bytes((len(nm) + 1, _AD_NAME_COMPLETE)) + nm
        forever = secs <= 0
        if show:
            window = 'until Ctrl-C' if forever else 'for {} s'.format(secs)
            print(
                '  Advertising as {!r} {} (scan with a phone BLE app)...'.format(
                    name, window
                )
            )
        ble.gap_advertise(100000, adv_data=payload)  # 100 ms interval
        try:
            if forever:
                while True:
                    time.sleep_ms(500)
            else:
                time.sleep(secs)
        except KeyboardInterrupt:
            pass
        finally:
            ble.gap_advertise(None)
        if show:
            print('  stopped advertising.')

    # -- report ----------------------------------------------------------

    def report(self):
        print('=' * 78)
        print('BLE Diagnostics — ESP32-P4 / ESP32-C6 (hosted)')
        print('=' * 78)
        info = self.probe(show=True)
        if info.get('active'):
            print('\nScan:')
            self.scan(5000, show=True)
        else:
            print('\n(BLE not active — scan skipped.)')
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- BLE Diagnostics (ESP32-P4 / C6) ---
 1) Full report       3) Advertise a beacon
 2) Scan (5 s)        0) Exit
Choose: """


def main(b=None):
    import netutils

    b = b or BLEDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return b
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(b.report)
        elif choice == '2':
            s = input('seconds [5]: ').strip()
            netutils.run_action(lambda: b.scan(int(s or '5') * 1000))
        elif choice == '3':
            nm = input('name [P4-TEST]: ').strip() or 'P4-TEST'
            netutils.run_action(lambda: b.advertise(nm))
        elif choice == '0':
            return b
        else:
            print('?')
