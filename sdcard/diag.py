# sdcard/diag.py
#
# microSD (SDMMC) diagnostics for the Waveshare ESP32-P4-NANO.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
# microSD verified on v1.29.0-preview; needs >= dc44bdbac (2026-04-02) for ldo.
#
# --- Config (matches Waveshare's ESP-IDF example, examples/esp-idf/06_sdmmc) -
#   Native SDMMC slot 0 (SDIO 3.0): CLK=43 CMD=44 D0=39 D1=40 D2=41 D3=42
#   SD card IO is powered by the P4 ON-CHIP LDO channel 4 — without enabling
#   that LDO the card has no IO power and times out (ESP_ERR_TIMEOUT).
# MicroPython SDMMC kwargs: sck(=CLK), cmd, data(tuple of D0..), ldo.
#
# FIRMWARE REQUIREMENT: needs a build whose machine.SDCard supports the P4
# 'ldo'/'cmd'/'data' kwargs (current MicroPython). Older builds (incl. the
# tested v1.28.0 "Generic ESP32P4") reject them ("extra keyword arguments")
# and CANNOT drive the slot — mount() detects this and says so.
#
# Usage (REPL):
#   from sdcard import SDCardDiagnostics, main
#   sd = SDCardDiagnostics()
#   sd.report()      # mount + info + read/write speed
#   sd.mount(); sd.info(); sd.speed(); sd.umount()
#   main()           # interactive menu

import os
import time

import machine

MOUNT = '/sd'
PIN_CLK = 43
PIN_CMD = 44
PIN_D0 = 39
PIN_D1 = 40
PIN_D2 = 41
PIN_D3 = 42
LDO_CHAN = 4  # P4 on-chip LDO channel powering SD IO (Waveshare ex.)


def _fmt_bytes(n):
    if n >= 1024 * 1024 * 1024:
        return '{:.2f} GB'.format(n / 1024 / 1024 / 1024)
    if n >= 1024 * 1024:
        return '{:.1f} MB'.format(n / 1024 / 1024)
    if n >= 1024:
        return '{:.1f} KB'.format(n / 1024)
    return '{} B'.format(n)


