# gpio/diag.py
#
# Generic GPIO test for the ESP32-P4 — drive/blink/read any pin or header.
# The ESP32-P4-NANO has no documented user LED (only a power indicator), so
# this points at an arbitrary GPIO: wire an LED (+ resistor) or a scope/meter
# to verify output, or read a button/jumper as input.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# Usage (REPL):
#   from gpio import GPIODiagnostics, main
#   g = GPIODiagnostics()
#   g.blink(2, count=10, period_ms=200)   # blink GPIO2 ten times
#   g.high(2); g.low(2); g.read(2)
#   main()

import time

import machine


class GPIODiagnostics:
    def blink(self, pin, count=5, period_ms=500, show=True):
        """Toggle `pin` on/off `count` times with `period_ms` per half-cycle."""
        p = machine.Pin(pin, machine.Pin.OUT)
        if show:
            print('  Blinking GPIO{} x{} ({} ms)...'.format(pin, count, period_ms))
        try:
            for i in range(count):
                p.value(1)
                if show:
                    print('    [{}/{}] HIGH'.format(i + 1, count))
                time.sleep_ms(period_ms)
                p.value(0)
                time.sleep_ms(period_ms)
        except KeyboardInterrupt:
            p.value(0)
            print('  stopped.')
        if show:
            print('  done (GPIO{} left LOW).'.format(pin))
        return {'pin': pin, 'count': count}

    def high(self, pin, show=True):
        machine.Pin(pin, machine.Pin.OUT).value(1)
        if show:
            print('  GPIO{} driven HIGH'.format(pin))

    def low(self, pin, show=True):
        machine.Pin(pin, machine.Pin.OUT).value(0)
        if show:
            print('  GPIO{} driven LOW'.format(pin))

    def read(self, pin, pull=None, show=True):
        """Read `pin` as input. pull: None / 'up' / 'down'."""
        pulls = {
            None: None,
            'up': machine.Pin.PULL_UP,
            'down': getattr(machine.Pin, 'PULL_DOWN', None),
        }
        p = machine.Pin(pin, machine.Pin.IN, pulls.get(pull))
        v = p.value()
        if show:
            print('  GPIO{} reads {} (pull={})'.format(pin, v, pull or 'none'))
        return v

    def report(self):
        print('=' * 78)
        print('GPIO Test — ESP32-P4')
        print('=' * 78)
        print('  No dedicated user LED on the P4-NANO; use the menu to drive or')
        print('  read any GPIO. Wire an LED+resistor or a meter to a header pin.')
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- GPIO Test (ESP32-P4) ---
 1) Blink a pin        3) Drive LOW
 2) Drive HIGH         4) Read a pin
 0) Exit
Choose: """


def _ask_pin():
    s = input('GPIO number: ').strip()
    return int(s) if s else None


def main(g=None):
    import netutils

    g = g or GPIODiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return g
        print('> option {}'.format(choice))
        if choice == '1':
            pin = _ask_pin()
            if pin is None:
                continue
            n = input('count [10]: ').strip()
            ms = input('period ms [250]: ').strip()
            netutils.run_action(
                lambda: g.blink(pin, int(n) if n else 10, int(ms) if ms else 250)
            )
        elif choice == '2':
            pin = _ask_pin()
            if pin is not None:
                netutils.run_action(lambda: g.high(pin))
        elif choice == '3':
            pin = _ask_pin()
            if pin is not None:
                netutils.run_action(lambda: g.low(pin))
        elif choice == '4':
            pin = _ask_pin()
            if pin is not None:
                pull = input('pull up/down/none [none]: ').strip() or None
                netutils.run_action(lambda: g.read(pin, pull))
        elif choice == '0':
            return g
        else:
            print('?')
