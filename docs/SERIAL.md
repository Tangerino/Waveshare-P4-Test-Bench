# Adding 4 serial ports to the ESP32-P4-NANO

Two RS485 (Modbus-RTU energy meters), one RS232/TTL, and one TTL link to a
Quectel **EC200U / EG915U** (LTE Cat-1) modem for MQTT.

The ESP32-P4 has **5 hardware UARTs**; the console is on USB-Serial-JTAG, so
**UART1–UART5 are free**, and the GPIO matrix routes TX/RX to any free pin.

## Pin map (confirmed against the GPIO-header pinout)

All pins below are **free GPIOs broken out to the 2× headers** (the green pins
in Waveshare's pin-definition diagram), avoiding I2C `7/8`, the pre-wired UART
`37/38`, audio amp `53`, and C6 reset `54`. Edit the constants at the top of
each `*/diag.py` for other board revisions.

| Port | UART | TX | RX | Ctrl | Driver constants |
|------|-----:|---:|---:|------|------------------|
| RS485 #1 | 1 | **GPIO20** | **GPIO21** | — (auto-direction) | `rs485/diag.py` `PORTS[1]` |
| RS485 #2 | 2 | **GPIO23** | **GPIO22** | — (auto-direction) | `rs485/diag.py` `PORTS[2]` |
| RS232/TTL | 3 | **GPIO24** | **GPIO25** | — | `rs232/diag.py` |
| Modem | 4 | **GPIO26** | **GPIO27** | PWRKEY=**GPIO32**, PWR_EN=**GPIO33** | `modem/diag.py` |

Budget: 8 UART + 2 modem-control = **10 header GPIOs** (no DE pins —
auto-direction transceivers). Other free header GPIOs left for expansion:
`36, 45, 46, 47, 48` (plus low pins `1–6`, but treat those as possible
strapping). The header also exposes a **ready-made UART on GPIO37(TX)/38(RX)**
and `5V`/`3V3`/`GND` rails.

> The pinout diagram silkscreen reads *ESP32-P4-Module-DEV-KIT*; confirm it
> matches your board revision. Use the repo's `gpio` test (`g.blink(n)`) to
> sanity-check a header pin before wiring.

## RS485 ×2 (Modbus-RTU meters) — auto-direction (DE-free)

Use an **auto-direction** 3.3 V transceiver so there's **no DE/RE GPIO** — the
chip senses the UART TX and drives the bus automatically. Good options:
**MAX13487E** (auto-direction, single chip), or an **isolated** auto module
(recommended for meters in a panel — avoids ground loops, survives surges).

```
ESP32-P4              RS485 xcvr (auto-dir, 3.3 V)   twisted pair → meter
UART1 TX (20) ───────► DI
UART1 RX (21) ◄─────── RO          A ───────────────► A / D+
3V3 ──────────────────► VCC        B ───────────────► B / D-
GND ──────────────────► GND
        120 Ω across A–B at EACH bus end (not in the middle)
        one bias network per bus: ~680 Ω A→3V3 and ~680 Ω B→GND
        add TVS (e.g. SM712) across A/B for field wiring
```
No direction pin to wire or time — repeat for RS485 #2 on UART2 / pins 23,22.

**Echo note:** many auto-direction parts keep RX enabled during TX, so you read
back your own transmitted bytes. The `Modbus` driver is **echo-tolerant** — it
scans the received bytes for the valid response frame (slave addr + func + CRC)
and skips the echo. (If you ever use a manual DE/RE transceiver instead, pass
`de=<gpio>` to `Modbus(...)` and the driver will toggle it.)

Meter wiring: all meters share one A/B pair (daisy-chain), each with a unique
Modbus slave address. Match **baud + parity** to the meter (often 9600 8N1).

## RS232 / TTL ×1

Your 4-pin **RX / TX / GND / VCC** is **TTL 3.3 V** (true RS232 has no VCC
pin), so wire straight to UART3 — **no transceiver**:

```
UART3 TX (24) ─────────► RX (device)
UART3 RX (25) ◄───────── TX (device)
3V3 ──────────────────► VCC          GND ─► GND
```
(If you ever attach a real ±12 V RS232 device, drop a **MAX3232** + 5×0.1 µF
charge-pump caps between the UART and the connector — the driver is unchanged.)

## Quectel EC200U / EG915U (TTL → MQTT)

Two things will bite you if ignored: **power** and **IO voltage**.

```
                +3.8 V  (dedicated buck, ~2 A burst; bulk 1000 µF + 100 µF)
                  │ VBAT
ESP32-P4          ▼
UART4 TX (26) ─►[level-shift 3.3↔1.8 V]─► RXD     EC200U/EG915U VIO = 1.8 V
UART4 RX (27) ◄─[level-shift]◄──────────  TXD     → TXS0108E (unless your
GPIO PWRKEY (32) ─►(pulse, via transistor)─► PWRKEY   breakout already shifts)
GPIO PWR_EN (33) ─►(enable the 3.8 V buck)
modem NET/STATUS ─►(optional input)        GND common to everything
```

- **Power:** the modem pulls ~2 A in bursts on TX. Give it its **own
  3.4–4.2 V supply** (e.g. a buck from 5 V) with **bulk caps**; never from the
  P4 3V3 rail (it browns out and the modem resets).
- **Level shift:** module UART is **1.8 V** → use a TXS0108E on TX/RX. A
  Quectel breakout/EVB may already shift to 3.3 V (then skip it).
- **PWRKEY:** pulse low ≥500 ms to power on. Polarity depends on your drive
  transistor → set `pwrkey_active` in `modem/diag.py`.
- **SIM + antenna** required for registration.

MQTT uses the module's **built-in QMTxxx AT stack** (no PPP):
`AT+QMTOPEN` → `AT+QMTCONN` → `AT+QMTPUB`/`AT+QMTSUB`.

## Drivers (this repo)

| Package | What it does |
|---------|--------------|
| `rs485/` | RS485 half-duplex (auto DE) + Modbus-RTU master (FC03/FC04, CRC16, address scan) |
| `rs232/` | plain TTL UART (write/read/readline + jumper loopback self-test) |
| `modem/` | Quectel power-on, AT engine, network registration, MQTT publish/subscribe |

```python
# two meter buses
from rs485 import open_port
m1 = open_port(1, baud=9600); m1.scan(); m1.read_holding(addr=1, reg=0, count=2)
m2 = open_port(2, baud=9600); m2.scan()

# TTL device
from rs232 import RS232
p = RS232(); p.loopback(); p.write('hi\r\n'); print(p.read())

# modem MQTT
from modem import QuectelModem
q = QuectelModem(); q.power_on(); q.wait_network()
q.mqtt_publish_once('broker.host', 1883, 'p4-meter', 'meters/p4', '{"kwh":123}')
```

One-shot tests: `./deploy.sh --rs485 | --rs232 | --modem`, or the menu
(options 9 / 10 / 11).

## Loopback test jumpers (hardware bring-up)

Before soldering any transceiver, verify the raw UART pins: jumper **TX ↔ RX**
on each port and run the `serial` test (`./deploy.sh --serial`, or menu 12). It
loops a pattern through all 4 ports at once and sweeps for the max baud.

**4 jumpers to fit** (female-female Dupont wires):

| Jumper | Port (UART) | Connect | Where on the header |
|--------|-------------|---------|---------------------|
| JP1 | RS485 #1 (UART1) | GPIO20 ↔ GPIO21 | both **left** column, adjacent rows — easiest |
| JP2 | RS485 #2 (UART2) | GPIO23 ↔ GPIO22 | GPIO23 left (upper) ↔ GPIO22 right — short wire |
| JP3 | RS232 (UART3) | GPIO24 ↔ GPIO25 | **same row**, straight across left↔right |
| JP4 | Modem (UART4) | GPIO26 ↔ GPIO27 | GPIO26 left ↔ GPIO27 right (lower) — wire |

> The ESP32-P4 has **5 UART controllers (UART0–4)**, but **UART0 is left unused
> on purpose** — it's the boot/console UART, so reserving it avoids future
> conflicts (boot logs, a serial console, ROM download mode). The four ports
> use **UART1–4**, leaving `GPIO37/38` (TXD/RXD) free. Run `probe()` (menu 4)
> to see which controllers this firmware exposes.

Header pinout for reference (Waveshare pin-definition diagram), with the test
pins marked `◄JPn`:

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
  13   GND                     GPIO32
  14   GPIO24  ◄JP3            GPIO25  ◄JP3
  15   GPIO33                  GND
  16   GPIO26  ◄JP4            GPIO54 (C6 reset)
  17   GPIO48                  GND
  18   GPIO53 (audio amp)      GPIO46
  19   GPIO47                  GPIO27  ◄JP4
  20   GND                     GPIO45
```

Notes:
- **JP1** (GPIO20↔21) sits on two adjacent left-column pins — the simplest jumper.
- **JP3** (GPIO24↔25) is one row, straight across the two columns.
- **JP2** and **JP4** span columns/rows → use a short jumper wire.
- A port that shows `FAIL` in the test simply has its jumper missing; remove the
  jumpers afterwards before wiring the real transceivers.
- `GPIO37/38` (UART0) are left **free/reserved** — don't jumper them.

## Bill of materials (typical)

- 2× **auto-direction** RS485 transceiver: **MAX13487E** (or an isolated
  auto-direction RS485 module — recommended for meters in a panel)
- 4× 120 Ω termination + bias resistors; TVS diodes (SM712) for RS485 field lines
- 1× MAX3232 + 5×0.1 µF — **only** if a real ±12 V RS232 device is attached
- Quectel EC200U/EG915U module + SIM holder + LTE antenna
- Modem power: 5 V→3.8 V buck (≥2 A) + bulk caps (1000 µF + 100 µF + 0.1 µF)
- 1× TXS0108E level shifter (for the 1.8 V modem UART), unless the breakout shifts
- Common ground across all transceivers, the modem supply, and the P4
