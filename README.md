# ESP32-P4 Hardware Tests

Hardware test tooling for the **Waveshare ESP32-P4-NANO** board. Each
peripheral lives in its own package; `main.py` is a top-level selector.

- **Target:** MicroPython v1.28.0, Generic ESP32P4 module
- **WiFi radio:** external ESP32-C6 (hosted RPC transport)
- **Ethernet:** built-in P4 EMAC + IP101 PHY over RMII

## Layout

```
p4/
├── deploy.sh          # upload + run helper (mpremote wrapper)
├── main.py            # boot entry point → hardware selector (WiFi / Ethernet)
├── netutils.py        # shared IP helpers: resolve, tcp_check, ping, run_action
├── wifi/              # WiFi diagnostics package
│   ├── __init__.py    # re-exports WiFiDiagnostics, main
│   └── diag.py
├── eth/               # Ethernet diagnostics package
│   ├── __init__.py    # re-exports EthernetDiagnostics, main
│   └── diag.py
├── system/            # CPU / memory / flash package
│   ├── __init__.py    # re-exports SystemDiagnostics, main
│   └── diag.py
├── sdcard/            # microSD (SDMMC) package
│   ├── __init__.py    # re-exports SDCardDiagnostics, main
│   └── diag.py
├── i2c/               # I2C bus scan package
│   ├── __init__.py    # re-exports I2CDiagnostics, main
│   └── diag.py
└── sleep/             # deep/light sleep + wake package
    ├── __init__.py    # re-exports SleepDiagnostics, main, check_wake
    └── diag.py
```

New hardware goes in a sibling package (e.g. `i2c/`, `sensors/`): add it to
`PKGS` in `deploy.sh` and a line to the selector in `main.py`.

## Deploy

`deploy.sh` wraps `mpremote` (set `PORT` or edit the default at the top):

```sh
./deploy.sh           # upload, reset, open the interactive menu (REPL)
./deploy.sh --wifi    # upload, then WiFi connect + one-shot report
./deploy.sh --eth     # upload, then Ethernet up + one-shot report
./deploy.sh --system  # upload, then CPU/memory/flash one-shot report
./deploy.sh --sd      # upload, then microSD mount + speed one-shot report
./deploy.sh --i2c     # upload, then I2C bus scan
./deploy.sh --sleep   # upload, then sleep info + light-sleep test
./deploy.sh --help    # all options
```

Manual equivalent:

```sh
mpremote connect $PORT fs cp main.py :main.py + fs cp netutils.py :netutils.py \
  + fs cp -r wifi : + fs cp -r eth : + fs cp -r system :
mpremote connect $PORT repl
```

## System tests (CPU / memory / flash)

```python
from system import SystemDiagnostics
s = SystemDiagnostics()
s.report()            # board info + CPU + memory + flash
s.cpu()               # freq + int/float benchmark (+ MCU temp if available)
s.cpu(set_mhz=360)    # change core frequency, then benchmark
s.memory()            # heap free/used + largest block + fragmentation
s.flash()             # FS usage + write/read throughput (64 KB temp file)
s.info()              # uname, freq, unique id, flash size
```

The flash test writes and reads a small temp file (`/_flash_test.bin`,
default 64 KB) and deletes it — minimal wear.

## microSD (SDMMC)

Pins (ESP32-P4-NANO, 4-bit SDMMC): `CLK=43 CMD=44 D0=39 D1=40 D2=41 D3=42`.
Edit the constants at the top of `sdcard/diag.py` for other variants.

```python
from sdcard import SDCardDiagnostics
sd = SDCardDiagnostics()
sd.report()       # mount + capacity/usage + write/read speed
sd.mount(); sd.info(); sd.speed(); sd.umount()
```

The speed test writes/reads `/sd/_sdtest.bin` (default 512 KB) and removes it.
Card must be inserted and FAT-formatted.

### Correct config (per Waveshare's ESP-IDF example)

Native SDMMC **slot 0** (SDIO 3.0), CLK=43 CMD=44 D0-3=39-42, and — crucially —
the SD card IO is powered by the P4's **on-chip LDO channel 4**. MicroPython's
SDMMC kwargs are `sck`(=CLK), `cmd`, `data` (tuple of D0..), and `ldo`:

