#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: Unlicense
# This is free and unencumbered software released into the public domain.
#
# OpenV2K.py -- Voice Zero-Crossing Pulse Transmitter
# =================================================
# Requirements:
#   sudo apt install gnuradio gr-osmosdr hackrf python3-pyqt5 espeak-ng
#   pip3 install matplotlib --break-system-packages   (for waterfall)
# Usage:
#   python3 OpenV2K.py

import sys
import os
import math
import wave
import struct
import signal
import threading
import subprocess
import datetime
import numpy as np

# -- GNU Radio imports --------------------------------------------------------
from gnuradio import gr, audio, analog, blocks
from gnuradio import filter as gr_filter
from gnuradio.filter import firdes

try:
    from gnuradio.fft import window as gr_window
    _WIN_HAMMING = gr_window.WIN_HAMMING
except (ImportError, AttributeError):
    _WIN_HAMMING = firdes.WIN_HAMMING

import osmosdr

# -- Qt imports ---------------------------------------------------------------
try:
    from PyQt5 import QtWidgets, QtCore, QtGui
except ImportError:
    sys.exit("PyQt5 required: sudo apt install python3-pyqt5")

# -- Optional: matplotlib for waterfall generation ----------------------------
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    _MPL_OK = True
except ImportError:
    _MPL_OK = False


# =============================================================================
#  HackRF hardware detection
# =============================================================================

def detect_hackrf():
    """Run hackrf_info; return (found: bool, info_string: str)."""
    try:
        result = subprocess.run(
            ['hackrf_info'], capture_output=True, text=True, timeout=5)
        output = result.stdout + result.stderr
        if 'HackRF' in output and result.returncode == 0:
            lines = output.splitlines()
            firmware = next(
                (l.split(': ', 1)[1].strip() for l in lines
                 if 'Firmware Version' in l), 'unknown')
            return True, "HackRF One found\nFW: {}".format(firmware)
        return False, (output.strip().splitlines()[0]
                       if output.strip() else "HackRF not found")
    except FileNotFoundError:
        return False, "hackrf_info not found -- sudo apt install hackrf"
    except subprocess.TimeoutExpired:
        return False, "hackrf_info timed out -- check USB connection"
    except Exception as e:
        return False, "Detection error: {}".format(e)


# =============================================================================
#  Zero-Crossing Pulse Generator (GNU Radio sync block)
# =============================================================================

class ZeroCrossPulse(gr.sync_block):
    """Emits a 1.0 pulse of pulse_width_us microseconds on every
    zero-crossing (rising AND falling) of a float32 audio stream."""

    def __init__(self, sample_rate=48000.0, pulse_width_us=100.0):
        gr.sync_block.__init__(
            self, name="Zero Cross Pulse",
            in_sig=[np.float32], out_sig=[np.float32])
        self._sr    = float(sample_rate)
        self._pw_us = float(pulse_width_us)
        self._last  = 0.0
        self._rem   = 0
        self._recompute()

    def set_pulse_width_us(self, v):
        self._pw_us = float(v); self._recompute()

    def set_sample_rate(self, v):
        self._sr = float(v); self._recompute()

    def _recompute(self):
        self._plen = max(1, int(round(self._sr * self._pw_us * 1e-6)))

    def work(self, input_items, output_items):
        in0, out        = input_items[0], output_items[0]
        last, rem, plen = self._last, self._rem, self._plen
        for i in range(len(in0)):
            curr = float(in0[i])
            if (last < 0.0 <= curr) or (last >= 0.0 > curr):
                rem = plen
            out[i] = 1.0 if rem > 0 else 0.0
            if rem > 0:
                rem -= 1
            last = curr
        self._last, self._rem = last, rem
        return len(in0)


# =============================================================================
#  Simple Noise Gate (GNU Radio sync block)
# =============================================================================

class SimpleNoiseGate(gr.sync_block):
    """Gates the stream when short-term power falls below threshold_db."""

    def __init__(self, threshold_db=-30.0, window=480):
        gr.sync_block.__init__(self, name="Noise Gate",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False
        self._alpha   = 1.0 / max(1, window)
        self._power   = 0.0
        self.set_threshold_db(threshold_db)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)

    def set_threshold_db(self, db):
        self._thresh = 10.0 ** (float(db) / 10.0)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0
            return len(in0)
        alpha, thresh, power = self._alpha, self._thresh, self._power
        for i in range(len(in0)):
            s = float(in0[i])
            power = (1.0 - alpha) * power + alpha * s * s
            out[i] = s if power >= thresh else 0.0
        self._power = power
        return len(in0)


