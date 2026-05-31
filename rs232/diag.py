# rs232/diag.py
#
# Plain TTL UART port for the ESP32-P4 (your "RS232" 4-pin RX/TX/GND/VCC is
# TTL 3.3 V, so it wires straight to a UART — no transceiver).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# HARDWARE: UART TX -> device RX, UART RX <- device TX, 3V3 -> VCC, GND -> GND.
# (If it were TRUE +-12 V RS232, you'd add a MAX3232 between the UART and the
# connector; nothing changes in this driver.)
#
# Pins confirmed against the board's GPIO-header pinout (free header GPIOs).
#
# Usage (REPL):
#   from rs232 import RS232
#   p = RS232(uart=3, tx=24, rx=25, baud=115200)
#   p.write('hello\r\n'); print(p.read())
#   p.loopback()        # jumper TX<->RX to self-test

import time

import machine

UART_ID = 3
PIN_TX = 24  # header GPIO24
PIN_RX = 25  # header GPIO25
DEFAULT_BAUD = 115200


class RS232:
    def __init__(
        self,
        uart=UART_ID,
        tx=PIN_TX,
        rx=PIN_RX,
        baud=DEFAULT_BAUD,
        bits=8,
        parity=None,
        stop=1,
    ):
        self.baud = baud
        self.tx, self.rx = tx, rx
        self.uart = machine.UART(
            uart,
            baudrate=baud,
            tx=machine.Pin(tx),
            rx=machine.Pin(rx),
            bits=bits,
            parity=parity,
            stop=stop,
            timeout=200,
            timeout_char=20,
        )

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        return self.uart.write(data)

    def read(self, n=None, timeout_ms=500):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        buf = b''
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunk = self.uart.read(n) if n else self.uart.read()
            if chunk:
                buf += chunk
                if n and len(buf) >= n:
                    break
            else:
                time.sleep_ms(5)
        return buf

    def readline(self, timeout_ms=1000):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        buf = b''
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            c = self.uart.read(1)
            if c:
                buf += c
                if c == b'\n':
                    break
            else:
                time.sleep_ms(2)
        return buf

    def loopback(self, msg=b'P4-RS232-TEST', show=True):
        """Self-test: jumper TX<->RX, send msg, expect it back."""
        self.uart.read()  # flush
        self.write(msg)
        got = self.read(len(msg), timeout_ms=500)
        ok = got == msg
        if show:
            print(
                '  loopback (TX{}<->RX{}): sent {} got {} -> {}'.format(
                    self.tx, self.rx, msg, got, 'OK' if ok else 'FAIL'
                )
            )
            if not ok:
                print('    jumper TX to RX to test; check pins/baud.')
        return ok

    def report(self):
        print('=' * 78)
        print(
            'RS232/TTL UART{} TX={} RX={} @ {} baud'.format(
                UART_ID, self.tx, self.rx, self.baud
            )
        )
        print('=' * 78)
        self.loopback()
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- RS232 / TTL UART (ESP32-P4) ---
 1) Loopback self-test   3) Read (5 s)
 2) Send text            0) Exit
Choose: """


def main(p=None):
    import netutils

    p = p or RS232()
    while True:
        try:
            choice = input(MENU).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return p
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(p.loopback)
        elif choice == '2':
            s = input('text to send: ')
            netutils.run_action(lambda: print('  sent', p.write(s + '\r\n'), 'bytes'))
        elif choice == '3':
            netutils.run_action(lambda: print('  rx:', p.read(timeout_ms=5000)))
        elif choice == '0':
            return p
        else:
            print('?')
