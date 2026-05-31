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
#   a.ring(4)              # telephone ring (NA ringback 440+480 Hz, cadence)
#   a.song("ode")          # play a built-in melody by name...
#   a.song(2)              # ...or by number (see a.song_names())
#   a.report(); main()

import array
import math
import time

import machine

CODEC_ADDR = 0x18
PIN_SDA = 7
PIN_SCL = 8
PIN_PA = 53  # NS4150B amplifier enable
PIN_MCLK = 13
PIN_BCLK = 12
PIN_WS = 10
PIN_DOUT = 9
I2S_ID = 0

# ES8311 register init for DAC playback (adapted from raptor09010's MIT driver).
ES8311_INIT = (
    (0x00, 0x80),
    (0x01, 0x3F),
    (0x02, 0x00),
    (0x03, 0x10),
    (0x04, 0x10),
    (0x05, 0x00),
    (0x06, 0x03),
    (0x07, 0x00),
    (0x08, 0xFF),
    (0x09, 0x0C),
    (0x0A, 0x4C),
    (0x0B, 0x00),
    (0x0C, 0x00),
    (0x0D, 0x01),
    (0x0E, 0x02),
    (0x0F, 0x00),
    (0x10, 0x1F),
    (0x11, 0x7F),
    (0x12, 0x00),
    (0x13, 0x10),
    (0x14, 0x1A),
    (0x15, 0x40),
    (0x16, 0x24),
    (0x17, 0xBF),
    (0x18, 0x00),
    (0x19, 0x00),
    (0x1A, 0x00),
    (0x1B, 0x0A),
    (0x1C, 0x6A),
    (0x32, 0x9F),
    (0x37, 0x08),
    (0x44, 0x50),
)
# Power-down sequence (avoids pops / I2C lockups).
ES8311_DEINIT = (
    (0x32, 0x00),
    (0x17, 0x00),
    (0x0E, 0x6A),
    (0x12, 0x02),
    (0x14, 0x10),
    (0x0D, 0xFC),
    (0x15, 0x00),
    (0x37, 0x08),
    (0x00, 0x1F),
)

# Equal-tempered note frequencies (Hz, A4=440). "R" = rest.
NOTES = {
    'R': 0,
    'C4': 262,
    'C#4': 277,
    'D4': 294,
    'D#4': 311,
    'E4': 330,
    'F4': 349,
    'F#4': 370,
    'G4': 392,
    'G#4': 415,
    'A4': 440,
    'A#4': 466,
    'B4': 494,
    'C5': 523,
    'C#5': 554,
    'D5': 587,
    'D#5': 622,
    'E5': 659,
    'F5': 698,
    'F#5': 740,
    'G5': 784,
    'G#5': 831,
    'A5': 880,
    'A#5': 932,
    'B5': 988,
    'C6': 1047,
}

_Q = 350  # quarter-note ms; _H = half, _E = eighth
_H, _E = _Q * 2, _Q // 2

