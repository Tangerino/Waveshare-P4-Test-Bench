# audio/diag.py
#
# Audio / speaker diagnostics for the Waveshare ESP32-P4-NANO.
# Codec: ES8311 (I2C 0x18) + NS4150B speaker amplifier.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI).
#
# --- Pin map (Waveshare 07_I2SCodec example, ESP32-P4-NANO block) ------------
#   Codec I2C : I2C0  SDA=GPIO7  SCL=GPIO8   (ES8311 @ 0x18)
#   Amp enable: GPIO53  (NS4150B; drive high to un-mute the speaker)
#   I2S0      : MCLK=GPIO13  BCLK=GPIO12  WS/LRCK=GPIO10  DOUT=GPIO9  DIN=GPIO11
#
# MicroPython's machine.I2S does NOT output MCLK, so the codec MCLK is generated
# on GPIO13 with PWM at rate*256 (trick from the MIT-licensed MicroPython ES8311
# driver by raptor09010, github.com/raptor09010/Micropython-ES8311-Library —
# the ES8311 register tables below are adapted from it).
#
# Usage (REPL):
#   from audio import AudioDiagnostics, main
#   a = AudioDiagnostics()
#   a.probe()              # confirm ES8311 chip ID over I2C
#   a.tone(440, 2)         # play a 440 Hz tone for 2 s out the speaker
#   a.report(); main()

import array
import math
import time

import machine

CODEC_ADDR = 0x18
PIN_SDA = 7
PIN_SCL = 8
PIN_PA = 53            # NS4150B amplifier enable
PIN_MCLK = 13
PIN_BCLK = 12
PIN_WS = 10
PIN_DOUT = 9
I2S_ID = 0

# ES8311 register init for DAC playback (adapted from raptor09010's MIT driver).
ES8311_INIT = (
    (0x00, 0x80), (0x01, 0x3F), (0x02, 0x00), (0x03, 0x10), (0x04, 0x10),
    (0x05, 0x00), (0x06, 0x03), (0x07, 0x00), (0x08, 0xFF), (0x09, 0x0C),
    (0x0A, 0x4C), (0x0B, 0x00), (0x0C, 0x00), (0x0D, 0x01), (0x0E, 0x02),
    (0x0F, 0x00), (0x10, 0x1F), (0x11, 0x7F), (0x12, 0x00), (0x13, 0x10),
    (0x14, 0x1A), (0x15, 0x40), (0x16, 0x24), (0x17, 0xBF), (0x18, 0x00),
    (0x19, 0x00), (0x1A, 0x00), (0x1B, 0x0A), (0x1C, 0x6A),
    (0x32, 0x9F), (0x37, 0x08), (0x44, 0x50),
)
# Power-down sequence (avoids pops / I2C lockups).
ES8311_DEINIT = (
    (0x32, 0x00), (0x17, 0x00), (0x0E, 0x6A), (0x12, 0x02), (0x14, 0x10),
    (0x0D, 0xFC), (0x15, 0x00), (0x37, 0x08), (0x00, 0x1F),
)


