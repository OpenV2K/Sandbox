#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: Unlicense
# This is free and unencumbered software released into the public domain.
#
# OpenV2K16.py -- Zero-Crossing Pulse Transmitter
# ================================================
# Requirements:
#   sudo apt install gnuradio gr-osmosdr hackrf python3-pyqt5 espeak-ng
#   pip3 install matplotlib --break-system-packages
# Usage:
#   python3 OpenV2K16.py

import sys
import os
import math
import wave
import signal
import threading
import subprocess
import datetime
import numpy as np

from gnuradio import gr, audio, analog, blocks
from gnuradio import filter as gr_filter
from gnuradio.filter import firdes

try:
    from gnuradio.fft import window as gr_window
    _WIN_HAMMING = gr_window.WIN_HAMMING
except (ImportError, AttributeError):
    _WIN_HAMMING = firdes.WIN_HAMMING

import osmosdr

try:
    from PyQt5 import QtWidgets, QtCore, QtGui
except ImportError:
    sys.exit("PyQt5 required: sudo apt install python3-pyqt5")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    _MPL_OK = True
except ImportError:
    _MPL_OK = False


# =============================================================================
#  HackRF hardware detection  (robust firmware version parsing)
# =============================================================================

def detect_hackrf():
    try:
        result = subprocess.run(
            ['hackrf_info'], capture_output=True, text=True, timeout=5)
        output = result.stdout + result.stderr
        if 'HackRF' in output and result.returncode == 0:
            lines    = output.splitlines()
            firmware = None
            for l in lines:
                ll = l.lower()
                if 'firmware version' in ll and ':' in l:
                    firmware = l.split(':', 1)[1].strip()
                    break
                if 'firmware' in ll and '=' in l:
                    firmware = l.split('=', 1)[1].strip()
                    break
            if firmware is None:
                firmware = 'detected'
            if '(' in firmware:
                firmware = firmware.split('(')[0].strip()
            return True, "HackRF One found\nFW: {}".format(firmware)
        return False, (output.strip().splitlines()[0]
                       if output.strip() else "HackRF not found")
    except FileNotFoundError:
        return False, "hackrf_info not found -- sudo apt install hackrf"
    except subprocess.TimeoutExpired:
        return False, "hackrf_info timed out -- check USB"
    except Exception as e:
        return False, "Detection error: {}".format(e)


# =============================================================================
#  GNU Radio blocks
# =============================================================================

class ZeroCrossPulse(gr.sync_block):
    def __init__(self, sample_rate=48000.0, pulse_width_us=100.0):
        gr.sync_block.__init__(
            self, name="Zero Cross Pulse",
            in_sig=[np.float32], out_sig=[np.float32])
        self._sr = float(sample_rate); self._pw_us = float(pulse_width_us)
        self._last = 0.0; self._rem = 0; self._recompute()

    def set_pulse_width_us(self, v): self._pw_us = float(v); self._recompute()
    def set_sample_rate(self, v):    self._sr    = float(v); self._recompute()

    def _recompute(self):
        self._plen = max(1, int(round(self._sr * self._pw_us * 1e-6)))

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        last, rem, plen = self._last, self._rem, self._plen
        for i in range(len(in0)):
            curr = float(in0[i])
            if (last < 0.0 <= curr) or (last >= 0.0 > curr): rem = plen
            out[i] = 1.0 if rem > 0 else 0.0
            if rem > 0: rem -= 1
            last = curr
        self._last, self._rem = last, rem
        return len(in0)


class SimpleNoiseGate(gr.sync_block):
    def __init__(self, threshold_db=-30.0, window=480):
        gr.sync_block.__init__(self, name="Noise Gate",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False
        self._alpha   = 1.0 / max(1, window)
        self._power   = 0.0
        self.set_threshold_db(threshold_db)

    def set_enabled(self, e):       self._enabled = bool(e)
    def set_threshold_db(self, db): self._thresh  = 10.0 ** (float(db) / 10.0)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled: out[:] = in0; return len(in0)
        alpha, thresh, power = self._alpha, self._thresh, self._power
        for i in range(len(in0)):
            s = float(in0[i])
            power = (1.0 - alpha) * power + alpha * s * s
            out[i] = s if power >= thresh else 0.0
        self._power = power; return len(in0)


# =============================================================================
#  Section Header  (tab-style, draws own full-width top rule)
# =============================================================================

class SectionHeader(QtWidgets.QWidget):
    _PT = 12; _GAP = 7; _ML = 2; _RP = 14

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text
        self._font = QtGui.QFont("Monospace"); self._font.setBold(True)
        self._font.setPointSize(self._PT)
        fm = QtGui.QFontMetrics(self._font)
        self._tw  = fm.horizontalAdvance(text)
        self._th  = fm.height(); self._asc = fm.ascent()
        self.setFixedHeight(self._GAP + self._th + self._GAP + 1)

    def paintEvent(self, event):
        p   = QtGui.QPainter(self)
        w   = self.width()
        lm  = self._ML
        gap = self._GAP
        pen = QtGui.QPen(QtGui.QColor("#888"), 1)
        p.setPen(pen); p.drawLine(0, 0, w, 0)
        p.setFont(self._font)
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(lm, gap + self._asc, self._text)
        line_y  = gap + self._th + gap
        line_x2 = lm + self._tw + self._RP
        p.setPen(pen)
        p.drawLine(lm,      line_y, line_x2, line_y)
        p.drawLine(line_x2, line_y, line_x2, 0)


# =============================================================================
#  Swap Button  (circular, with vertical connector lines)
# =============================================================================

class SwapButton(QtWidgets.QWidget):
    BTN_D = 30; W = 44
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.W)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0); vbox.setSpacing(0)
        vbox.addStretch(1)
        r = self.BTN_D // 2
        self._btn = QtWidgets.QPushButton("<>")
        self._btn.setFixedSize(self.BTN_D, self.BTN_D)
        self._btn.setStyleSheet(
            "QPushButton {{ background-color:#888; color:#2a6ebb;"
            " border-radius:{r}px; font-weight:bold; font-size:9pt;"
            " padding:0px; }}"
            "QPushButton:hover {{ background-color:#aaa; }}".format(r=r))
        self._btn.clicked.connect(self.clicked.emit)
        vbox.addWidget(self._btn, 0, QtCore.Qt.AlignHCenter)
        vbox.addStretch(1)

    def paintEvent(self, event):
        p   = QtGui.QPainter(self)
        pen = QtGui.QPen(QtGui.QColor("#888"), 1)
        p.setPen(pen)
        cx     = self.width() // 2
        mid    = self.height() // 2
        half_d = self.BTN_D // 2
        p.drawLine(cx, 0,            cx, mid - half_d)
        p.drawLine(cx, mid + half_d, cx, self.height())


