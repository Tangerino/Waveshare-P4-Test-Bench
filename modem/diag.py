# modem/diag.py
#
# Quectel EC200U / EG915U (LTE Cat-1) driver for the ESP32-P4: power-on, AT
# engine, network registration, and MQTT via the module's built-in QMTxxx AT
# stack (no PPP needed).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# HARDWARE (critical):
#   * POWER: the modem needs its OWN 3.4-4.2 V supply (~2 A bursts on TX) with
#     bulk caps (1000uF + 100uF). Do NOT power it from the P4 3V3 rail.
#   * IO LEVEL: EC200U/EG915U UART VIO is 1.8 V -> use a level shifter
#     (TXS0108E) between the P4 (3.3 V) and the modem, unless your breakout
#     already shifts to 3.3 V.
#   * PWRKEY: pulse to power the module on. Polarity depends on your drive
#     circuit (usually an NPN transistor inverts it) -> set `pwrkey_active`.
#
# Pins confirmed against the board's GPIO-header pinout (free header GPIOs).
#
# Usage (REPL):
#   from modem import QuectelModem
#   q = QuectelModem(uart=4, tx=26, rx=27, pwrkey=32, pwr_en=33)
#   q.power_on(); q.info(); q.wait_network()
#   q.mqtt_publish_once('broker.host', 1883, 'p4-meter',
#                       'meters/p4', '{"kwh": 123}')

import time

import machine

UART_ID = 4
PIN_TX = 26  # header GPIO26
PIN_RX = 27  # header GPIO27
PIN_PWRKEY = 32  # header GPIO32
PIN_PWR_EN = 33  # header GPIO33 (modem 3.8 V buck enable; set None to skip)
DEFAULT_BAUD = 115200


def _txt(resp):
    return ' '.join(resp.decode('utf-8', 'ignore').split())


