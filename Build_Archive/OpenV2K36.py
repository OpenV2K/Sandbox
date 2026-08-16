#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: Unlicense
# This is free and unencumbered software released into the public domain.
#
# OpenV2K36.py -- Zero-Crossing Pulse Transmitter
# ================================================
# Requirements:
#   sudo apt install gnuradio gr-osmosdr hackrf python3-pyqt5 espeak-ng
#   pip3 install matplotlib --break-system-packages
# Usage:
#   python3 OpenV2K36.py

import sys
import os
import re
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
#  HackRF detection
# =============================================================================

def detect_hackrf():
    try:
        result = subprocess.run(
            ['hackrf_info'], capture_output=True, text=True, timeout=5)
        output = result.stdout + result.stderr
        if ('No HackRF boards found' in output or
                'hackrf_open() failed' in output or
                result.returncode != 0):
            return False, "HackRF not connected\nPlug in USB and restart"
        if 'Found HackRF' not in output and 'HackRF One' not in output:
            return False, "HackRF not detected\nCheck USB connection"
        lines    = output.splitlines()
        firmware = None
        for l in lines:
            if '(API:' in l or '(api:' in l.lower():
                m = re.search(r'(\d+\.\d+[\.\d]*)', l)
                if m: firmware = m.group(1); break
        if firmware is None:
            for l in lines:
                ll = l.lower().lstrip()
                if ll.startswith('hackrf_info') or ll.startswith('libhackrf'):
                    continue
                m = re.search(r'(\d{4}\.\d+[\.\d]*)', l)
                if m: firmware = m.group(1); break
        if firmware is None:
            for l in lines:
                ll = l.lower().lstrip()
                if ll.startswith('hackrf_info') or ll.startswith('libhackrf'):
                    continue
                if 'firmware' in ll:
                    m = re.search(r'(\d+\.\d+[\.\d]*)', l)
                    if m: firmware = m.group(1); break
        if firmware is None: firmware = 'check hackrf_info'
        return True, "HackRF One found\nFW: {}".format(firmware)
    except FileNotFoundError:
        return False, "hackrf_info not found\nsudo apt install hackrf"
    except subprocess.TimeoutExpired:
        return False, "hackrf_info timed out\nCheck USB connection"
    except Exception as e:
        return False, "Detection error:\n{}".format(e)


# =============================================================================
#  GNU Radio blocks
# =============================================================================

class ZeroCrossPulse(gr.sync_block):
    def __init__(self, sample_rate=48000.0, pulse_width_us=100.0):
        gr.sync_block.__init__(self, name="Zero Cross Pulse",
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
#  Section Header
# =============================================================================

class SectionHeader(QtWidgets.QWidget):
    _PT = 12; _GAP = 7

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
        w   = self.width(); gap = self._GAP
        bg   = self.palette().color(QtGui.QPalette.Window)
        grad = QtGui.QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QtGui.QColor("#2a6ebb")); grad.setColorAt(1.0, bg)
        p.fillRect(self.rect(), grad)
        pen = QtGui.QPen(QtGui.QColor("#888"), 1)
        p.setPen(pen)
        p.drawLine(0, 0, w, 0); p.drawLine(0, self.height()-1, w, self.height()-1)
        tx = (w - self._tw)//2; ty = gap + self._asc
        p.setFont(self._font)
        p.setPen(QtGui.QColor("white")); p.drawText(tx+1, ty+1, self._text)
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(tx, ty, self._text)


# =============================================================================
#  Swap Button
# =============================================================================

class SwapButton(QtWidgets.QWidget):
    BTN_D = 30; W = 44
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.W)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0,0,0,0); vbox.setSpacing(0)
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
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QPen(QtGui.QColor("#888"), 1))
        cx = self.width()//2; mid = self.height()//2; hd = self.BTN_D//2
        p.drawLine(cx, 0, cx, mid-hd); p.drawLine(cx, mid+hd, cx, self.height())


# =============================================================================
#  Audio level meter
# =============================================================================

class LevelMeter(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0,0,0,0); vbox.setSpacing(1)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0,600); self._bar.setValue(0)
        self._bar.setTextVisible(False); self._bar.setFixedHeight(16)
        self._bar.setStyleSheet(
            "QProgressBar { border:1px solid #444; background:#1a1a1a;"
            " border-radius:3px; }"
            "QProgressBar::chunk { background: qlineargradient("
            "  x1:0,y1:0,x2:1,y2:0,"
            "  stop:0.00 #27ae60,stop:0.70 #27ae60,"
            "  stop:0.80 #f39c12,stop:0.90 #f39c12,"
            "  stop:1.00 #e74c3c); border-radius:3px; }")
        vbox.addWidget(self._bar)
        scale = QtWidgets.QHBoxLayout(); scale.setContentsMargins(0,0,0,0)
        for txt, align in [("-60", QtCore.Qt.AlignLeft),
                            ("-30", QtCore.Qt.AlignCenter),
                            ("0 dB", QtCore.Qt.AlignRight)]:
            lbl = QtWidgets.QLabel(txt)
            lbl.setFont(QtGui.QFont("Monospace",7))
            lbl.setStyleSheet("color:#777;"); lbl.setAlignment(align)
            scale.addWidget(lbl)
        vbox.addLayout(scale)

    def set_level_db(self, db):
        self._bar.setValue(int((max(-60.0,min(0.0,db))+60.0)*10.0))

    def freeze(self): self.set_level_db(-60.0)


# =============================================================================
#  Labelled slider
# =============================================================================

