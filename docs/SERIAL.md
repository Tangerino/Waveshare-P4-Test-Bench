# Serial port (UART) hardware test

A pure-hardware loopback test for the ESP32-P4's UARTs — no protocol. Jumper
**TX ↔ RX** on each port, then the `serial` package writes a pattern through
all ports at once, verifies it comes back, and sweeps baud to find the maximum
each port passes.

The ESP32-P4 has **5 UART controllers (UART0–4)**. **UART0 is reserved** (it's
the boot/console UART — leaving it free avoids conflicts with boot logs, a
serial console, or ROM download mode), so the test uses **UART1–4**.

## Pin map (free header GPIOs)

Confirmed against the board's GPIO-header pin-definition diagram (green pins,
not used by I2C `7/8`, audio `9-13/53`, C6 `14-19/54`, Ethernet `28-35/49-52`,
or microSD `39-44`). Edit `PORTS` at the top of `serial/diag.py` to change them.

| Port | UART | TX | RX |
|------|-----:|---:|---:|
| 1 | 1 | GPIO20 | GPIO21 |
| 2 | 2 | GPIO23 | GPIO22 |
| 3 | 3 | GPIO32 | GPIO33 |
| 4 | 4 | GPIO26 | GPIO27 |

`UART0` and its header pins `GPIO37/38` (TXD/RXD) are intentionally left free.

> ⚠️ **`GPIO24/25` are the USB-Serial-JTAG D−/D+ pins** (the REPL/USB link), so
> they can't be used as a UART while connected over USB — `machine.UART` rejects
> them as `invalid pin`. That's why UART3 uses `GPIO32/33`, not `24/25`.

## Loopback jumpers

Fit a jumper (female-female Dupont wire) **TX ↔ RX** on each port you want to
test:

| Jumper | UART | Connect | Where on the header |
|--------|-----:|---------|---------------------|
| JP1 | 1 | GPIO20 ↔ GPIO21 | both **left** column, adjacent rows — easiest |
| JP2 | 2 | GPIO23 ↔ GPIO22 | GPIO23 left (upper) ↔ GPIO22 right — short wire |
| JP3 | 3 | GPIO32 ↔ GPIO33 | GPIO32 right ↔ GPIO33 left — short wire |
| JP4 | 4 | GPIO26 ↔ GPIO27 | GPIO26 left ↔ GPIO27 right (lower) — wire |

Header pinout for reference (the test pins marked `◄JPn`):

```
        LEFT column            RIGHT column
   1   3V3                     5V
   2   GPIO7 (SDA / I2C)       5V
   3   GPIO8 (SCL / I2C)       GND
   4   GPIO23  ◄JP2            GPIO37 (TXD, UART0 — reserved/free)
   5   GND                     GPIO38 (RXD, UART0 — reserved/free)
   6   GPIO21  ◄JP1            GPIO22  ◄JP2
   7   GPIO20  ◄JP1            GND
   8   GPIO6                   GPIO5
   9   3V3                     GPIO4
  10   GPIO3                   GND
  11   GPIO2                   GPIO1
  12   GPIO0                   GPIO36
  13   GND                     GPIO32  ◄JP3
  14   GPIO24 (USB-JTAG D-)     GPIO25 (USB-JTAG D+)
  15   GPIO33  ◄JP3            GND
  16   GPIO26  ◄JP4            GPIO54 (C6 reset)
  17   GPIO48                  GND
  18   GPIO53 (audio amp)      GPIO46
  19   GPIO47                  GPIO27  ◄JP4
  20   GND                     GPIO45
```

Notes:
- **JP1** (GPIO20↔21) sits on two adjacent left-column pins — the simplest.
- **JP2**, **JP3**, **JP4** span columns/rows → use a short jumper wire.
- `GPIO24/25` are **USB-Serial-JTAG** (the REPL link) — never use them as UART.
- A port that shows `FAIL` simply has its jumper missing.
- Don't jumper `GPIO37/38` (UART0 reserved).

## Run it

```sh
./deploy.sh --serial      # one-shot, or:
./deploy.sh               # menu → 9
```

```python
from serial import probe, echo, max_speed, report, monitor
probe()              # which UART controllers (0..5) the firmware exposes
echo(921600)         # loop all 4 ports concurrently at one baud
max_speed()          # highest passing baud per port (sweep 115k..5M)
report()             # probe + concurrent echo + per-port max-baud sweep
monitor()            # live: each port ON/off line as you fit/remove jumpers
```

`probe()` needs **no jumpers** — it opens each UART id on scratch pins and
reports which controllers exist, so you can confirm UART1–4 are available
before wiring.

### Live monitor

`monitor()` (menu option 5) loops continuously and prints each port's status,
reacting as you plug jumpers — a port with no jumper shows `off line`, fit the
TX↔RX jumper and it flips to `ON line`. Only **transitions** print, so it stays
quiet until something changes. Ctrl-C stops.

```
Live loopback monitor @ 115200 baud — fit/remove TX<->RX jumpers.
(Ctrl-C to stop)
  UART1  off line
  UART2  off line
  UART3  off line
  UART4  off line
  UART3  ON  line      <- fitted the GPIO32<->33 jumper
  UART3  off line      <- removed it
```

Sample output:

```
UART controllers:
    UART0: available  (reserved — console, not used)
    UART1: available
    UART2: available  ...  -> 5 UART controller(s): [0, 1, 2, 3, 4]
Concurrent echo @ 921600:
    UART1: PASS  112.4 KB/s
    UART2: PASS  112.4 KB/s
    UART3: PASS  112.4 KB/s
    UART4: FAIL  (32 err) — jumper TX<->RX?
Per-port maximum baud:
    UART1: 3000000 baud
    ...
```

## What it verifies

- The UART **controllers** are present and openable (`probe`).
- The **header pins** route correctly and carry data (loopback PASS).
- The **maximum reliable baud** per port over a direct jumper (`max_speed`).

A direct TX↔RX jumper has no transceiver/line losses, so the max baud reflects
the SoC/firmware UART limit, not a real cable.