```python
machine.SDCard(slot=0, width=4, sck=Pin(43), cmd=Pin(44),
               data=(Pin(39), Pin(40), Pin(41), Pin(42)), ldo=4)
```

> **Firmware requirement:** the SD slot needs a MicroPython build whose
> `machine.SDCard` supports the ESP32-P4 `ldo`/`cmd`/`data` kwargs (present in
> current MicroPython — see the [docs](https://docs.micropython.org/en/latest/library/machine.SDCard.html)
> and [issue #18984](https://github.com/micropython/micropython/issues/18984)).
>
> The **tested build** (`v1.28.0`, machine = "Generic ESP32P4 module …")
> **predates this** — it rejects those kwargs (`extra keyword arguments given`),
> so it cannot enable the on-chip LDO that powers the card's IO. The result is
> `ESP_ERR_TIMEOUT` (no card power), regardless of pins or SPI tricks. `mount()`
> uses the correct config above and **detects the old-firmware case** with a
> clear message. **Flash a newer MicroPython P4 image and the SD test works as
> is** — no code change needed. The other test areas (WiFi, Ethernet, System,
> I2C, Sleep) work on the current build.

The pin/LDO values come from Waveshare's
[`06_sdmmc` ESP-IDF example](https://github.com/waveshareteam/ESP32-P4-Platform/tree/main/examples/esp-idf/06_sdmmc)
(`Kconfig.projbuild`: P4 CLK=43/CMD=44/D0-3=39-42, `SD_PWR_CTRL_LDO_IO_ID=4`).

## I2C bus scan

Default pins (ESP32-P4-NANO): `SDA=GPIO7 SCL=GPIO8`.

```python
from i2c import I2CDiagnostics
I2CDiagnostics().scan()                      # default pins, 400 kHz
I2CDiagnostics(sda=7, scl=8, freq=100000).scan()
```

Reports each responding 7-bit address with a best-guess device name (a hit
only means *something* answered — confirm against your wiring). Needs pull-ups
on SDA/SCL.

## Sleep / wake

```python
from sleep import SleepDiagnostics
s = SleepDiagnostics()
s.info()              # reset cause + wake reason + RTC-memory marker
s.light_sleep(2000)   # light sleep 2 s, resumes in place, reports elapsed
s.deep_sleep(5)       # marker + deep sleep 5 s -> REBOOT (does not return)
```

**Light sleep** resumes execution where it left off. **Deep sleep reboots the
chip** on wake, dropping the serial/REPL link — reconnect after the sleep
interval. The test stashes a marker in RTC memory before sleeping; on the next
boot `main.py` calls `sleep.check_wake()`, which detects the marker, confirms
`reset_cause == DEEPSLEEP_RESET`, and prints how long the board was out. Deep
sleep is interactive-only (menu option 3, with a confirm) since it reboots.

## Ethernet pin map (ESP32-P4-NANO, IP101 PHY)

Verified against the Waveshare wiki and ESPHome board config. Only the
management/clock pins are configurable from `network.LAN()`; the RMII **data**
pins are fixed by the board wiring and the firmware EMAC config.

| Signal | GPIO | Settable in `network.LAN`? |
|--------|-----:|----------------------------|
| MDC | 31 | yes (`mdc`) |
| MDIO | 52 | yes (`mdio`) |
| PHY power / reset | 51 | yes (`power`) |
| RMII REF_CLK (50 MHz, **input** to P4) | 50 | yes (`ref_clk`, `ref_clk_mode=Pin.IN`) |
| TXD0 / TXD1 | 34 / 35 | no (fixed) |
| RXD0 / RXD1 | 30 / 29 | no (fixed) |
| TX_EN | 49 | no (fixed) |
| CRS_DV | 28 | no (fixed) |

PHY address = `1`. Edit the constants at the top of `eth/diag.py` for other
board variants. If MDC/MDIO/power/clk are correct but the link never comes up,
the firmware build's RMII **data**-pin mapping doesn't match this board.

```python
from eth import EthernetDiagnostics
e = EthernetDiagnostics()
e.up()            # bring link up + DHCP
e.report()        # status, IP, connectivity, ping
e.ifconfig()
e.ping("8.8.8.8")
e.down()
```

## Single entry point

Resetting the board runs `main.py`, which launches the WiFi menu. From the
REPL you can also call it directly:

```python
import wifi
d = wifi.main()        # menu loop; returns the object so `d` stays usable
```

## Credentials (secrets.py)

WiFi credentials live in `secrets.py`, which is **gitignored** (never
committed). Create it from the template:

```sh
cp secrets_example.py secrets.py     # then edit WIFI_SSID / WIFI_PASSWORD
```

`deploy.sh` uploads `secrets.py` to the board when present; `wifi/diag.py`
reads `WIFI_SSID` / `WIFI_PASSWORD` from it for `connect()`'s defaults. If
`secrets.py` is absent the defaults are blank — pass credentials explicitly:
`d.connect("ssid", "pw")`.

## Use (REPL)

```python
from wifi import WiFiDiagnostics
d = WiFiDiagnostics()

d.report()                # full one-shot: scan, power, link, connectivity, ping
d.scan()                  # list networks (sorted by signal)
d.connect()               # join with default creds (blocks until GOT_IP/timeout)
d.connect("ssid", "pw")   # ...or explicit creds
d.link()                  # current association + RSSI
d.ifconfig()              # IP / netmask / gateway / DNS
d.connectivity()          # DNS resolution + internet reachability
d.ping("8.8.8.8")         # ICMP echo, RTT min/avg/max + loss%
d.monitor()               # live RSSI bar graph (Ctrl-C to stop)
d.monitor(count=10)       # ...or a fixed number of samples
d.power()                 # read power-save mode + TX power
d.power(txpower=15)       # set TX power (dBm)
d.disconnect()
```

## Notes

- The `W (xxxxx) rpc_rsp: Hosted RPC_Resp ...` lines printed during
  `scan()`/`connect()` come from the esp-hosted transport between the P4 and
  the C6 radio. They are informational, not errors.
- `ping()` uses a raw ICMP socket. If the firmware/lwIP build doesn't permit
  raw sockets it says so — fall back to `tcp_check()` / `connectivity()`, which
  use DNS resolution and a TCP connect to `8.8.8.8:53`.
- Security types are decoded from the ESP-IDF `wifi_auth_mode_t` integer
  returned by `scan()` (e.g. `3` = WPA2-PSK, `7` = WPA2/WPA3-PSK).

## Resources

**Board (Waveshare ESP32-P4-NANO)**
- [ESP32-P4-NANO wiki](https://www.waveshare.com/wiki/ESP32-P4-Nano-StartPage) — pinout, Ethernet/SD/I2C details
- [ESP32-P4-NANO schematic (PDF)](https://files.waveshare.com/wiki/ESP32-P4-NANO/ESP32-P4-NANO-schematic.pdf) — authoritative pin source
- [ESPHome board page](https://devices.esphome.io/devices/waveshare-esp32-p4-nano) — cross-check for Ethernet/PHY config
- [Espressif ESP32-P4 SoC](https://www.espressif.com/en/products/socs/esp32-p4)

**MicroPython**
- [ESP32 quick reference](https://docs.micropython.org/en/latest/esp32/quickref.html)
- [`network`](https://docs.micropython.org/en/latest/library/network.html) ·
  [`network.WLAN`](https://docs.micropython.org/en/latest/library/network.WLAN.html) ·
  [`network.LAN`](https://docs.micropython.org/en/latest/library/network.LAN.html)
- [`machine`](https://docs.micropython.org/en/latest/library/machine.html) ·
  [`machine.SDCard`](https://docs.micropython.org/en/latest/library/machine.SDCard.html) ·
  [`machine.I2C`](https://docs.micropython.org/en/latest/library/machine.I2C.html)
- [`mpremote` tool](https://docs.micropython.org/en/latest/reference/mpremote.html)

**ESP-IDF (background)**
- [SDMMC host driver — ESP32-P4](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/peripherals/sdmmc_host.html)
- [Ethernet (EMAC/PHY)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/network/esp_eth.html)
- [Sleep modes](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/system/sleep_modes.html)

## License

MIT — see [LICENSE](LICENSE).
