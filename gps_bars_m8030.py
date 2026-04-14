#!/usr/bin/env python3
"""
gps_bars_m8030.py
GPS satellite C/N0 signal strength bar display.

Target hardware:
  - G72 M8130-KT USB GPS dongle
  - VK-162 G-Mouse (u-blox M8030 chip)

Both present as /dev/ttyUSB0 at 9600 baud and output standard
NMEA sentences including GPGSV / GLGSV / GAGSV / GBGSV.

Usage:
  python gps_bars_m8030.py [--device /dev/ttyUSB0] [--baud 9600]

Requires:
  pip install pyserial pynmea2
"""

import argparse
import serial
import threading
import time
import pynmea2
import tkinter as tk
import sys

# ── Config ────────────────────────────────────────────────────────────────────

DEVICE_DEFAULT = '/dev/ttyUSB0'
BAUD_DEFAULT   = 9600
TITLE          = 'GPS Signal Bars — VK-162 / G72 M8130-KT'
UPDATE_MS      = 800   # canvas redraw interval

# ── Colour palette (raspi standard) ──────────────────────────────────────────

BG          = '#080818'
PANEL       = '#0d0d20'
BORDER      = '#4a4a8a'
TEXT        = '#f0f0ff'
MUTED       = '#aaaadd'
HEADING     = '#8888cc'
CLOCK       = '#66dd66'
ALERT       = '#ff6666'

# C/N0 bar colours (used satellite)
BAR_COLOURS_USED = [
    (10, '#ff4444'),   # < 10 dBHz — very weak
    (20, '#ff8800'),   # < 20 dBHz — weak
    (30, '#ffdd00'),   # < 30 dBHz — marginal
    (40, '#44cc44'),   # < 40 dBHz — good
    (60, '#00ffaa'),   # >= 40 dBHz — excellent
]

# Dimmed variants for satellites not used in fix
BAR_COLOURS_UNUSED = [
    (10, '#661111'),
    (20, '#663300'),
    (30, '#665500'),
    (40, '#225522'),
    (60, '#115544'),
]

CONSTELLATION_COLOUR = {
    'GP': '#44aaff',   # GPS — blue
    'GL': '#ff8844',   # GLONASS — orange
    'GA': '#aa44ff',   # Galileo — purple
    'GB': '#ff4488',   # BeiDou — pink
    'BD': '#ff4488',   # BeiDou alt talker
    'GN': '#ffffff',   # multi
}

CONSTELLATION_LABEL = {
    'GP': 'GPS', 'GL': 'GLO', 'GA': 'GAL',
    'GB': 'BDS', 'BD': 'BDS', 'GN': 'GNS',
}

# ── Shared state ──────────────────────────────────────────────────────────────

_lock = threading.Lock()

_satellites = {}   # prn_str -> {el, az, snr, talker, used}
_active_prns = set()
_status = {
    'device': DEVICE_DEFAULT,
    'connected': False,
    'error': '',
    'last_update': '---',
    'sats_used': 0,
    'sats_seen': 0,
}

# GSV accumulator — keyed by talker ID
_gsv_buf   = {}   # talker -> {prn: {el, az, snr, talker}}
_gsv_total = {}   # talker -> expected message count
_gsv_seq   = {}   # talker -> messages received so far


def _bar_colour(snr, used):
    table = BAR_COLOURS_USED if used else BAR_COLOURS_UNUSED
    for threshold, colour in table:
        if snr < threshold:
            return colour
    return table[-1][1]


# ── NMEA parser thread ────────────────────────────────────────────────────────

def _parse_gsv(msg):
    """Accumulate GSV satellite records; commit when last message arrives."""
    global _gsv_buf, _gsv_total, _gsv_seq

    talker = msg.talker  # 'GP', 'GL', 'GA', 'GB', ...
    try:
        total = int(msg.num_messages)
        seq   = int(msg.msg_num)
    except (ValueError, AttributeError):
        return

    if talker not in _gsv_buf or seq == 1:
        _gsv_buf[talker]   = {}
        _gsv_total[talker] = total
        _gsv_seq[talker]   = 0

    _gsv_seq[talker] = seq

    # Each GSV carries up to 4 satellites in fields sv_prn_num_N etc.
    for i in range(1, 5):
        try:
            prn = getattr(msg, f'sv_prn_num_{i}', None)
            el  = getattr(msg, f'elevation_deg_{i}', None)
            az  = getattr(msg, f'azimuth_{i}', None)
            snr = getattr(msg, f'snr_{i}', None)
            if prn:
                _gsv_buf[talker][str(prn)] = {
                    'el':     int(el)  if el  else None,
                    'az':     int(az)  if az  else None,
                    'snr':    int(snr) if snr else 0,
                    'talker': talker,
                }
        except (ValueError, TypeError, AttributeError):
            pass

    # Commit when all messages for this talker have arrived
    if seq == total:
        with _lock:
            for prn, data in _gsv_buf[talker].items():
                if prn in _satellites:
                    _satellites[prn].update(data)
                else:
                    _satellites[prn] = dict(data, used=False)
        _gsv_buf[talker] = {}


