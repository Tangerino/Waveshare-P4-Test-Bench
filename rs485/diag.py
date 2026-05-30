# rs485/diag.py
#
# RS485 (half-duplex) + Modbus-RTU master for the ESP32-P4.
# Use one instance per RS485 port (you have two, for the energy meters).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# HARDWARE: an AUTO-DIRECTION RS485 transceiver (no DE/RE GPIO) is the default
# here — e.g. MAX13487E, or a module with automatic flow control. Just wire
# DI<-UART TX, RO->UART RX, A/B to the bus. (A manual DE/RE transceiver also
# works: pass `de=<gpio>` and the driver will toggle it.)
#
# Auto-direction modules often ECHO the transmitted bytes back on RX (the
# receiver stays enabled during TX). The Modbus layer handles this by scanning
# the received bytes for the valid response frame (matching slave/func + CRC),
# so the echo is skipped automatically — works with or without DE.
#
# !! ASSIGN/VERIFY these pins to FREE header GPIOs on YOUR board (not used by
#    Ethernet/SD/audio/C6/I2C). Defaults are placeholders. !!
#
# Usage (REPL):
#   from rs485 import Modbus
#   m1 = Modbus(uart=1, tx=20, rx=21, baud=9600)   # auto-direction, no DE
#   m1.read_holding(addr=1, reg=0, count=2)        # FC03
#   m1.read_input(addr=1, reg=0, count=2)          # FC04

import struct
import time

import machine

# --- default pin map (PLACEHOLDERS — verify free header GPIOs) ---------------
# Auto-direction transceivers: no DE pin. (Add 'de': <gpio> for manual parts.)
PORTS = {
    1: {'uart': 1, 'tx': 20, 'rx': 21},  # RS485 #1
    2: {'uart': 2, 'tx': 23, 'rx': 24},  # RS485 #2
}
DEFAULT_BAUD = 9600


def _crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc  # appended low-byte first


class RS485:
    """Half-duplex RS485 byte transport.

    de=None  -> auto-direction transceiver (no direction GPIO).
    de=<pin> -> manual transceiver; the driver raises DE, writes, waits for the
                bytes to shift out, then drops DE.
    """

    def __init__(
        self,
        uart=1,
        tx=20,
        rx=21,
        de=None,
        baud=DEFAULT_BAUD,
        bits=8,
        parity=None,
        stop=1,
    ):
        self.baud = baud
        self.de = machine.Pin(de, machine.Pin.OUT) if de is not None else None
        if self.de is not None:
            self.de.value(0)  # receive
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
        self._bits_per_char = 1 + bits + (0 if parity is None else 1) + stop

    def send(self, frame):
        self.uart.read()  # flush stale rx
        if self.de is None:
            self.uart.write(frame)  # auto-direction handles the bus
            return
        self.de.value(1)
        self.uart.write(frame)
        if hasattr(self.uart, 'txdone'):
            t0 = time.ticks_ms()
            while not self.uart.txdone():
                if time.ticks_diff(time.ticks_ms(), t0) > 200:
                    break
            time.sleep_us(150)
        else:
            us = int(1_000_000 * len(frame) * self._bits_per_char / self.baud) + 150
            time.sleep_us(us)
        self.de.value(0)

    def read_window(self, timeout_ms=1000, idle_ms=8):
        """Collect bytes until an idle gap follows received data, or timeout."""
        buf = b''
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        last = time.ticks_ms()
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunk = self.uart.read()
            if chunk:
                buf += chunk
                last = time.ticks_ms()
            else:
                if buf and time.ticks_diff(time.ticks_ms(), last) > idle_ms:
                    break
                time.sleep_ms(2)
        return buf