# Songs: list of (note, duration_ms). Public-domain melodies.
SONGS = {
    'ode': [  # Beethoven — Ode to Joy
        ('E4', _Q),
        ('E4', _Q),
        ('F4', _Q),
        ('G4', _Q),
        ('G4', _Q),
        ('F4', _Q),
        ('E4', _Q),
        ('D4', _Q),
        ('C4', _Q),
        ('C4', _Q),
        ('D4', _Q),
        ('E4', _Q),
        ('E4', _Q + _E),
        ('D4', _E),
        ('D4', _H),
    ],
    'twinkle': [  # Twinkle Twinkle Little Star
        ('C4', _Q),
        ('C4', _Q),
        ('G4', _Q),
        ('G4', _Q),
        ('A4', _Q),
        ('A4', _Q),
        ('G4', _H),
        ('F4', _Q),
        ('F4', _Q),
        ('E4', _Q),
        ('E4', _Q),
        ('D4', _Q),
        ('D4', _Q),
        ('C4', _H),
        ('G4', _Q),
        ('G4', _Q),
        ('F4', _Q),
        ('F4', _Q),
        ('E4', _Q),
        ('E4', _Q),
        ('D4', _H),
        ('G4', _Q),
        ('G4', _Q),
        ('F4', _Q),
        ('F4', _Q),
        ('E4', _Q),
        ('E4', _Q),
        ('D4', _H),
        ('C4', _Q),
        ('C4', _Q),
        ('G4', _Q),
        ('G4', _Q),
        ('A4', _Q),
        ('A4', _Q),
        ('G4', _H),
        ('F4', _Q),
        ('F4', _Q),
        ('E4', _Q),
        ('E4', _Q),
        ('D4', _Q),
        ('D4', _Q),
        ('C4', _H),
    ],
    'scale': [(n, 200) for n in ('C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5')],
    'birthday': [  # Happy Birthday to You (key of C)
        ('C4', _E),
        ('C4', _E),
        ('D4', _Q),
        ('C4', _Q),
        ('F4', _Q),
        ('E4', _H),
        ('C4', _E),
        ('C4', _E),
        ('D4', _Q),
        ('C4', _Q),
        ('G4', _Q),
        ('F4', _H),
        ('C4', _E),
        ('C4', _E),
        ('C5', _Q),
        ('A4', _Q),
        ('F4', _Q),
        ('E4', _Q),
        ('D4', _H),
        ('A#4', _E),
        ('A#4', _E),
        ('A4', _Q),
        ('F4', _Q),
        ('G4', _Q),
        ('F4', _H),
    ],
    'mario': [  # Super Mario Bros — opening theme (R = rest)
        ('E5', 120),
        ('R', 40),
        ('E5', 120),
        ('R', 120),
        ('E5', 120),
        ('R', 120),
        ('C5', 120),
        ('E5', 120),
        ('R', 40),
        ('G5', 150),
        ('R', 300),
        ('G4', 150),
        ('R', 300),
        ('C5', 200),
        ('R', 100),
        ('G4', 150),
        ('R', 100),
        ('E4', 150),
        ('R', 100),
        ('A4', 150),
        ('B4', 150),
        ('A#4', 120),
        ('A4', 150),
        ('G4', 100),
        ('E5', 100),
        ('G5', 120),
        ('A5', 150),
        ('R', 60),
        ('F5', 100),
        ('G5', 120),
        ('R', 60),
        ('E5', 150),
        ('R', 60),
        ('C5', 100),
        ('D5', 100),
        ('B4', 200),
    ],
}