def _parse_gsa(msg):
    """Extract active PRN set from GSA sentence."""
    used = set()
    for i in range(1, 13):
        try:
            prn = getattr(msg, f'sv_{i}', None)
            if prn:
                used.add(str(prn).lstrip('0') or '0')
                used.add(str(prn))
        except AttributeError:
            pass
    with _lock:
        _active_prns.update(used)
        for prn in list(_satellites.keys()):
            _satellites[prn]['used'] = (
                prn in used or prn.lstrip('0') in used
            )


def _reader(device, baud):
    """Background thread: open serial port and parse NMEA forever."""
    while True:
        try:
            with _lock:
                _status['device']    = device
                _status['connected'] = False
                _status['error']     = f'Opening {device}…'

            ser = serial.Serial(device, baud, timeout=2)

            with _lock:
                _status['connected'] = True
                _status['error']     = ''

            while True:
                try:
                    raw = ser.readline().decode('ascii', errors='replace').strip()
                    if not raw.startswith('$'):
                        continue
                    msg = pynmea2.parse(raw)
                    sentence = type(msg).__name__

                    if sentence == 'GSV':
                        _parse_gsv(msg)
                        with _lock:
                            _status['last_update'] = time.strftime('%H:%M:%S')
                            _status['sats_seen']   = len(_satellites)
                            _status['sats_used']   = sum(
                                1 for s in _satellites.values() if s.get('used')
                            )

                    elif sentence == 'GSA':
                        _parse_gsa(msg)

                except pynmea2.ParseError:
                    pass
                except Exception:
                    pass

        except serial.SerialException as e:
            with _lock:
                _status['connected'] = False
                _status['error']     = str(e)
            time.sleep(3)
        except Exception as e:
            with _lock:
                _status['connected'] = False
                _status['error']     = str(e)
            time.sleep(3)


# ── Tkinter GUI ───────────────────────────────────────────────────────────────

BAR_W    = 38    # bar width px
BAR_GAP  = 8     # gap between bars
MARGIN_L = 50    # left margin (Y-axis labels)
MARGIN_R = 12
MARGIN_T = 28    # top margin
MARGIN_B = 48    # bottom margin (PRN labels)
SCALE_MAX = 60   # dBHz full scale
YAXIS_STEP = 10  # grid lines every N dBHz


def _snr_to_colour(snr, used):
    return _bar_colour(snr, used)