class Modbus(RS485):
    """Minimal Modbus-RTU master (FC03 read-holding, FC04 read-input).

    Echo-tolerant: locates the valid response frame in the received bytes by
    matching slave address + function code + CRC, so auto-direction echo (or
    line noise) is skipped.
    """

    @staticmethod
    def _extract(buf, addr, func, count):
        for length in (5 + 2 * count, 5):  # normal response, then exception
            for i in range(len(buf) - length + 1):
                f = buf[i : i + length]
                if f[0] != addr or f[1] not in (func, func | 0x80):
                    continue
                c = _crc16(f[:-2])
                if (c & 0xFF) == f[-2] and (c >> 8) == f[-1]:
                    return f
        return None

    def _txn(self, addr, func, reg, count, timeout_ms=1000):
        req = struct.pack('>BBHH', addr, func, reg, count)
        crc = _crc16(req)
        self.send(req + bytes([crc & 0xFF, crc >> 8]))
        raw = self.read_window(timeout_ms)
        f = self._extract(raw, addr, func, count)
        if f is None:
            raise OSError('modbus: no valid response ({} bytes rx)'.format(len(raw)))
        if f[1] & 0x80:
            raise OSError('modbus: exception code {}'.format(f[2]))
        nbytes = f[2]
        return list(struct.unpack('>{}H'.format(nbytes // 2), f[3 : 3 + nbytes]))

    def read_holding(self, addr, reg, count=1, show=True):
        regs = self._txn(addr, 0x03, reg, count)
        if show:
            print(
                '  slave {} holding[{}..{}] = {}'.format(
                    addr, reg, reg + count - 1, regs
                )
            )
        return regs

    def read_input(self, addr, reg, count=1, show=True):
        regs = self._txn(addr, 0x04, reg, count)
        if show:
            print(
                '  slave {} input[{}..{}] = {}'.format(addr, reg, reg + count - 1, regs)
            )
        return regs

    def scan(self, lo=1, hi=16, reg=0, show=True):
        """Probe slave addresses by reading one register; list responders."""
        found = []
        if show:
            print('  Scanning Modbus addresses {}..{}...'.format(lo, hi))
        for a in range(lo, hi + 1):
            try:
                self.read_holding(a, reg, 1, show=False)
                found.append(a)
                if show:
                    print('    addr {} responded'.format(a))
            except OSError:
                pass
        if show and not found:
            print('    none responded (check wiring/baud/termination)')
        return found

    def report(self, port=1):
        print('=' * 78)
        print(
            'RS485 / Modbus-RTU — port {} ({} baud, auto-direction)'.format(
                port, self.baud
            )
        )
        print('=' * 78)
        self.scan()
        print('=' * 78)


def open_port(port=1, baud=DEFAULT_BAUD):
    """Open a configured RS485 port (1 or 2) as a Modbus master."""
    p = PORTS[port]
    return Modbus(uart=p['uart'], tx=p['tx'], rx=p['rx'], de=p.get('de'), baud=baud)


# -- interactive menu ----------------------------------------------------

MENU = """
--- RS485 / Modbus (ESP32-P4, auto-direction) ---
 1) Scan bus (port 1)   3) Read holding reg
 2) Scan bus (port 2)   4) Read input reg
 0) Exit
Choose: """


def main(m=None):
    import netutils

    ports = {}

    def get(p):
        if p not in ports:
            ports[p] = open_port(p)
        return ports[p]

    while True:
        try:
            choice = input(MENU).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ports
        print('> option {}'.format(choice))
        if choice in ('1', '2'):
            netutils.run_action(lambda: get(int(choice)).scan())
        elif choice in ('3', '4'):
            p = int(input('port [1]: ').strip() or '1')
            a = int(input('slave addr [1]: ').strip() or '1')
            r = int(input('register [0]: ').strip() or '0')
            n = int(input('count [2]: ').strip() or '2')
            fn = 'read_holding' if choice == '3' else 'read_input'
            netutils.run_action(lambda: getattr(get(p), fn)(a, r, n))
        elif choice == '0':
            return ports
        else:
            print('?')
