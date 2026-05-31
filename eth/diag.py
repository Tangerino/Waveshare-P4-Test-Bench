# eth/diag.py
#
# Ethernet diagnostics for the Waveshare ESP32-P4-NANO.
# The P4's built-in EMAC drives an IP101 (IP101GRI) PHY over RMII.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI); verified v1.29.0-preview.
#
# --- Verified pin map (Waveshare wiki + ESPHome board config) ---------------
#   PHY              : IP101 (IP101GRI),  phy_addr = 1
#   MDC              : GPIO31     (settable)
#   MDIO             : GPIO52     (settable)
#   PHY power/reset  : GPIO51     (settable -> `power`)
#   RMII REF_CLK     : GPIO50     (settable -> `ref_clk`); 50 MHz fed INTO the
#                                  P4 from the board, so ref_clk_mode = Pin.IN
#   RMII data pins   : TXD0=34 TXD1=35 RXD0=30 RXD1=29 TX_EN=49 CRS_DV=28
#
# IMPORTANT: the RMII data pins above are wired on the board and fixed by the
# firmware's EMAC config — they are NOT arguments to network.LAN(). If MDC/
# MDIO/power/clk are correct but the link never comes up, the firmware build's
# RMII data-pin mapping doesn't match this board (needs a board-specific build).
#
# Usage (REPL):
#   from eth import EthernetDiagnostics, main
#   e = EthernetDiagnostics()
#   e.up()        # bring the link up + DHCP
#   e.report()    # full one-shot report
#   main()        # interactive menu

import time
import network

import netutils

PHY_NAME = 'IP101'  # -> network.PHY_IP101
PIN_MDC = 31
PIN_MDIO = 52
PIN_POWER = 51  # PHY reset / enable
PIN_REF_CLK = 50  # 50 MHz RMII reference clock, input to the P4
PHY_ADDR = 1


