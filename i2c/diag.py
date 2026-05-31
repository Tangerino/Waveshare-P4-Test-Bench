# i2c/diag.py
#
# I2C bus scan for the Waveshare ESP32-P4-NANO.
#
# Target: MicroPython on ESP32-P4 (ESP32_GENERIC_P4-C6_WIFI); verified v1.29.0-preview.
#
# --- Default I2C pins (Waveshare ESP32-P4-NANO) -----------------------------
#   SDA = GPIO7    SCL = GPIO8
# Remappable via the P4 GPIO matrix; pass different pins or edit the constants.
#
# Usage (REPL):
#   from i2c import I2CDiagnostics, main
#   b = I2CDiagnostics()                  # default pins/freq
#   b = I2CDiagnostics(sda=7, scl=8, freq=400000)
#   b.scan()        # list device addresses (with best-guess names)
#   b.report()
#   main()          # interactive menu

import machine

PIN_SDA = 7
PIN_SCL = 8
DEFAULT_FREQ = 400000

# Best-guess names for common I2C device addresses (7-bit). A hit only means
# *something* answered at that address — confirm against your wiring.
KNOWN = {
    0x0D: 'QMC5883L mag',
    0x1E: 'HMC5883L mag',
    0x20: 'PCF8574 / MCP23017',
    0x23: 'BH1750 light',
    0x27: 'PCF8574 (LCD backpack)',
    0x29: 'VL53L0X / TSL2561',
    0x38: 'AHT10/20 / FT6x36 touch',
    0x39: 'TSL2561',
    0x3C: 'SSD1306 OLED',
    0x3D: 'SSD1306 OLED',
    0x40: 'INA219 / HTU21 / Si7021',
    0x44: 'SHT3x',
    0x48: 'ADS1115 / LM75 / PCF8591',
    0x4A: 'ADS1115',
    0x50: 'AT24C EEPROM',
    0x51: 'PCF8563 RTC',
    0x53: 'ADXL345',
    0x57: 'MAX30100 / AT24',
    0x5A: 'MLX90614 / CCS811',
    0x68: 'MPU6050 / DS1307 / DS3231',
    0x69: 'MPU6050 (alt)',
    0x76: 'BME280 / BMP280',
    0x77: 'BME280 / BMP280 (alt)',
}


class I2CDiagnostics:
    def __init__(self, id=0, sda=PIN_SDA, scl=PIN_SCL, freq=DEFAULT_FREQ):
        self.id = id
        self.sda = sda
        self.scl = scl
        self.freq = freq
        self.i2c = None

    def setup(self):
        if self.i2c is not None:
            return self.i2c
        from machine import Pin

        # Try the requested controller id, then the other common one.
        for bus_id in (self.id, 1 - self.id if self.id in (0, 1) else 0):
            try:
                self.i2c = machine.I2C(
                    bus_id, scl=Pin(self.scl), sda=Pin(self.sda), freq=self.freq
                )
                self.id = bus_id
                return self.i2c
            except (ValueError, OSError):
                continue
        # Last resort: software I2C (bit-banged) on the same pins.
        self.i2c = machine.SoftI2C(scl=Pin(self.scl), sda=Pin(self.sda), freq=self.freq)
        return self.i2c

    def scan(self, show=True):
        i2c = self.setup()
        addrs = i2c.scan()
        devices = [{'addr': a, 'name': KNOWN.get(a, 'unknown')} for a in addrs]
        if show:
            print(
                '  Bus        : I2C{} SDA=GPIO{} SCL=GPIO{} @ {} Hz'.format(
                    self.id, self.sda, self.scl, self.freq
                )
            )
            if not devices:
                print('  No devices found. Check wiring, power, and pull-ups.')
            else:
                print('  {} device(s):'.format(len(devices)))
                for d in devices:
                    print(
                        '    0x{:02X} ({})  {}'.format(d['addr'], d['addr'], d['name'])
                    )
        return devices

    def report(self):
        print('=' * 78)
        print('I2C Bus Scan — ESP32-P4-NANO')
        print('=' * 78)
        self.scan(show=True)
        print('=' * 78)


# -- interactive menu ----------------------------------------------------

MENU = """
--- I2C Diagnostics (ESP32-P4) ---
 1) Scan bus          2) Set pins/freq
 0) Exit
Choose: """


def main(b=None):
    import netutils

    b = b or I2CDiagnostics()
    while True:
        try:
            choice = input(MENU).strip()
        except EOFError:
            print()
            return b
        print('> option {}'.format(choice))
        if choice == '1':
            netutils.run_action(b.scan)
        elif choice == '2':
            sda = input('SDA GPIO [{}]: '.format(b.sda)).strip()
            scl = input('SCL GPIO [{}]: '.format(b.scl)).strip()
            frq = input('freq [{}]: '.format(b.freq)).strip()
            b.__init__(
                id=b.id,
                sda=int(sda) if sda else b.sda,
                scl=int(scl) if scl else b.scl,
                freq=int(frq) if frq else b.freq,
            )
            print(
                '  pins set: SDA=GPIO{} SCL=GPIO{} @ {} Hz'.format(b.sda, b.scl, b.freq)
            )
        elif choice == '0':
            return b
        else:
            print('?')