class BarsCanvas(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG, highlightthickness=0, **kw)
        self._last_count = 0

    def redraw(self, satellites):
        self.delete('all')
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return

        chart_h = h - MARGIN_T - MARGIN_B
        chart_w = w - MARGIN_L - MARGIN_R

        # Sort satellites: used first, then by SNR descending
        sats = sorted(
            satellites.values(),
            key=lambda s: (not s.get('used', False), -(s.get('snr') or 0))
        )

        # ── Grid lines ────────────────────────────────────────────────────────
        for db in range(0, SCALE_MAX + 1, YAXIS_STEP):
            y = MARGIN_T + chart_h - int(chart_h * db / SCALE_MAX)
            self.create_line(MARGIN_L, y, w - MARGIN_R, y,
                             fill='#1a1a35', width=1)
            self.create_text(MARGIN_L - 6, y, text=str(db),
                             anchor='e', fill=MUTED, font=('monospace', 8))

        # ── Y-axis label ──────────────────────────────────────────────────────
        self.create_text(10, MARGIN_T + chart_h // 2,
                         text='C/N₀\ndBHz', anchor='center',
                         fill=HEADING, font=('monospace', 8), justify='center')

        if not sats:
            self.create_text(w // 2, h // 2,
                             text='Waiting for satellites…',
                             fill=MUTED, font=('monospace', 13))
            return

        # ── Bars ──────────────────────────────────────────────────────────────
        total_w = len(sats) * (BAR_W + BAR_GAP) - BAR_GAP
        x_start = MARGIN_L + max(0, (chart_w - total_w) // 2)

        for i, sat in enumerate(sats):
            prn    = sat.get('prn', '?')
            snr    = sat.get('snr') or 0
            used   = sat.get('used', False)
            talker = sat.get('talker', 'GP')

            x = x_start + i * (BAR_W + BAR_GAP)
            bar_h = int(chart_h * min(snr, SCALE_MAX) / SCALE_MAX)
            y_top = MARGIN_T + chart_h - bar_h
            y_bot = MARGIN_T + chart_h

            colour = _snr_to_colour(snr, used)
            con_col = CONSTELLATION_COLOUR.get(talker, '#aaaaff')

            # Bar body
            self.create_rectangle(x, y_top, x + BAR_W, y_bot,
                                   fill=colour, outline='')

            # Thin bright top edge on used satellites
            if used and bar_h > 2:
                self.create_line(x, y_top, x + BAR_W, y_top,
                                 fill='#ffffff', width=2)

            # SNR value above bar
            if bar_h > 14:
                label_y = y_top + 4
                anchor  = 'n'
            else:
                label_y = y_top - 4
                anchor  = 's'
            if snr > 0:
                self.create_text(x + BAR_W // 2, label_y,
                                 text=str(snr), anchor=anchor,
                                 fill=TEXT, font=('monospace', 8, 'bold'))

            # PRN label below bar
            self.create_text(x + BAR_W // 2, y_bot + 4,
                             text=prn, anchor='n',
                             fill=TEXT if used else MUTED,
                             font=('monospace', 9, 'bold'))

            # Constellation dot above PRN
            self.create_text(x + BAR_W // 2, y_bot + 17,
                             text=CONSTELLATION_LABEL.get(talker, talker),
                             anchor='n', fill=con_col,
                             font=('monospace', 7))


class App(tk.Tk):
    def __init__(self, device, baud):
        super().__init__()
        self.title(TITLE)
        self.configure(bg=BG)
        self.minsize(480, 340)
        self.geometry('900x420')

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=PANEL, pady=6)
        hdr.pack(fill='x')

        tk.Label(hdr, text=TITLE, bg=PANEL, fg=HEADING,
                 font=('monospace', 12, 'bold')).pack(side='left', padx=12)

        self._lbl_status = tk.Label(hdr, text='', bg=PANEL, fg=MUTED,
                                     font=('monospace', 10))
        self._lbl_status.pack(side='right', padx=12)

        # ── Canvas ────────────────────────────────────────────────────────────
        self._canvas = BarsCanvas(self)
        self._canvas.pack(fill='both', expand=True, padx=4, pady=4)

        # ── Status bar ────────────────────────────────────────────────────────
        sb = tk.Frame(self, bg=PANEL, pady=3)
        sb.pack(fill='x')

        self._lbl_dev  = tk.Label(sb, text=device, bg=PANEL, fg=MUTED,
                                   font=('monospace', 9))
        self._lbl_dev.pack(side='left', padx=10)

        self._lbl_time = tk.Label(sb, text='', bg=PANEL, fg=CLOCK,
                                   font=('monospace', 9))
        self._lbl_time.pack(side='right', padx=10)

        self._lbl_sats = tk.Label(sb, text='', bg=PANEL, fg=TEXT,
                                   font=('monospace', 9))
        self._lbl_sats.pack(side='right', padx=10)

        self._update()

    def _update(self):
        with _lock:
            sats  = {k: dict(v, prn=k) for k, v in _satellites.items()}
            st    = dict(_status)

        # Status header
        if st['connected']:
            conn_text = f"● {st['device']}"
            conn_fg   = CLOCK
        else:
            conn_text = f"✗ {st['error'] or st['device']}"
            conn_fg   = ALERT
        self._lbl_status.config(text=conn_text, fg=conn_fg)

        # Satellite counts
        used = st['sats_used']
        seen = st['sats_seen']
        self._lbl_sats.config(
            text=f"Sats: {used} used / {seen} seen",
            fg=CLOCK if used >= 4 else (TEXT if used > 0 else MUTED)
        )
        self._lbl_time.config(text=f"Updated: {st['last_update']}")

        # Redraw bars
        self._canvas.redraw(sats)

        self.after(UPDATE_MS, self._update)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument('--device', default=DEVICE_DEFAULT,
                    help=f'Serial device (default: {DEVICE_DEFAULT})')
    ap.add_argument('--baud',   default=BAUD_DEFAULT, type=int,
                    help=f'Baud rate (default: {BAUD_DEFAULT})')
    args = ap.parse_args()

    _status['device'] = args.device

    t = threading.Thread(target=_reader, args=(args.device, args.baud),
                         daemon=True)
    t.start()

    app = App(args.device, args.baud)
    app.mainloop()


if __name__ == '__main__':
    main()