# =============================================================================
#  Audio level meter widget
# =============================================================================

class LevelMeter(QtWidgets.QWidget):
    """Horizontal dB VU meter. Call set_level_db(db) to update."""

    def __init__(self, parent=None):
        super().__init__(parent)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0, 2, 0, 2)
        vbox.setSpacing(1)

        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 600)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(16)
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

        self._readout = QtWidgets.QLabel("---  dB")
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


# =============================================================================
#  Labelled slider with tick marks
# =============================================================================

class LabelledSlider(QtWidgets.QWidget):
    """Compact horizontal slider with label, ticks, and readout."""

    def __init__(self, label, lo, hi, step, default,
                 fmt="{:.0f}", callback=None, tick_steps=10, parent=None):
        super().__init__(parent)
        self._lo   = float(lo)
        self._step = float(step)
        self._fmt  = fmt
        self._cb   = callback

        n_steps = max(1, int(round((hi - lo) / step)))

        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(0, n_steps)
        self._slider.setValue(int(round((default - lo) / step)))
        self._slider.setMinimumWidth(140)
        self._slider.setMaximumWidth(200)
        self._slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._slider.setTickInterval(tick_steps)

        self._readout = QtWidgets.QLabel(fmt.format(default))
        self._readout.setMinimumWidth(68)
        self._readout.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._readout.setFont(QtGui.QFont("Monospace", 8))

        lbl = QtWidgets.QLabel("<b>{}</b>".format(label))
        lbl.setMinimumWidth(88)
        lbl.setMaximumWidth(96)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(lbl)
        row.addWidget(self._slider)
        row.addWidget(self._readout)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, pos):
        val = self._lo + pos * self._step
        self._readout.setText(self._fmt.format(val))
        if self._cb:
            self._cb(val)

    def value(self):
        return self._lo + self._slider.value() * self._step


# =============================================================================
#  Top Block (GNU Radio flow graph + Qt main window)
# =============================================================================