class AudioDiagnostics:
    def __init__(self):
        self.i2c = None

    def _bus(self):
        if self.i2c is None:
            self.i2c = machine.I2C(
                0, scl=machine.Pin(PIN_SCL), sda=machine.Pin(PIN_SDA), freq=400000)
        return self.i2c

    # -- presence / id ---------------------------------------------------

    def probe(self, show=True):
        """Read the ES8311 chip-ID registers (0xFD=0x83, 0xFE=0x11)."""
        i2c = self._bus()
        info = {"present": CODEC_ADDR in i2c.scan()}
        try:
            id1 = i2c.readfrom_mem(CODEC_ADDR, 0xFD, 1)[0]
            id2 = i2c.readfrom_mem(CODEC_ADDR, 0xFE, 1)[0]
            ver = i2c.readfrom_mem(CODEC_ADDR, 0xFF, 1)[0]
            info.update(id1=id1, id2=id2, version=ver,
                        is_es8311=(id1 == 0x83 and id2 == 0x11))
        except OSError as e:
            info["error"] = str(e)
        if show:
            print("  Codec @0x{:02X}: {}".format(
                CODEC_ADDR, "present" if info["present"] else "NOT FOUND"))
            if "id1" in info:
                print("  Chip ID    : 0x{:02X} 0x{:02X} (ver 0x{:02X}) -> {}".format(
                    info["id1"], info["id2"], info["version"],
                    "ES8311 OK" if info["is_es8311"] else "unexpected"))
            elif "error" in info:
                print("  ID read failed: {}".format(info["error"]))
        return info

    # -- tone playback ---------------------------------------------------

    @staticmethod
    def _sine(freq, rate, amp):
        # One second of samples => integer cycles for integer freq => loops
        # seamlessly. 16-bit signed mono.
        buf = array.array("h", bytearray(2 * rate))
        step = 2.0 * math.pi * freq / rate
        for i in range(rate):
            buf[i] = int(amp * math.sin(step * i))
        return buf

    def tone(self, freq=440, secs=2, rate=16000, volume=90, amp=28000,
             show=True):
        """Configure the ES8311 + I2S and play a sine tone on the speaker."""
        Pin = machine.Pin
        if show:
            print("  Tone {} Hz for {} s (vol {}%)...".format(freq, secs, volume))

        mclk = machine.PWM(Pin(PIN_MCLK), freq=rate * 256, duty_u16=32768)
        i2c = self._bus()
        for reg, val in ES8311_INIT:
            i2c.writeto_mem(CODEC_ADDR, reg, bytes([val]))
            time.sleep_ms(2)
        i2c.writeto_mem(CODEC_ADDR, 0x32, bytes([int(255 * volume / 100)]))

        audio = machine.I2S(
            I2S_ID, sck=Pin(PIN_BCLK), ws=Pin(PIN_WS), sd=Pin(PIN_DOUT),
            mode=machine.I2S.TX, bits=16, format=machine.I2S.MONO,
            rate=rate, ibuf=8192)
        pa = Pin(PIN_PA, Pin.OUT)
        pa.value(1)  # enable the speaker amplifier
        buf = self._sine(freq, rate, amp)
        try:
            for _ in range(max(1, int(secs))):
                audio.write(buf)
        finally:
            pa.value(0)
            audio.deinit()
            for reg, val in ES8311_DEINIT:
                try:
                    i2c.writeto_mem(CODEC_ADDR, reg, bytes([val]))
                except OSError:
                    pass
                time.sleep_ms(2)
            mclk.deinit()
        if show:
            print("  done.")
        return {"freq": freq, "secs": secs}

    def beep(self, show=True):
        """Short confirmation beep (1 kHz, ~1 s)."""
        return self.tone(1000, 1, rate=16000, volume=90, show=show)

    # -- report ----------------------------------------------------------

    def report(self):
        print("=" * 78)
        print("Audio Diagnostics — ESP32-P4-NANO (ES8311 + NS4150B)")
        print("=" * 78)
        print("Codec presence:")
        info = self.probe(show=True)
        if info.get("present"):
            print("\nPlaying test tone (440 Hz, 2 s):")
            self.tone(440, 2, show=True)
        else:
            print("\nCodec not detected on I2C — skipping tone.")
        print("=" * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Audio Diagnostics (ESP32-P4 / ES8311) ---
 1) Full report        3) Play tone (freq, secs)
 2) Codec presence/ID  4) Beep
 0) Exit
Choose: """


def main(a=None):
    import netutils
    a = a or AudioDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return a
        print("> option {}".format(choice))
        if choice == "1":
            netutils.run_action(a.report)
        elif choice == "2":
            netutils.run_action(a.probe)
        elif choice == "3":
            f = input("freq Hz [440]: ").strip()
            s = input("seconds [2]: ").strip()
            netutils.run_action(
                lambda: a.tone(int(f) if f else 440, int(s) if s else 2))
        elif choice == "4":
            netutils.run_action(a.beep)
        elif choice == "0":
            return a
        else:
            print("?")
