# gps-tester

Satellite C/N₀ signal strength bar display for GPS hardware comparison and antenna testing.

Reads NMEA sentences directly from serial — no gpsd required.  
Shows per-satellite C/N₀ bars in a desktop window, colour-coded by strength and fix usage.  
No position data is displayed.

---

## Hardware versions

### Version 1 — VK-162 G-Mouse / G72 M8130-KT

`gps_bars_m8030.py`

Targets USB GPS dongles based on the **u-blox M8030** chip.  
Both the VK-162 G-Mouse and G72 M8130-KT use identical firmware and present the same NMEA output.

| Parameter | Value |
|-----------|-------|
| Device    | `/dev/ttyACM0` |
| Baud rate | 9600 |
| Chipset   | u-blox M8030 |
| Constellations | GPS · GLONASS · Galileo · BeiDou |

### Version 2 — T-Beam v1.2 (NEO-6M)

`gps_bars_tbeam.py`

Targets the **LILYGO T-Beam v1.2** flashed with the `tbeam_gps_passthrough` firmware.  
The ESP32 powers the NEO-6M GPS chip via AXP2101 and relays raw NMEA over USB at 115200 baud.  
GPS only — single constellation.

| Parameter | Value |
|-----------|-------|
| Device    | `/dev/ttyACM0` |
| Baud rate | 115200 |
| Chipset   | u-blox NEO-6M |
| Constellations | GPS only |

---

## What the display shows

- One bar per satellite visible to the receiver
- Y-axis: C/N₀ in dBHz, scale 0–60
- Bar colour by signal strength:
  - Red — below 10 dBHz (very weak)
  - Orange — 10–20 dBHz (weak)
  - Yellow — 20–30 dBHz (marginal)
  - Green — 30–40 dBHz (good)
  - Bright teal — 40+ dBHz (excellent)
- Satellites **used in the fix** are bright with a white top edge
- Satellites **not used in the fix** are dimmed
- PRN number shown below each bar
- Constellation shown in colour: blue=GPS, orange=GLONASS, purple=Galileo, pink=BeiDou
- Status bar: sats used / seen, last update time, device name

---

## Requirements

- Python 3.9 or newer
- A desktop environment (Tkinter window)
- Linux — tested on Ubuntu 24 and Debian 12

**Python packages** (installed into a venv — see below):

```
pyserial
pynmea2
```

---

## Installation

**System packages** — install these first (required on Debian/Ubuntu/Mint):

```bash
sudo apt install python3-pip python3-venv python3-tk
```

> Note: do not use `python3.12-venv` or any version-specific name — `python3-venv` works on all Debian and Ubuntu releases regardless of the Python version installed.

```bash
git clone https://github.com/fotografm/gps-tester.git
cd gps-tester
```

```bash
python3 -m venv venv
source venv/bin/activate
pip install pyserial pynmea2
```

**Serial port access** — add your user to the `dialout` group if not already a member:

```bash
sudo usermod -aG dialout $USER
```

Then log out and back in (or run `newgrp dialout` in the current shell).

---

## Running

Activate the venv first:

```bash
source venv/bin/activate
```

**VK-162 / G72 (plug into USB, device appears as `/dev/ttyACM0`):**

```bash
python gps_bars_m8030.py
```

**T-Beam v1.2 (plug into USB, device appears as `/dev/ttyACM0`):**

```bash
python gps_bars_tbeam.py
```

**Override device or baud rate if needed:**

```bash
python gps_bars_m8030.py --device /dev/ttyACM1 --baud 9600
python gps_bars_tbeam.py --device /dev/ttyACM1 --baud 115200
```

---

## Troubleshooting

**No device found / Permission denied**

Check which device your dongle appeared as:

```bash
dmesg | tail -20
```

If the device exists but access is refused, confirm group membership:

```bash
groups $USER
```

If `dialout` is missing, run the `usermod` command above and re-login.

**Bars stay empty / "Waiting for satellites…"**

The receiver needs a clear view of the sky. Indoors the NEO-6M on the T-Beam is particularly weak — place it near a window or take it outside. The M8030 dongles have a patch antenna that performs slightly better indoors. Allow up to 60 seconds for the first satellites to appear.

**Wrong baud rate**

The VK-162 / G72 default is 9600. The T-Beam passthrough firmware outputs at 115200. If you previously reconfigured your dongle, override with `--baud`.

---

## File overview

```
gps-tester/
├── gps_bars_m8030.py   VK-162 / G72 M8130-KT (u-blox M8030, /dev/ttyUSB0, 9600 baud)
├── gps_bars_tbeam.py   T-Beam v1.2 NEO-6M (/dev/ttyACM0, 115200 baud)
└── README.md
```