# =============================================================================
#  Audio level meter
# =============================================================================

class LevelMeter(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0, 2, 0, 2); vbox.setSpacing(1)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 600); self._bar.setValue(0)
        self._bar.setTextVisible(False); self._bar.setFixedHeight(16)
        self._bar.setStyleSheet(
            "QProgressBar { border:1px solid #444; background:#1a1a1a;"
            " border-radius:3px; }"
            "QProgressBar::chunk { background: qlineargradient("
            "  x1:0,y1:0,x2:1,y2:0,"
            "  stop:0.00 #27ae60, stop:0.70 #27ae60,"
            "  stop:0.80 #f39c12, stop:0.90 #f39c12,"
            "  stop:1.00 #e74c3c); border-radius:3px; }")
        vbox.addWidget(self._bar)
        scale = QtWidgets.QHBoxLayout()
        scale.setContentsMargins(0, 0, 0, 0)
        for txt, align in [("-60", QtCore.Qt.AlignLeft),
                            ("-30", QtCore.Qt.AlignCenter),
                            ("0 dB", QtCore.Qt.AlignRight)]:
            lbl = QtWidgets.QLabel(txt)
            lbl.setFont(QtGui.QFont("Monospace", 7))
            lbl.setStyleSheet("color: #777;")
            lbl.setAlignment(align)
            scale.addWidget(lbl)
        vbox.addLayout(scale)
        self._readout = QtWidgets.QLabel("--- dB")
        self._readout.setFont(QtGui.QFont("Monospace", 8))
        self._readout.setAlignment(QtCore.Qt.AlignCenter)
        self._readout.setStyleSheet("color: #999;")
        vbox.addWidget(self._readout)

    def set_level_db(self, db):
        db = max(-60.0, min(0.0, db))
        self._bar.setValue(int((db + 60.0) * 10.0))
        self._readout.setText("{:+.1f} dB".format(db))
        colour = ("#e74c3c" if db > -6.0 else
                  "#f39c12" if db > -18.0 else "#27ae60")
        self._readout.setStyleSheet("color: {};".format(colour))

    def freeze(self):
        """Freeze display at silence when input side is inactive."""
        self.set_level_db(-60.0)


# =============================================================================
#  Labelled slider
# =============================================================================

class LabelledSlider(QtWidgets.QWidget):
    def __init__(self, label, lo, hi, step, default,
                 fmt="{:.0f}", callback=None, tick_steps=10, parent=None):
        super().__init__(parent)
        self._lo = float(lo); self._step = float(step)
        self._fmt = fmt; self._cb = callback
        n_steps = max(1, int(round((hi - lo) / step)))
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(0, n_steps)
        self._slider.setValue(int(round((default - lo) / step)))
        self._slider.setMinimumWidth(180); self._slider.setMaximumWidth(260)
        self._slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._slider.setTickInterval(tick_steps)
        self._readout = QtWidgets.QLabel(fmt.format(default))
        self._readout.setMinimumWidth(62)
        self._readout.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._readout.setFont(QtGui.QFont("Monospace", 8))
        lbl = QtWidgets.QLabel("<b>{}</b>".format(label))
        lbl.setMinimumWidth(80); lbl.setMaximumWidth(90)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        row.addWidget(lbl)
        row.addWidget(self._slider)
        row.addSpacing(20)           # gap between track and readout
        row.addWidget(self._readout)
        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, pos):
        val = self._lo + pos * self._step
        self._readout.setText(self._fmt.format(val))
        if self._cb: self._cb(val)

    def value(self): return self._lo + self._slider.value() * self._step


# =============================================================================
#  Main application
# =============================================================================

