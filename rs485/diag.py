# rs485/diag.py
#
# RS485 (half-duplex) + Modbus-RTU master for the ESP32-P4.
# Use one instance per RS485 port (you have two, for the energy meters).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# HARDWARE: a 3.3 V RS485 transceiver (MAX3485 / SP3485 / THVD1450, or isolated
# ADM2587E). DI<-UART TX, RO->UART RX, DE+/RE tied together -> one GPIO
# (high = transmit, low = receive). 120 ohm termination at each bus end.
#
# MicroPython has no native RS485 DE control, so we raise DE, write, wait for
# the bytes to shift out (uart.txdone() if available, else a baud-based delay),
# then drop DE to receive.
#
# !! ASSIGN/VERIFY these pins to FREE header GPIOs on YOUR board (not used by
#    Ethernet/SD/audio/C6/I2C). Defaults are placeholders. !!
#
# Usage (REPL):
#   from rs485 import Modbus
#   m1 = Modbus(uart=1, tx=20, rx=21, de=22, baud=9600)   # meter bus 1
#   m1.read_holding(addr=1, reg=0, count=2)               # FC03
#   m1.read_input(addr=1, reg=0, count=2)                 # FC04

import struct
import time

import machine

# --- default pin map (PLACEHOLDERS — verify free header GPIOs) ---------------
PORTS = {
    1: {'uart': 1, 'tx': 20, 'rx': 21, 'de': 22},  # RS485 #1
    2: {'uart': 2, 'tx': 23, 'rx': 24, 'de': 25},  # RS485 #2
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
    """Half-duplex RS485 byte transport with auto DE direction control."""

    def __init__(
        self,
        uart=1,
        tx=20,
        rx=21,
        de=22,
        baud=DEFAULT_BAUD,
        bits=8,
        parity=None,
        stop=1,
    ):
        self.baud = baud
        self.de = machine.Pin(de, machine.Pin.OUT)
        self.de.value(0)  # receive by default
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
        # per-char bit time (start + data + parity + stop)
        self._bits_per_char = 1 + bits + (0 if parity is None else 1) + stop

    def send(self, frame):
        self.uart.read()  # flush stale rx
        self.de.value(1)
        self.uart.write(frame)
        if hasattr(self.uart, 'txdone'):
            t0 = time.ticks_ms()
            while not self.uart.txdone():
                if time.ticks_diff(time.ticks_ms(), t0) > 200:
                    break
        # guard for the final stop bit even after txdone
        us = int(1_000_000 * len(frame) * self._bits_per_char / self.baud) + 150
        time.sleep_us(us if not hasattr(self.uart, 'txdone') else 150)
        self.de.value(0)

    def recv(self, n, timeout_ms=1000):
        buf = b''
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while len(buf) < n and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunk = self.uart.read(n - len(buf))
            if chunk:
                buf += chunk
            else:
                time.sleep_ms(2)
        return buf


class Modbus(RS485):
    """Minimal Modbus-RTU master (FC03 read-holding, FC04 read-input)."""

    def _txn(self, addr, func, reg, count, timeout_ms=1000):
        req = struct.pack('>BBHH', addr, func, reg, count)
        crc = _crc16(req)
        self.send(req + bytes([crc & 0xFF, crc >> 8]))
        # response: addr, func, bytecount, data(2*count), crc(2)
        resp = self.recv(5 + 2 * count, timeout_ms)
        if len(resp) < 5:
            raise OSError('modbus: timeout/short response ({} bytes)'.format(len(resp)))
        if resp[0] != addr:
            raise OSError('modbus: wrong slave addr 0x{:02X}'.format(resp[0]))
        if resp[1] & 0x80:
            raise OSError('modbus: exception code {}'.format(resp[2]))
        rcrc = _crc16(resp[:-2])
        if (rcrc & 0xFF, rcrc >> 8) != (resp[-2], resp[-1]):
            raise OSError('modbus: CRC mismatch')
        nbytes = resp[2]
        regs = struct.unpack('>{}H'.format(nbytes // 2), resp[3 : 3 + nbytes])
        return list(regs)

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
        print('RS485 / Modbus-RTU — port {} ({} baud)'.format(port, self.baud))
        print('=' * 78)
        self.scan()
        print('=' * 78)


def open_port(port=1, baud=DEFAULT_BAUD):
    """Open a configured RS485 port (1 or 2) as a Modbus master."""
    p = PORTS[port]
    return Modbus(uart=p['uart'], tx=p['tx'], rx=p['rx'], de=p['de'], baud=baud)


# -- interactive menu ----------------------------------------------------

MENU = """
--- RS485 / Modbus (ESP32-P4) ---
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