class SDCardDiagnostics:
    def __init__(self):
        self.sd = None
        self.mounted = False

    # -- setup / mount ---------------------------------------------------

    def _attempts(self):
        """Construction strategies, tried in order until one MOUNTS.

        Correct ESP32-P4 SDMMC config, matching Waveshare's own ESP-IDF
        example (examples/esp-idf/06_sdmmc): native slot 0, CLK/CMD/D0-3 on
        43/44/39-42, IO powered by the on-chip LDO channel 4. MicroPython's
        SDMMC kwargs are sck(=CLK), cmd, data(tuple of D0..), ldo.
        """
        from machine import Pin

        return (
            (
                'slot0 w4 +LDO{} (Waveshare P4 config)'.format(LDO_CHAN),
                lambda: machine.SDCard(
                    slot=0,
                    width=4,
                    sck=Pin(PIN_CLK),
                    cmd=Pin(PIN_CMD),
                    data=(Pin(PIN_D0), Pin(PIN_D1), Pin(PIN_D2), Pin(PIN_D3)),
                    ldo=LDO_CHAN,
                ),
            ),
            (
                'slot0 w1 +LDO{}'.format(LDO_CHAN),
                lambda: machine.SDCard(
                    slot=0,
                    width=1,
                    sck=Pin(PIN_CLK),
                    cmd=Pin(PIN_CMD),
                    data=(Pin(PIN_D0),),
                    ldo=LDO_CHAN,
                ),
            ),
        )

    def mount(self, show=True):
        if self.mounted:
            return True
        if not hasattr(machine, 'SDCard'):
            print('  machine.SDCard not in this firmware build')
            return False
        old_firmware = False
        for label, make in self._attempts():
            try:
                sd = make()
            except TypeError as e:
                # Old machine.SDCard without P4 ldo/cmd/data kwargs.
                if 'extra keyword' in str(e):
                    old_firmware = True
                    print(
                        '    [{}] firmware too old (no ldo/cmd/data args)'.format(label)
                    )
                else:
                    print('    [{}] construct failed: {}'.format(label, e))
                continue
            except (ValueError, OSError) as e:
                print('    [{}] construct failed: {}'.format(label, e))
                continue
            try:
                os.mount(sd, MOUNT)
            except OSError as e:
                if e.args and e.args[0] == 1:  # EPERM = already mounted
                    self.sd, self.mounted = sd, True
                    if show:
                        print('  Already mounted at {}'.format(MOUNT))
                    return True
                print('    [{}] mount failed: {}'.format(label, e))
                try:
                    sd.deinit()
                except (AttributeError, OSError):
                    pass
                continue
            self.sd, self.mounted = sd, True
            if show:
                print('  Mounted at {} via {}'.format(MOUNT, label))
            return True

        if old_firmware:
            print('  SD UNSUPPORTED BY THIS FIRMWARE.')
            print("  The pins/LDO are correct (match Waveshare's example), but this")
            print("  MicroPython build's machine.SDCard lacks the ESP32-P4 'ldo'/")
            print("  'cmd'/'data' kwargs needed to power & drive the slot. The card")
            print(
                '  IO is fed by the P4 on-chip LDO ch{} — with no API to enable'.format(
                    LDO_CHAN
                )
            )
            print('  it the card gets no power (ESP_ERR_TIMEOUT). Flash a newer')
            print('  MicroPython P4 build with SD LDO support. See README > microSD.')
        else:
            print('  Could not mount the card with any config (see errors above).')
        return False

    def umount(self, show=True):
        try:
            os.umount(MOUNT)
        except OSError:
            pass
        self.mounted = False
        if show:
            print('  Unmounted {}'.format(MOUNT))

    def ensure_mounted(self):
        return self.mounted or self.mount()

    # -- info ------------------------------------------------------------

    def info(self, show=True):
        if not self.ensure_mounted():
            return None
        st = os.statvfs(MOUNT)
        frsize = st[1]
        total = frsize * st[2]
        free = frsize * st[3]
        used = total - free
        info = {'total': total, 'used': used, 'free': free, 'block_size': frsize}
        if show:
            print('  Capacity   : {}'.format(_fmt_bytes(total)))
            print(
                '  Used       : {}  ({}%)'.format(
                    _fmt_bytes(used), round(100 * used / total) if total else 0
                )
            )
            print('  Free       : {}'.format(_fmt_bytes(free)))
            print('  Block size : {} B'.format(frsize))
            try:
                print('  Contents   : {}'.format(os.listdir(MOUNT)))
            except OSError:
                pass
        return info

    # -- throughput ------------------------------------------------------

    def speed(self, test_bytes=512 * 1024, show=True):
        """Write then read a temp file on the card and report KB/s."""
        if not self.ensure_mounted():
            return None
        path = MOUNT + '/_sdtest.bin'
        buf = bytearray(4096)
        chunks = max(1, test_bytes // 4096)
        info = {}
        try:
            t0 = time.ticks_ms()
            with open(path, 'wb') as f:
                for _ in range(chunks):
                    f.write(buf)
            wdt = time.ticks_diff(time.ticks_ms(), t0)
            t0 = time.ticks_ms()
            with open(path, 'rb') as f:
                while f.readinto(buf):
                    pass
            rdt = time.ticks_diff(time.ticks_ms(), t0)
            written = chunks * 4096
            info['write_kbps'] = round(written / 1024 / (wdt / 1000), 1) if wdt else 0
            info['read_kbps'] = round(written / 1024 / (rdt / 1000), 1) if rdt else 0
            info['test_bytes'] = written
        except OSError as e:
            print('  SD R/W test failed: {}'.format(e))
            return None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if show:
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
        print('microSD Diagnostics — ESP32-P4-NANO (SDMMC)')
        print('=' * 78)
        if not self.mount(show=True):
            # mount() already printed the precise reason.
            print('=' * 78)
            return
        print('\nCard info:')
        self.info(show=True)
        print('\nThroughput:')
        self.speed(show=True)
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- microSD Diagnostics (ESP32-P4 / SDMMC) ---
 1) Full report       4) Unmount
 2) Mount + info      0) Exit
 3) Speed test
Choose: """


def main(sd=None):
    import netutils

    sd = sd or SDCardDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return sd
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(sd.report)
        elif choice == '2':
            netutils.run_action(sd.info)
        elif choice == '3':
            netutils.run_action(sd.speed)
        elif choice == '4':
            netutils.run_action(sd.umount)
        elif choice == '0':
            return sd
        else:
            print('?')
