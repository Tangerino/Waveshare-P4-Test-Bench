# netutils.py
#
# Interface-agnostic IP-level helpers shared by the hardware test packages
# (wifi/, eth/, ...). Once an interface is up and is the default route, these
# work identically over WiFi or Ethernet.

import struct
import time

try:
    import socket
except ImportError:  # pragma: no cover
    import usocket as socket

try:
    import select
except ImportError:  # pragma: no cover
    import uselect as select

try:
    import sys
except ImportError:  # pragma: no cover
    sys = None


def resolve(host='example.org', show=True):
    """Test DNS resolution. Returns the resolved IP or None."""
    t0 = time.ticks_ms()
    try:
        ip = socket.getaddrinfo(host, 80)[0][-1][0]
        dt = time.ticks_diff(time.ticks_ms(), t0)
        if show:
            print('  DNS {:<16} -> {} ({} ms)'.format(host, ip, dt))
        return ip
    except OSError as e:
        if show:
            print('  DNS {:<16} -> FAILED ({})'.format(host, e))
        return None


def tcp_check(host='8.8.8.8', port=53, timeout=5, show=True):
    """Test reachability via a TCP connect. Returns True/False."""
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


def _checksum(data):
    if len(data) & 1:
        data += b'\x00'
    cs = 0
    for i in range(0, len(data), 2):
        cs += (data[i] << 8) + data[i + 1]
    cs = (cs & 0xFFFF) + (cs >> 16)
    cs = (cs & 0xFFFF) + (cs >> 16)
    return ~cs & 0xFFFF


def ping(host='8.8.8.8', count=4, timeout=1000, interval=500, size=56, show=True):
    """ICMP echo via a raw socket. Returns a stats dict (or None on setup
    failure). Caller is responsible for ensuring an interface is up.
    """
    try:
        addr = socket.getaddrinfo(host, 1)[0][-1][0]
    except OSError as e:
        if show:
            print('  ping: cannot resolve {} ({})'.format(host, e))
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, 1)
    except (OSError, AttributeError) as e:
        if show:
            print('  ping: raw socket unavailable ({}); try tcp_check()'.format(e))
        return None

    pid = time.ticks_ms() & 0xFFFF
    poller = select.poll()
    poller.register(sock, select.POLLIN)
    forever = count is None or count <= 0  # forever -> Ctrl-C to stop
    sent = recv = rtt_sum = 0
    rtt_min = rtt_max = None
    if show:
        print(
            'PING {} ({}): {} data bytes{}'.format(
                host, addr, size, '  (Ctrl-C to stop)' if forever else ''
            )
        )
    seq = 0
    try:
        while forever or seq < count:
            seq += 1
            sq = seq & 0xFFFF  # ICMP seq is 16-bit; wrap for forever runs
            payload = b'Q' * size
            hdr = struct.pack('!BBHHH', 8, 0, 0, pid, sq)
            cks = _checksum(hdr + payload)
            pkt = struct.pack('!BBHHH', 8, 0, cks, pid, sq) + payload
            sent += 1
            try:
                sock.sendto(pkt, (addr, 1))
            except OSError as e:
                if show:
                    print('  seq={} send failed ({})'.format(seq, e))
                if forever or seq < count:
                    time.sleep_ms(interval)
                continue
            t0 = time.ticks_ms()
            got = False
            while True:
                left = timeout - time.ticks_diff(time.ticks_ms(), t0)
                if left <= 0:
                    break
                if not poller.poll(left):
                    break
                resp = sock.recv(128)
                rtt = time.ticks_diff(time.ticks_ms(), t0)
                ihl = (resp[0] & 0x0F) * 4
                icmp = resp[ihl : ihl + 8]
                if len(icmp) < 8:
                    continue
                r_type, _, _, r_id, r_seq = struct.unpack('!BBHHH', icmp)
                if r_type == 0 and r_id == pid and r_seq == sq:
                    recv += 1
                    rtt_sum += rtt
                    rtt_min = rtt if rtt_min is None else min(rtt_min, rtt)
                    rtt_max = rtt if rtt_max is None else max(rtt_max, rtt)
                    if show:
                        print(
                            '  {} bytes from {}: seq={} time={} ms'.format(
                                len(resp) - ihl, addr, seq, rtt
                            )
                        )
                    got = True
                    break
            if not got and show:
                print('  seq={} timeout'.format(seq))
            if forever or seq < count:
                time.sleep_ms(interval)
    except KeyboardInterrupt:
        if show:
            print('  (stopped)')
    finally:
        poller.unregister(sock)
        sock.close()

    loss = round(100 * (sent - recv) / sent) if sent else 100
    avg = round(rtt_sum / recv, 1) if recv else None
    stats = {'host': host, 'addr': addr, 'sent': sent, 'recv': recv, 'loss_pct': loss}
    if recv:
        stats.update(min=rtt_min, max=rtt_max, avg=avg)
    if show:
        print(
            '  --- {} stats: {}/{} received, {}% loss{}'.format(
                host,
                recv,
                sent,
                loss,
                ''
                if not recv
                else ', rtt min/avg/max = {}/{}/{} ms'.format(rtt_min, avg, rtt_max),
            )
        )
    return stats


# -- speed test ----------------------------------------------------------

# Plain-HTTP download targets (TLS would bottleneck on the P4's crypto and
# under-report link speed). Tried in order until one streams data. Override by
# passing your own URL (e.g. a file on a local server) for LAN-only testing —
# that's the most reliable way to compare WiFi vs Ethernet on the same network.
DOWNLOAD_URLS = (
    'http://ipv4.download.thinkbroadband.com/10MB.zip',
    'http://speedtest.belwue.net/10M',
    'http://proof.ovh.net/files/10Mb.dat',
)