class QuectelModem:
    def __init__(
        self,
        uart=UART_ID,
        tx=PIN_TX,
        rx=PIN_RX,
        pwrkey=PIN_PWRKEY,
        pwr_en=PIN_PWR_EN,
        baud=DEFAULT_BAUD,
        pwrkey_active=1,
    ):
        self.uart = machine.UART(
            uart,
            baudrate=baud,
            tx=machine.Pin(tx),
            rx=machine.Pin(rx),
            timeout=300,
            timeout_char=50,
        )
        self.pwrkey = machine.Pin(pwrkey, machine.Pin.OUT)
        self.pwrkey_active = pwrkey_active
        self.pwrkey.value(0 if pwrkey_active else 1)
        self.pwr_en = (
            machine.Pin(pwr_en, machine.Pin.OUT) if pwr_en is not None else None
        )

    # -- low level -------------------------------------------------------

    def _write(self, s):
        self.uart.write(s if isinstance(s, bytes) else s.encode())

    def _read_until(self, tokens, timeout_ms):
        if isinstance(tokens, (bytes, str)):
            tokens = [tokens]
        tokens = [t.encode() if isinstance(t, str) else t for t in tokens]
        buf = b''
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunk = self.uart.read()
            if chunk:
                buf += chunk
                if any(t in buf for t in tokens):
                    return buf
            else:
                time.sleep_ms(10)
        return buf

    def at(self, cmd, timeout_ms=3000, expect=('OK', 'ERROR'), show=False):
        self.uart.read()  # flush
        self._write(cmd + '\r\n')
        resp = self._read_until(list(expect), timeout_ms)
        if show:
            print('  {:<22} -> {}'.format(cmd, _txt(resp) or '<timeout>'))
        return resp

    @staticmethod
    def _ok(resp):
        return b'OK' in resp

    # -- power -----------------------------------------------------------

    def power_on(self, show=True):
        if self.pwr_en is not None:
            self.pwr_en.value(1)
            time.sleep_ms(200)
        # PWRKEY pulse (>= 500 ms low at the module pin)
        self.pwrkey.value(self.pwrkey_active)
        time.sleep_ms(700)
        self.pwrkey.value(0 if self.pwrkey_active else 1)
        if show:
            print('  PWRKEY pulsed; waiting for module RDY...')
        self._read_until(['RDY', 'APP RDY'], 15000)
        for _ in range(20):
            if self._ok(self.at('AT', 1000)):
                self.at('ATE0')  # echo off
                if show:
                    print('  module responding (AT OK)')
                return True
            time.sleep_ms(500)
        print('  NO RESPONSE — check 3.8V supply, PWRKEY polarity, level shifter, baud')
        return False

    # -- info / network --------------------------------------------------

    def signal(self, show=True):
        r = self.at('AT+CSQ')
        rssi = None
        try:
            s = _txt(r).split('+CSQ:')[1].split()[0]
            rssi = int(s.split(',')[0])
        except (IndexError, ValueError):
            pass
        dbm = (-113 + 2 * rssi) if (rssi is not None and rssi != 99) else None
        if show:
            print(
                '  Signal     : CSQ={} ({})'.format(
                    rssi, '{} dBm'.format(dbm) if dbm is not None else 'unknown'
                )
            )
        return {'csq': rssi, 'dbm': dbm}

    def info(self, show=True):
        items = (
            ('Model', 'AT+CGMM'),
            ('Revision', 'AT+CGMR'),
            ('IMEI', 'AT+CGSN'),
            ('SIM ICCID', 'AT+QCCID'),
            ('Reg (CEREG)', 'AT+CEREG?'),
            ('Operator', 'AT+COPS?'),
        )
        out = {}
        for label, cmd in items:
            out[label] = _txt(self.at(cmd))
            if show:
                print('  {:<12}: {}'.format(label, out[label]))
        self.signal(show=show)
        return out

    def wait_network(self, timeout=60, show=True):
        if show:
            print('  Waiting for network registration (up to {}s)...'.format(timeout))
        deadline = time.ticks_add(time.ticks_ms(), timeout * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            r = _txt(self.at('AT+CEREG?'))
            # +CEREG: <n>,<stat> ; stat 1=home, 5=roaming
            if '+CEREG:' in r:
                stat = r.split('+CEREG:')[1].split(',')[1].strip()[:1]
                if stat in ('1', '5'):
                    if show:
                        print('  registered (stat={})'.format(stat))
                    return True
            time.sleep_ms(1000)
        print('  network registration TIMEOUT (SIM? antenna? coverage?)')
        return False

    # -- MQTT (Quectel built-in QMTxxx) ----------------------------------

    def mqtt_open(self, host, port=1883, idx=0, timeout=15, show=True):
        self.uart.read()
        self._write('AT+QMTOPEN={},"{}",{}\r\n'.format(idx, host, port))
        r = self._read_until(['+QMTOPEN:', 'ERROR'], timeout * 1000)
        ok = '+QMTOPEN: {},0'.format(idx).encode() in r
        if show:
            print('  MQTT open {}:{} -> {}'.format(host, port, 'OK' if ok else _txt(r)))
        return ok

    def mqtt_connect(self, client_id, user=None, pw=None, idx=0, timeout=15, show=True):
        if user is not None:
            cmd = 'AT+QMTCONN={},"{}","{}","{}"'.format(idx, client_id, user, pw)
        else:
            cmd = 'AT+QMTCONN={},"{}"'.format(idx, client_id)
        self.uart.read()
        self._write(cmd + '\r\n')
        r = self._read_until(['+QMTCONN:', 'ERROR'], timeout * 1000)
        ok = '+QMTCONN: {},0,0'.format(idx).encode() in r
        if show:
            print(
                '  MQTT connect "{}" -> {}'.format(client_id, 'OK' if ok else _txt(r))
            )
        return ok

    def mqtt_sub(self, topic, qos=0, idx=0, msgid=1, show=True):
        self.uart.read()
        self._write('AT+QMTSUB={},{},"{}",{}\r\n'.format(idx, msgid, topic, qos))
        r = self._read_until(['+QMTSUB:', 'ERROR'], 10000)
        ok = '+QMTSUB:'.encode() in r and b'ERROR' not in r
        if show:
            print('  MQTT sub "{}" -> {}'.format(topic, 'OK' if ok else _txt(r)))
        return ok

    def mqtt_pub(self, topic, payload, qos=0, retain=0, idx=0, msgid=0, show=True):
        self.uart.read()
        self._write(
            'AT+QMTPUB={},{},{},{},"{}"\r\n'.format(idx, msgid, qos, retain, topic)
        )
        r = self._read_until(['>', 'ERROR'], 3000)
        if b'>' not in r:
            if show:
                print('  MQTT pub: no ">" prompt ({})'.format(_txt(r)))
            return False
        self._write(payload if isinstance(payload, bytes) else payload.encode())
        self._write(b'\x1a')  # Ctrl-Z = send
        r = self._read_until(['+QMTPUB:', 'ERROR'], 15000)
        ok = '+QMTPUB:'.encode() in r and b'ERROR' not in r
        if show:
            print(
                '  MQTT pub "{}" ({} B) -> {}'.format(
                    topic, len(payload), 'OK' if ok else _txt(r)
                )
            )
        return ok

    def mqtt_disconnect(self, idx=0, show=True):
        self.at('AT+QMTDISC={}'.format(idx), 5000)
        if show:
            print('  MQTT disconnected')

    def mqtt_publish_once(
        self, host, port, client_id, topic, msg, user=None, pw=None, qos=0, show=True
    ):
        """End-to-end: ensure network, open, connect, publish, disconnect."""
        if not self.wait_network(show=show):
            return False
        if not self.mqtt_open(host, port, show=show):
            return False
        if not self.mqtt_connect(client_id, user, pw, show=show):
            return False
        ok = self.mqtt_pub(topic, msg, qos=qos, show=show)
        self.mqtt_disconnect(show=show)
        return ok

    # -- report ----------------------------------------------------------

    def report(self):
        print('=' * 78)
        print('Quectel modem (EC200U/EG915U) — ESP32-P4')
        print('=' * 78)
        if not self.power_on(show=True):
            print('=' * 78)
            return
        print('\nModule info:')
        self.info(show=True)
        print('\nNetwork:')
        self.wait_network(show=True)
        print('(MQTT: use mqtt_publish_once(host, port, client_id, topic, msg))')
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Quectel modem (ESP32-P4) ---
 1) Power on + info     3) Wait network reg
 2) Signal (CSQ)        4) MQTT publish test
 0) Exit
Choose: """


def main(q=None):
    import netutils

    q = q or QuectelModem()
    while True:
        try:
            choice = input(MENU).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return q
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(lambda: (q.power_on(), q.info()))
        elif choice == '2':
            netutils.run_action(q.signal)
        elif choice == '3':
            netutils.run_action(q.wait_network)
        elif choice == '4':
            host = input('broker host: ').strip()
            port = int(input('port [1883]: ').strip() or '1883')
            cid = input('client id [p4]: ').strip() or 'p4'
            topic = input('topic [test/p4]: ').strip() or 'test/p4'
            msg = input('message [hello]: ').strip() or 'hello'
            netutils.run_action(
                lambda: q.mqtt_publish_once(host, port, cid, topic, msg)
            )
        elif choice == '0':
            return q
        else:
            print('?')
