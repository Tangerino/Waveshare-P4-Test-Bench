# ESP32-WROOM → ESP32-P4 migration: 4 UARTs + USB-to-RS485

Design assessment for a firmware that needs, **simultaneously and conflict-free**:

- **4 native UART serial ports**, and
- **one or more USB-to-RS485 adapters** on the P4's USB port (the P4 acting as
  **USB host**, talking to USB-serial dongles — FTDI / CH340 / CP210x / generic
  CDC-ACM RS485 converters).

## TL;DR

| Goal | Verdict |
|------|---------|
| 4 native UART ports | ✅ feasible — P4 has **5 UARTs** (UART0–4); WROOM had only 3 |
| USB-to-RS485 (USB host) | ✅ feasible **only on ESP-IDF (C) / Arduino-ESP32** — **not MicroPython** |
| Conflicts (4 UARTs + USB-JTAG console + USB-OTG host) | ❌ **none** — disjoint resources, all run at once |

## Hardware inventory (ESP32-P4)

| Block | Where | Use |
|-------|-------|-----|
| 5× UART (UART0–4) + 1 LP-UART | GPIO matrix (any free pin) | UART0 = console; **UART1–4 = the 4 ports** |
| USB-Serial-JTAG (Full-Speed) | **GPIO24 / 25** (fixed) | console / flashing / REPL |
| USB 2.0 OTG **High-Speed** | **dedicated USB D+/D- pads** (not the GPIO matrix) | **host port for the USB-RS485 adapters** |

## Native UART pin map (verified on the test bench)

From `serial/diag.py` `PORTS` — validated on-device with the loopback test:

| Port | UART | TX | RX |
|------|-----:|---:|---:|
| 1 | 1 | GPIO20 | GPIO21 |
| 2 | 2 | GPIO23 | GPIO22 |
| 3 | 3 | GPIO32 | GPIO33 |
| 4 | 4 | GPIO26 | GPIO27 |

- **Never use GPIO24/25 for a UART** — they are the USB-Serial-JTAG console.
  (UART3 was deliberately moved off 24/25 to 32/33 for exactly this reason.)
- 8 GPIO total for the four UARTs; USB host costs **0 GPIO** (dedicated pads).
- Spare free header GPIOs after the four UARTs: `36, 45, 46, 47, 48`.

## USB-to-RS485 (USB host) — details & the firmware gate

- **The P4 can be USB host** on the OTG-HS controller. Only **one USB controller
  can be host at a time** (HS host for the adapters); the FS USB-Serial-JTAG
  console is a separate peripheral and keeps working for debug.
- **ESP-IDF USB-host VCP stack is mature/production-ready** — managed components
  `usb_host_cdc_acm` plus VCP drivers `usb_host_ftdi`, `usb_host_ch34x_vcp`,
  `usb_host_cp210x_vcp` (and generic CDC-ACM). The VCP service auto-loads the
  right driver on plug-in; see the ESP-IDF `cdc_acm_vcp` example.
- **Multiple adapters at once:** ✅ via a **USB hub** (ESP-IDF external-hub driver,
  single/multi-level; the P4 has 16 channels). One host port → hub → N USB-RS485s.
- **MicroPython:** ❌ no USB-host on the P4 (`machine.USBHost` does not exist).
- **Arduino-ESP32:** ✅ the `EspUsbHost` library wraps the ESP-IDF host stack
  (CDC/VCP).
- **→ The decision gate:** if USB-RS485 is required, the firmware **must be
  ESP-IDF (C) or Arduino-ESP32**. MicroPython is not an option for it.
- **VBUS power:** the P4 does **not** internally source 5 V to VBUS. Bus-powered
  adapters need an **external 5 V → VBUS** path (often a GPIO-switched load
  switch); self-powered adapters/hubs don't. Confirm on the chosen board port.

## Conflict matrix

| Resource | Pins / bus | Conflict with the others? |
|----------|-----------|---------------------------|
| UART1–4 | GPIO 20/21, 23/22, 32/33, 26/27 (matrix) | none |
| USB-Serial-JTAG console | GPIO24/25 (fixed) | none (UARTs avoid 24/25) |
| USB-OTG-HS host (RS485) | dedicated USB pads (not GPIO matrix) | none |

→ **Console + USB-host + 4 UARTs coexist.** Note: the HS USB D+/D- are dedicated
USB pads — do **not** confuse them with GPIO50/51 (which on this board are the
Ethernet ref-clk / PHY-power pins); USB-HS is not in the GPIO matrix at all.

## WROOM → P4: why the migration unlocks this

- **WROOM** = 3 UARTs (UART0/1/2; UART1 overlaps the SPI-flash pins) and **no USB
  host** → 4 native UARTs + USB-RS485 is **impossible**.
- **P4** = 5 UARTs + USB-OTG host → enables the whole design, with headroom.

## Recommendation

1. **Firmware:** target **ESP-IDF (C)** (or Arduino-ESP32) if USB-RS485 is needed —
   MicroPython can't host USB serial on the P4.
2. **Native UARTs:** use the verified pin map above. If those UARTs also drive
   wired RS485, use **auto-direction transceivers** (no DE GPIO).
3. **USB host:** `usb_host_cdc_acm` + VCP drivers; add a USB hub for multiple
   adapters; provide external 5 V VBUS if the adapters are bus-powered.
4. **Keep the USB-Serial-JTAG console** for debug — it coexists with everything.

## Verifying on hardware (new firmware)

- Flash the ESP-IDF `cdc_acm_vcp` example + four `uart_driver` instances on the
  verified pins.
- Plug a known USB-RS485 dongle (CH340 / FTDI / CP210x); confirm enumeration and
  RS485 read/write; confirm VBUS powers the dongle.
- The bench's `serial` loopback test already proves the four UART pin routes.

## Sources

- [ESP32-P4 USB Host API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/peripherals/usb_host.html) ·
  [USB-host CDC-ACM VCP component](https://components.espressif.com/component/espressif/usb_host_cdc_acm) ·
  [USB external-hub driver](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/peripherals/usb_host/usb_host_notes_ext_hub.html)
- [USB-Serial-JTAG console (GPIO24/25)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-guides/usb-serial-jtag-console.html) ·
  [ESP32-P4 UART](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/peripherals/uart.html)
- [Arduino EspUsbHost](https://github.com/tanakamasayuki/EspUsbHost) ·
  [MicroPython machine.USBDevice (device-only, S3 not P4)](https://docs.micropython.org/en/latest/library/machine.USBDevice.html)
