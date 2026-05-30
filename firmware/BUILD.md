# Firmware for the ESP32-P4 (with microSD / LDO support)

The microSD test needs a MicroPython build whose `machine.SDCard` supports the
ESP32-P4 `ldo` / `cmd` / `data` kwargs. That support landed in **master** in:

| Date | Commit | Adds |
|------|--------|------|
| 2026-03-23 | `a8ba8fab3` | SDMMC power control via on-chip LDO |
| 2026-03-27 | `e57e52218` | configurable default SDMMC slot |
| 2026-04-02 | `dc44bdbac` | **`ldo=` kwarg (configurable LDO channel)** |

The stock Waveshare `v1.28.0` image (built 2026-04-06) was snapshotted from
source **before** `dc44bdbac`, so it lacks these. Use a build at/after
`dc44bdbac` and the repo's SD test works unchanged (it already passes
`slot=0, sck=43, cmd=44, data=(39,40,41,42), ldo=4`).

---

## Quick path: flash a prebuilt image (recommended, ✅ tested)

No build needed — download a recent **`ESP32_GENERIC_P4-C6_WIFI`** nightly (the
`C6_WIFI` variant keeps the ESP32-C6 WiFi) from
<https://micropython.org/download/ESP32_GENERIC_P4/> and flash it.

> **Verified:** `ESP32_GENERIC_P4-C6_WIFI-20260529-v1.29.0-preview.337.g44a569b637.bin`
> flashed cleanly and all six test areas pass, microSD included.

```sh
PORT=/dev/tty.usbmodem5B610378241        # your board's serial port
FW=ESP32_GENERIC_P4-C6_WIFI-20260529-v1.29.0-preview.337.g44a569b637.bin

# (optional) back up the current image first — 16 MB flash:
esptool --chip esp32p4 --port $PORT read_flash 0x0 0x1000000 backup-stock.bin

esptool --chip esp32p4 --port $PORT erase_flash
esptool --chip esp32p4 --port $PORT --baud 460800 write_flash 0x2000 "$FW"
```

> ⚠️ **ESP32-P4 flashes at offset `0x2000`** (its bootloader lives there) — not
> `0x0`/`0x1000` like other ESP32 chips. esptool **≥ v5** required.

Flashing **erases the filesystem** (your uploaded test files + `secrets.py`).
Re-deploy and test:

```sh
./deploy.sh            # re-upload the suite (+ secrets.py)
./deploy.sh --sd       # microSD should now mount + benchmark
```

`*.bin` (firmware images and `backup-*.bin`) are gitignored.

---

## Alternative: build from source

Only needed if you want a custom build or a non-`C6_WIFI` variant.

## Prerequisites

- macOS/Linux, Python 3, git, cmake, ninja
- **ESP-IDF ≥ v5.4** (ESP32-P4 + the `sd_pwr_ctrl_by_on_chip_ldo` driver).
  Always match the exact version MicroPython pins — see
  `micropython/ports/esp32/README.md`.

## 1. Install ESP-IDF for the ESP32-P4

```sh
git clone -b v5.4.1 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32p4
. ./export.sh          # run this in every new shell (sets up the toolchain)
cd ..
```

## 2. Get MicroPython master (with the LDO commits)

```sh
git clone https://github.com/micropython/micropython.git
cd micropython

# Ensure the LDO kwarg is present (must list dc44bdbac or newer):
git log --oneline -3 -- ports/esp32/machine_sdcard.c
# If your checkout predates it, just stay on the latest master:
git pull origin master

# Sanity check the source actually has the ldo arg:
grep -n "ARG_ldo" ports/esp32/machine_sdcard.c   # expect a match
```

## 3. Build

```sh
make -C mpy-cross                                  # one-time host tool

cd ports/esp32
make submodules BOARD=ESP32_GENERIC_P4
make BOARD=ESP32_GENERIC_P4 -j8
# -> build artifact: build-ESP32_GENERIC_P4/firmware.bin (+ bootloader, etc.)
```

> If `ESP32_GENERIC_P4` isn't under `ports/esp32/boards/`, list what's there
> (`ls ports/esp32/boards | grep -i p4`) and use that board name.

## 4. Flash

```sh
# erase first, then deploy (set your port)
make BOARD=ESP32_GENERIC_P4 PORT=/dev/tty.usbmodem5B610378241 erase
make BOARD=ESP32_GENERIC_P4 PORT=/dev/tty.usbmodem5B610378241 deploy
```

## 5. Verify

```sh
cd <this repo>
./deploy.sh --sd
```

Expect `Mounted at /sd via slot0 w4 +LDO4 ...` followed by capacity and R/W
speed — no code change needed.

---

## ⚠️ Caveat: ESP32-C6 WiFi on a generic build

WiFi on the P4-NANO is provided by the **ESP32-C6 over the esp-hosted link**.
The Waveshare stock image bundles that integration; a **plain
`ESP32_GENERIC_P4` master build may not include the hosted-WiFi support**, so
flashing it can get microSD working but **lose WiFi**. Ethernet is the P4's
native EMAC and should keep working.

If you need WiFi *and* microSD together, the robust path is to **cherry-pick
the three commits above onto the MicroPython source Waveshare builds from**
(which already wires up the C6), rather than flashing plain master:

```sh
# in a checkout of the Waveshare/vendor MicroPython source:
git remote add upstream https://github.com/micropython/micropython.git
git fetch upstream
git cherry-pick a8ba8fab3 e57e52218 dc44bdbac
# resolve any conflicts in ports/esp32/machine_sdcard.c, then build as above
```

Always back up the current firmware before flashing:

```sh
esptool.py --port /dev/tty.usbmodem5B610378241 read_flash 0 ALL backup-stock.bin
```