class LabelledSlider(QtWidgets.QWidget):
    def __init__(self, label, lo, hi, step, default,
                 fmt="{:.0f}", callback=None, tick_steps=10, parent=None):
        super().__init__(parent)
        self._lo=float(lo); self._step=float(step); self._fmt=fmt; self._cb=callback
        n = max(1,int(round((hi-lo)/step)))
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(0,n)
        self._slider.setValue(int(round((default-lo)/step)))
        self._slider.setMinimumWidth(180); self._slider.setMaximumWidth(280)
        self._slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._slider.setTickInterval(tick_steps)
        self._readout = QtWidgets.QLabel(fmt.format(default))
        self._readout.setMinimumWidth(62)
        self._readout.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
        self._readout.setFont(QtGui.QFont("Monospace",8))
        lbl = QtWidgets.QLabel("<b>{}</b>".format(label))
        lbl.setMinimumWidth(80); lbl.setMaximumWidth(90)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0,0,0,0); row.setSpacing(4)
        row.addWidget(lbl); row.addWidget(self._slider); row.addWidget(self._readout)
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

    AUDIO_RATE         = 48000
    HACKRF_RATE        = 2000000
    RESAMP_INTERP      = 125
    RESAMP_DECIM       = 3
    FREQ_70CM          = 425e6
    FREQ_23CM          = 1300e6
    AMP_1MW            = 0.500
    AMP_2MW            = 0.707
    ESPEAK_WAV         = '/tmp/openv2k_espeak.wav'
    ESPEAK_RAW         = '/tmp/openv2k_espeak_raw.wav'
    ESPEAK_SILENCE_SEC = 3.0
    _DISABLED_BG       = QtGui.QColor("#b8b8b8")
    BTN_H              = 58
    _ESPEAK_RE         = re.compile(r'^[a-zA-Z ]+$')

    _TX_LICENSE = (
        "A valid amateur radio licence is required to "
        "transmit on these frequencies. "
        "Verify your national band plan and "
        "licence privileges before transmitting.")

    _SAVE_DESCRIPTION = (
        "Saves raw IQ samples as complex64 binary.\n"
        "Two channels: I (real) and Q (imaginary).\n"
        "Compatible with GNU Radio, inspectrum,\n"
        "GQRX, and SDR# for offline analysis.\n"
        " \n"
        "At 2 MHz sample rate: approx 16 MB/sec.\n"
        "A 30 second capture uses about 480 MB.\n"
        "Plan your storage before long recordings.\n"
        " \n"
        "Waterfall: short-time FFT via numpy,\n"
        "rendered with matplotlib inferno map.\n"
        "Opens automatically in system viewer.")

    def __init__(self):
        gr.top_block.__init__(self, "OpenV2K", catch_exceptions=True)
        QtWidgets.QMainWindow.__init__(self)
        self.setWindowTitle("OpenV2K (2026/7/23 - Version 36)")
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
        self._audio_left_active  = False
        self._output_left_active = False
        self._espeak_auto_record = False   # True when recording was auto-started by Generate Voice
        self._espeak_timer       = None    # QTimer that fires when one-shot playback ends
        self._log_text           = None   # set in _build_gui

        self._build_gui()
        self._build_blocks()
        self._connect_blocks()

        self._chk_notch.setChecked(True)
        self._chk_preemph.setChecked(True)
        self._chk_noisegate.setChecked(True)

        self._level_timer = QtCore.QTimer()
        self._level_timer.timeout.connect(self._update_displays)
        self._level_timer.start(100)

        self._log("Ready")

    # =========================================================================
    #  Event Log -- timestamped append, thread-safe
    # =========================================================================

    def _log(self, msg, in_progress=False):
        if self._log_text is None:
            return
        now    = datetime.datetime.now()
        ms     = now.microsecond // 1000
        ts     = now.strftime("%H:%M:%S.") + "{:03d}".format(ms)
        suffix = "   ..." if in_progress else "."
        line   = "[{}] {}{}".format(ts, msg, suffix)
        if (QtCore.QThread.currentThread() !=
                QtWidgets.QApplication.instance().thread()):
            QtCore.QMetaObject.invokeMethod(
                self._log_text, "append",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, line))
        else:
            self._log_text.append(line)
            sb = self._log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    # =========================================================================
    #  Event Log overlay geometry
    #  The overlay is a child of the central widget, positioned absolutely to
    #  cover everything BELOW the title row.  The title row (with the Event Log
    #  button and the OpenV2K heading) is never covered.
    # =========================================================================

    def showEvent(self, event):
        super().showEvent(event)
        # Delay one event-loop tick so the layout engine has computed heights
        QtCore.QTimer.singleShot(0, self._update_overlay_geometry)

    def _update_overlay_geometry(self):
        if not hasattr(self, '_overlay_w') or not hasattr(self, '_title_frame'):
            return
        cw = self.centralWidget()
        if cw is None:
            return
        # Map the bottom edge of the title frame into central-widget coordinates
        tf_bottom = self._title_frame.mapTo(
            cw, QtCore.QPoint(0, self._title_frame.height())).y()
        self._overlay_w.setGeometry(
            0, tf_bottom, cw.width(), cw.height() - tf_bottom)

    def _toggle_event_log(self, checked):
        if checked:
            self._update_overlay_geometry()  # ensure geometry is fresh
            self._overlay_w.show()
            self._overlay_w.raise_()         # bring above all content
            self._log("Event Log opened")
        else:
            self._overlay_w.hide()
            self._log("Event Log closed")

    # =========================================================================
    #  GUI helpers
    # =========================================================================

    def _set_panel_active(self, panel, active):
        panel.setEnabled(active)
        panel.setAutoFillBackground(True)
        pal = panel.palette()
        pal.setColor(QtGui.QPalette.Window,
                     (QtWidgets.QApplication.palette().color(
                          QtGui.QPalette.Window) if active
                      else self._DISABLED_BG))
        panel.setPalette(pal)

    @staticmethod
    def _keep_black(widget):
        pal = widget.palette(); black = QtGui.QColor("black")
        pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, black)
        pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText,  black)
        widget.setPalette(pal)

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
                "QPushButton:hover { background-color:#2ecc71; }"
                "QPushButton:disabled { background-color:#555555;"
                " color:#999999; border-radius:4px; }")

    @staticmethod
    def _style_red():
        return ("QPushButton { background-color:#c0392b; color:white;"
                " border-radius:4px; font-weight:bold; }"
                "QPushButton:hover { background-color:#e74c3c; }"
                "QPushButton:disabled { background-color:#555555;"
                " color:#999999; border-radius:4px; }")

    # =========================================================================
    #  GUI build
    # =========================================================================

    def _build_gui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        # The content widget fills the central area via a zero-margin layout
        content_w = QtWidgets.QWidget(central)
        cl = QtWidgets.QVBoxLayout(central)
        cl.setContentsMargins(0,0,0,0); cl.setSpacing(0)
        cl.addWidget(content_w)

        # Main content vbox (standard margins inside content_w)
        vbox = QtWidgets.QVBoxLayout(content_w)
        vbox.setContentsMargins(12,12,12,12); vbox.setSpacing(0)

        # ---- Title row (NEVER covered by the overlay) ----------------------
        # The title frame is a named widget so we can mapTo() its bottom edge.
        self._title_frame = QtWidgets.QWidget()
        tr = QtWidgets.QHBoxLayout(self._title_frame)
        tr.setContentsMargins(0,0,0,0); tr.setSpacing(8)

        # "Event Log" button -- rounded, blue, top-left corner
        self._log_btn = QtWidgets.QPushButton("Event Log")
        self._log_btn.setCheckable(True)
        self._log_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #2a6ebb; color: white;"
            "  border-radius: 8px; font-weight: bold;"
            "  padding: 4px 10px; font-size: 9pt; }"
            "QPushButton:checked {"
            "  background-color: #1c4f8a; }"
            "QPushButton:hover {"
            "  background-color: #3a7ebb; }"
            "QPushButton:checked:hover {"
            "  background-color: #245f9a; }")
        self._log_btn.toggled.connect(self._toggle_event_log)
        tr.addWidget(self._log_btn)

        # OpenV2K clickable title (centred in remaining space)
        title = QtWidgets.QLabel(
            "<h3 style='margin:0;'>"
            "<a href='https://github.com/OpenV2K'"
            " style='color:#2a6ebb; text-decoration:none;'>OpenV2K</a>"
            "</h3><small>Audio Waveform Zero-Crossing Pulse Stream Generator</small>")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setOpenExternalLinks(True)
        tr.addWidget(title, 1)

        # 2x2 reference button cluster -- top-right of window
        _refs = [
            ("RefA", "https://www.amazon.com/Auditory-Effects-Microwave-Radiation-James/dp/3030645436"),
            ("RefB", "https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques"),
            ("RefC", "https://web.archive.org/web/20160910133313/http://www.mitchelleffect.com/1973_voice_to_skull.pdf"),
            ("RefD", "https://www.reddit.com/r/OpenV2K/comments/1g69tey/exodus_12ghz_solid_state_high_pulse_power/"),
        ]
        ref_frame = QtWidgets.QWidget()
        ref_grid  = QtWidgets.QGridLayout(ref_frame)
        ref_grid.setContentsMargins(0, 0, 0, 0); ref_grid.setSpacing(2)
        bw = max(36, (self._log_btn.sizeHint().width() - 4) // 2)
        for i, (lbl, url) in enumerate(_refs):
            rb = QtWidgets.QPushButton(lbl)
            rb.setFixedSize(bw, 20)
            rb.setStyleSheet(
                "QPushButton { font-size:8px; font-weight:bold;"
                " background:#2a6ebb; color:white; border-radius:3px; }"
                "QPushButton:hover { background:#3a7ebb; }")
            rb.clicked.connect(
                lambda checked=False, u=url:
                subprocess.Popen(['xdg-open', u],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL))
            ref_grid.addWidget(rb, i // 2, i % 2)
        ref_frame.setFixedWidth(self._log_btn.sizeHint().width())
        tr.addWidget(ref_frame)

        vbox.addWidget(self._title_frame)
        vbox.addSpacing(6)

        # =====================================================================
        # Audio Input
        # =====================================================================
        vbox.addWidget(SectionHeader("Audio Input"))
        vbox.addSpacing(2)
        audio_row = QtWidgets.QHBoxLayout(); audio_row.setSpacing(0)

        self._mic_panel = QtWidgets.QWidget()
        self._mic_panel.setAutoFillBackground(True)
        mic_vbox = QtWidgets.QVBoxLayout(self._mic_panel)
        mic_vbox.setContentsMargins(0,4,4,4); mic_vbox.setSpacing(4)

        mic_sub = QtWidgets.QLabel("Live Microphone")
        mic_sub.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(mic_sub)
        mic_vbox.addWidget(mic_sub)

        # Description below header (wider: fills to button edge)
        meter_lbl = QtWidgets.QLabel(
            "Mic Level: in silence -45 dB, aim for -18 dB when speaking.\n"
            "Adjust in your OS: System Settings > Sound > Input.")
        meter_lbl.setStyleSheet("color:#777; font-size:9px;")
        meter_lbl.setWordWrap(True)
        meter_lbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                QtWidgets.QSizePolicy.Preferred)
        mic_vbox.addWidget(meter_lbl)

        # dB readout and meter below description
        self._level_db_lbl = QtWidgets.QLabel("-60.0 dB")
        self._level_db_lbl.setFont(QtGui.QFont("Monospace",8))
        self._level_db_lbl.setAlignment(QtCore.Qt.AlignRight)
        self._level_db_lbl.setStyleSheet("color:#27ae60;")
        mic_vbox.addWidget(self._level_db_lbl)

        self._level_meter = LevelMeter()
        self._level_meter.freeze()
        mic_vbox.addWidget(self._level_meter)

        # Stretch pushes Mic button down to roughly align with Generate Voice
        mic_vbox.addStretch(1)

        self._btn_mute = QtWidgets.QPushButton("Mic: MUTED")
        self._btn_mute.setCheckable(True); self._btn_mute.setChecked(True)
        self._btn_mute.setMinimumHeight(self.BTN_H)
        self._btn_mute.setStyleSheet(self._style_red())
        self._btn_mute.toggled.connect(self._cb_mute)
        mic_vbox.addWidget(self._btn_mute)
        audio_row.addWidget(self._mic_panel, 1)

        audio_swap = SwapButton(parent=self)
        audio_swap.clicked.connect(self._cb_audio_swap)
        audio_row.addWidget(audio_swap)

        self._es_panel = QtWidgets.QWidget()
        self._es_panel.setAutoFillBackground(True)
        es_vbox = QtWidgets.QVBoxLayout(self._es_panel)
        es_vbox.setContentsMargins(4,4,0,4); es_vbox.setSpacing(0)

        es_hdr = QtWidgets.QHBoxLayout()
        es_title = QtWidgets.QLabel("eSpeak Text To Speech")
        es_title.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(es_title)
        es_hdr.addWidget(es_title, 1)
        self._char_counter = QtWidgets.QLabel("0/140")
        self._char_counter.setFont(QtGui.QFont("Monospace",8))
        self._char_counter.setAlignment(
            QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
        self._char_counter.setStyleSheet("color:#777;")
        es_hdr.addWidget(self._char_counter)
        es_vbox.addLayout(es_hdr)
        es_vbox.addSpacing(8)

        self._espeak_input = QtWidgets.QTextEdit()
        self._espeak_input.setPlaceholderText("Hello World")
        self._espeak_input.setMinimumHeight(50)
        self._espeak_input.setMaximumHeight(54)
        self._espeak_input.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff)
        self._espeak_input.textChanged.connect(self._on_espeak_text_changed)
        es_vbox.addWidget(self._espeak_input)
        es_vbox.addSpacing(8)

        self._btn_generate = QtWidgets.QPushButton("Generate Voice")
        self._btn_generate.setMinimumHeight(self.BTN_H)
        self._btn_generate.setEnabled(False)
        self._btn_generate.setStyleSheet(self._style_green())
        self._btn_generate.clicked.connect(self._cb_generate_espeak)
        es_vbox.addWidget(self._btn_generate)

        self._espeak_status = QtWidgets.QLabel("")   # kept as attribute, not shown
        es_vbox.addStretch()
        audio_row.addWidget(self._es_panel, 1)
        vbox.addLayout(audio_row)
        vbox.addSpacing(2)

        # =====================================================================
        # Signal Processing
        # =====================================================================
        vbox.addWidget(SectionHeader("Signal Processing"))

        sp_row = QtWidgets.QHBoxLayout()
        sp_row.setSpacing(0); sp_row.setContentsMargins(0,0,0,0)

        left_sp = QtWidgets.QWidget()
        left_vbox = QtWidgets.QVBoxLayout(left_sp)
        left_vbox.setContentsMargins(0,8,10,8); left_vbox.setSpacing(4)

        left_vbox.addSpacing(4)   # sliders sit 4px lower than section header
        self._sl_pulse = LabelledSlider("Pulse (us)",50,500,5,self._pulse_us,
            fmt="{:.0f} us",callback=self._cb_pulse,tick_steps=10)
        left_vbox.addWidget(self._sl_pulse)
        self._sl_hpf = LabelledSlider("HPF (Hz)",250,1000,10,self._hpf_hz,
            fmt="{:.0f} Hz",callback=self._cb_hpf,tick_steps=10)
        left_vbox.addWidget(self._sl_hpf)
        self._sl_lpf = LabelledSlider("LPF (Hz)",1000,15000,100,self._lpf_hz,
            fmt="{:.0f} Hz",callback=self._cb_lpf,tick_steps=5)
        left_vbox.addWidget(self._sl_lpf)

        opt_box = QtWidgets.QGroupBox("Optional Filters")
        opt_box.setStyleSheet(
            "QGroupBox { font-size:9pt; } QCheckBox { font-size:9pt; }")
        opt_layout = QtWidgets.QVBoxLayout(); opt_layout.setSpacing(3)
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
        sp_row.addWidget(left_sp, 4)
        sp_row.addWidget(self._vline())

        dc_panel = QtWidgets.QWidget()
        dc_vbox  = QtWidgets.QVBoxLayout(dc_panel)
        dc_vbox.setContentsMargins(4,2,4,6); dc_vbox.setSpacing(0)
        self._dc_readout = QtWidgets.QLabel("--.-%")
        font_r = QtGui.QFont("Monospace",9); font_r.setBold(True)
        self._dc_readout.setFont(font_r)
        self._dc_readout.setAlignment(QtCore.Qt.AlignCenter)
        self._dc_readout.setStyleSheet("color:black;")
        dc_vbox.addWidget(self._dc_readout)
        dc_vbox.addSpacing(4)
        self._dc_vbar = QtWidgets.QProgressBar()
        self._dc_vbar.setOrientation(QtCore.Qt.Vertical)
        self._dc_vbar.setRange(0,1000); self._dc_vbar.setValue(0)
        self._dc_vbar.setTextVisible(False); self._dc_vbar.setFixedWidth(20)
        self._dc_vbar.setStyleSheet(
            "QProgressBar { border:1px solid #444; background:#1a1a1a;"
            " border-radius:3px; }"
            "QProgressBar::chunk { background: qlineargradient("
            "  x1:0,y1:1,x2:0,y2:0,"
            "  stop:0.00 #27ae60,stop:0.55 #27ae60,"
            "  stop:0.60 #f39c12,stop:0.70 #f39c12,"
            "  stop:0.80 #e74c3c,stop:1.00 #e74c3c); border-radius:3px; }")
        bar_row = QtWidgets.QHBoxLayout()
        bar_row.setContentsMargins(0,0,0,0); bar_row.setSpacing(0)
        bar_row.addStretch(); bar_row.addWidget(self._dc_vbar); bar_row.addStretch()
        dc_vbox.addLayout(bar_row,1); dc_vbox.addSpacing(4)
        summary = QtWidgets.QLabel("Avg: 2-4%\nMax: 10%\n>6% over spec")
        summary.setFont(QtGui.QFont("Monospace",7))
        summary.setStyleSheet("color:#777;")
        summary.setAlignment(QtCore.Qt.AlignCenter); summary.setWordWrap(False)
        dc_vbox.addWidget(summary); dc_vbox.addSpacing(4)
        dc_lbl = QtWidgets.QLabel("Pulse Duty Cycle")
        font_dc = QtGui.QFont("Monospace",7); font_dc.setBold(True)
        dc_lbl.setFont(font_dc); dc_lbl.setStyleSheet("color:black;")
        dc_lbl.setAlignment(QtCore.Qt.AlignCenter); dc_lbl.setWordWrap(False)
        dc_vbox.addWidget(dc_lbl)
        sp_row.addWidget(dc_panel,1)
        vbox.addLayout(sp_row)

        # =====================================================================
        # Output
        # =====================================================================
        vbox.addWidget(SectionHeader("Output"))
        vbox.addSpacing(2)
        output_row = QtWidgets.QHBoxLayout(); output_row.setSpacing(0)

        self._tx_panel = QtWidgets.QWidget()
        self._tx_panel.setAutoFillBackground(True)
        self._tx_panel.setMinimumHeight(240)
        tx_vbox = QtWidgets.QVBoxLayout(self._tx_panel)
        tx_vbox.setContentsMargins(0,4,4,4); tx_vbox.setSpacing(4)

        hdr_row = QtWidgets.QHBoxLayout(); hdr_row.setContentsMargins(0,0,0,0)
        tx_hdr = QtWidgets.QLabel(
            "<span style='font-weight:bold; color:black;'>Transmitter</span><br>"
            "<span style='font-size:10px; color:#777;'>HackRF SDR Output</span>")
        self._keep_black(tx_hdr)
        hdr_row.addWidget(tx_hdr)
        self._hw_lbl = QtWidgets.QLabel(self._hackrf_info)
        self._hw_lbl.setFont(QtGui.QFont("Monospace",7))
        self._hw_lbl.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
        self._hw_lbl.setStyleSheet(
            "color:#27ae60;" if self._hackrf_found else "color:#e74c3c;")
        hdr_row.addWidget(self._hw_lbl)
        tx_vbox.addLayout(hdr_row)

        lic_lbl = QtWidgets.QLabel(
            "<a href='https://en.wikipedia.org/wiki/"
            "Amateur_radio_frequency_allocations#ITU_Region_2'"
            " style='color:#555; text-decoration:none;'>"
            "<b>{}</b></a>".format(self._TX_LICENSE))
        lic_lbl.setOpenExternalLinks(True)
        lic_lbl.setStyleSheet("font-size:10px;")
        lic_lbl.setWordWrap(True)
        tx_vbox.addWidget(lic_lbl)
        tx_vbox.addStretch(1)

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

        tx_vbox.addSpacing(8)
        self._btn_tx = QtWidgets.QPushButton("TX: DISABLED")
        self._btn_tx.setCheckable(True); self._btn_tx.setChecked(True)
        self._btn_tx.setMinimumHeight(self.BTN_H)
        self._btn_tx.setStyleSheet(self._style_red())
        self._btn_tx.toggled.connect(self._cb_tx_toggle)
        tx_vbox.addWidget(self._btn_tx)
        output_row.addWidget(self._tx_panel, 1)

        out_swap = SwapButton(parent=self)
        out_swap.clicked.connect(self._cb_output_swap)
        output_row.addWidget(out_swap)

        self._save_panel = QtWidgets.QWidget()
        self._save_panel.setAutoFillBackground(True)
        self._save_panel.setMinimumHeight(240)
        save_vbox = QtWidgets.QVBoxLayout(self._save_panel)
        save_vbox.setContentsMargins(4,4,0,5); save_vbox.setSpacing(4)

        save_hdr = QtWidgets.QLabel("Save to Disk")
        save_hdr.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(save_hdr)
        save_vbox.addWidget(save_hdr)

        self._save_path_lbl = QtWidgets.QLabel(self._SAVE_DESCRIPTION)
        self._save_path_lbl.setStyleSheet(
            "color:#777; font-size:11px; margin-left:10px; margin-top:5px;")
        self._save_path_lbl.setWordWrap(True)
        self._save_path_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        save_vbox.addWidget(self._save_path_lbl)
        save_vbox.addStretch(1)
        save_vbox.addSpacing(8)

        self._btn_record = QtWidgets.QPushButton("Record IQ")
        self._btn_record.setCheckable(True); self._btn_record.setChecked(False)
        self._btn_record.setMinimumHeight(self.BTN_H)
        self._btn_record.setStyleSheet(self._style_green())
        self._btn_record.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._btn_record.toggled.connect(self._cb_record_toggle)
        save_vbox.addWidget(self._btn_record)

        self._chk_waterfall = QtWidgets.QCheckBox("Generate Waterfall Graph Image")
        self._chk_waterfall.setChecked(True)
        self._chk_waterfall.setStyleSheet("color:black;")
        self._keep_black(self._chk_waterfall)
        if not _MPL_OK:
            self._chk_waterfall.setEnabled(False)
            self._chk_waterfall.setText("Waterfall (pip3 install matplotlib)")
        save_vbox.addWidget(self._chk_waterfall)

        output_row.addWidget(self._save_panel, 1)
        vbox.addLayout(output_row)

        # ---- Initial panel states ------------------------------------------
        self._set_panel_active(self._mic_panel,  False)
        self._set_panel_active(self._es_panel,   True)
        self._set_panel_active(self._tx_panel,   False)
        self._set_panel_active(self._save_panel, True)

        # =====================================================================
        # Event Log overlay
        # Child of central; positioned absolutely to cover everything BELOW
        # the title row (title row is never covered so the button stays visible).
        # =====================================================================
        self._overlay_w = QtWidgets.QWidget(central)
        self._overlay_w.setAutoFillBackground(True)
        pal = self._overlay_w.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self._overlay_w.setPalette(pal)
        self._overlay_w.hide()

        ovl = QtWidgets.QVBoxLayout(self._overlay_w)
        ovl.setContentsMargins(0,0,0,0); ovl.setSpacing(0)

        ovl_hdr = QtWidgets.QLabel("  OpenV2K  Event Log")
        ovl_hdr.setStyleSheet(
            "background:#1a1a1a; color:#666; font-family:Monospace;"
            " font-size:9px; padding:3px; border-bottom:1px solid #333;")
        ovl.addWidget(ovl_hdr)

        self._log_text = QtWidgets.QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QtGui.QFont("Monospace",9))
        self._log_text.setStyleSheet(
            "QTextEdit { background:black; color:white; border:none; }")
        ovl.addWidget(self._log_text)

    # =========================================================================
    #  GNU Radio blocks
    # =========================================================================

    def _build_blocks(self):
        sr = self.AUDIO_RATE
        self.audio_src   = audio.source(sr,"",True)
        self.espeak_src  = blocks.wavfile_source(self.ESPEAK_WAV,True)
        self.mic_gate    = blocks.multiply_const_ff(0.0)
        self.espeak_gate = blocks.multiply_const_ff(1.0)
        self.src_adder   = blocks.add_ff(1)
        self.level_probe = analog.probe_avg_mag_sqrd_f(0,1e-3)
        self.mute_gate   = blocks.multiply_const_ff(0.0)
        self.dc_blocker  = gr_filter.iir_filter_ffd([1.0,-1.0],[-0.999],True)
        _f0=60.0; _Q=30.0
        _w0=2.0*math.pi*_f0/float(sr); _al=math.sin(_w0)/(2.0*_Q)
        _cw=math.cos(_w0); _a0=1.0+_al
        self._notch_b=[1.0/_a0,-2.0*_cw/_a0,1.0/_a0]
        self._notch_a=[-2.0*_cw/_a0,(1.0-_al)/_a0]
        self.notch      = gr_filter.iir_filter_ffd([1.0],[0.0],True)
        self.pre_emph   = gr_filter.fir_filter_fff(1,[1.0])
        self.noise_gate = SimpleNoiseGate(threshold_db=-30.0,window=480)
        self.hpf = gr_filter.fir_filter_fff(
            1, firdes.high_pass(1,sr,self._hpf_hz,50,_WIN_HAMMING,6.76))
        self.lpf = gr_filter.fir_filter_fff(
            1, firdes.low_pass(1,sr,self._lpf_hz,200,_WIN_HAMMING,6.76))
        self.agc = analog.agc_ff(1e-4,0.5,1.0); self.agc.set_max_gain(65536)
        self.zcp      = ZeroCrossPulse(sr,self._pulse_us)
        self.dc_probe = analog.probe_avg_mag_sqrd_f(0,2e-5)
        self.mult     = blocks.multiply_const_ff(self._amplitude)
        self.resampler= gr_filter.rational_resampler_fff(
            interpolation=self.RESAMP_INTERP,decimation=self.RESAMP_DECIM,
            taps=[],fractional_bw=0.0)
        self.null_src    = blocks.null_source(gr.sizeof_float)
        self.f2c         = blocks.float_to_complex(1)
        self.tx_gate     = blocks.multiply_const_cc((0+0j))
        self.iq_recorder = blocks.null_sink(gr.sizeof_gr_complex)
        if self._hackrf_found:
            self.hackrf = osmosdr.sink(args="numchan=1 hackrf=0")
            self.hackrf.set_sample_rate(self.HACKRF_RATE)
            self.hackrf.set_center_freq(self._freq_hz,0)
            self.hackrf.set_freq_corr(0,0); self.hackrf.set_gain(0,0)
            self.hackrf.set_if_gain(40,0); self.hackrf.set_bb_gain(20,0)
            self.hackrf.set_antenna("",0); self.hackrf.set_bandwidth(0,0)
        else:
            self.hackrf = blocks.null_sink(gr.sizeof_gr_complex)

    def _connect_blocks(self):
        self.connect(self.audio_src,  self.mic_gate)
        self.connect(self.espeak_src, self.espeak_gate)
        self.connect(self.mic_gate,   (self.src_adder,0))
        self.connect(self.espeak_gate,(self.src_adder,1))
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
        self.connect(self.resampler,  (self.f2c,0))
        self.connect(self.null_src,   (self.f2c,1))
        self.connect(self.f2c,        self.tx_gate)
        self.connect(self.f2c,        self.iq_recorder)
        self.connect(self.tx_gate,    self.hackrf)

    # =========================================================================
    #  Display update
    # =========================================================================

    def _update_displays(self):
        if self._audio_left_active:
            mag_sq = self.level_probe.level()
            db = max(-60.0,min(0.0,
                10.0*math.log10(mag_sq) if mag_sq>1e-12 else -60.0))
            self._level_meter.set_level_db(db)
            col=("#e74c3c" if db>-6 else "#f39c12" if db>-18 else "#27ae60")
            self._level_db_lbl.setText("{:+.1f} dB".format(db))
            self._level_db_lbl.setStyleSheet(
                "color:{}; font-family:Monospace; font-size:8px;".format(col))
        dc=self.dc_probe.level()*100.0
        self._dc_vbar.setValue(int(min(1000,max(0,dc*100))))
        self._dc_readout.setText("{:4.1f}%".format(max(0.0,dc)))

    # =========================================================================
    #  Callbacks
    # =========================================================================

    def _cb_pulse(self,v): self._pulse_us=v; self.zcp.set_pulse_width_us(v)

    def _cb_hpf(self,v):
        self._hpf_hz=v
        self.hpf.set_taps(firdes.high_pass(1,self.AUDIO_RATE,v,50,_WIN_HAMMING,6.76))

    def _cb_lpf(self,v):
        self._lpf_hz=v
        self.lpf.set_taps(firdes.low_pass(1,self.AUDIO_RATE,v,200,_WIN_HAMMING,6.76))

    def _toggle_notch(self,e):
        self.notch.set_taps(self._notch_b if e else [1.0],
                            self._notch_a if e else [0.0])

    def _toggle_preemph(self,e):
        self.pre_emph.set_taps([1.0,-0.9375] if e else [1.0])

    def _toggle_noisegate(self,e): self.noise_gate.set_enabled(e)

    def _cb_audio_swap(self):
        self._audio_left_active = not self._audio_left_active
        if self._audio_left_active:
            self._set_panel_active(self._mic_panel,True)
            self._set_panel_active(self._es_panel,False)
            self.mic_gate.set_k(1.0); self.espeak_gate.set_k(0.0)
            self._btn_mute.setChecked(True)
            self._btn_mute.setText("Mic: MUTED")
            self._btn_mute.setStyleSheet(self._style_red())
            self.mute_gate.set_k(0.0); self._muted=True
            self._log("Input: Live Microphone (muted)")
        else:
            self._set_panel_active(self._mic_panel,False)
            self._set_panel_active(self._es_panel,True)
            self.mic_gate.set_k(0.0); self.espeak_gate.set_k(1.0)
            self._level_meter.freeze()
            self._level_db_lbl.setText("-60.0 dB")
            self._level_db_lbl.setStyleSheet(
                "color:#27ae60; font-family:Monospace; font-size:8px;")
            t=self._espeak_input.toPlainText().strip()
            self._btn_generate.setEnabled(
                len(t)>0 and t.lower()!='hello world')
            self._log("Input: eSpeak TTS")

    def _cb_output_swap(self):
        self._output_left_active = not self._output_left_active
        if self._output_left_active:
            self._hw_lbl.setText(self._hackrf_info)
            self._hw_lbl.setStyleSheet(
                "color:#27ae60;" if self._hackrf_found else "color:#e74c3c;")
            self._set_panel_active(self._tx_panel,True)
            self._set_panel_active(self._save_panel,False)
            self.tx_gate.set_k((0+0j))
            self._btn_tx.setChecked(True)
            self._btn_tx.setText("TX: DISABLED")
            self._btn_tx.setStyleSheet(self._style_red())
            self._log("Output: HackRF Transmitter (disabled)")
        else:
            self.tx_gate.set_k((0+0j))
            if not self._btn_tx.isChecked(): self._btn_tx.setChecked(True)
            self._set_panel_active(self._tx_panel,False)
            self._set_panel_active(self._save_panel,True)
            self._log("Output: Save to Disk")

    def _cb_freq_combo(self,idx):
        self._freq_hz=self._freq_combo.itemData(idx)
        if self._hackrf_found: self.hackrf.set_center_freq(self._freq_hz,0)

    def _cb_pwr_combo(self,idx):
        self._amplitude=self._pwr_combo.itemData(idx)
        self.mult.set_k(self._amplitude)

    def _cb_mute(self,muted):
        self._muted=muted; self.mute_gate.set_k(0.0 if muted else 1.0)
        self._btn_mute.setText("Mic: MUTED" if muted else "Mic: LIVE")
        self._btn_mute.setStyleSheet(
            self._style_red() if muted else self._style_green())
        self._log("Microphone muted" if muted else "Microphone live -- monitoring")

    def _cb_tx_toggle(self,disabled):
        if disabled:
            self.tx_gate.set_k((0+0j))
            self._btn_tx.setText("TX: DISABLED")
            self._btn_tx.setStyleSheet(self._style_red())
            self._log("Transmitter disabled")
        else:
            self.tx_gate.set_k((1+0j))
            self._btn_tx.setText("TX: ENABLED")
            self._btn_tx.setStyleSheet(self._style_green())
            self._log("Transmitting on {:.0f} MHz".format(self._freq_hz/1e6))

    def _on_espeak_text_changed(self):
        raw=self._espeak_input.toPlainText().replace('\n',' ')
        clean=re.sub(r'[^a-zA-Z ]','',raw)[:140]
        if clean!=raw:
            self._espeak_input.blockSignals(True)
            pos=self._espeak_input.textCursor().position()
            self._espeak_input.setPlainText(clean)
            cur=self._espeak_input.textCursor()
            cur.setPosition(min(pos,len(clean)))
            self._espeak_input.setTextCursor(cur)
            self._espeak_input.blockSignals(False)
        self._char_counter.setText("{}/140".format(len(clean)))
        s=clean.strip()
        self._btn_generate.setEnabled(len(s)>0 and s.lower()!='hello world')

    def _cb_generate_espeak(self):
        text = self._espeak_input.toPlainText().strip().replace('\n',' ')
        text = re.sub(r'[^a-zA-Z ]','',text)[:140]
        if not text: return

        self._log("Generating eSpeak audio", in_progress=True)
        QtWidgets.QApplication.processEvents()

        # Find espeak binary
        cmd_found = None
        for cmd in ['espeak-ng','espeak']:
            try:
                r = subprocess.run([cmd,'--version'],capture_output=True,timeout=3)
                if r.returncode == 0: cmd_found = cmd; break
            except (FileNotFoundError, subprocess.TimeoutExpired): continue

        if cmd_found is None:
            self._log("ERROR: espeak-ng not found -- sudo apt install espeak-ng")
            return

        r = subprocess.run([cmd_found,'-w',self.ESPEAK_RAW,text],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            self._log("ERROR eSpeak: {}".format(r.stderr.strip()[:80]))
            return

        try:
            with wave.open(self.ESPEAK_RAW,'r') as wf:
                sr_in = wf.getframerate(); n_ch = wf.getnchannels()
                raw_bytes = wf.readframes(wf.getnframes())
        except Exception as e:
            self._log("ERROR WAV read: {}".format(e))
            return

        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        samples /= 32768.0
        if n_ch > 1: samples = samples.reshape(-1, n_ch).mean(axis=1)
        if sr_in != self.AUDIO_RATE:
            new_len = int(round(len(samples) * self.AUDIO_RATE / sr_in))
            samples = np.interp(
                np.linspace(0, len(samples)-1, new_len),
                np.arange(len(samples)), samples).astype(np.float32)

        # Trailing silence so the loop restarts silently (gate closes before it loops)
        silence = np.zeros(
            int(self.AUDIO_RATE * self.ESPEAK_SILENCE_SEC), dtype=np.float32)
        samples = np.concatenate([samples, silence])

        # Total one-shot duration in ms (speech + silence padding)
        total_ms = int(len(samples) / self.AUDIO_RATE * 1000)

        self._write_samples_wav(self.ESPEAK_WAV, samples, self.AUDIO_RATE)

        try:
            self.lock()
            self.disconnect(self.espeak_src, self.espeak_gate)
            self.espeak_src = blocks.wavfile_source(self.ESPEAK_WAV, True)
            self.connect(self.espeak_src, self.espeak_gate)
            self.unlock()
        except Exception as e:
            self._log("ERROR GR reload: {}".format(e))
            return

        self.espeak_gate.set_k(1.0)
        self.mic_gate.set_k(0.0)
        self.mute_gate.set_k(1.0)

        short = text[:30] + ("..." if len(text) > 30 else "")
        self._log('eSpeak playing: "{}"'.format(short))

        # -- Auto-start recording when Save to Disk is the active output ------
        if self._save_panel.isEnabled() and not self._btn_record.isChecked():
            self._espeak_auto_record = True
            self._btn_record.setChecked(True)   # triggers _cb_record_toggle(True)
            self._log("Auto-recording eSpeak output", in_progress=True)

        # -- One-shot playback: cancel old timer, start new one ---------------
        if self._espeak_timer is not None:
            self._espeak_timer.stop()
        self._espeak_timer = QtCore.QTimer()
        self._espeak_timer.setSingleShot(True)
        self._espeak_timer.timeout.connect(self._on_espeak_playback_done)
        self._espeak_timer.start(total_ms)

    def _on_espeak_playback_done(self):
        """Fires when one-shot eSpeak playback finishes (speech + silence padding)."""
        self.espeak_gate.set_k(0.0)   # silence the source -- no loop heard
        self._log("eSpeak playback complete")
        if self._espeak_auto_record and self._btn_record.isChecked():
            self._espeak_auto_record = False
            self._btn_record.setChecked(False)   # auto-stop recording
        else:
            self._espeak_auto_record = False

    def _cb_record_toggle(self,recording):
        if recording:
            stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            self._record_path=os.path.expanduser('~/openvk2_{}.iq'.format(stamp))
            try:
                self.lock()
                self.disconnect(self.f2c,self.iq_recorder)
                self.iq_recorder=blocks.file_sink(
                    gr.sizeof_gr_complex,self._record_path)
                self.connect(self.f2c,self.iq_recorder)
                self.unlock()
            except Exception as e:
                self._log("ERROR starting record: {}".format(e)); return
            self._btn_record.setText("Recording...")
            self._btn_record.setStyleSheet(self._style_red())
            self._save_path_lbl.setText(os.path.basename(self._record_path))
            self._log("Recording IQ to disk",in_progress=True)
        else:
            try:
                self.lock()
                self.disconnect(self.f2c,self.iq_recorder)
                self.iq_recorder=blocks.null_sink(gr.sizeof_gr_complex)
                self.connect(self.f2c,self.iq_recorder)
                self.unlock()
            except Exception as e:
                self._log("ERROR stopping record: {}".format(e))
            self._btn_record.setText("Record IQ")
            self._btn_record.setStyleSheet(self._style_green())
            self._save_path_lbl.setText(self._SAVE_DESCRIPTION)
            self._log("Recording stopped")
            if self._chk_waterfall.isChecked() and self._record_path and _MPL_OK:
                self._log("Generating waterfall graph image",in_progress=True)
                QtWidgets.QApplication.processEvents()
                t=threading.Thread(target=self._generate_waterfall,
                                   args=(self._record_path,),daemon=True)
                t.start()

    def _generate_waterfall(self,iq_path):
        try:
            data=np.fromfile(iq_path,dtype=np.complex64)
            if len(data)<1024:
                self._log("Waterfall: recording too short"); return
            fft_size=1024; hop=512
            window=np.hanning(fft_size).astype(np.float32)
            n_frames=(len(data)-fft_size)//hop
            spec=np.zeros((n_frames,fft_size),dtype=np.float32)
            for i in range(n_frames):
                frame=data[i*hop:i*hop+fft_size]
                spec[i]=10.0*np.log10(
                    np.fft.fftshift(np.abs(np.fft.fft(frame*window))**2)+1e-10)
            sr=self.HACKRF_RATE; dur=n_frames*hop/sr
            fig,ax=plt.subplots(figsize=(12,5))
            ax.imshow(spec.T,aspect='auto',origin='lower',
                      extent=[-sr/2/1e6,sr/2/1e6,0,dur],cmap='inferno')
            ax.set_xlabel('Frequency offset (MHz)'); ax.set_ylabel('Time (s)')
            ax.set_title('OpenV2K Waterfall -- {}'.format(
                os.path.basename(iq_path)))
            plt.colorbar(ax.images[0],ax=ax,label='Power (dB)')
            plt.tight_layout()
            png=iq_path.replace('.iq','.png')
            plt.savefig(png,dpi=150); plt.close(fig)
            subprocess.Popen(['xdg-open',png])
            self._log("Waterfall saved: {}".format(os.path.basename(png)))
        except Exception as e:
            self._log("ERROR waterfall: {}".format(e))

    # =========================================================================
    #  WAV helpers
    # =========================================================================

    def _write_silence_wav(self,path):
        with wave.open(path,'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(self.AUDIO_RATE)
            wf.writeframes(np.zeros(self.AUDIO_RATE,dtype=np.int16).tobytes())

    def _write_samples_wav(self,path,samples,sr):
        s16=np.clip(samples*32767.0,-32768,32767).astype(np.int16)
        with wave.open(path,'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(sr); wf.writeframes(s16.tobytes())

    def closeEvent(self,event):
        self._level_timer.stop(); self.stop(); self.wait(); event.accept()


# =============================================================================
#  Entry point
# =============================================================================

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("OpenV2K")
    tb = OpenV2K(); tb.show(); tb.start()

    def _quit(sig=None,frame=None):
        tb.stop(); tb.wait(); app.quit()

    signal.signal(signal.SIGINT,  _quit)
    signal.signal(signal.SIGTERM, _quit)
    tick = QtCore.QTimer(); tick.start(200)
    tick.timeout.connect(lambda: None)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
