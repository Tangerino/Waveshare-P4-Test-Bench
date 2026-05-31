# system/diag.py
#
# CPU / memory / flash diagnostics for the ESP32-P4.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI); verified v1.29.0-preview.
#
# Usage (REPL):
#   from system import SystemDiagnostics, main
#   s = SystemDiagnostics()
#   s.report()        # full one-shot
#   s.cpu()           # frequency + integer/float benchmark
#   s.memory()        # heap free/used + largest allocatable block
#   s.flash()         # filesystem usage + read/write throughput
#   main()            # interactive menu

import gc
import os
import time

import machine

try:
    import esp
except ImportError:  # pragma: no cover
    esp = None

try:
    import esp32
except ImportError:  # pragma: no cover
    esp32 = None

# Captured at import (≈ boot when loaded from main.py) for uptime.
BOOT_TICKS = time.ticks_ms()

# machine.*_RESET cause codes -> name, built from whatever this build exposes.
RESET_CAUSES = {}
for _name in (
    'PWRON_RESET',
    'HARD_RESET',
    'WDT_RESET',
    'DEEPSLEEP_RESET',
    'SOFT_RESET',
    'BROWNOUT_RESET',
    'LOCKUP_RESET',
):
    _code = getattr(machine, _name, None)
    if _code is not None:
        RESET_CAUSES[_code] = _name


def _fmt_uptime(ms):
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    out = []
    if d:
        out.append('{}d'.format(d))
    if d or h:
        out.append('{}h'.format(h))
    out.append('{}m'.format(m))
    out.append('{}s'.format(s))
    return ' '.join(out)


def _fmt_bytes(n):
    if n >= 1024 * 1024:
        return '{:.2f} MB'.format(n / 1024 / 1024)
    if n >= 1024:
        return '{:.1f} KB'.format(n / 1024)
    return '{} B'.format(n)


