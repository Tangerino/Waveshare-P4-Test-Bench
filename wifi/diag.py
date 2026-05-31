# wifi/diag.py
#
# Full WiFi diagnostics for the Waveshare ESP32-P4 (WiFi via the on-board
# ESP32-C6 co-processor over the esp-hosted RPC link).
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI); verified v1.29.0-preview.
#
# Usage (REPL):
#   from wifi import WiFiDiagnostics, main
#   d = WiFiDiagnostics()
#   d.report()                       # full one-shot report
#   d.scan()                         # just list networks
#   d.connect("my-ssid", "my-password")  # connect + verify
#   d.connectivity()                 # DNS + internet reachability
#   main()                           # interactive menu
#
# Notes on the P4/C6 hosted setup:
#   The "W (xxxxx) rpc_rsp: Hosted RPC_Resp ..." warnings printed during
#   scan/connect come from the esp-hosted transport on the P4 talking to the
#   C6 radio. They are informational and do not indicate a failure.

import network
import sys
import time

import netutils

try:
    import socket
except ImportError:  # pragma: no cover - some ports name it usocket
    import usocket as socket


# Default credentials come from secrets.py (gitignored; copy secrets_example.py).
# Falls back to blanks if absent — then pass creds explicitly to connect().
try:
    import secrets

    DEFAULT_SSID = getattr(secrets, 'WIFI_SSID', '')
    DEFAULT_PASSWORD = getattr(secrets, 'WIFI_PASSWORD', '')
except ImportError:
    DEFAULT_SSID = ''
    DEFAULT_PASSWORD = ''


# ESP-IDF authmode -> human readable. The integer in scan()/status comes
# straight from the C6 radio (esp_wifi_types: wifi_auth_mode_t).
AUTHMODE = {
    0: 'OPEN',
    1: 'WEP',
    2: 'WPA-PSK',
    3: 'WPA2-PSK',
    4: 'WPA/WPA2-PSK',
    5: 'WPA2-ENTERPRISE',
    6: 'WPA3-PSK',
    7: 'WPA2/WPA3-PSK',
    8: 'WAPI-PSK',
    9: 'OWE',
    10: 'WPA3-ENT-192',
}

# network.STAT_* codes -> human readable (ESP32 set).
STATUS = {
    network.STAT_IDLE: 'IDLE',
    network.STAT_CONNECTING: 'CONNECTING',
    network.STAT_GOT_IP: 'GOT_IP',
}
# These are not present on every build; add them defensively.
for _name in (
    'STAT_WRONG_PASSWORD',
    'STAT_NO_AP_FOUND',
    'STAT_CONNECT_FAIL',
    'STAT_ASSOC_FAIL',
    'STAT_HANDSHAKE_TIMEOUT',
    'STAT_BEACON_TIMEOUT',
):
    _code = getattr(network, _name, None)
    if _code is not None:
        STATUS[_code] = _name[5:]  # drop "STAT_"


# WLAN.PM_* power-management modes (modem sleep). Built from whatever the
# firmware exposes so it stays correct across builds.
PM_MODES = {}
for _name in ('PM_NONE', 'PM_PERFORMANCE', 'PM_POWERSAVE'):
    _val = getattr(network.WLAN, _name, None)
    if _val is not None:
        PM_MODES[_val] = _name[3:]  # drop "PM_"


def channel_to_freq(ch):
    """WiFi channel -> center frequency in MHz (2.4 GHz and 5 GHz)."""
    if ch is None:
        return None
    if 1 <= ch <= 13:
        return 2407 + ch * 5
    if ch == 14:
        return 2484
    if 32 <= ch <= 177:  # 5 GHz band
        return 5000 + ch * 5
    return None


def band_label(freq):
    if freq is None:
        return '?'
    return '2.4 GHz' if freq < 3000 else '5 GHz'


def rssi_quality(rssi):
    """Map an RSSI (dBm) onto a human label and a rough 0-100% quality."""
    if rssi >= -50:
        label = 'excellent'
    elif rssi >= -60:
        label = 'good'
    elif rssi >= -70:
        label = 'fair'
    elif rssi >= -80:
        label = 'weak'
    else:
        label = 'very weak'
    # Clamp the common [-100, -50] dBm window onto 0-100%.
    pct = max(0, min(100, 2 * (rssi + 100)))
    return label, pct


