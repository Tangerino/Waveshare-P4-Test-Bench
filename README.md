# Waveshare ESP32-P4-NANO Test Bench

![MicroPython](https://img.shields.io/badge/MicroPython-%E2%89%A5v1.29-blue)
![Board](https://img.shields.io/badge/board-ESP32--P4--NANO-orange)
![License](https://img.shields.io/badge/License-MIT-green.svg)

MicroPython hardware diagnostics for the **Waveshare ESP32-P4-NANO** — eight
self-contained tests (WiFi, Ethernet, CPU/memory/flash, microSD, I2C,
sleep/wake, audio, GPIO), each with a one-shot report and an interactive menu.
Every peripheral is its own package; `main.py` is a top-level selector.

> **Board-specific.** Pin maps and config target the **ESP32-P4-NANO**. Other
> ESP32-P4 boards differ — edit the pin constants at the top of each
> `*/diag.py`. Pins are sourced from Waveshare's schematic and examples (cited
> per section).

## Quick start

```sh
# 1. Flash MicroPython for the ESP32-P4 (>= v1.29.0-preview, C6_WIFI variant).
#    microSD needs this; every other test also runs on older builds.
#    See firmware/BUILD.md (download a prebuilt image or build your own).

# 2. Point at your board and set WiFi credentials.
export PORT=/dev/tty.usbmodemXXXX     # your serial port (or edit deploy.sh)
cp secrets_example.py secrets.py      # then edit WIFI_SSID / WIFI_PASSWORD

# 3. Deploy and run.
./deploy.sh             # upload everything + open the interactive menu
./deploy.sh --system    # ...or a one-shot report for a single test
./deploy.sh --help      # all options
```

## Requirements

### Hardware
- **Waveshare ESP32-P4-NANO** (ESP32-P4, rev v1.3, dual-core RISC-V @ 400 MHz,
  PSRAM, 16 MB flash)
- **ESP32-C6** WiFi co-processor on-board, linked to the P4 over **SDIO**
  (esp-hosted) — GPIO 18/19/14/15/16/17 (+54 reset)
- **IP101 Ethernet PHY** (RMII) — see the pin table below
- **microSD** slot (SDIO 3.0), IO powered by the P4 **on-chip LDO channel 4**
- **I2C** header (default SDA=GPIO7, SCL=GPIO8)
- **ES8311** audio codec (I2C `0x18`) + **NS4150B** speaker amplifier (I2S)
- No user-controllable LED (power indicator only) — the GPIO test targets any pin
- For tests that need it: an Ethernet cable, a FAT-formatted microSD card, and
  an I2C device

### Software / firmware
- **MicroPython for ESP32-P4**, `C6_WIFI` variant (includes the ESP32-C6
  hosted-WiFi support).
- **microSD requires ≥ `v1.29.0-preview` (2026-05-29)** — or any build from
  MicroPython master ≥ commit `dc44bdbac` (2026-04-02), which added the P4
  `machine.SDCard` `ldo`/`cmd`/`data` kwargs. Older builds (e.g. the stock
  `v1.28.0`) can run every other test but **cannot drive the SD slot**.
- **Verified on:** `MicroPython v1.29.0-preview.337.g44a569b637 (2026-05-29)`,
  `ESP32_GENERIC_P4-C6_WIFI`, ESP32-P4 rev v1.3. microSD confirmed mounting +
  benchmarking on this build; the other areas were exercised on-device during
  development (WiFi, System, I2C) or are ready to run (Ethernet needs a cable,
  Sleep's deep-sleep path reboots the board).

### Host tooling
- [`mpremote`](https://docs.micropython.org/en/latest/reference/mpremote.html)
  (upload + run) and `esptool` ≥ v5 (only for flashing firmware).
- [`ruff`](https://docs.astral.sh/ruff/) for formatting/linting (`ruff format .`,
  `ruff check .`) — config in `ruff.toml` (single-quote strings).

See [`firmware/BUILD.md`](firmware/BUILD.md) to flash the prebuilt image or
build your own.

## Layout

```
p4/
├── deploy.sh          # upload + run helper (mpremote wrapper)
├── firmware/BUILD.md  # how to build a P4 image with microSD/LDO support
├── main.py            # boot entry point → top-level selector (all 8 tests)
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
├── sleep/             # deep/light sleep + wake package
│   ├── __init__.py    # re-exports SleepDiagnostics, main, check_wake
│   └── diag.py
├── audio/             # ES8311 codec / speaker package
│   ├── __init__.py    # re-exports AudioDiagnostics, main
│   └── diag.py
├── gpio/              # generic GPIO blink/read package
│   ├── __init__.py    # re-exports GPIODiagnostics, main
│   └── diag.py
├── serial/            # raw 4-UART loopback test (HW, no protocol)
├── ble/               # BLE probe / scan / advertise (via C6, hosted)
├── thread/            # threading / message-passing / parallel-perf (dual-core)
├── docs/SERIAL.md     # serial port UART test: pins, jumpers, how to run
└── docs/P4-MIGRATION.md  # 4 UARTs + USB-to-RS485 conflict assessment (WROOM→P4)
```

New hardware goes in a sibling package (e.g. `i2c/`, `sensors/`): add it to
`PKGS` in `deploy.sh` and a line to the selector in `main.py`.

## Tests

| # | Test | Package | Checks | One-shot |
|---|------|---------|--------|----------|
| 1 | WiFi | `wifi/` | scan, connect, link/RSSI, monitor, ping, power, speedtest | `--wifi` |
| 2 | Ethernet | `eth/` | IP101 link + DHCP, connectivity, ping, speedtest | `--eth` |
| 3 | System | `system/` | CPU bench, heap/PSRAM, flash R/W, uptime, reset cause | `--system` |
| 4 | microSD | `sdcard/` | SDMMC mount, capacity, R/W speed (needs ≥ v1.29 fw) | `--sd` |
| 5 | I2C | `i2c/` | bus scan + device-name hints | `--i2c` |
| 6 | Sleep | `sleep/` | light/deep sleep + wake detection (RTC memory) | `--sleep` |
| 7 | Audio | `audio/` | ES8311 codec ID probe + I2S tone on the speaker | `--audio` |
| 8 | GPIO | `gpio/` | drive/blink/read any pin (no onboard user LED) | `--gpio` |
| 9 | Serial | `serial/` | raw 4-UART loopback + max-baud sweep + controller probe (jumper TX↔RX) | `--serial` |
| 10 | BLE | `ble/` | availability probe + advertiser scan + beacon (via C6, hosted) | `--ble` |
| 11 | Threads | `thread/` | spawn, lock/race, message-passing throughput/latency, 1-vs-2-thread perf (dual-core) | `--thread` |

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
./deploy.sh --audio   # upload, then ES8311 probe + a test tone
./deploy.sh --gpio    # upload, then GPIO test summary
./deploy.sh --serial  # upload, then 4-UART loopback + max-baud sweep
./deploy.sh --ble     # upload, then BLE availability probe + scan
./deploy.sh --thread  # upload, then threading + message-passing + perf report
./deploy.sh --help    # all options
```

Manual equivalent (what `deploy.sh` does — copy the root files, `secrets.py`,
and every package directory, then open the REPL):

```sh
mpremote connect $PORT \
  fs cp main.py :main.py + fs cp netutils.py :netutils.py + fs cp secrets.py :secrets.py \
  + fs cp -r wifi eth system sdcard i2c sleep audio gpio :
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

### Config (native SDMMC slot 0 + on-chip LDO)

Native SDMMC **slot 0** (SDIO 3.0), CLK=43 CMD=44 D0-3=39-42, and — crucially —
the SD card IO is powered by the P4's **on-chip LDO channel 4**. MicroPython's
SDMMC kwargs are `sck`(=CLK), `cmd`, `data` (tuple of D0..), and `ldo`:

```python
machine.SDCard(slot=0, width=4, sck=Pin(43), cmd=Pin(44),
               data=(Pin(39), Pin(40), Pin(41), Pin(42)), ldo=4)
```

These values come from Waveshare's
[`06_sdmmc` ESP-IDF example](https://github.com/waveshareteam/ESP32-P4-Platform/tree/main/examples/esp-idf/06_sdmmc)
(`Kconfig.projbuild`: P4 CLK=43/CMD=44/D0-3=39-42, `SD_PWR_CTRL_LDO_IO_ID=4`).

> ✅ **Verified working** on `v1.29.0-preview.337` (`C6_WIFI`): mounts on the
> first config, e.g. a 256 MB card → `Capacity 255.7 MB`, write ≈ 67 KB/s, read
> ≈ 1065 KB/s in 4-bit mode.
>
> ⚠️ **Firmware requirement.** The `ldo`/`cmd`/`data` kwargs (which power and
> drive the slot) were added to MicroPython master in March–April 2026:
> `a8ba8fab3` (LDO power ctrl), `e57e52218` (configurable slot), **`dc44bdbac`**
> (2026-04-02, the `ldo=` kwarg). Builds older than that — e.g. the stock
> `v1.28.0` — reject those kwargs (`extra keyword arguments given`), so the SD
> slot gets no LDO power and times out (`ESP_ERR_TIMEOUT`). `sdcard/diag.py`
> uses the correct config and **detects old firmware** with a clear message.
> Flash ≥ `v1.29.0-preview` (see [`firmware/BUILD.md`](firmware/BUILD.md)) and
> the SD test works **unchanged**.
> Refs: [`machine.SDCard` docs](https://docs.micropython.org/en/latest/library/machine.SDCard.html),
> [issue #18984](https://github.com/micropython/micropython/issues/18984).

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

## Audio / speaker (ES8311 + NS4150B)

The P4-NANO has an **ES8311** mono codec (I2C `0x18`) driving an **NS4150B**
speaker amplifier. Pins (from Waveshare's `07_I2SCodec` example):

| Signal | GPIO |
|--------|------|
| Codec I2C (SDA / SCL) | 7 / 8 |
| Amp enable (NS4150B) | 53 |
| I2S MCLK / BCLK / WS / DOUT / DIN | 13 / 12 / 10 / 9 / 11 |

```python
from audio import AudioDiagnostics
a = AudioDiagnostics()
a.probe()                       # confirm ES8311 chip ID (0x83 0x11) over I2C
a.tone(440, 2)                  # 440 Hz sine, 2 s (default vol 90, amp 28000)
a.tone(440, 2, volume=100, amp=32000)   # max level
a.ring(4)                       # telephone ring: NA ringback 440+480 Hz
a.ring(2, off_ms=4000)          # true cadence (2 s on / 4 s off)
a.song('ode')                   # by name: ode/twinkle/scale/birthday/mario
a.song(2)                       # ...or by number (a.song_names() lists them)
a.beep()                        # short 1 kHz beep
```

`song()` plays a built-in tune (`ode`, `twinkle`, `scale`, `birthday`, `mario`)
as a note sequence; `melody([(note, ms), ...])` plays your own — notes are
`NOTES` keys (`'C4'`, `'A4'`, …) or raw Hz, with a short per-note fade to avoid
clicks.

`ring()` plays the North American ringback (dual-tone 440+480 Hz) with a
configurable on/off cadence (default 2 s on / 2 s off so a test is quick; pass
`off_ms=4000` for the real cadence).

Two software gain stages: `amp` (digital sine amplitude, 0–32767 — a pure sine
won't clip at full scale) and `volume` (ES8311 DAC register `0x32`, 0–100%).
The NS4150B amplifier gain is fixed in hardware.

MicroPython's `machine.I2S` does **not** emit MCLK, so the codec clock is
generated on GPIO13 with **PWM** (rate×256). The ES8311 register init table is
adapted from the MIT-licensed
[MicroPython ES8311 driver by raptor09010](https://github.com/raptor09010/Micropython-ES8311-Library).
`probe()` is verified (`ES8311 OK`); `tone()` runs the full
codec→I2S→amp path.

## GPIO (generic blink / read)

The P4-NANO has **no documented user LED** (only a power indicator), so this is
a generic pin tool — wire an LED+resistor or a meter to any header pin.

```python
from gpio import GPIODiagnostics
g = GPIODiagnostics()
g.blink(2, count=10, period_ms=200)   # blink GPIO2
g.high(2); g.low(2); g.read(2, pull='up')
```

## Serial ports (UART loopback)

A pure-hardware UART test — **no protocol**. Jumper **TX↔RX** on each port and
the `serial` test loops a pattern through all 4 ports concurrently, verifies
it, and **sweeps baud to find the max each port passes**. Full pin map, jumper
table, and header diagram are in **[`docs/SERIAL.md`](docs/SERIAL.md)**.

```python
from serial import probe, echo, max_speed, report, monitor
probe()               # which UART controllers (0..5) the firmware exposes
report()              # probe + concurrent echo @ 921600 + per-port max-baud sweep
echo(2000000)         # all 4 ports at one baud
max_speed()           # highest passing baud per port
monitor()             # live ON/off-line per port as you fit/remove jumpers
```

The ESP32-P4 has **5 UART controllers** (UART0–4); the bench uses **UART1–4**
and **reserves UART0** (the boot/console UART) to avoid future conflicts — so
`GPIO37/38` stay free. Jumper: `20↔21`, `23↔22`, `32↔33`, `26↔27`. A `FAIL`
just means that port's jumper is missing; `probe()` confirms controller
availability with no jumpers. (UART3 uses `32/33` because `GPIO24/25` are the
USB-Serial-JTAG pins and can't be a UART.) One-shot: `./deploy.sh --serial`.

## BLE (via the ESP32-C6)

The P4 has no radio — BLE comes from the **ESP32-C6 over the esp-hosted link**.
Whether MicroPython can use it depends on the build routing BLE/HCI through the
hosted transport, which the **`C6_WIFI`** image may not do. The `ble` test
**probes that first**, then scans/advertises if BLE is live.

```python
from ble import BLEDiagnostics
b = BLEDiagnostics()
b.probe()                 # is BLE available on this firmware?
b.scan(5000)              # list nearby BLE advertisers (addr, RSSI, name)
b.advertise('P4-TEST')    # advertise a beacon (find it in a phone BLE app)
```

`probe()` reports one of:
- `bluetooth module: NOT present` → BLE isn't compiled into this build.
- `BLE controller: FAILED to activate` → module present, but the hosted C6 link
  doesn't bridge BLE on this firmware.
- `BLE controller: ACTIVE` → BLE works; scan/advertise are usable.

One-shot: `./deploy.sh --ble`.

## Threads (dual-core)

The P4 has **two RISC-V cores**, and MicroPython exposes `_thread` — but note
the ESP32 port pins **all** Python (the interpreter task *and* every `_thread`)
to **core 1 only** (`MP_TASK_COREID`); core 0 is reserved for the ESP-IDF
WiFi/BLE system tasks. So your threads share one core, and a global VM lock (a
GIL) serialises bytecode on top of that. This test spawns workers, checks lock
correctness, measures message-passing throughput, and compares 1- vs 2-thread
CPU work.

```python
from thread import ThreadDiagnostics
t = ThreadDiagnostics()
t.spawn(4)           # start 4 workers, confirm all ran
t.race(200000)       # shared counter: unlocked (racy) vs locked (exact)
t.messaging(5000)    # producer->consumer throughput + latency
t.performance()      # 1-thread vs 2-thread CPU work
```

What the bench actually shows on the P4:

- **Message passing works well** — a lock-guarded mailbox sustains ~11k msg/s
  with ~130 µs latency. Threads are great for I/O-bound concurrency and IPC.
- **CPU-bound Python does NOT parallelise** — all Python runs on one core and a
  GIL serialises bytecode. Splitting math across 2 threads is *slower* than 1
  (GIL handoffs + context switches on the same core), so `performance()` reports
  well under 1× — that result is **correct/expected**, not a bug.
- **Contended `lock.acquire()` costs ~one RTOS tick** here, so heavy
  fine-grained locking is expensive (the lock sub-test uses a small count).
- For real CPU parallelism use native code (`@micropython.viper` / C);
  `_thread` buys you concurrency, not compute throughput.

### `_thread` vs `asyncio`

Because threads give **no** parallelism here (one core + GIL), `asyncio` is the
better default for concurrency: no GIL-handoff/context-switch overhead, no data
races (cooperative single-thread, so no locks needed), lower RAM (no separate
per-thread stack), and deterministic scheduling at `await` points. Reach for
`_thread` only when you must run a *blocking* call you can't make async (one
that releases the GIL while blocked) or a library only offers blocking APIs —
and even then it's concurrency, not speedup.

One-shot: `./deploy.sh --thread`.

## USB / USB host

The P4 has **two USB interfaces**:

| Interface | Pins | Role |
|-----------|------|------|
| USB-Serial-JTAG (Full-Speed) | **GPIO24 / 25** (fixed) | console / flashing / the REPL link |
| USB 2.0 OTG **High-Speed** | **dedicated USB D+/D- pads** (not the GPIO matrix) | OTG host/device port |

- **No GPIO/UART conflict:** the JTAG console pins (24/25) are reserved — the
  serial test deliberately avoids them (UART3 is on 32/33) — and the OTG-HS data
  lines aren't GPIO at all. Console + USB-OTG + the 4 UARTs all coexist.
- **USB host is not usable from MicroPython** on the P4 (`machine.USBHost` doesn't
  exist; `machine.USBDevice` doesn't cover the P4). The OTG-HS host port (e.g. to
  read USB-serial / USB-to-RS485 dongles, a flash drive, or a keyboard) needs
  **ESP-IDF (C)** or **Arduino-ESP32** (`EspUsbHost`). ESP-IDF's
  `usb_host_cdc_acm` + VCP drivers (FTDI/CH34x/CP210x) and a USB hub handle
  multiple USB-serial adapters at once.
- **VBUS:** the P4 doesn't internally source 5 V — bus-powered USB devices need an
  external 5 V→VBUS path on the host port.

There is therefore **no MicroPython "USB host" test** in this bench; the
USB-Serial-JTAG port is implicitly proven by `mpremote` connecting over it. Full
design analysis (4 UARTs + USB-to-RS485, conflicts, VBUS, firmware gate) is in
[`docs/P4-MIGRATION.md`](docs/P4-MIGRATION.md).

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
e.ping('8.8.8.8')
e.down()
```

## Single entry point

On boot the board runs `main.py`, the **top-level selector** (WiFi / Ethernet /
System / microSD / I2C / Sleep / Audio / GPIO). Each package also exposes its
own menu and class for direct REPL use:

```python
import system
system.main()          # that package's menu; returns its object so it stays usable
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
`d.connect('ssid', 'pw')`.

## WiFi (REPL)

```python
from wifi import WiFiDiagnostics
d = WiFiDiagnostics()

d.report()                # full one-shot: scan, power, link, connectivity, ping
d.scan()                  # list networks (sorted by signal)
d.connect()               # join with default creds (blocks until GOT_IP/timeout)
d.connect('ssid', 'pw')   # ...or explicit creds
d.link()                  # current association + RSSI
d.ifconfig()              # IP / netmask / gateway / DNS
d.connectivity()          # DNS resolution + internet reachability
d.ping('8.8.8.8')         # ICMP echo, RTT min/avg/max + loss%
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

**This repo**
- [`docs/SERIAL.md`](docs/SERIAL.md) — serial-port UART test: pins, jumpers, how to run
- [`docs/P4-MIGRATION.md`](docs/P4-MIGRATION.md) — 4 UARTs + USB-to-RS485 conflict assessment (WROOM → P4)
- [`firmware/BUILD.md`](firmware/BUILD.md) — flashing / building a P4 image with microSD support

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

## Contributing

Each test is a self-contained package exposing a `*Diagnostics` class and a
`main()` menu. To add one:

1. Create `yourtest/` with `__init__.py` (re-export the class + `main`) and
   `diag.py`.
2. Add `yourtest` to `PKGS` in `deploy.sh` and a line to the selector in
   `main.py`.
3. Cite the source for any board-specific pins (schematic / vendor example).
4. Format and lint before opening a PR:

```sh
ruff format .
ruff check .
```

Issues and PRs welcome — especially pin maps / results for **other ESP32-P4
boards**.

## License

MIT — see [LICENSE](LICENSE). The ES8311 register init table in `audio/diag.py`
is adapted from the MIT-licensed
[MicroPython ES8311 driver by raptor09010](https://github.com/raptor09010/Micropython-ES8311-Library).