_UA = 'esp32-p4-speedtest/1.0'


def _parse_http_url(url):
    proto, _, rest = url.partition('://')
    if proto != 'http':
        raise ValueError('not plain http://: ' + url)
    hostport, _, path = rest.partition('/')
    host, _, port = hostport.partition(':')
    return host, int(port) if port else 80, '/' + path


def _header_value(header, name):
    """Case-insensitive lookup of an HTTP header value (bytes)."""
    name = name.lower()
    for line in header.split(b'\r\n')[1:]:
        k, _, v = line.partition(b':')
        if k.strip().lower() == name:
            return v.strip()
    return None


def http_download(
    url, limit_bytes=8 * 1024 * 1024, limit_ms=10000, chunk=1460, show=True, _hops=3
):
    """Stream a URL over plain HTTP, counting bytes (discarded) until a byte
    or time cap. Follows HTTP redirects. Returns {bytes, ms, mbps, url} or
    None on failure.
    """
    try:
        host, port, path = _parse_http_url(url)
    except ValueError:
        if show:
            print(
                '  download: {} is HTTPS — TLS not supported for speed test'.format(url)
            )
        return None
    if show:
        print('  GET {}'.format(url))
    try:
        addr = socket.getaddrinfo(host, port)[0][-1]
    except OSError as e:
        if show:
            print('  download: cannot resolve {} ({})'.format(host, e))
        return None

    s = socket.socket()
    s.settimeout(8)
    try:
        s.connect(addr)
        req = (
            'GET {} HTTP/1.0\r\nHost: {}\r\nUser-Agent: {}\r\n'
            'Accept: */*\r\nConnection: close\r\n\r\n'
        ).format(path, host, _UA)
        s.send(req.encode())

        # Read headers; keep any body bytes that arrive in the same recv.
        buf = b''
        while b'\r\n\r\n' not in buf:
            d = s.recv(256)
            if not d:
                break
            buf += d
        header, _, body = buf.partition(b'\r\n\r\n')
        parts = header.split(b'\r\n', 1)[0].split(b' ', 2)
        code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        # Follow redirects (301/302/303/307/308).
        if code in (301, 302, 303, 307, 308) and _hops > 0:
            loc = _header_value(header, 'location')
            s.close()
            if not loc:
                if show:
                    print('  download: {} with no Location'.format(code))
                return None
            loc = loc.decode()
            if loc.startswith('/'):
                loc = 'http://{}:{}{}'.format(host, port, loc)
            if show:
                print('  -> {} redirect'.format(code))
            return http_download(loc, limit_bytes, limit_ms, chunk, show, _hops - 1)

        if code // 100 != 2:
            if show:
                print('  download: HTTP {} from {}'.format(code, host))
            return None

        total = len(body)
        t0 = time.ticks_ms()
        deadline = time.ticks_add(t0, limit_ms)
        while total < limit_bytes:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                break
            try:
                d = s.recv(chunk)
            except OSError:
                break
            if not d:
                break
            total += len(d)
        dt = time.ticks_diff(time.ticks_ms(), t0)
    except OSError as e:
        if show:
            print('  download: connection error ({})'.format(e))
        return None
    finally:
        s.close()

    dt = dt if dt > 0 else 1
    mbps = round(total * 8 / dt / 1000, 2)  # bytes*8 / ms / 1000 = Mbit/s
    if show:
        print(
            '  Download   : {:.2f} Mbit/s  ({} KB in {} ms)'.format(
                mbps, total // 1024, dt
            )
        )
        print('  Source     : {}'.format(url))
    return {'bytes': total, 'ms': dt, 'mbps': mbps, 'url': url}


def speedtest(download_url=None, ping_host='8.8.8.8', show=True, forever=False):
    """Latency (ping) + HTTP download throughput. Returns a summary dict.

    forever=True repeats the test until Ctrl-C (each run numbered).
    """
    if forever:
        run = 0
        last = None
        if show:
            print('Speed test loop (Ctrl-C to stop):')
        try:
            while True:
                run += 1
                if show:
                    print('--- run {} ---'.format(run))
                last = speedtest(download_url, ping_host, show=show, forever=False)
                time.sleep_ms(500)
        except KeyboardInterrupt:
            if show:
                print('  (stopped after {} run(s))'.format(run))
        return last

    if show:
        print('Speed test (plain HTTP; needs internet):')

    # Latency
    p = ping(ping_host, count=4, show=False)
    latency = p.get('avg') if p else None
    if show:
        if latency is not None:
            print(
                '  Latency    : {} ms avg ({}% loss, {})'.format(
                    latency, p['loss_pct'], ping_host
                )
            )
        else:
            print('  Latency    : unavailable')

    # Download — try targets until one works
    dl = None
    urls = (download_url,) if download_url else DOWNLOAD_URLS
    for url in urls:
        dl = http_download(url, show=show)
        if dl:
            break
    if not dl and show:
        print('  Download   : FAILED (all targets unreachable/redirected)')
        print('  Tip: pass a plain-http URL to a local file, e.g.')
        print("       speedtest('http://192.168.0.10/test.bin')")

    return {
        'latency_ms': latency,
        'download_mbps': dl['mbps'] if dl else None,
        'source': dl['url'] if dl else None,
        'loss_pct': p['loss_pct'] if p else None,
    }


def run_action(action):
    """Run a menu action, surfacing any error/interrupt instead of dying."""
    try:
        action()
    except KeyboardInterrupt:
        print('\n(interrupted — back to menu)')
    except Exception as e:  # noqa: BLE001 - menus must never die silently
        print('\n!! error during action:')
        if sys is not None:
            sys.print_exception(e)
        else:
            print(repr(e))