class OpenV2K(gr.top_block, QtWidgets.QMainWindow):

    # -- Constants ------------------------------------------------------------
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

    def __init__(self):
        gr.top_block.__init__(self, "OpenV2K", catch_exceptions=True)
        QtWidgets.QMainWindow.__init__(self)

        self.setWindowTitle("OpenV2K (2026/7/23 - Version 13)")
        self.setFixedWidth(580)

        # -- Detect HackRF ----------------------------------------------------
        self._hackrf_found, self._hackrf_info = detect_hackrf()

        # -- Create initial silence WAV for eSpeak source ---------------------
        self._write_silence_wav(self.ESPEAK_WAV)

        # -- Runtime state (starts muted and TX disabled) ---------------------
        self._pulse_us    = 100.0
        self._hpf_hz      = 300.0
        self._lpf_hz      = 3400.0
        self._freq_hz     = self.FREQ_23CM
        self._amplitude   = self.AMP_1MW
        self._muted       = True
        self._tx_enabled  = False
        self._recording   = False
        self._record_path = None

        self._build_gui()
        self._build_blocks()
        self._connect_blocks()

        # -- Level meter / duty cycle polling (10 Hz) -------------------------
        self._level_timer = QtCore.QTimer()
        self._level_timer.timeout.connect(self._update_displays)
        self._level_timer.start(100)

    # =========================================================================
    #  GUI helpers
    # =========================================================================

    def _section_header(self, text):
        """Bold monospace section header label."""
        lbl = QtWidgets.QLabel(text)
        font = QtGui.QFont("Monospace")
        font.setBold(True)
        font.setPointSize(10)
        lbl.setFont(font)
        return lbl

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
        vbox.setContentsMargins(12, 12, 12, 17)   # +5 px at bottom
        vbox.setSpacing(8)

        # Title
        title = QtWidgets.QLabel(
            "<h3 style='color:#2a6ebb; margin:0;'>OpenV2K</h3>"
            "<small>Zero-Crossing Pulse Transmitter</small>")
        title.setAlignment(QtCore.Qt.AlignCenter)
        vbox.addWidget(title)
        vbox.addWidget(self._hline())

        # =====================================================================
        # Section 1: Audio Input
        # =====================================================================
        vbox.addWidget(self._section_header("Audio Input"))

        audio_row = QtWidgets.QHBoxLayout()
        audio_row.setSpacing(0)

        # -- Left panel: Microphone -------------------------------------------
        mic_panel = QtWidgets.QWidget()
        mic_vbox  = QtWidgets.QVBoxLayout(mic_panel)
        mic_vbox.setContentsMargins(0, 4, 8, 4)
        mic_vbox.setSpacing(4)

        self._btn_mute = QtWidgets.QPushButton("Mic: MUTED")
        self._btn_mute.setCheckable(True)
        self._btn_mute.setChecked(True)
        self._btn_mute.setStyleSheet(self._style_red())
        self._btn_mute.toggled.connect(self._cb_mute)
        mic_vbox.addWidget(self._btn_mute)

        meter_lbl = QtWidgets.QLabel(
            "Mic Input Level:\n"
            "Silence: -45 dB or lower\n"
            "Speaking: aim for -18 dB\n"
            "OS: Settings > Sound > Input")
        meter_lbl.setStyleSheet("color: #777; font-size: 9px;")
        mic_vbox.addWidget(meter_lbl)

        self._level_meter = LevelMeter()
        mic_vbox.addWidget(self._level_meter)
        mic_vbox.addStretch()

        audio_row.addWidget(mic_panel, 1)
        audio_row.addWidget(self._vline())

        # -- Right panel: eSpeak TTS ------------------------------------------
        es_panel = QtWidgets.QWidget()
        es_vbox  = QtWidgets.QVBoxLayout(es_panel)
        es_vbox.setContentsMargins(8, 4, 0, 4)
        es_vbox.setSpacing(4)

        es_title = QtWidgets.QLabel("eSpeak Text To Speech")
        es_title.setStyleSheet("font-weight: bold;")
        es_vbox.addWidget(es_title)

        self._espeak_input = QtWidgets.QLineEdit()
        self._espeak_input.setPlaceholderText("Hello World")
        es_vbox.addWidget(self._espeak_input)

        self._btn_generate = QtWidgets.QPushButton("Generate")
        self._btn_generate.setStyleSheet(self._style_green())
        self._btn_generate.clicked.connect(self._cb_generate_espeak)
        es_vbox.addWidget(self._btn_generate)

        self._espeak_status = QtWidgets.QLabel("Ready")
        self._espeak_status.setStyleSheet("color: #777; font-size: 9px;")
        self._espeak_status.setWordWrap(True)
        es_vbox.addWidget(self._espeak_status)
        es_vbox.addStretch()

        audio_row.addWidget(es_panel, 1)
        vbox.addLayout(audio_row)
        vbox.addWidget(self._hline())

        # =====================================================================
        # Section 2: Signal Processing
        # =====================================================================
        vbox.addWidget(self._section_header("Signal Processing"))
        vbox.addSpacing(5)      # +5 px under this header only

        self._sl_pulse = LabelledSlider(
            "Pulse (us)", 50, 500, 5, self._pulse_us,
            fmt="{:.0f} us", callback=self._cb_pulse, tick_steps=10)
        vbox.addWidget(self._sl_pulse)

        self._sl_hpf = LabelledSlider(
            "HPF (Hz)", 250, 1000, 10, self._hpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_hpf, tick_steps=10)
        vbox.addWidget(self._sl_hpf)

        self._sl_lpf = LabelledSlider(
            "LPF (Hz)", 1000, 15000, 100, self._lpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_lpf, tick_steps=5)
        vbox.addWidget(self._sl_lpf)

        # Optional filters
        opt_box = QtWidgets.QGroupBox("Optional Filters")
        opt_box.setStyleSheet(
            "QGroupBox { font-size:9pt; }"
            "QCheckBox  { font-size:9pt; }")
        opt_layout = QtWidgets.QVBoxLayout()
        opt_layout.setSpacing(4)

        self._chk_notch = QtWidgets.QCheckBox(
            "50/60 Hz Mains Notch: removes hum from power lines")
        self._chk_notch.setChecked(False)
        self._chk_notch.toggled.connect(self._toggle_notch)
        opt_layout.addWidget(self._chk_notch)

        self._chk_preemph = QtWidgets.QCheckBox(
            "Pre-emphasis: +6 dB/oct above 1 kHz, sharpens consonants")
        self._chk_preemph.setChecked(False)
        self._chk_preemph.toggled.connect(self._toggle_preemph)
        opt_layout.addWidget(self._chk_preemph)

        self._chk_noisegate = QtWidgets.QCheckBox(
            "Noise Gate: zeros output below -30 dB, kills inter-word noise")
        self._chk_noisegate.setChecked(False)
        self._chk_noisegate.toggled.connect(self._toggle_noisegate)
        opt_layout.addWidget(self._chk_noisegate)

        opt_box.setLayout(opt_layout)
        vbox.addWidget(opt_box)

        # Duty cycle meter
        dc_row = QtWidgets.QHBoxLayout()
        dc_row.setSpacing(6)

        dc_lbl = QtWidgets.QLabel("Pulse Duty Cycle:")
        dc_lbl.setStyleSheet("color: #777; font-size:10px;")
        dc_lbl.setMinimumWidth(110)
        dc_row.addWidget(dc_lbl)

        self._dc_bar = QtWidgets.QProgressBar()
        self._dc_bar.setRange(0, 1000)
        self._dc_bar.setValue(0)
        self._dc_bar.setTextVisible(False)
        self._dc_bar.setFixedHeight(14)
        self._dc_bar.setStyleSheet(
            "QProgressBar { border:1px solid #444; background:#1a1a1a;"
            " border-radius:2px; }"
            "QProgressBar::chunk { background: qlineargradient("
            "  x1:0,y1:0,x2:1,y2:0,"
            "  stop:0.00 #27ae60, stop:0.55 #27ae60,"
            "  stop:0.60 #f39c12, stop:0.70 #f39c12,"
            "  stop:0.80 #e74c3c, stop:1.00 #e74c3c"
            "); border-radius:2px; }")
        dc_row.addWidget(self._dc_bar, 1)

        self._dc_readout = QtWidgets.QLabel("--.-%")
        self._dc_readout.setFont(QtGui.QFont("Monospace", 9))
        self._dc_readout.setMinimumWidth(46)
        self._dc_readout.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        dc_row.addWidget(self._dc_readout)
        vbox.addLayout(dc_row)

        vbox.addWidget(self._hline())
        vbox.addSpacing(7)

        # =====================================================================
        # Section 3: SDR Output
        # =====================================================================
        vbox.addWidget(self._section_header("SDR Output"))

        output_row = QtWidgets.QHBoxLayout()
        output_row.setSpacing(0)

        # -- Left panel: HackRF transmitter -----------------------------------
        tx_panel = QtWidgets.QWidget()
        tx_vbox  = QtWidgets.QVBoxLayout(tx_panel)
        tx_vbox.setContentsMargins(0, 4, 8, 4)
        tx_vbox.setSpacing(4)

        # Two-line sub-header + hardware status on same row
        hdr_row = QtWidgets.QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        tx_hdr = QtWidgets.QLabel(
            "<b>Transmitter</b><br>"
            "<span style='font-size:10px; color:#777;'>HackRF SDR Output</span>")
        hdr_row.addWidget(tx_hdr)
        hw_lbl = QtWidgets.QLabel(self._hackrf_info)
        hw_lbl.setFont(QtGui.QFont("Monospace", 7))
        hw_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        hw_lbl.setStyleSheet(
            "color: #27ae60;" if self._hackrf_found else "color: #e74c3c;")
        hdr_row.addWidget(hw_lbl)
        tx_vbox.addLayout(hdr_row)

        # Frequency: compact combo box replaces radio buttons
        freq_lbl = QtWidgets.QLabel("Frequency:")
        freq_lbl.setStyleSheet("font-size:9pt; color:#777;")
        tx_vbox.addWidget(freq_lbl)
        self._freq_combo = QtWidgets.QComboBox()
        self._freq_combo.addItem("425 MHz  (70cm)", self.FREQ_70CM)
        self._freq_combo.addItem("1300 MHz (23cm)", self.FREQ_23CM)
        self._freq_combo.setCurrentIndex(1)
        self._freq_combo.currentIndexChanged.connect(self._cb_freq_combo)
        tx_vbox.addWidget(self._freq_combo)

        # Power: compact combo box
        pwr_lbl = QtWidgets.QLabel("TX Power (relative):")
        pwr_lbl.setStyleSheet("font-size:9pt; color:#777;")
        tx_vbox.addWidget(pwr_lbl)
        self._pwr_combo = QtWidgets.QComboBox()
        self._pwr_combo.addItem("1 mW", self.AMP_1MW)
        self._pwr_combo.addItem("2 mW", self.AMP_2MW)
        self._pwr_combo.currentIndexChanged.connect(self._cb_pwr_combo)
        tx_vbox.addWidget(self._pwr_combo)

        # TX toggle
        self._btn_tx = QtWidgets.QPushButton("TX: DISABLED")
        self._btn_tx.setCheckable(True)
        self._btn_tx.setChecked(True)
        self._btn_tx.setStyleSheet(self._style_red())
        self._btn_tx.toggled.connect(self._cb_tx_toggle)
        tx_vbox.addWidget(self._btn_tx)
        tx_vbox.addStretch()

        if not self._hackrf_found:
            tx_panel.setEnabled(False)
            no_hw = QtWidgets.QLabel(
                "Connect HackRF via USB data cable and restart.")
            no_hw.setStyleSheet("color: #777; font-size:9px;")
            no_hw.setWordWrap(True)
            tx_vbox.addWidget(no_hw)

        output_row.addWidget(tx_panel, 1)
        output_row.addWidget(self._vline())

        # -- Right panel: Save to Disk ----------------------------------------
        save_panel = QtWidgets.QWidget()
        save_vbox  = QtWidgets.QVBoxLayout(save_panel)
        save_vbox.setContentsMargins(8, 4, 0, 4)
        save_vbox.setSpacing(4)

        save_hdr = QtWidgets.QLabel("Save to Disk")
        save_hdr.setStyleSheet("font-weight: bold;")
        save_vbox.addWidget(save_hdr)

        self._save_path_lbl = QtWidgets.QLabel("Ready")
        self._save_path_lbl.setStyleSheet("color: #777; font-size:9px;")
        self._save_path_lbl.setWordWrap(True)
        save_vbox.addWidget(self._save_path_lbl)

        self._btn_record = QtWidgets.QPushButton("Record IQ")
        self._btn_record.setCheckable(True)
        self._btn_record.setChecked(False)
        self._btn_record.setStyleSheet(self._style_green())
        self._btn_record.toggled.connect(self._cb_record_toggle)
        save_vbox.addWidget(self._btn_record)

        self._chk_waterfall = QtWidgets.QCheckBox(
            "Generate Waterfall Image")
        self._chk_waterfall.setChecked(True)
        if not _MPL_OK:
            self._chk_waterfall.setEnabled(False)
            self._chk_waterfall.setText(
                "Waterfall (pip3 install matplotlib)")
        save_vbox.addWidget(self._chk_waterfall)

        self._waterfall_status = QtWidgets.QLabel("")
        self._waterfall_status.setStyleSheet("color: #777; font-size:9px;")
        self._waterfall_status.setWordWrap(True)
        save_vbox.addWidget(self._waterfall_status)
        save_vbox.addStretch()

        output_row.addWidget(save_panel, 1)
        vbox.addLayout(output_row)

        vbox.addStretch()
        vbox.addSpacing(5)

    # =========================================================================
    #  GNU Radio blocks
    # =========================================================================

    def _build_blocks(self):
        sr = self.AUDIO_RATE

        # 1. Microphone
        self.audio_src = audio.source(sr, "", True)

        # 2. eSpeak file source (starts as silence; updated on Generate)
        self.espeak_src = blocks.wavfile_source(self.ESPEAK_WAV, True)

        # 3. Source mixer -- replaces blocks.selector which requires
        #    connections before set_input_index() can be called.
        #    mic_gate starts at 1.0 (active), espeak_gate at 0.0 (silent).
        #    src_adder sums both; only one gate is non-zero at a time.
        self.mic_gate    = blocks.multiply_const_ff(1.0)
        self.espeak_gate = blocks.multiply_const_ff(0.0)
        self.src_adder   = blocks.add_ff(1)

        # 4. Level probe -- always taps raw mic regardless of source mode
        #    Alpha 1e-3 -> ~20 ms averaging
        self.level_probe = analog.probe_avg_mag_sqrd_f(0, 1e-3)

        # 5. Mute gate -- starts at 0.0 (muted)
        self.mute_gate = blocks.multiply_const_ff(0.0)

        # 6. DC blocker IIR: H(z) = (1 - z^-1) / (1 - 0.999*z^-1)
        self.dc_blocker = gr_filter.iir_filter_ffd(
            [1.0, -1.0], [-0.999], True)

        # 7a. Mains notch (starts as passthrough)
        _f0 = 60.0; _Q = 30.0
        _w0 = 2.0 * math.pi * _f0 / float(sr)
        _al = math.sin(_w0) / (2.0 * _Q)
        _cw = math.cos(_w0)
        _a0 = 1.0 + _al
        self._notch_b = [1.0/_a0, -2.0*_cw/_a0, 1.0/_a0]
        self._notch_a = [-2.0*_cw/_a0, (1.0-_al)/_a0]
        self.notch = gr_filter.iir_filter_ffd([1.0], [0.0], True)

        # 7b. Pre-emphasis FIR (starts as passthrough)
        self.pre_emph = gr_filter.fir_filter_fff(1, [1.0])

        # 7c. Noise gate (disabled at start)
        self.noise_gate = SimpleNoiseGate(threshold_db=-30.0, window=480)

        # 8. HPF (variable)
        self.hpf = gr_filter.fir_filter_fff(
            1, firdes.high_pass(1, sr, self._hpf_hz, 50,
                                _WIN_HAMMING, 6.76))

        # 9. LPF (variable)
        self.lpf = gr_filter.fir_filter_fff(
            1, firdes.low_pass(1, sr, self._lpf_hz, 200,
                               _WIN_HAMMING, 6.76))

        # 10. AGC
        self.agc = analog.agc_ff(1e-4, 0.5, 1.0)
        self.agc.set_max_gain(65536)

        # 11. Zero-crossing pulse generator
        self.zcp = ZeroCrossPulse(sr, self._pulse_us)

        # 12. Duty cycle probe (ZCP output is 0/1; avg == duty cycle)
        #     Alpha 2e-5 -> ~1 second rolling average
        self.dc_probe = analog.probe_avg_mag_sqrd_f(0, 2e-5)

        # 13. Amplitude scaler
        self.mult = blocks.multiply_const_ff(self._amplitude)

        # 14. Resampler: 48000 -> 2000000 Hz (125/3, exact)
        self.resampler = gr_filter.rational_resampler_fff(
            interpolation=self.RESAMP_INTERP,
            decimation=self.RESAMP_DECIM,
            taps=[], fractional_bw=0.0)

        # 15. Null source for Q channel
        self.null_src = blocks.null_source(gr.sizeof_float)

        # 16. Float -> Complex IQ
        self.f2c = blocks.float_to_complex(1)

        # 17. TX gate: (0+0j) = silent, (1+0j) = transmit; starts silent
        self.tx_gate = blocks.multiply_const_cc((0+0j))

        # 18. IQ recorder (starts as null sink; toggled to file_sink)
        self.iq_recorder = blocks.null_sink(gr.sizeof_gr_complex)

        # 19. HackRF sink (or null sink if hardware absent)
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
        # Source mixer: each source gated, then summed
        self.connect(self.audio_src,  self.mic_gate)
        self.connect(self.espeak_src, self.espeak_gate)
        self.connect(self.mic_gate,   (self.src_adder, 0))
        self.connect(self.espeak_gate,(self.src_adder, 1))

        # Level probe always sees raw mic regardless of source mode
        self.connect(self.audio_src, self.level_probe)

        # Main processing chain
        self.connect(self.src_adder,  self.mute_gate)
        self.connect(self.mute_gate,    self.dc_blocker)
        self.connect(self.dc_blocker,   self.notch)
        self.connect(self.notch,        self.hpf)
        self.connect(self.hpf,          self.lpf)
        self.connect(self.lpf,          self.pre_emph)
        self.connect(self.pre_emph,     self.agc)
        self.connect(self.agc,          self.noise_gate)
        self.connect(self.noise_gate,   self.zcp)
        self.connect(self.zcp,          self.mult)
        self.connect(self.zcp,          self.dc_probe)    # duty cycle tap
        self.connect(self.mult,         self.resampler)
        self.connect(self.resampler,    (self.f2c, 0))
        self.connect(self.null_src,     (self.f2c, 1))
        self.connect(self.f2c,          self.tx_gate)
        self.connect(self.f2c,          self.iq_recorder) # recording tap
        self.connect(self.tx_gate,      self.hackrf)

    # =========================================================================
    #  Display update (QTimer 10 Hz)
    # =========================================================================

    def _update_displays(self):
        # Audio level meter
        mag_sq = self.level_probe.level()
        db = 10.0 * math.log10(mag_sq) if mag_sq > 1e-12 else -60.0
        self._level_meter.set_level_db(db)

        # Duty cycle bar and readout
        dc_pct = self.dc_probe.level() * 100.0
        self._dc_bar.setValue(int(min(1000, max(0, dc_pct * 100))))
        self._dc_readout.setText("{:4.1f}%".format(max(0.0, dc_pct)))

    # =========================================================================
    #  Slider callbacks
    # =========================================================================

    def _cb_pulse(self, v):
        self._pulse_us = v
        self.zcp.set_pulse_width_us(v)

    def _cb_hpf(self, v):
        self._hpf_hz = v
        self.hpf.set_taps(firdes.high_pass(
            1, self.AUDIO_RATE, v, 50, _WIN_HAMMING, 6.76))

    def _cb_lpf(self, v):
        self._lpf_hz = v
        self.lpf.set_taps(firdes.low_pass(
            1, self.AUDIO_RATE, v, 200, _WIN_HAMMING, 6.76))

    # =========================================================================
    #  Optional filter toggles
    # =========================================================================

    def _toggle_notch(self, enabled):
        if enabled:
            self.notch.set_taps(self._notch_b, self._notch_a)
        else:
            self.notch.set_taps([1.0], [0.0])

    def _toggle_preemph(self, enabled):
        self.pre_emph.set_taps([1.0, -0.9375] if enabled else [1.0])

    def _toggle_noisegate(self, enabled):
        self.noise_gate.set_enabled(enabled)

    # =========================================================================
    #  SDR output toggles
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
        if muted:
            self._btn_mute.setText("Mic: MUTED")
            self._btn_mute.setStyleSheet(self._style_red())
        else:
            # Switching mic LIVE restores mic as audio source
            self.espeak_gate.set_k(0.0)
            self.mic_gate.set_k(1.0)
            self._espeak_status.setText("Ready")
            self._btn_mute.setText("Mic: LIVE")
            self._btn_mute.setStyleSheet(self._style_green())

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

        # Try espeak-ng first, fall back to espeak
        cmd_found = None
        for cmd in ['espeak-ng', 'espeak']:
            try:
                r = subprocess.run([cmd, '--version'],
                                   capture_output=True, timeout=3)
                if r.returncode == 0:
                    cmd_found = cmd
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        if cmd_found is None:
            self._espeak_status.setText(
                "Not found: sudo apt install espeak-ng")
            return

        # Generate WAV
        r = subprocess.run(
            [cmd_found, '-w', self.ESPEAK_RAW, text],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            self._espeak_status.setText(
                "eSpeak error: {}".format(r.stderr.strip()[:60]))
            return

        # Read and resample to AUDIO_RATE
        try:
            with wave.open(self.ESPEAK_RAW, 'r') as wf:
                sr_in     = wf.getframerate()
                n_ch      = wf.getnchannels()
                raw_bytes = wf.readframes(wf.getnframes())
        except Exception as e:
            self._espeak_status.setText("WAV read error: {}".format(e))
            return

        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        samples /= 32768.0
        if n_ch > 1:                          # stereo -> mono
            samples = samples.reshape(-1, n_ch).mean(axis=1)
        if sr_in != self.AUDIO_RATE:          # resample via linear interp
            new_len  = int(round(len(samples) * self.AUDIO_RATE / sr_in))
            old_idx  = np.arange(len(samples))
            new_idx  = np.linspace(0, len(samples) - 1, new_len)
            samples  = np.interp(new_idx, old_idx, samples).astype(np.float32)

        # Write resampled WAV
        self._write_samples_wav(self.ESPEAK_WAV, samples, self.AUDIO_RATE)

        # Lock graph, swap espeak source with new file, switch to espeak
        self.lock()
        self.disconnect(self.espeak_src, self.espeak_gate)
        self.espeak_src = blocks.wavfile_source(self.ESPEAK_WAV, True)
        self.connect(self.espeak_src, self.espeak_gate)
        self.unlock()
        # Switch source mix after unlock: espeak on, mic off
        self.espeak_gate.set_k(1.0)
        self.mic_gate.set_k(0.0)

        self._espeak_status.setText(
            "Playing: \"{}\"".format(
                text[:35] + ("..." if len(text) > 35 else "")))

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
            if (self._chk_waterfall.isChecked()
                    and self._record_path
                    and _MPL_OK):
                self._waterfall_status.setText("Generating waterfall...")
                QtWidgets.QApplication.processEvents()
                t = threading.Thread(
                    target=self._generate_waterfall,
                    args=(self._record_path,), daemon=True)
                t.start()

    def _generate_waterfall(self, iq_path):
        """Generate a waterfall PNG from a raw complex64 IQ file and open it."""
        try:
            data = np.fromfile(iq_path, dtype=np.complex64)
            if len(data) < 1024:
                self._set_waterfall_status("Recording too short for waterfall")
                return

            fft_size = 1024
            hop      = 512
            window   = np.hanning(fft_size).astype(np.float32)
            n_frames = (len(data) - fft_size) // hop

            spec = np.zeros((n_frames, fft_size), dtype=np.float32)
            for i in range(n_frames):
                frame    = data[i*hop : i*hop+fft_size]
                spectrum = np.fft.fftshift(
                    np.abs(np.fft.fft(frame * window))**2)
                spec[i]  = 10.0 * np.log10(spectrum + 1e-10)

            sr  = self.HACKRF_RATE
            dur = n_frames * hop / sr

            fig, ax = plt.subplots(figsize=(12, 5))
            ax.imshow(spec.T, aspect='auto', origin='lower',
                      extent=[-sr/2/1e6, sr/2/1e6, 0, dur],
                      cmap='inferno')
            ax.set_xlabel('Frequency offset (MHz)')
            ax.set_ylabel('Time (s)')
            ax.set_title('OpenV2K Waterfall  --  {}'.format(
                os.path.basename(iq_path)))
            plt.colorbar(ax.images[0], ax=ax, label='Power (dB)')
            plt.tight_layout()

            png_path = iq_path.replace('.iq', '.png')
            plt.savefig(png_path, dpi=150)
            plt.close(fig)

            # Open with system default image viewer (Linux: xdg-open)
            subprocess.Popen(['xdg-open', png_path])
            self._set_waterfall_status(
                "Saved: {}".format(os.path.basename(png_path)))

        except Exception as e:
            self._set_waterfall_status("Waterfall error: {}".format(e))

    def _set_waterfall_status(self, text):
        """Thread-safe label update via Qt signal."""
        QtCore.QMetaObject.invokeMethod(
            self._waterfall_status, "setText",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, text))

    # =========================================================================
    #  WAV file helpers
    # =========================================================================

    def _write_silence_wav(self, path):
        """Write 1 second of silence at AUDIO_RATE to path."""
        n = self.AUDIO_RATE
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.AUDIO_RATE)
            wf.writeframes(np.zeros(n, dtype=np.int16).tobytes())

    def _write_samples_wav(self, path, samples, sr):
        """Write float32 samples normalised to [-1,1] as 16-bit WAV."""
        s16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(s16.tobytes())

    # =========================================================================
    #  Shutdown
    # =========================================================================

    def closeEvent(self, event):
        self._level_timer.stop()
        self.stop()
        self.wait()
        event.accept()


# =============================================================================
#  Entry point
# =============================================================================

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("OpenV2K")

    tb = OpenV2K()
    tb.show()
    tb.start()

    def _quit(sig=None, frame=None):
        tb.stop()
        tb.wait()
        app.quit()

    signal.signal(signal.SIGINT,  _quit)
    signal.signal(signal.SIGTERM, _quit)

    tick = QtCore.QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