class OpenV2K(gr.top_block, QtWidgets.QMainWindow):

    AUDIO_RATE    = 48000
    HACKRF_RATE   = 2000000
    RESAMP_INTERP = 125
    RESAMP_DECIM  = 3
    FREQ_70CM     = 425e6
    FREQ_23CM     = 1300e6
    AMP_1MW       = 0.500
    AMP_2MW       = 0.707
    ESPEAK_WAV    = '/tmp/openv2k_espeak.wav'
    ESPEAK_RAW    = '/tmp/openv2k_espeak_raw.wav'

    _SAVE_DESCRIPTION = (
        "Records raw IQ (complex64).\n"
        "Waterfall: numpy FFT,\n"
        "matplotlib inferno colormap.\n"
        " \n"
        "At 2 MHz: ~16 MB / sec.\n"
        "30 sec capture = ~480 MB.\n"
        "Waterfall image opens\n"
        "automatically on stop.")

    def __init__(self):
        gr.top_block.__init__(self, "OpenV2K", catch_exceptions=True)
        QtWidgets.QMainWindow.__init__(self)
        self.setWindowTitle("OpenV2K (2026/7/23 - Version 16)")
        self.setFixedWidth(580)

        self._hackrf_found, self._hackrf_info = detect_hackrf()
        self._write_silence_wav(self.ESPEAK_WAV)

        self._pulse_us           = 100.0
        self._hpf_hz             = 300.0
        self._lpf_hz             = 3400.0
        self._freq_hz            = self.FREQ_23CM
        self._amplitude          = self.AMP_1MW
        self._muted              = True
        self._recording          = False
        self._record_path        = None
        self._audio_left_active  = False   # eSpeak (right) active by default
        self._output_left_active = False   # Save to Disk (right) active by default

        self._build_gui()
        self._build_blocks()
        self._connect_blocks()

        self._level_timer = QtCore.QTimer()
        self._level_timer.timeout.connect(self._update_displays)
        self._level_timer.start(100)

    # =========================================================================
    #  GUI helpers
    # =========================================================================

    @staticmethod
    def _hline():
        f = QtWidgets.QFrame()
        f.setFrameShape(QtWidgets.QFrame.HLine)
        f.setFrameShadow(QtWidgets.QFrame.Sunken)
        return f

    @staticmethod
    def _vline():
        f = QtWidgets.QFrame()
        f.setFrameShape(QtWidgets.QFrame.VLine)
        f.setFrameShadow(QtWidgets.QFrame.Sunken)
        return f

    @staticmethod
    def _style_green():
        return ("QPushButton { background-color:#27ae60; color:white;"
                " border-radius:4px; font-weight:bold; }"
                "QPushButton:hover { background-color:#2ecc71; }")

    @staticmethod
    def _style_red():
        return ("QPushButton { background-color:#c0392b; color:white;"
                " border-radius:4px; font-weight:bold; }"
                "QPushButton:hover { background-color:#e74c3c; }")

    # =========================================================================
    #  GUI build
    # =========================================================================

    def _build_gui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(0)

        # Title
        title = QtWidgets.QLabel(
            "<h3 style='color:#2a6ebb; margin:0;'>OpenV2K</h3>"
            "<small>Zero-Crossing Pulse Transmitter</small>")
        title.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(title)
        vbox.addSpacing(6)

        # =====================================================================
        # Section 1: Audio Input
        # =====================================================================
        vbox.addWidget(SectionHeader("Audio Input"))
        vbox.addSpacing(2)

        audio_row = QtWidgets.QHBoxLayout()
        audio_row.setSpacing(0)

        # -- Left: Live Microphone (starts DISABLED -- eSpeak is default) -----
        self._mic_panel = QtWidgets.QWidget()
        mic_vbox = QtWidgets.QVBoxLayout(self._mic_panel)
        mic_vbox.setContentsMargins(0, 4, 4, 4)
        mic_vbox.setSpacing(4)

        mic_sub = QtWidgets.QLabel("Live Microphone")
        mic_sub.setStyleSheet("font-size:9pt; color:#666;")
        mic_vbox.addWidget(mic_sub)

        self._btn_mute = QtWidgets.QPushButton("Mic: MUTED")
        self._btn_mute.setCheckable(True)
        self._btn_mute.setChecked(True)
        self._btn_mute.setStyleSheet(self._style_red())
        self._btn_mute.toggled.connect(self._cb_mute)
        mic_vbox.addWidget(self._btn_mute)

        # Compact 2-line label -- same width as button via expanding policy
        meter_lbl = QtWidgets.QLabel(
            "Mic Level: silence -45 dB | voice -18 dB\n"
            "Adjust in System Settings > Sound > Input")
        meter_lbl.setStyleSheet("color: #777; font-size:9px;")
        meter_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred)
        mic_vbox.addWidget(meter_lbl)

        self._level_meter = LevelMeter()
        self._level_meter.freeze()
        mic_vbox.addWidget(self._level_meter)
        mic_vbox.addStretch()

        audio_row.addWidget(self._mic_panel, 1)
        audio_row.addWidget(SwapButton(parent=self))
        self._audio_swap_btn = audio_row.itemAt(
            audio_row.count() - 1).widget()
        self._audio_swap_btn.clicked.connect(self._cb_audio_swap)

        # -- Right: eSpeak TTS (starts ENABLED by default) -------------------
        self._es_panel = QtWidgets.QWidget()
        es_vbox = QtWidgets.QVBoxLayout(self._es_panel)
        es_vbox.setContentsMargins(4, 4, 0, 4)
        es_vbox.setSpacing(0)

        es_title = QtWidgets.QLabel("eSpeak Text To Speech")
        es_title.setStyleSheet("font-weight:bold;")
        es_vbox.addWidget(es_title)
        es_vbox.addSpacing(10)

        self._espeak_input = QtWidgets.QLineEdit()
        self._espeak_input.setPlaceholderText("Hello World")
        es_vbox.addWidget(self._espeak_input)
        es_vbox.addSpacing(10)

        self._btn_generate = QtWidgets.QPushButton("Generate")
        self._btn_generate.setStyleSheet(self._style_green())
        self._btn_generate.clicked.connect(self._cb_generate_espeak)
        es_vbox.addWidget(self._btn_generate)

        self._espeak_status = QtWidgets.QLabel("")
        self._espeak_status.setStyleSheet("color: #777; font-size:9px;")
        self._espeak_status.setWordWrap(True)
        es_vbox.addWidget(self._espeak_status)
        es_vbox.addStretch()

        audio_row.addWidget(self._es_panel, 1)
        vbox.addLayout(audio_row)
        vbox.addSpacing(2)

        # =====================================================================
        # Section 2: Signal Processing (80/20 horizontal split)
        # VLine at 80% -- spans from SectionHeader bottom to output hline
        # =====================================================================
        vbox.addWidget(SectionHeader("Signal Processing"))

        sp_row = QtWidgets.QHBoxLayout()
        sp_row.setSpacing(0)
        sp_row.setContentsMargins(0, 0, 0, 0)

        # -- Left 80%: sliders + optional filters -----------------------------
        left_sp = QtWidgets.QWidget()
        left_vbox = QtWidgets.QVBoxLayout(left_sp)
        left_vbox.setContentsMargins(0, 8, 10, 8)   # 10px right before VLine
        left_vbox.setSpacing(4)

        self._sl_pulse = LabelledSlider(
            "Pulse (us)", 50, 500, 5, self._pulse_us,
            fmt="{:.0f} us", callback=self._cb_pulse, tick_steps=10)
        left_vbox.addWidget(self._sl_pulse)

        self._sl_hpf = LabelledSlider(
            "HPF (Hz)", 250, 1000, 10, self._hpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_hpf, tick_steps=10)
        left_vbox.addWidget(self._sl_hpf)

        self._sl_lpf = LabelledSlider(
            "LPF (Hz)", 1000, 15000, 100, self._lpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_lpf, tick_steps=5)
        left_vbox.addWidget(self._sl_lpf)

        opt_box = QtWidgets.QGroupBox("Optional Filters")
        opt_box.setStyleSheet(
            "QGroupBox { font-size:9pt; } QCheckBox { font-size:9pt; }")
        opt_layout = QtWidgets.QVBoxLayout()
        opt_layout.setSpacing(3)
        self._chk_notch = QtWidgets.QCheckBox(
            "50/60 Hz Mains Notch: removes hum from power lines")
        self._chk_notch.toggled.connect(self._toggle_notch)
        opt_layout.addWidget(self._chk_notch)
        self._chk_preemph = QtWidgets.QCheckBox(
            "Pre-emphasis: +6 dB/oct above 1 kHz, sharpens consonants")
        self._chk_preemph.toggled.connect(self._toggle_preemph)
        opt_layout.addWidget(self._chk_preemph)
        self._chk_noisegate = QtWidgets.QCheckBox(
            "Noise Gate: zeros output below -30 dB")
        self._chk_noisegate.toggled.connect(self._toggle_noisegate)
        opt_layout.addWidget(self._chk_noisegate)
        opt_box.setLayout(opt_layout)
        left_vbox.addWidget(opt_box)
        left_vbox.addStretch()

        sp_row.addWidget(left_sp, 4)   # 80%

        # -- VLine divider at 80% mark ----------------------------------------
        sp_row.addWidget(self._vline())

        # -- Right 20%: vertical duty cycle meter -----------------------------
        dc_panel = QtWidgets.QWidget()
        dc_vbox  = QtWidgets.QVBoxLayout(dc_panel)
        dc_vbox.setContentsMargins(10, 8, 4, 8)   # 10px left after VLine
        dc_vbox.setSpacing(4)

        # Percentage readout at top
        self._dc_readout = QtWidgets.QLabel("--.-%")
        self._dc_readout.setFont(QtGui.QFont("Monospace", 8))
        self._dc_readout.setAlignment(QtCore.Qt.AlignCenter)
        self._dc_readout.setStyleSheet("color: #ccc;")
        dc_vbox.addWidget(self._dc_readout)

        # Vertical progress bar (fills bottom to top)
        self._dc_vbar = QtWidgets.QProgressBar()
        self._dc_vbar.setOrientation(QtCore.Qt.Vertical)
        self._dc_vbar.setRange(0, 1000)   # 0.0% to 10.0%
        self._dc_vbar.setValue(0)
        self._dc_vbar.setTextVisible(False)
        self._dc_vbar.setStyleSheet(
            "QProgressBar { border:1px solid #444; background:#1a1a1a;"
            " border-radius:3px; }"
            "QProgressBar::chunk { background: qlineargradient("
            "  x1:0, y1:1, x2:0, y2:0,"   # bottom (y=1) to top (y=0)
            "  stop:0.00 #27ae60,"           # green  -- low duty (good)
            "  stop:0.55 #27ae60,"
            "  stop:0.60 #f39c12,"           # amber  -- near amp limit (6%)
            "  stop:0.70 #f39c12,"
            "  stop:0.80 #e74c3c,"           # red    -- over amp spec
            "  stop:1.00 #e74c3c"
            "); border-radius:3px; }")
        dc_vbox.addWidget(self._dc_vbar, 1)   # expand to fill height

        # Label at bottom
        dc_lbl = QtWidgets.QLabel("Pulse\nDuty\nCycle")
        dc_lbl.setFont(QtGui.QFont("Monospace", 7))
        dc_lbl.setStyleSheet("color: #777;")
        dc_lbl.setAlignment(QtCore.Qt.AlignCenter)
        dc_vbox.addWidget(dc_lbl)

        sp_row.addWidget(dc_panel, 1)   # 20%
        vbox.addLayout(sp_row)

        # =====================================================================
        # Section 3: SDR Output  (hline only, no section label)
        # =====================================================================
        vbox.addWidget(self._hline())
        vbox.addSpacing(2)

        output_row = QtWidgets.QHBoxLayout()
        output_row.setSpacing(0)

        # -- Left: HackRF Transmitter (starts DISABLED) -----------------------
        self._tx_panel = QtWidgets.QWidget()
        tx_vbox = QtWidgets.QVBoxLayout(self._tx_panel)
        tx_vbox.setContentsMargins(0, 4, 4, 4)
        tx_vbox.setSpacing(4)

        hdr_row = QtWidgets.QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        tx_hdr = QtWidgets.QLabel(
            "<b>Transmitter</b><br>"
            "<span style='font-size:10px; color:#777;'>HackRF SDR Output</span>")
        hdr_row.addWidget(tx_hdr)
        self._hw_lbl = QtWidgets.QLabel(self._hackrf_info)
        self._hw_lbl.setFont(QtGui.QFont("Monospace", 7))
        self._hw_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._hw_lbl.setStyleSheet(
            "color: #27ae60;" if self._hackrf_found else "color: #e74c3c;")
        hdr_row.addWidget(self._hw_lbl)
        tx_vbox.addLayout(hdr_row)

        freq_lbl = QtWidgets.QLabel("Frequency:")
        freq_lbl.setStyleSheet("font-size:9pt; color:#777;")
        tx_vbox.addWidget(freq_lbl)
        self._freq_combo = QtWidgets.QComboBox()
        self._freq_combo.addItem("425 MHz  (70cm)", self.FREQ_70CM)
        self._freq_combo.addItem("1300 MHz (23cm)", self.FREQ_23CM)
        self._freq_combo.setCurrentIndex(1)
        self._freq_combo.currentIndexChanged.connect(self._cb_freq_combo)
        tx_vbox.addWidget(self._freq_combo)

        pwr_lbl = QtWidgets.QLabel("TX Power (relative):")
        pwr_lbl.setStyleSheet("font-size:9pt; color:#777;")
        tx_vbox.addWidget(pwr_lbl)
        self._pwr_combo = QtWidgets.QComboBox()
        self._pwr_combo.addItem("1 mW", self.AMP_1MW)
        self._pwr_combo.addItem("2 mW", self.AMP_2MW)
        self._pwr_combo.currentIndexChanged.connect(self._cb_pwr_combo)
        tx_vbox.addWidget(self._pwr_combo)

        tx_vbox.addSpacing(12)
        self._btn_tx = QtWidgets.QPushButton("TX: DISABLED")
        self._btn_tx.setCheckable(True)
        self._btn_tx.setChecked(True)
        self._btn_tx.setStyleSheet(self._style_red())
        self._btn_tx.toggled.connect(self._cb_tx_toggle)
        tx_vbox.addWidget(self._btn_tx)
        tx_vbox.addStretch()

        output_row.addWidget(self._tx_panel, 1)

        # -- Swap button (output) ---------------------------------------------
        out_swap = SwapButton(parent=self)
        out_swap.clicked.connect(self._cb_output_swap)
        output_row.addWidget(out_swap)

        # -- Right: Save to Disk (starts ENABLED by default) -----------------
        self._save_panel = QtWidgets.QWidget()
        save_vbox = QtWidgets.QVBoxLayout(self._save_panel)
        save_vbox.setContentsMargins(4, 4, 0, 4)
        save_vbox.setSpacing(4)

        save_hdr = QtWidgets.QLabel("Save to Disk")
        save_hdr.setStyleSheet("font-weight:bold;")
        save_vbox.addWidget(save_hdr)

        self._save_path_lbl = QtWidgets.QLabel(self._SAVE_DESCRIPTION)
        self._save_path_lbl.setStyleSheet("color: #777; font-size:9px;")
        self._save_path_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred)
        save_vbox.addWidget(self._save_path_lbl)

        self._btn_record = QtWidgets.QPushButton("Record IQ")
        self._btn_record.setCheckable(True)
        self._btn_record.setChecked(False)
        self._btn_record.setStyleSheet(self._style_green())
        self._btn_record.toggled.connect(self._cb_record_toggle)
        save_vbox.addWidget(self._btn_record)

        self._chk_waterfall = QtWidgets.QCheckBox("Generate Waterfall Image")
        self._chk_waterfall.setChecked(True)
        if not _MPL_OK:
            self._chk_waterfall.setEnabled(False)
            self._chk_waterfall.setText("Waterfall (pip3 install matplotlib)")
        save_vbox.addWidget(self._chk_waterfall)

        self._waterfall_status = QtWidgets.QLabel("")
        self._waterfall_status.setStyleSheet("color: #777; font-size:9px;")
        self._waterfall_status.setWordWrap(True)
        save_vbox.addWidget(self._waterfall_status)
        save_vbox.addStretch()

        output_row.addWidget(self._save_panel, 1)
        vbox.addLayout(output_row)
        vbox.addSpacing(8)

        # =====================================================================
        # Apply initial disabled states:
        #   Input  -> eSpeak active, mic panel disabled
        #   Output -> Save to Disk active, HackRF panel disabled + TX frozen
        # =====================================================================
        self._mic_panel.setEnabled(False)
        self._tx_panel.setEnabled(False)

    # =========================================================================
    #  GNU Radio blocks
    # =========================================================================

    def _build_blocks(self):
        sr = self.AUDIO_RATE
        self.audio_src   = audio.source(sr, "", True)
        self.espeak_src  = blocks.wavfile_source(self.ESPEAK_WAV, True)

        # eSpeak active by default; mic silent
        self.mic_gate    = blocks.multiply_const_ff(0.0)
        self.espeak_gate = blocks.multiply_const_ff(1.0)
        self.src_adder   = blocks.add_ff(1)

        self.level_probe = analog.probe_avg_mag_sqrd_f(0, 1e-3)
        self.mute_gate   = blocks.multiply_const_ff(0.0)

        self.dc_blocker  = gr_filter.iir_filter_ffd(
            [1.0, -1.0], [-0.999], True)

        _f0 = 60.0; _Q = 30.0
        _w0 = 2.0 * math.pi * _f0 / float(sr)
        _al = math.sin(_w0) / (2.0 * _Q)
        _cw = math.cos(_w0); _a0 = 1.0 + _al
        self._notch_b = [1.0/_a0, -2.0*_cw/_a0, 1.0/_a0]
        self._notch_a = [-2.0*_cw/_a0, (1.0-_al)/_a0]
        self.notch      = gr_filter.iir_filter_ffd([1.0], [0.0], True)
        self.pre_emph   = gr_filter.fir_filter_fff(1, [1.0])
        self.noise_gate = SimpleNoiseGate(threshold_db=-30.0, window=480)

        self.hpf = gr_filter.fir_filter_fff(
            1, firdes.high_pass(1, sr, self._hpf_hz, 50, _WIN_HAMMING, 6.76))
        self.lpf = gr_filter.fir_filter_fff(
            1, firdes.low_pass(1, sr, self._lpf_hz, 200, _WIN_HAMMING, 6.76))

        self.agc = analog.agc_ff(1e-4, 0.5, 1.0)
        self.agc.set_max_gain(65536)

        self.zcp       = ZeroCrossPulse(sr, self._pulse_us)
        self.dc_probe  = analog.probe_avg_mag_sqrd_f(0, 2e-5)
        self.mult      = blocks.multiply_const_ff(self._amplitude)

        self.resampler = gr_filter.rational_resampler_fff(
            interpolation=self.RESAMP_INTERP,
            decimation=self.RESAMP_DECIM,
            taps=[], fractional_bw=0.0)

        self.null_src    = blocks.null_source(gr.sizeof_float)
        self.f2c         = blocks.float_to_complex(1)
        self.tx_gate     = blocks.multiply_const_cc((0+0j))
        self.iq_recorder = blocks.null_sink(gr.sizeof_gr_complex)

        if self._hackrf_found:
            self.hackrf = osmosdr.sink(args="numchan=1 hackrf=0")
            self.hackrf.set_sample_rate(self.HACKRF_RATE)
            self.hackrf.set_center_freq(self._freq_hz, 0)
            self.hackrf.set_freq_corr(0, 0)
            self.hackrf.set_gain(0, 0)
            self.hackrf.set_if_gain(40, 0)
            self.hackrf.set_bb_gain(20, 0)
            self.hackrf.set_antenna("", 0)
            self.hackrf.set_bandwidth(0, 0)
        else:
            self.hackrf = blocks.null_sink(gr.sizeof_gr_complex)

    def _connect_blocks(self):
        self.connect(self.audio_src,  self.mic_gate)
        self.connect(self.espeak_src, self.espeak_gate)
        self.connect(self.mic_gate,   (self.src_adder, 0))
        self.connect(self.espeak_gate,(self.src_adder, 1))
        self.connect(self.audio_src,  self.level_probe)
        self.connect(self.src_adder,  self.mute_gate)
        self.connect(self.mute_gate,  self.dc_blocker)
        self.connect(self.dc_blocker, self.notch)
        self.connect(self.notch,      self.hpf)
        self.connect(self.hpf,        self.lpf)
        self.connect(self.lpf,        self.pre_emph)
        self.connect(self.pre_emph,   self.agc)
        self.connect(self.agc,        self.noise_gate)
        self.connect(self.noise_gate, self.zcp)
        self.connect(self.zcp,        self.mult)
        self.connect(self.zcp,        self.dc_probe)
        self.connect(self.mult,       self.resampler)
        self.connect(self.resampler,  (self.f2c, 0))
        self.connect(self.null_src,   (self.f2c, 1))
        self.connect(self.f2c,        self.tx_gate)
        self.connect(self.f2c,        self.iq_recorder)
        self.connect(self.tx_gate,    self.hackrf)

    # =========================================================================
    #  Display update (10 Hz)
    # =========================================================================

    def _update_displays(self):
        # Level meter: only live when mic panel is active
        if self._audio_left_active:
            mag_sq = self.level_probe.level()
            db = 10.0 * math.log10(mag_sq) if mag_sq > 1e-12 else -60.0
            self._level_meter.set_level_db(db)

        # Vertical duty cycle meter
        dc_pct = self.dc_probe.level() * 100.0
        self._dc_vbar.setValue(int(min(1000, max(0, dc_pct * 100))))
        self._dc_readout.setText("{:4.1f}%".format(max(0.0, dc_pct)))

    # =========================================================================
    #  Slider callbacks
    # =========================================================================

    def _cb_pulse(self, v): self._pulse_us = v; self.zcp.set_pulse_width_us(v)

    def _cb_hpf(self, v):
        self._hpf_hz = v
        self.hpf.set_taps(firdes.high_pass(
            1, self.AUDIO_RATE, v, 50, _WIN_HAMMING, 6.76))

    def _cb_lpf(self, v):
        self._lpf_hz = v
        self.lpf.set_taps(firdes.low_pass(
            1, self.AUDIO_RATE, v, 200, _WIN_HAMMING, 6.76))

    # =========================================================================
    #  Filter toggles
    # =========================================================================

    def _toggle_notch(self, e):
        self.notch.set_taps(self._notch_b if e else [1.0],
                            self._notch_a if e else [0.0])

    def _toggle_preemph(self, e):
        self.pre_emph.set_taps([1.0, -0.9375] if e else [1.0])

    def _toggle_noisegate(self, e):
        self.noise_gate.set_enabled(e)

    # =========================================================================
    #  Swap callbacks
    # =========================================================================

    def _cb_audio_swap(self):
        self._audio_left_active = not self._audio_left_active
        if self._audio_left_active:
            self._mic_panel.setEnabled(True)
            self._es_panel.setEnabled(False)
            self.mic_gate.set_k(1.0)
            self.espeak_gate.set_k(0.0)
            muted = self._btn_mute.isChecked()
            self.mute_gate.set_k(0.0 if muted else 1.0)
        else:
            self._mic_panel.setEnabled(False)
            self._es_panel.setEnabled(True)
            self.mic_gate.set_k(0.0)
            self.espeak_gate.set_k(1.0)
            self._level_meter.freeze()

    def _cb_output_swap(self):
        self._output_left_active = not self._output_left_active
        if self._output_left_active:
            # Switching TO HackRF TX -- re-detect hardware
            self._hw_lbl.setText("Detecting HackRF...")
            QtWidgets.QApplication.processEvents()
            found, info = detect_hackrf()
            self._hackrf_found = found
            self._hw_lbl.setText(info)
            self._hw_lbl.setStyleSheet(
                "color: #27ae60;" if found else "color: #e74c3c;")
            self._tx_panel.setEnabled(True)
            self._save_panel.setEnabled(False)
        else:
            # Switching TO Save to Disk -- force TX off and grey HackRF panel
            self.tx_gate.set_k((0+0j))
            if not self._btn_tx.isChecked():
                self._btn_tx.setChecked(True)
            self._tx_panel.setEnabled(False)
            self._save_panel.setEnabled(True)

    # =========================================================================
    #  SDR toggle callbacks
    # =========================================================================

    def _cb_freq_combo(self, idx):
        self._freq_hz = self._freq_combo.itemData(idx)
        if self._hackrf_found:
            self.hackrf.set_center_freq(self._freq_hz, 0)

    def _cb_pwr_combo(self, idx):
        self._amplitude = self._pwr_combo.itemData(idx)
        self.mult.set_k(self._amplitude)

    def _cb_mute(self, muted):
        self._muted = muted
        self.mute_gate.set_k(0.0 if muted else 1.0)
        self._btn_mute.setText("Mic: MUTED" if muted else "Mic: LIVE")
        self._btn_mute.setStyleSheet(
            self._style_red() if muted else self._style_green())

    def _cb_tx_toggle(self, disabled):
        if disabled:
            self.tx_gate.set_k((0+0j))
            self._btn_tx.setText("TX: DISABLED")
            self._btn_tx.setStyleSheet(self._style_red())
        else:
            self.tx_gate.set_k((1+0j))
            self._btn_tx.setText("TX: ENABLED")
            self._btn_tx.setStyleSheet(self._style_green())

    # =========================================================================
    #  eSpeak TTS
    # =========================================================================

    def _cb_generate_espeak(self):
        text = self._espeak_input.text().strip() or "Hello World"
        self._espeak_status.setText("Generating...")
        QtWidgets.QApplication.processEvents()

        cmd_found = None
        for cmd in ['espeak-ng', 'espeak']:
            try:
                r = subprocess.run([cmd, '--version'],
                                   capture_output=True, timeout=3)
                if r.returncode == 0: cmd_found = cmd; break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        if cmd_found is None:
            self._espeak_status.setText("Not found: sudo apt install espeak-ng")
            return

        r = subprocess.run(
            [cmd_found, '-w', self.ESPEAK_RAW, text],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            self._espeak_status.setText(
                "eSpeak error: {}".format(r.stderr.strip()[:60]))
            return

        try:
            with wave.open(self.ESPEAK_RAW, 'r') as wf:
                sr_in = wf.getframerate(); n_ch = wf.getnchannels()
                raw_bytes = wf.readframes(wf.getnframes())
        except Exception as e:
            self._espeak_status.setText("WAV error: {}".format(e)); return

        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        samples /= 32768.0
        if n_ch > 1: samples = samples.reshape(-1, n_ch).mean(axis=1)
        if sr_in != self.AUDIO_RATE:
            new_len = int(round(len(samples) * self.AUDIO_RATE / sr_in))
            samples = np.interp(
                np.linspace(0, len(samples)-1, new_len),
                np.arange(len(samples)), samples).astype(np.float32)

        self._write_samples_wav(self.ESPEAK_WAV, samples, self.AUDIO_RATE)

        self.lock()
        self.disconnect(self.espeak_src, self.espeak_gate)
        self.espeak_src = blocks.wavfile_source(self.ESPEAK_WAV, True)
        self.connect(self.espeak_src, self.espeak_gate)
        self.unlock()

        self.espeak_gate.set_k(1.0)
        self.mic_gate.set_k(0.0)
        self.mute_gate.set_k(1.0)   # auto-unmute on Generate

        self._espeak_status.setText(
            "Playing: \"{}\"".format(
                text[:34] + ("..." if len(text) > 34 else "")))

    # =========================================================================
    #  IQ recording and waterfall
    # =========================================================================

    def _cb_record_toggle(self, recording):
        if recording:
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            self._record_path = os.path.expanduser(
                '~/openvk2_{}.iq'.format(stamp))
            self.lock()
            self.disconnect(self.f2c, self.iq_recorder)
            self.iq_recorder = blocks.file_sink(
                gr.sizeof_gr_complex, self._record_path)
            self.connect(self.f2c, self.iq_recorder)
            self.unlock()
            self._btn_record.setText("Recording...")
            self._btn_record.setStyleSheet(self._style_red())
            self._save_path_lbl.setText(
                os.path.basename(self._record_path))
        else:
            self.lock()
            self.disconnect(self.f2c, self.iq_recorder)
            self.iq_recorder = blocks.null_sink(gr.sizeof_gr_complex)
            self.connect(self.f2c, self.iq_recorder)
            self.unlock()
            self._btn_record.setText("Record IQ")
            self._btn_record.setStyleSheet(self._style_green())
            self._save_path_lbl.setText(self._SAVE_DESCRIPTION)
            if (self._chk_waterfall.isChecked()
                    and self._record_path and _MPL_OK):
                self._waterfall_status.setText("Generating waterfall...")
                QtWidgets.QApplication.processEvents()
                t = threading.Thread(
                    target=self._generate_waterfall,
                    args=(self._record_path,), daemon=True)
                t.start()

    def _generate_waterfall(self, iq_path):
        try:
            data = np.fromfile(iq_path, dtype=np.complex64)
            if len(data) < 1024:
                self._set_wf_status("Recording too short"); return
            fft_size = 1024; hop = 512
            window   = np.hanning(fft_size).astype(np.float32)
            n_frames = (len(data) - fft_size) // hop
            spec     = np.zeros((n_frames, fft_size), dtype=np.float32)
            for i in range(n_frames):
                frame   = data[i*hop : i*hop+fft_size]
                spec[i] = 10.0 * np.log10(
                    np.fft.fftshift(
                        np.abs(np.fft.fft(frame * window))**2) + 1e-10)
            sr = self.HACKRF_RATE; dur = n_frames * hop / sr
            fig, ax = plt.subplots(figsize=(12, 5))
            ax.imshow(spec.T, aspect='auto', origin='lower',
                      extent=[-sr/2/1e6, sr/2/1e6, 0, dur], cmap='inferno')
            ax.set_xlabel('Frequency offset (MHz)'); ax.set_ylabel('Time (s)')
            ax.set_title('OpenV2K Waterfall -- {}'.format(
                os.path.basename(iq_path)))
            plt.colorbar(ax.images[0], ax=ax, label='Power (dB)')
            plt.tight_layout()
            png_path = iq_path.replace('.iq', '.png')
            plt.savefig(png_path, dpi=150); plt.close(fig)
            subprocess.Popen(['xdg-open', png_path])
            self._set_wf_status("Saved: {}".format(
                os.path.basename(png_path)))
        except Exception as e:
            self._set_wf_status("Error: {}".format(e))

    def _set_wf_status(self, text):
        QtCore.QMetaObject.invokeMethod(
            self._waterfall_status, "setText",
            QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, text))

    # =========================================================================
    #  WAV helpers
    # =========================================================================

    def _write_silence_wav(self, path):
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(self.AUDIO_RATE)
            wf.writeframes(
                np.zeros(self.AUDIO_RATE, dtype=np.int16).tobytes())

    def _write_samples_wav(self, path, samples, sr):
        s16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(sr); wf.writeframes(s16.tobytes())

    def closeEvent(self, event):
        self._level_timer.stop(); self.stop(); self.wait(); event.accept()


# =============================================================================
#  Entry point
# =============================================================================

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("OpenV2K")
    tb = OpenV2K(); tb.show(); tb.start()

    def _quit(sig=None, frame=None):
        tb.stop(); tb.wait(); app.quit()

    signal.signal(signal.SIGINT,  _quit)
    signal.signal(signal.SIGTERM, _quit)
    tick = QtCore.QTimer()
    tick.start(200); tick.timeout.connect(lambda: None)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