class SystemDiagnostics:
    # -- board / firmware info ------------------------------------------

    def info(self, show=True):
        u = os.uname()
        up_ms = time.ticks_diff(time.ticks_ms(), BOOT_TICKS)
        cause = machine.reset_cause()
        info = {
            'sysname': u.sysname,
            'release': u.release,
            'version': u.version,
            'machine': u.machine,
            'freq_mhz': machine.freq() // 1_000_000,
            'uid': ''.join('{:02x}'.format(b) for b in machine.unique_id()),
            'uptime_ms': up_ms,
            'reset_cause': cause,
            'reset_cause_name': RESET_CAUSES.get(cause, 'code({})'.format(cause)),
        }
        if esp is not None:
            try:
                info['flash_size'] = esp.flash_size()
            except OSError:
                pass
        if show:
            print('  Machine    : {}'.format(info['machine']))
            print('  MicroPython: {} ({})'.format(info['release'], info['version']))
            print('  CPU freq   : {} MHz'.format(info['freq_mhz']))
            print('  Unique ID  : {}'.format(info['uid']))
            if 'flash_size' in info:
                print('  Flash size : {}'.format(_fmt_bytes(info['flash_size'])))
            print(
                '  Reset cause: {} ({})'.format(
                    info['reset_cause_name'], info['reset_cause']
                )
            )
            print('  Uptime     : {}'.format(_fmt_uptime(up_ms)))
        return info

    # -- CPU -------------------------------------------------------------

    @staticmethod
    def _bench_int(loops):
        # Mask to 30 bits so x stays a fast small int (no bignum growth).
        t0 = time.ticks_us()
        x = 0
        for i in range(loops):
            x = (x + i * 3 - 1) & 0x3FFFFFFF
        dt = time.ticks_diff(time.ticks_us(), t0)
        return dt, x

    @staticmethod
    def _bench_float(loops):
        # Converges toward a fixed point (~500000), so x stays bounded.
        t0 = time.ticks_us()
        x = 1.0
        for i in range(loops):
            x = x * 1.000001 + 0.5
        dt = time.ticks_diff(time.ticks_us(), t0)
        return dt, x

    def cpu(self, set_mhz=None, loops=100_000, show=True):
        """Report CPU frequency and run integer/float micro-benchmarks.

        Pass set_mhz to change the core frequency first (e.g. 360).
        """
        if set_mhz is not None:
            try:
                machine.freq(int(set_mhz) * 1_000_000)
            except (ValueError, OSError) as e:
                print('  set freq failed: {}'.format(e))
        freq = machine.freq()
        if show:
            print('  CPU freq   : {} MHz'.format(freq // 1_000_000))
        gc.collect()

        di, _ = self._bench_int(loops)
        int_kops = round(loops / di * 1000, 1)  # loops/us*1000 = kops/s
        if show:
            print(
                '  Int  bench : {} kops/s  ({} loops in {} us)'.format(
                    int_kops, loops, di
                )
            )

        df, _ = self._bench_float(loops)
        float_kops = round(loops / df * 1000, 1)
        if show:
            print(
                '  Float bench: {} kops/s  ({} loops in {} us)'.format(
                    float_kops, loops, df
                )
            )

        info = {
            'freq_mhz': freq // 1_000_000,
            'int_kops': int_kops,
            'float_kops': float_kops,
        }

        # Temperature last: a blocking read here can't be caught, so it must
        # not sit between the benchmarks and their output.
        if esp32 is not None and hasattr(esp32, 'mcu_temperature'):
            try:
                info['temp_c'] = round(esp32.mcu_temperature(), 1)
                if show:
                    print('  MCU temp   : {} C'.format(info['temp_c']))
            except (AttributeError, OSError, ValueError) as e:
                if show:
                    print('  MCU temp   : unavailable ({})'.format(e))
        return info

    # -- memory ----------------------------------------------------------

    @staticmethod
    def _largest_block():
        """Largest single bytearray we can allocate right now (binary search)."""
        gc.collect()
        lo, hi, best = 0, gc.mem_free(), 0
        while lo <= hi:
            mid = (lo + hi) // 2
            try:
                b = bytearray(mid)
                del b
                best = mid
                lo = mid + 1
            except MemoryError:
                hi = mid - 1
            gc.collect()
        return best

    def memory(self, show=True):
        gc.collect()
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        total = free + alloc
        largest = self._largest_block()
        frag = round(100 * (1 - largest / free), 1) if free else 0
        info = {
            'free': free,
            'alloc': alloc,
            'total': total,
            'largest_block': largest,
            'frag_pct': frag,
        }
        if show:
            print('  Heap total : {}'.format(_fmt_bytes(total)))
            print(
                '  Heap used  : {}  ({}%)'.format(
                    _fmt_bytes(alloc), round(100 * alloc / total) if total else 0
                )
            )
            print('  Heap free  : {}'.format(_fmt_bytes(free)))
            print(
                '  Largest blk: {}  (fragmentation ~{}%)'.format(
                    _fmt_bytes(largest), frag
                )
            )
        return info

    # -- flash -----------------------------------------------------------

    def flash(self, test_bytes=64 * 1024, show=True):
        """Filesystem usage + read/write throughput on a temp file.

        Writes/reads a small temp file (default 64 KB) and deletes it.
        """
        st = os.statvfs('/')
        frsize = st[1]
        total = frsize * st[2]
        free = frsize * st[3]
        used = total - free
        info = {'fs_total': total, 'fs_used': used, 'fs_free': free}

        path = '/_flash_test.bin'
        buf = bytearray(1024)
        chunks = max(1, test_bytes // 1024)
        try:
            # Write
            t0 = time.ticks_ms()
            with open(path, 'wb') as f:
                for _ in range(chunks):
                    f.write(buf)
            wdt = time.ticks_diff(time.ticks_ms(), t0)
            # Read
            t0 = time.ticks_ms()
            with open(path, 'rb') as f:
                while f.readinto(buf):
                    pass
            rdt = time.ticks_diff(time.ticks_ms(), t0)
            written = chunks * 1024
            info['write_kbps'] = round(written / 1024 / (wdt / 1000), 1) if wdt else 0
            info['read_kbps'] = round(written / 1024 / (rdt / 1000), 1) if rdt else 0
            info['test_bytes'] = written
        except OSError as e:
            print('  flash R/W test failed: {}'.format(e))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        if show:
            print('  FS total   : {}'.format(_fmt_bytes(total)))
            print(
                '  FS used    : {}  ({}%)'.format(
                    _fmt_bytes(used), round(100 * used / total) if total else 0
                )
            )
            print('  FS free    : {}'.format(_fmt_bytes(free)))
            if 'write_kbps' in info:
                print(
                    '  Write speed: {} KB/s  ({} test)'.format(
                        info['write_kbps'], _fmt_bytes(info['test_bytes'])
                    )
                )
                print('  Read speed : {} KB/s'.format(info['read_kbps']))
        return info

    # -- full report -----------------------------------------------------

    def report(self):
        print('=' * 78)
        print('System Diagnostics — ESP32-P4 (MicroPython)')
        print('=' * 78)
        print('Board / firmware:')
        self.info(show=True)
        print('\nCPU:')
        self.cpu(show=True)
        print('\nMemory (heap):')
        self.memory(show=True)
        print('\nFlash / filesystem:')
        self.flash(show=True)
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- System Diagnostics (ESP32-P4) ---
 1) Full report       4) Flash (FS + R/W speed)
 2) CPU (freq + bench) 5) Board / firmware info
 3) Memory (heap)      0) Exit
Choose: """


def main(s=None):
    import netutils  # for the safe action runner

    s = s or SystemDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return s
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(s.report)
        elif choice == '2':
            netutils.run_action(s.cpu)
        elif choice == '3':
            netutils.run_action(s.memory)
        elif choice == '4':
            netutils.run_action(s.flash)
        elif choice == '5':
            netutils.run_action(s.info)
        elif choice == '0':
            return s
        else:
            print('?')