class EthernetDiagnostics:
    def __init__(self):
        self.lan = None

    # -- setup -----------------------------------------------------------

    def setup(self):
        """Construct the LAN interface once, with sensible fallbacks."""
        if self.lan is not None:
            return self.lan
        if not hasattr(network, 'LAN'):
            raise OSError('network.LAN not in this firmware — no Ethernet build')

        from machine import Pin

        phy = getattr(network, 'PHY_' + PHY_NAME, None)
        try:
            self.lan = network.LAN(
                mdc=Pin(PIN_MDC),
                mdio=Pin(PIN_MDIO),
                power=Pin(PIN_POWER),
                ref_clk=Pin(PIN_REF_CLK),
                ref_clk_mode=Pin.IN,
                phy_type=phy,
                phy_addr=PHY_ADDR,
            )
            print(
                '  LAN configured: IP101 mdc={} mdio={} power={} clk={}(IN)'.format(
                    PIN_MDC, PIN_MDIO, PIN_POWER, PIN_REF_CLK
                )
            )
        except (TypeError, ValueError, OSError) as e:
            # Different builds expose slightly different LAN signatures; fall
            # back to whatever board config the firmware already knows.
            print(
                '  explicit LAN config failed ({}); trying firmware default'.format(e)
            )
            self.lan = network.LAN()
            print('  LAN configured from firmware board defaults')
        return self.lan

    # -- link control ----------------------------------------------------

    def up(self, timeout=15, show=True):
        """Bring the interface up and wait for link + DHCP lease."""
        lan = self.setup()
        if not lan.active():
            lan.active(True)
        if show:
            print('Bringing Ethernet up (link + DHCP, up to {}s)...'.format(timeout))
        deadline = time.ticks_add(time.ticks_ms(), timeout * 1000)
        while not lan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                print(
                    '  TIMEOUT: no link/DHCP. Check cable, PHY power (GPIO{}),'.format(
                        PIN_POWER
                    )
                )
                print('  and that the firmware RMII data pins match this board.')
                self.status(show=True)
                return False
            time.sleep_ms(250)
        if show:
            print('  link up.')
            self.ifconfig(show=True)
        return True

    def down(self, show=True):
        if self.lan is not None:
            try:
                self.lan.active(False)
            except OSError:
                pass
        if show:
            print('  Ethernet down.')

    def ensure_up(self):
        """Auto-bring-up if not already linked (no prompts)."""
        if self.lan is not None and self.lan.isconnected():
            return True
        print('  (auto-bringing Ethernet up ...)')
        return self.up()

    # -- info ------------------------------------------------------------

    def status(self, show=True):
        lan = self.lan
        info = {'configured': lan is not None}
        if lan is not None:
            try:
                info['active'] = lan.active()
            except OSError:
                info['active'] = '?'
            try:
                info['link_up'] = lan.isconnected()
            except OSError:
                info['link_up'] = '?'
        if show:
            print('  Configured : {}'.format(info['configured']))
            if lan is not None:
                print('  Active     : {}'.format(info.get('active')))
                print('  Link up    : {}'.format(info.get('link_up')))
                print('  MAC        : {}'.format(self.mac()))
        return info

    def mac(self):
        try:
            m = self.lan.config('mac')
            return ':'.join('{:02x}'.format(b) for b in m)
        except (ValueError, OSError, AttributeError):
            return 'unavailable'

    def ifconfig(self, show=True):
        if self.lan is None:
            print('  not configured — run up() first.')
            return None
        ip, mask, gw, dns = self.lan.ifconfig()
        info = {'ip': ip, 'netmask': mask, 'gateway': gw, 'dns': dns}
        if show:
            print('  IP address : {}'.format(ip))
            print('  Netmask    : {}'.format(mask))
            print('  Gateway    : {}'.format(gw))
            print('  DNS        : {}'.format(dns))
        return info

    # -- connectivity ----------------------------------------------------

    def ping(self, host='8.8.8.8', **kw):
        if not self.ensure_up():
            print('  ping: link not up.')
            return None
        return netutils.ping(host, **kw)

    def speedtest(self, url=None, forever=False, show=True):
        if not self.ensure_up():
            print('  link not up; cannot run speed test.')
            return None
        return netutils.speedtest(download_url=url, show=show, forever=forever)

    def connectivity(self, show=True):
        if not self.ensure_up():
            print('  link not up; cannot test connectivity.')
            return {'link_up': False}
        if show:
            print('\nConnectivity:')
        dns_ok = netutils.resolve('example.org', show=show) is not None
        net_ok = netutils.tcp_check('8.8.8.8', 53, show=show)
        return {'link_up': True, 'dns_ok': dns_ok, 'internet_ok': net_ok}

    # -- full report -----------------------------------------------------

    def report(self):
        print('=' * 78)
        print('Ethernet Diagnostics — ESP32-P4-NANO / IP101 (MicroPython)')
        print('=' * 78)
        if not self.up(show=True):
            print('\nStatus:')
            self.status(show=True)
            print('=' * 78)
            return
        print('\nStatus:')
        self.status(show=True)
        print('\nIP configuration:')
        self.ifconfig(show=True)
        self.connectivity(show=True)
        print('\nPing:')
        self.ping(show=True)
        print('\nSpeed:')
        self.speedtest(show=True)
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Ethernet Diagnostics (ESP32-P4 / IP101) ---
 1) Full report          5) Connectivity (DNS + internet)
 2) Bring up (link+DHCP)  6) Ping
 3) Status                7) Speed test (download + latency)
 4) IP config             9) Bring down
                          0) Exit
Choose: """


def main(e=None):
    """Interactive entry point for the Ethernet tests."""
    e = e or EthernetDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return e
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(e.report)
        elif choice == '2':
            netutils.run_action(e.up)
        elif choice == '3':
            netutils.run_action(e.status)
        elif choice == '4':
            netutils.run_action(e.ifconfig)
        elif choice == '5':
            netutils.run_action(e.connectivity)
        elif choice == '6':
            host = input('host [8.8.8.8]: ').strip() or '8.8.8.8'
            netutils.run_action(lambda: e.ping(host, count=0))  # forever
        elif choice == '7':
            netutils.run_action(lambda: e.speedtest(forever=True))  # forever
        elif choice == '9':
            netutils.run_action(e.down)
        elif choice == '0':
            return e
        else:
            print('?')