class AudioDiagnostics:
    def __init__(self):
        self.i2c = None

    def _bus(self):
        if self.i2c is None:
            self.i2c = machine.I2C(
                0, scl=machine.Pin(PIN_SCL), sda=machine.Pin(PIN_SDA), freq=400000
            )
        return self.i2c

    # -- presence / id ---------------------------------------------------

    def probe(self, show=True):
        """Read the ES8311 chip-ID registers (0xFD=0x83, 0xFE=0x11)."""
        i2c = self._bus()
        info = {'present': CODEC_ADDR in i2c.scan()}
        try:
            id1 = i2c.readfrom_mem(CODEC_ADDR, 0xFD, 1)[0]
            id2 = i2c.readfrom_mem(CODEC_ADDR, 0xFE, 1)[0]
            ver = i2c.readfrom_mem(CODEC_ADDR, 0xFF, 1)[0]
            info.update(
                id1=id1, id2=id2, version=ver, is_es8311=(id1 == 0x83 and id2 == 0x11)
            )
        except OSError as e:
            info['error'] = str(e)
        if show:
            print(
                '  Codec @0x{:02X}: {}'.format(
                    CODEC_ADDR, 'present' if info['present'] else 'NOT FOUND'
                )
            )
            if 'id1' in info:
                print(
                    '  Chip ID    : 0x{:02X} 0x{:02X} (ver 0x{:02X}) -> {}'.format(
                        info['id1'],
                        info['id2'],
                        info['version'],
                        'ES8311 OK' if info['is_es8311'] else 'unexpected',
                    )
                )
            elif 'error' in info:
                print('  ID read failed: {}'.format(info['error']))
        return info

    # -- tone playback ---------------------------------------------------

    @staticmethod
    def _sine(freq, rate, amp):
        # One second of samples => integer cycles for integer freq => loops
        # seamlessly. 16-bit signed mono.
        buf = array.array('h', bytearray(2 * rate))
        step = 2.0 * math.pi * freq / rate
        for i in range(rate):
            buf[i] = int(amp * math.sin(step * i))
        return buf

    @staticmethod
    def _dual(f1, f2, rate, n, amp):
        # n samples summing two sines (each at amp; sum peaks at 2*amp).
        buf = array.array('h', bytearray(2 * n))
        s1 = 2.0 * math.pi * f1 / rate
        s2 = 2.0 * math.pi * f2 / rate
        for i in range(n):
            buf[i] = int(amp * (math.sin(s1 * i) + math.sin(s2 * i)))
        return buf

    def _open(self, rate, volume):
        """Bring up MCLK (PWM) + ES8311 + I2S + amp. Returns a handle tuple."""
        Pin = machine.Pin
        mclk = machine.PWM(Pin(PIN_MCLK), freq=rate * 256, duty_u16=32768)
        i2c = self._bus()
        for reg, val in ES8311_INIT:
            i2c.writeto_mem(CODEC_ADDR, reg, bytes([val]))
            time.sleep_ms(2)
        i2c.writeto_mem(CODEC_ADDR, 0x32, bytes([int(255 * volume / 100)]))
        audio = machine.I2S(
            I2S_ID,
            sck=Pin(PIN_BCLK),
            ws=Pin(PIN_WS),
            sd=Pin(PIN_DOUT),
            mode=machine.I2S.TX,
            bits=16,
            format=machine.I2S.MONO,
            rate=rate,
            ibuf=8192,
        )
        pa = Pin(PIN_PA, Pin.OUT)
        pa.value(1)  # enable the NS4150B speaker amplifier
        return mclk, i2c, audio, pa

    def _close(self, handle):
        mclk, i2c, audio, pa = handle
        try:
            pa.value(0)
        except Exception:
            pass
        try:
            audio.deinit()
        except Exception:
            pass
        for reg, val in ES8311_DEINIT:
            try:
                i2c.writeto_mem(CODEC_ADDR, reg, bytes([val]))
            except OSError:
                pass
            time.sleep_ms(2)
        try:
            mclk.deinit()
        except Exception:
            pass

    def tone(self, freq=440, secs=2, rate=16000, volume=90, amp=28000, show=True):
        """Configure the ES8311 + I2S and play a sine tone on the speaker."""
        if show:
            print('  Tone {} Hz for {} s (vol {}%)...'.format(freq, secs, volume))
        h = self._open(rate, volume)
        buf = self._sine(freq, rate, amp)
        try:
            for _ in range(max(1, int(secs))):
                h[2].write(buf)
        finally:
            self._close(h)
        if show:
            print('  done.')
        return {'freq': freq, 'secs': secs}

    def ring(
        self,
        rings=4,
        on_ms=2000,
        off_ms=2000,
        f1=440,
        f2=480,
        rate=16000,
        volume=90,
        amp=14000,
        show=True,
    ):
        """Telephone ring: North American ringback (440+480 Hz), cadence
        on_ms ON / off_ms OFF, repeated `rings` times.

        Defaults to the real cadence (2 s on / 4 s off is the standard; we use
        2/2 so a test isn't too long). Pass off_ms=4000 for the true cadence.
        """
        if show:
            print(
                '  Phone ring x{}: {}+{} Hz, {}ms on / {}ms off...'.format(
                    rings, f1, f2, on_ms, off_ms
                )
            )
        chunk = rate // 10  # 100 ms blocks
        on = self._dual(f1, f2, rate, chunk, amp)
        silence = array.array('h', bytearray(2 * chunk))
        n_on = max(1, on_ms // 100)
        n_off = max(0, off_ms // 100)
        h = self._open(rate, volume)
        try:
            for r in range(rings):
                if show:
                    print('    ring {}/{}'.format(r + 1, rings))
                for _ in range(n_on):
                    h[2].write(on)
                for _ in range(n_off):
                    h[2].write(silence)
        finally:
            self._close(h)
        if show:
            print('  done.')
        return {'rings': rings}

    def beep(self, show=True):
        """Short confirmation beep (1 kHz, ~1 s)."""
        return self.tone(1000, 1, rate=16000, volume=90, show=show)

    # -- melody / song ---------------------------------------------------

    @staticmethod
    def _note_buf(freq, rate, ms, amp):
        """One note as 16-bit samples, with ~5 ms fade in/out (anti-click)."""
        n = max(1, rate * ms // 1000)
        buf = array.array('h', bytearray(2 * n))
        if freq <= 0:  # rest
            return buf
        step = 2.0 * math.pi * freq / rate
        fade = min(n // 2, max(1, rate // 200))
        for i in range(n):
            v = amp * math.sin(step * i)
            if i < fade:
                v = v * i / fade
            elif i >= n - fade:
                v = v * (n - i) / fade
            buf[i] = int(v)
        return buf

    def melody(self, seq, rate=16000, volume=90, amp=26000, gap_ms=20, show=True):
        """Play a sequence of (note, duration_ms). note is a NOTES key or Hz."""
        h = self._open(rate, volume)
        try:
            for note, ms in seq:
                freq = NOTES.get(note, 0) if isinstance(note, str) else note
                h[2].write(self._note_buf(freq, rate, ms, amp))
                if gap_ms:
                    h[2].write(self._note_buf(0, rate, gap_ms, amp))
        finally:
            self._close(h)
        return {'notes': len(seq)}

    @staticmethod
    def song_names():
        """Sorted list of built-in song names (stable index for selection)."""
        return sorted(SONGS)

    def song(self, name='ode', show=True):
        """Play a built-in song by name ("ode") or 1-based number (1)."""
        if isinstance(name, int):
            names = self.song_names()
            if not (1 <= name <= len(names)):
                print('  invalid song number {} (1..{})'.format(name, len(names)))
                return None
            name = names[name - 1]
        seq = SONGS.get(name)
        if not seq:
            print(
                "  unknown song '{}'. Available: {}".format(
                    name, ', '.join(self.song_names())
                )
            )
            return None
        if show:
            print("  Playing '{}' ({} notes)...".format(name, len(seq)))
        self.melody(seq, show=False)
        if show:
            print('  done.')
        return {'song': name}

    # -- report ----------------------------------------------------------

    def report(self):
        print('=' * 78)
        print('Audio Diagnostics — ESP32-P4-NANO (ES8311 + NS4150B)')
        print('=' * 78)
        print('Codec presence:')
        info = self.probe(show=True)
        if info.get('present'):
            print('\nPlaying test tone (440 Hz, 2 s):')
            self.tone(440, 2, show=True)
        else:
            print('\nCodec not detected on I2C — skipping tone.')
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- Audio Diagnostics (ESP32-P4 / ES8311) ---
 1) Full report        4) Beep
 2) Codec presence/ID  5) Phone ring
 3) Play tone (freq,s)  6) Play a song
                        0) Exit
Choose: """


def main(a=None):
    import netutils

    a = a or AudioDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return a
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(a.report)
        elif choice == '2':
            netutils.run_action(a.probe)
        elif choice == '3':
            f = input('freq Hz [440]: ').strip()
            s = input('seconds [2]: ').strip()
            netutils.run_action(
                lambda: a.tone(int(f) if f else 440, int(s) if s else 2)
            )
        elif choice == '4':
            netutils.run_action(a.beep)
        elif choice == '5':
            n = input('rings [4]: ').strip()
            netutils.run_action(lambda: a.ring(int(n) if n else 4))
        elif choice == '6':
            names = a.song_names()
            for i, nm in enumerate(names, 1):
                print('    {}) {}'.format(i, nm))
            sel = input('song number [1]: ').strip()
            num = int(sel) if sel else 1
            netutils.run_action(lambda: a.song(num))
        elif choice == '0':
            return a
        else:
            print('?')