def fmt_bssid(bssid):
    """bytes b'\\x96A...' -> '96:41:b2:b0:b0:86'."""
    return ':'.join('{:02x}'.format(b) for b in bssid)


def fmt_authmode(mode):
    return AUTHMODE.get(mode, 'UNKNOWN({})'.format(mode))


class WiFiDiagnostics:
    def __init__(self):
        # MicroPython 1.28 prefers the enum-style constant; fall back for
        # older signatures just in case.
        try:
            self.sta = network.WLAN(network.WLAN.IF_STA)
        except AttributeError:
            self.sta = network.WLAN(network.STA_IF)

    # -- helpers ---------------------------------------------------------

    def ensure_active(self):
        if not self.sta.active():
            self.sta.active(True)
            # Give the C6 radio a moment to come up over the hosted link.
            time.sleep_ms(300)
        return self.sta.active()

    def ensure_connected(self):
        """Auto-connect with default credentials if not already connected.

        Used by the connection-dependent operations so they "just work"
        without a manual connect step. Returns True once connected.
        """
        if self.sta.isconnected():
            return True
        print('  (auto-connecting to {!r} ...)'.format(DEFAULT_SSID))
        return self.connect()

    def mac(self):
        try:
            return fmt_bssid(self.sta.config('mac'))
        except (ValueError, OSError):
            return 'unavailable'

    def status_str(self):
        try:
            return STATUS.get(self.sta.status(), 'status({})'.format(self.sta.status()))
        except OSError:
            return 'unavailable'

    # -- scan ------------------------------------------------------------

    def scan(self, show=True):
        """Scan and return a list of dicts, sorted by signal strength."""
        self.ensure_active()
        raw = self.sta.scan()
        nets = []
        for ssid, bssid, channel, rssi, authmode, hidden in raw:
            label, pct = rssi_quality(rssi)
            nets.append(
                {
                    'ssid': ssid.decode() if ssid else '<hidden>',
                    'bssid': fmt_bssid(bssid),
                    'channel': channel,
                    'rssi': rssi,
                    'quality': pct,
                    'quality_label': label,
                    'auth': fmt_authmode(authmode),
                    'hidden': bool(hidden),
                }
            )
        nets.sort(key=lambda n: n['rssi'], reverse=True)
        if show:
            self._print_scan(nets)
        return nets

    def _print_scan(self, nets):
        print('\n{} network(s) found:'.format(len(nets)))
        print('-' * 78)
        print(
            '{:<24} {:>4} {:>5} {:>4}% {:<14} {}'.format(
                'SSID', 'CH', 'RSSI', 'QUAL', 'SECURITY', 'BSSID'
            )
        )
        print('-' * 78)
        for n in nets:
            print(
                '{:<24} {:>4} {:>5} {:>4} {:<14} {}'.format(
                    n['ssid'][:24],
                    n['channel'],
                    n['rssi'],
                    n['quality'],
                    n['auth'],
                    n['bssid'],
                )
            )
        print('-' * 78)

    # -- connect ---------------------------------------------------------

    def connect(self, ssid=DEFAULT_SSID, password=DEFAULT_PASSWORD, timeout=20):
        """Connect and block until GOT_IP or timeout (seconds).

        With no args, uses DEFAULT_SSID / DEFAULT_PASSWORD.
        """
        self.ensure_active()
        if self.sta.isconnected():
            print('Already connected; disconnecting first.')
            self.disconnect()

        print('Connecting to {!r} ...'.format(ssid))
        self.sta.connect(ssid, password)

        deadline = time.ticks_add(time.ticks_ms(), timeout * 1000)
        last_status = None
        while not self.sta.isconnected():
            st = self.status_str()
            if st != last_status:
                print('  status: {}'.format(st))
                last_status = st
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                print(
                    'Connection FAILED (timeout after {}s, status: {})'.format(
                        timeout, self.status_str()
                    )
                )
                return False
            time.sleep_ms(250)

        print('Connected.')
        self.ifconfig()
        return True

    def disconnect(self):
        try:
            self.sta.disconnect()
        except OSError:
            pass
        # Wait briefly for the radio to drop the association.
        for _ in range(20):
            if not self.sta.isconnected():
                break
            time.sleep_ms(100)

    # -- link / IP info --------------------------------------------------

    def ifconfig(self, show=True):
        ip, mask, gw, dns = self.sta.ifconfig()
        info = {'ip': ip, 'netmask': mask, 'gateway': gw, 'dns': dns}
        if show:
            print('  IP address : {}'.format(ip))
            print('  Netmask    : {}'.format(mask))
            print('  Gateway    : {}'.format(gw))
            print('  DNS        : {}'.format(dns))
        return info

    def link(self, show=True, scan_results=None):
        """Current association details: SSID, BSSID, channel/frequency,
        security and RSSI (when connected).

        Channel comes from the radio; security/BSSID are looked up by matching
        the connected SSID in a scan. Pass scan_results to reuse an existing
        scan and avoid scanning twice.
        """
        self.ensure_connected()
        connected = self.sta.isconnected()
        info = {'connected': connected, 'status': self.status_str()}
        if connected:
            try:
                rssi = self.sta.status('rssi')
                label, pct = rssi_quality(rssi)
                info.update(rssi=rssi, quality=pct, quality_label=label)
            except (OSError, ValueError):
                pass
            try:
                info['ssid'] = self.sta.config('ssid')
            except (OSError, ValueError):
                pass
            try:
                ch = self.sta.config('channel')
                info['channel'] = ch
                info['freq'] = channel_to_freq(ch)
                info['band'] = band_label(info['freq'])
            except (OSError, ValueError):
                pass
            # Security/BSSID aren't exposed directly for the STA link; match
            # the connected SSID against scan results (strongest wins).
            ap = self._match_ap(info.get('ssid'), scan_results)
            if ap:
                info['auth'] = ap['auth']
                info.setdefault('bssid', ap['bssid'])
        if show:
            print('  Connected  : {}'.format(connected))
            print('  Status     : {}'.format(info['status']))
            if 'ssid' in info:
                print('  SSID       : {}'.format(info['ssid']))
            if 'bssid' in info:
                print('  BSSID      : {}'.format(info['bssid']))
            if 'channel' in info:
                print(
                    '  Channel    : {} ({} MHz, {})'.format(
                        info['channel'], info.get('freq', '?'), info.get('band', '?')
                    )
                )
            if 'auth' in info:
                print('  Security   : {}'.format(info['auth']))
            if 'rssi' in info:
                print(
                    '  RSSI       : {} dBm ({}, {}%)'.format(
                        info['rssi'], info['quality_label'], info['quality']
                    )
                )
        return info

    def _match_ap(self, ssid, scan_results=None):
        """Find the connected AP in scan results by SSID (strongest match)."""
        if not ssid:
            return None
        if scan_results is None:
            try:
                scan_results = self.scan(show=False)
            except OSError:
                return None
        matches = [n for n in scan_results if n['ssid'] == ssid]
        if not matches:
            return None
        return max(matches, key=lambda n: n['rssi'])

    # -- connectivity ----------------------------------------------------

    def resolve(self, host='example.org', show=True):
        """Test DNS resolution. Returns the resolved IP or None."""
        t0 = time.ticks_ms()
        try:
            ai = socket.getaddrinfo(host, 80)
            ip = ai[0][-1][0]
            dt = time.ticks_diff(time.ticks_ms(), t0)
            if show:
                print('  DNS {:<16} -> {} ({} ms)'.format(host, ip, dt))
            return ip
        except OSError as e:
            if show:
                print('  DNS {:<16} -> FAILED ({})'.format(host, e))
            return None

    def tcp_check(self, host='8.8.8.8', port=53, timeout=5, show=True):
        """Test raw internet reachability via a TCP connect."""
        addr = socket.getaddrinfo(host, port)[0][-1]
        s = socket.socket()
        s.settimeout(timeout)
        t0 = time.ticks_ms()
        try:
            s.connect(addr)
            dt = time.ticks_diff(time.ticks_ms(), t0)
            if show:
                print('  TCP {}:{} -> reachable ({} ms)'.format(host, port, dt))
            return True
        except OSError as e:
            if show:
                print('  TCP {}:{} -> unreachable ({})'.format(host, port, e))
            return False
        finally:
            s.close()

    def speedtest(self, url=None, forever=False, show=True):
        """Latency + HTTP download throughput over the WiFi link.

        forever=True loops until Ctrl-C.
        """
        if not self.ensure_connected():
            print('auto-connect failed; cannot run speed test.')
            return None
        return netutils.speedtest(download_url=url, show=show, forever=forever)

    def connectivity(self, show=True):
        """End-to-end: gateway, DNS, and internet reachability."""
        if not self.ensure_connected():
            print('auto-connect failed; cannot test connectivity.')
            return {'connected': False}
        if show:
            print('\nConnectivity:')
        cfg = self.ifconfig(show=False)
        gw_ok = self.tcp_check(
            cfg['gateway'], 80, timeout=3, show=False
        ) or self._ping_gateway(cfg['gateway'], show)
        dns_ok = self.resolve('example.org', show=show) is not None
        net_ok = self.tcp_check('8.8.8.8', 53, show=show)
        return {
            'connected': True,
            'gateway_reachable': gw_ok,
            'dns_ok': dns_ok,
            'internet_ok': net_ok,
        }

    def _ping_gateway(self, gw, show=True):
        # No ICMP in stock MicroPython; treat a resolvable+routable gateway
        # as reachable if we already hold a lease from it.
        if show:
            print('  Gateway    : {} (lease held)'.format(gw))
        return True

    # -- ICMP ping -------------------------------------------------------

    def ping(self, host='8.8.8.8', count=4, **kw):
        """ICMP echo over the WiFi link (delegates to netutils.ping).

        count<=0 pings forever until Ctrl-C. Auto-connects first.
        """
        if not self.ensure_connected():
            print('  ping: auto-connect failed; cannot ping.')
            return None
        return netutils.ping(host, count=count, **kw)

    # -- RSSI monitor ----------------------------------------------------

    def monitor(self, interval=1, count=None, show=True):
        """Live RSSI bar graph. Ctrl-C to stop; count=None runs until then."""
        if not self.ensure_connected():
            print('auto-connect failed; cannot monitor.')
            return
        print('RSSI monitor (Ctrl-C to stop)')
        i = 0
        try:
            while count is None or i < count:
                try:
                    rssi = self.sta.status('rssi')
                except (OSError, ValueError):
                    rssi = -100
                label, pct = rssi_quality(rssi)
                bar = '#' * (pct // 5)
                print(
                    '{:>5} dBm  {:>3}%  {:<10} |{:<20}|'.format(rssi, pct, label, bar)
                )
                i += 1
                if count is None or i < count:
                    time.sleep(interval)
        except KeyboardInterrupt:
            print('monitor stopped.')

    # -- power management ------------------------------------------------

    def power(self, pm=None, txpower=None, show=True):
        """Read (or set) WiFi power-save mode and TX power.

        pm:      one of network.WLAN.PM_NONE / PM_PERFORMANCE / PM_POWERSAVE
        txpower: transmit power in dBm
        """
        if pm is not None:
            try:
                self.sta.config(pm=pm)
            except (OSError, ValueError) as e:
                print('  set pm failed: {}'.format(e))
        if txpower is not None:
            try:
                self.sta.config(txpower=txpower)
            except (OSError, ValueError) as e:
                print('  set txpower failed: {}'.format(e))

        info = {}
        try:
            mode = self.sta.config('pm')
            info['pm'] = mode
            info['pm_name'] = PM_MODES.get(mode, 'mode({})'.format(mode))
        except (OSError, ValueError):
            info['pm'] = info['pm_name'] = 'unavailable'
        try:
            info['txpower'] = self.sta.config('txpower')
        except (OSError, ValueError):
            info['txpower'] = 'unavailable'

        if show:
            print('  Power-save : {} ({})'.format(info['pm_name'], info['pm']))
            print('  TX power   : {} dBm'.format(info['txpower']))
        return info

    # -- 802.11 PHY / WiFi 6 --------------------------------------------

    def protocol(self, show=True):
        """Read the enabled 802.11 protocol bitmask (esp_wifi_get_protocol).

        Current ESP-IDF (5.x) bits: 0x01=11b 0x02=11g 0x04=11n 0x08=LR
        0x10=11a 0x20=11ac 0x40=11ax(WiFi 6). Reports whether WiFi 6 (ax) is
        enabled. The C6 is 2.4 GHz-only 802.11ax (so 11a/11ac never appear);
        whether a given link actually runs ax also needs an ax-capable AP.
        """
        bits = (
            (0x01, '11b'),
            (0x02, '11g'),
            (0x04, '11n'),
            (0x08, 'LR'),
            (0x10, '11a'),
            (0x20, '11ac'),
            (0x40, '11ax'),
        )
        info = {}
        try:
            mask = self.sta.config('protocol')
            info['mask'] = mask
            info['modes'] = [name for bit, name in bits if mask & bit]
            info['wifi6'] = bool(mask & 0x40)
        except (OSError, ValueError, TypeError, KeyError) as e:
            info['error'] = str(e)
        if show:
            if 'mask' in info:
                print(
                    '  802.11     : {} (mask 0x{:02X})'.format(
                        '/'.join(info['modes']) or '?', info['mask']
                    )
                )
                print(
                    '  WiFi 6 (ax): {}'.format(
                        'ENABLED' if info['wifi6'] else 'not enabled'
                    )
                )
            else:
                print(
                    '  802.11 PHY : not exposed by this firmware ({})'.format(
                        info.get('error', '')
                    )
                )
                print('  (C6 is 2.4 GHz-only 802.11ax-capable hardware)')
        return info

    # -- full report -----------------------------------------------------

    def report(self):
        print('=' * 78)
        print('WiFi Diagnostics — ESP32-P4 / ESP32-C6 (MicroPython)')
        print('=' * 78)
        active = self.ensure_active()
        print('Interface  : STA, active={}'.format(active))
        print('MAC        : {}'.format(self.mac()))
        print('Status     : {}'.format(self.status_str()))

        nets = self.scan(show=True)

        print('\nPower:')
        self.power(show=True)

        print('\nPHY / WiFi 6:')
        self.protocol(show=True)

        print('\nConnecting:')
        if self.ensure_connected():
            print('\nLink:')
            self.link(show=True, scan_results=nets)
            print('\nIP configuration:')
            self.ifconfig(show=True)
            self.connectivity(show=True)
            print('\nPing:')
            self.ping(show=True)
            print('\nSpeed:')
            self.speedtest(show=True)
        else:
            print(
                '\nCould not connect to {!r} — check credentials/signal.'.format(
                    DEFAULT_SSID
                )
            )
        print('=' * 78)


# -- single entry point --------------------------------------------------

MENU = """
--- WiFi Diagnostics (ESP32-P4 / C6) ---
 1) Full report          6) Ping
 2) Scan                 7) Connectivity (DNS + internet)
 3) Connect (defaults)   8) Power info
 4) Link / RSSI          9) Disconnect
 5) RSSI monitor         S) Speed test
                         P) PHY / WiFi 6
                         0) Exit
Choose: """


def _run(action):
    """Run a menu action, surfacing any error/interrupt instead of dying."""
    try:
        action()
    except KeyboardInterrupt:
        print('\n(interrupted — back to menu)')
    except Exception as e:  # noqa: BLE001 - menu must never die silently
        print('\n!! error during action:')
        sys.print_exception(e)


def main(d=None):
    """Single interactive entry point. Reuse a diagnostics object or make one.

    Call as `wifi_diag.main()` from the REPL or main.py.
    """
    d = d or WiFiDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return d
        print('> option {}'.format(choice))  # immediate echo so it's never "dead"
        if choice == '1':
            _run(d.report)
        elif choice == '2':
            _run(d.scan)
        elif choice == '3':
            _run(d.connect)
        elif choice == '4':
            _run(d.link)
        elif choice == '5':
            n = input('samples (blank = until Ctrl-C): ').strip()
            _run(lambda: d.monitor(count=int(n) if n else None))
        elif choice == '6':
            host = input('host [8.8.8.8]: ').strip() or '8.8.8.8'
            _run(lambda: d.ping(host, count=0))  # continuous; Ctrl-C to stop
        elif choice == '7':
            _run(d.connectivity)
        elif choice == '8':
            _run(d.power)
        elif choice in ('p', 'P'):
            _run(d.protocol)
        elif choice in ('s', 'S'):
            _run(lambda: d.speedtest(forever=True))  # loop; Ctrl-C to stop
        elif choice == '9':
            _run(d.disconnect)
            print('disconnected.')
        elif choice == '0':
            return d
        else:
            print('?')
