# sdcard/diag.py
#
# microSD (SDMMC) diagnostics for the Waveshare ESP32-P4-NANO.
#
# Target: MicroPython v1.28.0, Generic ESP32P4 module.
#
# --- Verified pin map (Waveshare ESP32-P4-NANO, SDMMC 4-bit) -----------------
#   CLK = GPIO43   CMD = GPIO44
#   D0  = GPIO39   D1  = GPIO40   D2 = GPIO41   D3 = GPIO42
#
# Pins are remappable via the P4 GPIO matrix; edit the constants below for
# other board variants. The MicroPython machine.SDCard signature varies between
# builds, so setup() tries a few forms and falls back to board defaults.
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

MOUNT = "/sd"
PIN_CLK = 43
PIN_CMD = 44
PIN_D0 = 39
PIN_D1 = 40
PIN_D2 = 41
PIN_D3 = 42


def _fmt_bytes(n):
    if n >= 1024 * 1024 * 1024:
        return "{:.2f} GB".format(n / 1024 / 1024 / 1024)
    if n >= 1024 * 1024:
        return "{:.1f} MB".format(n / 1024 / 1024)
    if n >= 1024:
        return "{:.1f} KB".format(n / 1024)
    return "{} B".format(n)


class SDCardDiagnostics:
    def __init__(self):
        self.sd = None
        self.mounted = False

    # -- setup / mount ---------------------------------------------------

    def setup(self):
        if self.sd is not None:
            return self.sd
        if not hasattr(machine, "SDCard"):
            raise OSError("machine.SDCard not in this firmware build")
        from machine import Pin
        attempts = (
            ("4-bit", lambda: machine.SDCard(
                slot=1, width=4,
                clk=Pin(PIN_CLK), cmd=Pin(PIN_CMD),
                d0=Pin(PIN_D0), d1=Pin(PIN_D1),
                d2=Pin(PIN_D2), d3=Pin(PIN_D3))),
            ("1-bit", lambda: machine.SDCard(
                slot=1, width=1,
                clk=Pin(PIN_CLK), cmd=Pin(PIN_CMD), d0=Pin(PIN_D0))),
            ("slot defaults", lambda: machine.SDCard(slot=1)),
            ("firmware defaults", lambda: machine.SDCard()),
        )
        last = None
        for label, make in attempts:
            try:
                self.sd = make()
                print("  SDCard configured ({})".format(label))
                return self.sd
            except (TypeError, ValueError, OSError) as e:
                last = e
        raise OSError("could not construct SDCard: {}".format(last))

    def mount(self, show=True):
        if self.mounted:
            return True
        sd = self.setup()
        try:
            os.mount(sd, MOUNT)
            self.mounted = True
            if show:
                print("  Mounted at {}".format(MOUNT))
            return True
        except OSError as e:
            # EPERM (1) usually means already mounted.
            if e.args and e.args[0] == 1:
                self.mounted = True
                if show:
                    print("  Already mounted at {}".format(MOUNT))
                return True
            print("  mount failed ({}) — card inserted/formatted FAT?".format(e))
            return False

    def umount(self, show=True):
        try:
            os.umount(MOUNT)
        except OSError:
            pass
        self.mounted = False
        if show:
            print("  Unmounted {}".format(MOUNT))

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
        info = {"total": total, "used": used, "free": free,
                "block_size": frsize}
        if show:
            print("  Capacity   : {}".format(_fmt_bytes(total)))
            print("  Used       : {}  ({}%)".format(
                _fmt_bytes(used), round(100 * used / total) if total else 0))
            print("  Free       : {}".format(_fmt_bytes(free)))
            print("  Block size : {} B".format(frsize))
            try:
                print("  Contents   : {}".format(os.listdir(MOUNT)))
            except OSError:
                pass
        return info

    # -- throughput ------------------------------------------------------

    def speed(self, test_bytes=512 * 1024, show=True):
        """Write then read a temp file on the card and report KB/s."""
        if not self.ensure_mounted():
            return None
        path = MOUNT + "/_sdtest.bin"
        buf = bytearray(4096)
        chunks = max(1, test_bytes // 4096)
        info = {}
        try:
            t0 = time.ticks_ms()
            with open(path, "wb") as f:
                for _ in range(chunks):
                    f.write(buf)
            wdt = time.ticks_diff(time.ticks_ms(), t0)
            t0 = time.ticks_ms()
            with open(path, "rb") as f:
                while f.readinto(buf):
                    pass
            rdt = time.ticks_diff(time.ticks_ms(), t0)
            written = chunks * 4096
            info["write_kbps"] = round(written / 1024 / (wdt / 1000), 1) if wdt else 0
            info["read_kbps"] = round(written / 1024 / (rdt / 1000), 1) if rdt else 0
            info["test_bytes"] = written
        except OSError as e:
            print("  SD R/W test failed: {}".format(e))
            return None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if show:
            print("  Write speed: {} KB/s  ({} test)".format(
                info["write_kbps"], _fmt_bytes(info["test_bytes"])))
            print("  Read speed : {} KB/s".format(info["read_kbps"]))
        return info

    # -- full report -----------------------------------------------------

    def report(self):
        print("=" * 78)
        print("microSD Diagnostics — ESP32-P4-NANO (SDMMC)")
        print("=" * 78)
        if not self.mount(show=True):
            print("  No card mounted. Check the card is inserted and FAT-formatted,")
            print("  and that CLK/CMD/D0-D3 pins match this board.")
            print("=" * 78)
            return
        print("\nCard info:")
        self.info(show=True)
        print("\nThroughput:")
        self.speed(show=True)
        print("=" * 78)


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
        except (EOFError, KeyboardInterrupt):
            print()
            return sd
        print("> option {}".format(choice))
        if choice == "1":
            netutils.run_action(sd.report)
        elif choice == "2":
            netutils.run_action(sd.info)
        elif choice == "3":
            netutils.run_action(sd.speed)
        elif choice == "4":
            netutils.run_action(sd.umount)
        elif choice == "0":
            return sd
        else:
            print("?")
