#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: Unlicense
# This is free and unencumbered software released into the public domain.
#
# OpenV2K154.py -- Zero-Crossing Pulse Transmitter
# ================================================
# Requirements:
#   sudo apt install gnuradio gr-osmosdr hackrf python3-pyqt5 espeak-ng
#   pip3 install matplotlib --break-system-packages
# Usage:
#   python3 OpenV2K154.py

import sys
import os
import re
import math
import time
import random
import wave
import signal
import xml.etree.ElementTree as ET
import locale
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
#  MBROLA voice detection
#  Requires: sudo apt install mbrola mbrola-en1
# =============================================================================

def _check_mbrola():
    """
    Return True only when both the mbrola binary AND en1 voice data are present.
    espeak-ng calls mbrola as a subprocess; if the binary is missing the synthesis
    silently produces no audio even though espeak-ng itself exits 0.
    """
    # 1. Check the mbrola binary is executable
    try:
        subprocess.run(['mbrola'], capture_output=True, timeout=2)
        # mbrola exits non-zero when called with no args but it ran
    except FileNotFoundError:
        return False          # binary not installed
    except subprocess.TimeoutExpired:
        pass                  # binary exists, just waiting for stdin

    # 2. Check for en1 voice data in common install paths
    voice_paths = [
        '/usr/share/mbrola/en1',
        '/usr/share/mbrola/en1/en1',
        '/usr/lib/mbrola/en1',
        '/usr/share/espeak-ng-data/voices/mb/mb-en1',
    ]
    return any(os.path.exists(p) for p in voice_paths)

_MBROLA_OK = _check_mbrola()


# =============================================================================
#  Localization: OS-locale detection + UI string translation table
# =============================================================================
#
#  _tr(key) looks up the current UI string in the detected OS language,
#  falling back to English if the language or the specific key is missing.
#  Only the most visible UI elements are translated (section headers, button
#  labels, checkbox labels, slider labels, and primary description text).
#  Tooltips remain English-only in this pass to keep the table a manageable
#  size -- ask to extend translation coverage to tooltips if needed.

# Embedded English-only fallback -- used ONLY if Translations.xml
# (checked next to this script at startup) can't be found or fails to
# parse.  When that happens the app still runs fully in English; the
# full 49-language table normally lives in Translations.xml instead
# of inline here.  See _load_translations_xml() below.
_TRANSLATIONS = {
'en': {
    'section_audio_input':        'Audio Input',
    'section_signal_processing':  'Signal Processing',
    'section_output':             'Output',
    'live_microphone':            'Live Microphone',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Audio Waveform Zero-Crossing Pulse Stream Generator',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mic Level: in silence -45 dB, aim for -18 dB when speaking.\n'
        'Adjust in your OS: System Settings > Sound > Input.',
    'mic_muted':                  'Mic: MUTED',
    'mic_live':                   'Mic: LIVE',
    'generate_voice':             'Generate Voice',
    'placeholder_hello':          'Hello World',
    'placeholder_enter_text':     'Enter Some Text Here',
    'optional_filters':           'Optional Filters',
    'power_calculation':            'Power Calculation',
    'power_reset':                  'Reset',
    'power_session_count':          'Session Pulse Count:',
    'power_last_action_count':      'Last TTS Action:',
    'power_total_energy':           'Total Energy Output:',
    'power_last_action_count':      'Last TTS Action:',
    'power_calc_title':             'High Power Calculator',
    'power_calc_summary':
        'Hypothetical energy output from a high-power microwave amplifier, '
        'for the current pulse width and pulse count.\n'
        '1500W is the FCC amateur radio power ceiling, and 4kW is the '
        'rated maximum output of the Exodus AMP20057.\n'
        'Metro area average weekly microwave exposure: ~18 Joules. '
        'Muzzle energy from a .22 LR rifle round: ~200 Joules.',
    'power_recommended':            'Ideal for 16mJ Pulses:',
    'power_per_pulse':              'Power Per Pulse:',
    'col_signal_conditioning':    'Signal Conditioning',
    'col_noise_silence':          'Noise / Silence',
    'col_zcr_shaping':            'ZCR Shaping',
    'filt_notch':                 '50/60 Hz Notch',
    'filt_preemph':               'Pre-emphasis',
    'filt_deemph':                 'De-emphasis',
    'filt_fricative':               'Fricative Suppressor',
    'filt_f1bandpass':              'F1 Formant Bandpass',
    'filt_decimate':              'Downsample / Decimate',
    'filt_noisegate':             'Noise Gate',
    'filt_envfollow':             'Envelope Follower',
    'filt_specsub':               'Spectral Subtraction',
    'filt_hwrect':                'Half-wave Rect.',
    'filt_schmitt':                'Schmitt Trigger',
    'filt_hilbert':                'Hilbert Envelope',
    'slider_pulse':                'Pulse (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Avg: 2-4%\nMax: 8%\n>6% over spec',
    'duty_cycle_label':            'Duty Cycle',
    'transmitter_freq':            'Frequency:',
    'transmitter_pwr':             'TX Power:',
    'tx_disabled':                 'TX: DISABLED',
    'tx_enabled':                  'TX: ENABLED',
    'tx_license':
        'A valid amateur radio license is required to '
        'transmit on these frequencies. '
        'Verify your national band plan.',
    'save_to_disk':                'Save to Disk',
    'save_description':
        'Saves raw IQ samples as complex64 binary.\n'
        'Two channels: I (real) and Q (imaginary).\n'
        'Compatible with GNU Radio, inspectrum,\n'
        'GQRX, and SDR# for offline analysis.\n'
        'Uses 16MB/sec, plan storage accordingly.',
    'record_iq':                   'Record IQ',
    'recording':                   'Recording...',
    'waterfall_checkbox':          'Generate Spectrogram Image',
    'event_log':                   'Event Log',
    'event_log_title':             '  OpenV2K  Event Log',
    'no_mbrola_voice':
        'No MBROLA voice available for this language -- '
        'using eSpeak formant synthesis instead.',
    # Tooltip strings (added when tooltips were translated)
    'tt_notch':
        'Narrow biquad notch filter (Q=30) targeting 50 or 60Hz AC power\n'
        'line hum and its harmonics.  Compatible with all other filters.',
    'tt_preemph':
        '+6 dB/octave boost above 1kHz via FIR [1, -0.9375].\n'
        'Sharpens consonants and sibilants, but works AGAINST reducing\n'
        'zero-crossing rate -- off by default for that reason.\n'
        '\n'
        'MUTUALLY EXCLUSIVE with De-emphasis (opposite spectral tilt):\n'
        'selecting this unchecks De-emphasis.',
    'tt_deemph':
        'Inverse of Pre-emphasis: a one-pole leaky integrator,\n'
        'y[n] = x[n] + 0.5*y[n-1], tilting the spectrum TOWARD the\n'
        'fundamental instead of away from it -- reduces high-frequency\n'
        'zero-crossing contribution.\n'
        '\n'
        'MUTUALLY EXCLUSIVE with Pre-emphasis (opposite spectral tilt):\n'
        'selecting this unchecks Pre-emphasis.',
    'tt_fricative':
        'Attenuates fricatives (s, f, sh, th) using a local zero-crossing\n'
        'rate estimate as a voicing detector -- fricatives are filtered\n'
        'noise with by far the highest ZCR in speech; voiced content is\n'
        'quasi-periodic and passes through with minimal attenuation.\n'
        'Soft ramp, not a hard gate -- avoids on/off artifacts.\n'
        'Compatible with all filters, but must run before HWR/Schmitt/\n'
        'Hilbert to see the raw voicing information it needs.',
    'tt_f1bandpass':
        'Restricts audio to ~300-900Hz, the typical first-formant (F1)\n'
        'range across vowels and speaker genders.  Aggressive: strips\n'
        'consonant detail and F2/F3, but guarantees a large ZCR\n'
        'reduction since almost nothing outside F1 survives.\n'
        'Compatible with all filters, though most others do less once\n'
        'this is active since so little spectrum remains.',
    'tt_decimate':
        '4kHz IIR anti-alias lowpass before ZCP.  Equivalent to soft\n'
        'decimation from 48kHz to 8kHz -- removes high-harmonic content\n'
        'that generates the most spurious zero crossings.\n'
        'Compatible with all filters.',
    'tt_noisegate':
        'Zeros audio when instantaneous RMS power falls below -30dB.\n'
        'Prevents noise and pauses from generating spurious zero crossings.\n'
        'Use with Envelope Follower or Spectral Subtraction, not all three.',
    'tt_envfollow':
        '5ms IIR envelope gate: passes signal above threshold, zeros below.\n'
        'Smoother than Noise Gate -- better preserves phoneme transitions.\n'
        'Use with Noise Gate or Spectral Subtraction, not all three.',
    'tt_specsub':
        'Estimates noise floor during quiet periods and applies a\n'
        'Wiener gain (floor 0.2) -- suppresses noise-floor ZCR without\n'
        'fully silencing weak phonemes.\n'
        'Compatible with all filters.',
    'tt_hwrect':
        'Replaces negatives with -0.05 so only positive-lobe boundaries\n'
        'produce zero crossings.  The -0.05 bias sits below the Schmitt\n'
        'low threshold (-0.01) so the Schmitt resets between each lobe.\n'
        'Compatible with all filters in this column.',
    'tt_schmitt':
        'Hysteresis: output switches to +/-0.5 at +/-0.01 thresholds.\n'
        'Eliminates noise jitter near zero -- ZCP fires on decisive\n'
        'threshold crossings only.\n'
        '\n'
        'MUTUALLY EXCLUSIVE with Hilbert Envelope: Schmitt outputs\n'
        'constant amplitude, so Hilbert Envelope has no signal to track.\n'
        'Selecting this unchecks Hilbert Envelope.',
    'tt_hilbert':
        'Replaces audio with (envelope - slow_mean): positive during\n'
        'active speech, negative during pauses.  ZCP fires at syllable\n'
        'onset/offset -- very few, rhythmically meaningful pulses.\n'
        '\n'
        'MUTUALLY EXCLUSIVE with Schmitt Trigger: Schmitt outputs\n'
        'constant amplitude, so Hilbert Envelope has no signal to track.\n'
        'Selecting this unchecks Schmitt Trigger.\n'
        'Also: with Hilbert active, duty-cycle meter reads near-zero\n'
        '(by design -- syllable rate = 2-10 Hz).',
    'tt_mbrola':
        'MBROLA: Concatenative diphone synthesis.\n'
        'Uses recorded phoneme segments instead of\n'
        'eSpeak formant synthesis, producing more\n'
        'natural speech with lower zero-crossing rate\n'
        'and a duty cycle closer to human voice.',
    'tt_accent': 'Choose a regional MBROLA accent for {}.',
},
}


_TRANSLATIONS_XML_LOADED = False   # set True if Translations.xml loaded OK


def _load_translations_xml():
    """
    Look for Translations.xml in the same directory as this script.  If
    found and it parses correctly, REPLACE _TRANSLATIONS with the full
    49-language table from the file.  If the file is missing or fails to
    parse, leave _TRANSLATIONS as the embedded English-only fallback
    (defined above) and the app continues to run in English -- the
    language dropdown gets disabled and forced to English/American
    elsewhere in _build_gui() once this function's return value is known.
    """
    global _TRANSLATIONS, _TRANSLATIONS_XML_LOADED
    script_dir = os.path.dirname(os.path.abspath(__file__))
    xml_path = os.path.join(script_dir, "Translations.xml")
    if not os.path.isfile(xml_path):
        return False
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        new_translations = {}
        for lang_el in root.findall('language'):
            code = lang_el.get('code')
            if not code:
                continue
            table = {}
            for str_el in lang_el.findall('string'):
                key = str_el.get('key')
                if key is not None:
                    table[key] = str_el.text or ''
            new_translations[code] = table
        if 'en' not in new_translations or not new_translations['en']:
            return False   # malformed file -- keep the English fallback
        _TRANSLATIONS = new_translations
        _TRANSLATIONS_XML_LOADED = True
        return True
    except Exception:
        return False   # malformed/unreadable XML -- keep English fallback


_load_translations_xml()


# Native autonyms for the language selector combobox, sorted alphabetically
# by native name at combobox build time.  Falls back to the ISO code itself
# if a language is somehow missing from this dict (should never happen).
_LANG_NAMES = {
    'en': 'English',
    'de': 'Deutsch',
    'fr': 'Français',
    'es': 'Español',
    'it': 'Italiano',
    'sv': 'Svenska',
    'no': 'Norsk',
    'ru': 'Русский',
    'hi': 'हिन्दी',
    'ja': '日本語',
    'zh': '中文',
    'ar': 'العربية',
    'bn': 'বাংলা',
    'pt': 'Português',
    'ur': 'اردو',
    'id': 'Bahasa Indonesia',
    'ms': 'Bahasa Melayu',
    'sw': 'Kiswahili',
    'tr': 'Türkçe',
    'vi': 'Tiếng Việt',
    'ko': '한국어',
    'fa': 'فارسی',
    'pa': 'ਪੰਜਾਬੀ',
    'te': 'తెలుగు',
    'mr': 'मराठी',
    'ta': 'தமிழ்',
    'pl': 'Polski',
    'ro': 'Română',
    'nl': 'Nederlands',
    'hu': 'Magyar',
    'el': 'Ελληνικά',
    'cs': 'Čeština',
    'hr': 'Hrvatski',
    'lt': 'Lietuvių',
    'uk': 'Українська',
    'ca': 'Català',
    'fi': 'Suomi',
    'bg': 'Български',
    'sr': 'Српски',
    'bs': 'Bosanski',
    'da': 'Dansk',
    'sk': 'Slovenčina',
    'be': 'Беларуская',
    'et': 'Eesti',
    'is': 'Íslenska',
    'lv': 'Latviešu',
    'lb': 'Lëtzebuergesch',
    'mn': 'Монгол',
    'mi': 'Te Reo Māori',
}

# English name of each language, shown in the combobox as
# "Native Name  (English Name)" -- two-space prefix before the parenthesis.
_LANG_NAMES_EN = {
    'en': 'English',
    'de': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'it': 'Italian',
    'sv': 'Swedish',
    'no': 'Norwegian',
    'ru': 'Russian',
    'hi': 'Hindi',
    'ja': 'Japanese',
    'zh': 'Chinese',
    'ar': 'Arabic',
    'bn': 'Bengali',
    'pt': 'Portuguese',
    'ur': 'Urdu',
    'id': 'Indonesian',
    'ms': 'Malay',
    'sw': 'Swahili',
    'tr': 'Turkish',
    'vi': 'Vietnamese',
    'ko': 'Korean',
    'fa': 'Persian',
    'pa': 'Punjabi',
    'te': 'Telugu',
    'mr': 'Marathi',
    'ta': 'Tamil',
    'pl': 'Polish',
    'ro': 'Romanian',
    'nl': 'Dutch',
    'hu': 'Hungarian',
    'el': 'Greek',
    'cs': 'Czech',
    'hr': 'Croatian',
    'lt': 'Lithuanian',
    'uk': 'Ukrainian',
    'ca': 'Catalan',
    'fi': 'Finnish',
    'bg': 'Bulgarian',
    'sr': 'Serbian',
    'bs': 'Bosnian',
    'da': 'Danish',
    'sk': 'Slovak',
    'be': 'Belarusian',
    'et': 'Estonian',
    'is': 'Icelandic',
    'lv': 'Latvian',
    'lb': 'Luxembourgish',
    'mn': 'Mongolian',
    'mi': 'Maori',
}


def _detect_locale():
    """
    Detect the OS locale language code (e.g. 'de', 'fr', 'ja') from Python's
    locale module, falling back to environment variables, then to English
    if nothing is detected or the language isn't in _TRANSLATIONS.
    """
    lang = None
    try:
        lang, _enc = locale.getlocale()
    except Exception:
        lang = None
    if not lang:
        try:
            lang, _enc = locale.getdefaultlocale()
        except Exception:
            lang = None
    if not lang:
        lang = (os.environ.get('LANG') or os.environ.get('LC_ALL')
                or os.environ.get('LANGUAGE') or '')
    if not lang:
        return 'en'
    code = lang.split('_')[0].split('.')[0].split(':')[0].lower()
    _ALIASES = {'nb': 'no', 'nn': 'no', 'cmn': 'zh', 'zh-hans': 'zh',
               'zh-hant': 'zh', 'zh-cn': 'zh', 'zh-tw': 'zh'}
    code = _ALIASES.get(code, code)
    return code if code in _TRANSLATIONS else 'en'


_CURRENT_LANG = _detect_locale()


def _tr(key):
    """
    Look up a UI string in the detected OS language.  Falls back to English
    if the language table or the specific key is missing, and to the raw
    key itself as a last resort (should never happen for valid keys).
    """
    table = _TRANSLATIONS.get(_CURRENT_LANG, {})
    val = table.get(key)
    if val:
        return val
    return _TRANSLATIONS['en'].get(key, key)


# ---- espeak-ng / MBROLA voice selection by detected locale ----------------

_ESPEAK_VOICE_MAP = {
    'en': 'en-us', 'de': 'de', 'fr': 'fr', 'es': 'es', 'it': 'it',
    'sv': 'sv', 'no': 'nb', 'ru': 'ru', 'hi': 'hi', 'ja': 'ja',
    'zh': 'cmn', 'ar': 'ar',
    # Added in this pass:
    'bn': 'bn', 'pt': 'pt', 'ur': 'ur', 'id': 'id', 'ms': 'ms',
    'sw': 'sw', 'tr': 'tr', 'vi': 'vi', 'ko': 'ko', 'fa': 'fa',
    'pa': 'pa', 'te': 'te', 'mr': 'mr', 'ta': 'ta',
    # Added in this pass (European batch):
    'pl': 'pl', 'ro': 'ro', 'nl': 'nl', 'hu': 'hu', 'el': 'el',
    'cs': 'cs', 'hr': 'hr', 'lt': 'lt', 'uk': 'uk', 'ca': 'ca',
    'fi': 'fi', 'bg': 'bg', 'sr': 'sr', 'bs': 'bs', 'da': 'da',
    'sk': 'sk',
    # Added in this pass (country-list batch):
    'be': 'be', 'et': 'et', 'is': 'is', 'lv': 'lv', 'lb': 'lb',
    'mn': 'mn', 'mi': 'mi',
}

# Locale -> MBROLA voice code, limited to languages with a commonly
# available Debian mbrola-* voice package.  Languages not listed here have
# no widely-packaged MBROLA voice; the app falls back to eSpeak's own
# formant synthesis in that language and logs a friendly notice.
#
# Verified against the Debian mbrola-voice package list (packages.debian.org):
# pt1 (European Portuguese), tr1/tr2 (Turkish), id1 (Indonesian),
# ma1 (Malay), ir1 (Farsi/Persian), and tl1 (Telugu) are all real packages.
# Note: mbrola sw1/sw2 are SWEDISH voices, not Swahili -- Swahili has no
# packaged MBROLA voice despite the misleading 'sw' prefix, so it is
# correctly omitted here and falls back to formant synthesis.
# Bengali, Urdu, Vietnamese, Korean, Punjabi, Marathi, and Tamil also have
# no widely-packaged MBROLA voice and fall back to formant synthesis.
#
# European batch: pl1 (Polish), ro1 (Romanian), nl2 (Dutch), hu1 (Hungarian),
# gr2 (Greek), cz2 (Czech), and cr1 (Croatian) are real MBROLA packages.
# IMPORTANT: mbrola 'ca1'/'ca2' are CANADIAN FRENCH voices, NOT Catalan --
# same naming trap as sw1/sw2 being Swedish, not Swahili.  Catalan is
# correctly OMITTED from this map and falls back to formant synthesis;
# mapping 'ca' (Catalan locale) to 'ca1' would incorrectly speak Canadian
# French.  Lithuanian, Ukrainian, Finnish, Bulgarian, Serbian, Bosnian,
# Danish, and Slovak also have no widely-packaged MBROLA voice.
#
# Country-list batch: ee1 (Estonian) and ic1 (Icelandic) are real MBROLA
# packages.  Belarusian, Latvian, Luxembourgish, and Mongolian have no
# widely-packaged MBROLA voice.
#
# CORRECTION from an earlier version of this comment: MBROLA's 'nz1' voice
# actually IS Maori (male, recorded by Mark R. Laws) -- confirmed against
# the official numediart/MBROLA-voices repository and espeak-ng's own docs.
# An earlier pass here incorrectly guessed it was New Zealand-accented
# English by analogy with the sw1/ca1 naming traps; that guess was wrong
# and has been corrected.  nz1 is now correctly mapped to 'mi' below.
_MBROLA_VOICE_MAP = {
    'en': 'us1',
    'de': 'de6',
    'fr': 'fr4',
    'es': 'mx1',
    'it': 'it4',
    'pt': 'br1',
    'id': 'id1',
    'ms': 'ma1',
    'tr': 'tr1',
    'fa': 'ir1',
    'te': 'tl1',
    'pl': 'pl1',
    'ro': 'ro1',
    'nl': 'nl2',
    'hu': 'hu1',
    'el': 'gr2',
    'cs': 'cz2',
    'hr': 'cr1',
    'et': 'ee1',
    'is': 'ic1',
    'mi': 'nz1',
}

# Languages with more than one genuine national/regional MBROLA accent --
# i.e. different countries' pronunciation standard for the same language,
# not just a different speaker/gender of the same accent.  Each list's
# FIRST entry matches that language's default code in _MBROLA_VOICE_MAP
# above, so index 0 always represents "no change from the current default".
# Defaults are set to the most-spoken national variant of each language
# by population, not the historical/European origin: American English
# (~330M) over British (~65M); Mexican Spanish (~130M, the single largest
# Spanish-speaking country) over Spain (~47M) or Venezuela (~28M);
# Brazilian Portuguese (~215M, ~95% of all native Portuguese speakers)
# over European Portuguese (~10M).  French stays France-default since
# France's ~65M native speakers already exceed Quebec's ~7-8M.
# The many same-accent multi-speaker voices (de1-de8, it1-it4, fr1-fr7,
# etc.) are NOT accent choices -- they're just different voice actors of
# one standard accent, so they aren't exposed here.
_MBROLA_ACCENTS = {
    'en': [('American',   'us1'), ('British',   'en1')],
    'es': [('Mexico',     'mx1'), ('Spain',     'es1'), ('Venezuela', 'vz1')],
    'pt': [('Brazil',     'br1'), ('Portugal',  'pt1')],
    'fr': [('France',     'fr4'), ('Quebec',    'ca1')],
}


def _check_mbrola_voice(code):
    """Return True if the given MBROLA voice's data files are present."""
    if not code:
        return False
    candidates = [
        '/usr/share/mbrola/{0}'.format(code),
        '/usr/share/mbrola/{0}/{0}'.format(code),
        '/usr/lib/mbrola/{0}'.format(code),
    ]
    return any(os.path.exists(p) for p in candidates)


def _recompute_locale_voices():
    """
    (Re)compute the espeak-ng and MBROLA voice globals from the current
    _CURRENT_LANG.  Called once at import time and again whenever the user
    switches languages via the language selector combobox, so that eSpeak
    synthesis follows the selected UI language, not just the OS locale.
    """
    global _LOCALE_ESPEAK_VOICE, _LOCALE_MBROLA_CODE, _LOCALE_MBROLA_OK
    _LOCALE_ESPEAK_VOICE = _ESPEAK_VOICE_MAP.get(_CURRENT_LANG, 'en-us')
    _LOCALE_MBROLA_CODE  = _MBROLA_VOICE_MAP.get(_CURRENT_LANG)
    _LOCALE_MBROLA_OK    = bool(_LOCALE_MBROLA_CODE) and \
                            _check_mbrola_voice(_LOCALE_MBROLA_CODE)


_recompute_locale_voices()



# =============================================================================
#  Startup dependency report
#  Runs before the GUI starts so the user gets clear install instructions
#  instead of a Python traceback.  Exits on any critical missing package.
# =============================================================================

def check_prerequisites():
    OK   = '  OK       '
    WARN = '  OPTIONAL '
    ERR  = '  MISSING  '

    missing = []
    print("OpenV2K -- dependency check")
    print("-" * 52)

    # Python modules (critical)
    for mod, label, pkg in [
        ('gnuradio', 'GNU Radio',  'sudo apt install gnuradio'),
        ('osmosdr',  'gr-osmosdr', 'sudo apt install gr-osmosdr'),
        ('PyQt5',    'PyQt5',      'sudo apt install python3-pyqt5'),
        ('numpy',    'numpy',      'sudo apt install python3-numpy'),
    ]:
        try:
            __import__(mod)
            print("{}{}" .format(OK, label))
        except ImportError:
            print("{}{}  ->  {}".format(ERR, label, pkg))
            missing.append(label)

    # espeak-ng (critical)
    espeak_ok = False
    for cmd in ['espeak-ng', 'espeak']:
        try:
            subprocess.run([cmd, '--version'], capture_output=True, timeout=3)
            print("{}{}".format(OK, cmd))
            espeak_ok = True
            break
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            print("{}{}".format(OK, cmd)); espeak_ok = True; break
    if not espeak_ok:
        print("{}espeak-ng  ->  sudo apt install espeak-ng".format(ERR))
        missing.append('espeak-ng')

    # hackrf tools (optional)
    try:
        subprocess.run(['hackrf_info'], capture_output=True, timeout=5)
        print("{}hackrf tools".format(OK))
    except FileNotFoundError:
        print("{}hackrf tools  ->  sudo apt install hackrf".format(WARN))
    except subprocess.TimeoutExpired:
        print("{}hackrf tools".format(OK))

    # matplotlib (optional)
    try:
        import matplotlib
        print("{}matplotlib  (waterfall graphs)".format(OK))
    except ImportError:
        print("{}matplotlib  ->  pip3 install matplotlib --break-system-packages"
              .format(WARN))

    # MBROLA (optional) -- reports on the voice matching the detected OS
    # locale, plus how to install the complete set of all supported MBROLA
    # voices at once (18 languages -- see _MBROLA_VOICE_MAP).
    _all_mbrola_codes = sorted(set(_MBROLA_VOICE_MAP.values()))
    _all_mbrola_pkgs  = ' '.join('mbrola-{}'.format(c) for c in _all_mbrola_codes)

    if _LOCALE_MBROLA_OK:
        print("{}mbrola + {}  (MBROLA synthesis, locale={})".format(
            OK, _LOCALE_MBROLA_CODE, _CURRENT_LANG))
    elif _LOCALE_MBROLA_CODE:
        print("{}mbrola-{}  ->  sudo apt install mbrola mbrola-{}".format(
            WARN, _LOCALE_MBROLA_CODE, _LOCALE_MBROLA_CODE))
        print("             (voice for your detected locale, '{}', only)"
              .format(_CURRENT_LANG))
    else:
        print("{}no packaged MBROLA voice for locale '{}' -- "
              "using eSpeak formant synthesis".format(WARN, _CURRENT_LANG))
    print("             Install every supported MBROLA voice at once ({}):"
          .format(len(_all_mbrola_codes)))
    print("             sudo apt install mbrola {}".format(_all_mbrola_pkgs))

    print("-" * 52)
    if missing:
        print("Cannot start -- missing required package(s): {}"
              .format(', '.join(missing)))
        print("Install the packages listed above and retry.\n")
        sys.exit(1)
    print("All required dependencies present.\n")


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
            return False, "HackRF not connected"
        if 'Found HackRF' not in output and 'HackRF One' not in output:
            return False, "HackRF not detected"
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
        return True, "HackRF One found, FW: {}".format(firmware)
    except FileNotFoundError:
        return False, "hackrf_info not found -- sudo apt install hackrf"
    except subprocess.TimeoutExpired:
        return False, "hackrf_info timed out -- check USB connection"
    except Exception as e:
        return False, "Detection error: {}".format(e)


# =============================================================================
#  GNU Radio blocks
# =============================================================================

class ZeroCrossPulse(gr.sync_block):
    def __init__(self, sample_rate=48000.0, pulse_width_us=100.0):
        gr.sync_block.__init__(self, name="Zero Cross Pulse",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._sr = float(sample_rate); self._pw_us = float(pulse_width_us)
        self._last = 0.0; self._rem = 0; self._recompute()
        self._pulse_count = 0        # session total, reset only by Reset button
        self._last_action_count = 0  # since the last Generate Voice press

    def set_pulse_width_us(self, v): self._pw_us = float(v); self._recompute()
    def set_sample_rate(self, v):    self._sr    = float(v); self._recompute()
    def get_pulse_count(self):       return self._pulse_count
    def reset_pulse_count(self):     self._pulse_count = 0
    def get_last_action_count(self):   return self._last_action_count
    def reset_last_action_count(self): self._last_action_count = 0

    def _recompute(self):
        self._plen = max(1, int(round(self._sr * self._pw_us * 1e-6)))

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        last, rem, plen = self._last, self._rem, self._plen
        count, last_action = self._pulse_count, self._last_action_count
        for i in range(len(in0)):
            curr = float(in0[i])
            if (last < 0.0 <= curr) or (last >= 0.0 > curr):
                rem = plen
                count += 1        # one new pulse triggered
                last_action += 1
            out[i] = 1.0 if rem > 0 else 0.0
            if rem > 0: rem -= 1
            last = curr
        self._last, self._rem = last, rem
        self._pulse_count, self._last_action_count = count, last_action
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


class EnvelopeFollower(gr.sync_block):
    """
    5ms IIR envelope gate: passes the signal when short-term amplitude
    exceeds a threshold; outputs zero during pauses and low-energy regions.
    Smoother than the instantaneous Noise Gate -- preserves transitions.
    """
    def __init__(self, sample_rate=48000, tc=0.005, thresh=0.003):
        gr.sync_block.__init__(self, "Envelope Follower",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False
        self._alpha   = 1.0 - math.exp(-1.0 / (sample_rate * tc))
        self._thresh  = float(thresh)
        self._env     = 0.0

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0; return len(in0)
        alpha, thresh, env = self._alpha, self._thresh, self._env
        for i in range(len(in0)):
            s   = float(in0[i])
            env = alpha * abs(s) + (1.0 - alpha) * env
            out[i] = s if env > thresh else 0.0
        self._env = env
        return len(in0)


class HalfWaveRectifier(gr.sync_block):
    """
    Clips all negative samples to zero.  The waveform then only transitions
    from positive down to zero, roughly halving the zero-crossing rate.
    """
    def __init__(self):
        gr.sync_block.__init__(self, "Half Wave Rect",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0
        else:
            # Negatives are set to -0.05 (well below the Schmitt lo threshold
            # of -0.01) so the Schmitt trips back to -0.5 between each positive
            # lobe.  -1e-6 was too small: the Schmitt locked high after the
            # first lobe and ZCP saw only a single pulse.
            out[:] = np.where(in0 > 0.0, in0, np.float32(-0.05))
        return len(in0)


class HilbertEnvelopeExtractor(gr.sync_block):
    """
    Replaces audio with its amplitude envelope minus a slow-tracking mean.
    Output is positive during above-average activity (vowels) and negative
    during below-average activity (pauses).  ZCP fires at syllable onset /
    offset rather than at carrier frequency -- very few pulses per second.
    """
    def __init__(self, sample_rate=48000, tc_env=0.020, tc_mean=0.500):
        gr.sync_block.__init__(self, "Hilbert Envelope",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled    = False
        self._a_env  = 1.0 - math.exp(-1.0 / (sample_rate * tc_env))
        self._a_mean = 1.0 - math.exp(-1.0 / (sample_rate * tc_mean))
        self._env    = 0.0
        self._mean   = 0.0

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0; return len(in0)
        a_e, a_m, env, mean = (self._a_env, self._a_mean,
                               self._env,  self._mean)
        for i in range(len(in0)):
            env  = a_e * abs(float(in0[i])) + (1.0 - a_e) * env
            mean = a_m * env               + (1.0 - a_m) * mean
            out[i] = env - mean   # bipolar: + during speech, - during silence
        self._env, self._mean = env, mean
        return len(in0)


class Decimator(gr.sync_block):
    """
    4kHz IIR anti-alias lowpass before ZCP -- equivalent to soft decimation
    from 48kHz to 8kHz.  Removes high-frequency harmonic content above the
    speech intelligibility range that generates spurious zero crossings.
    """
    def __init__(self, sample_rate=48000, fc=4000.0):
        gr.sync_block.__init__(self, "Decimator",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False
        self._alpha   = 1.0 - math.exp(-2.0 * math.pi * fc / sample_rate)
        self._state   = 0.0

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0; return len(in0)
        a, s = self._alpha, self._state
        for i in range(len(in0)):
            s = s + a * (float(in0[i]) - s)
            out[i] = s
        self._state = s
        return len(in0)


class DCBlocker(gr.sync_block):
    """
    One-pole DC blocker, implemented explicitly in Python rather than
    via GNU Radio's iir_filter_ffd block:

        y[n] = x[n] - x[n-1] + R*y[n-1]        (R close to but below 1)

    DEBUGGING NOTE (ringing/ghosting investigation): found during this
    investigation that the feedback coefficient's SIGN differs between
    the last-known-good baseline (v78: iir_filter_ffd([1,-1],[-0.999]))
    and the current version (iir_filter_ffd([1,-1],[0.999])) -- exactly
    the kind of add-vs-subtract convention ambiguity that ALSO caused
    the notch filter's earlier bug (see NotchFilter's docstring), which
    was only fully resolved there by dropping iir_filter_ffd entirely
    for an explicit direct-form implementation.  Simulating both
    coefficient signs under both possible conventions confirms one
    combination properly removes DC while passing other frequencies,
    and the other doesn't -- but which one iir_filter_ffd's internal
    convention actually matches can't be verified from this environment
    (no GNU Radio runtime available here to test the real block
    directly).  Rather than guess, this sidesteps the ambiguity
    completely: the formula above is the standard, well-known-correct
    DC blocker difference equation, verified numerically against a
    DC-plus-tone test signal, with no GNU Radio IIR block involved at
    all.
    """
    def __init__(self, sample_rate=48000.0, r=0.999):
        gr.sync_block.__init__(self, "DC Blocker",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._r = float(r)
        self._x1 = 0.0
        self._y1 = 0.0

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        r = self._r
        x1, y1 = self._x1, self._y1
        for i in range(len(in0)):
            x0 = float(in0[i])
            y0 = x0 - x1 + r*y1
            out[i] = y0
            x1, y1 = x0, y0
        self._x1, self._y1 = x1, y1
        return len(in0)


class NotchFilter(gr.sync_block):
    """
    Direct-Form biquad notch filter (RBJ Audio EQ Cookbook), implemented
    explicitly in Python rather than via GNU Radio's iir_filter_ffd block.

    An earlier version used iir_filter_ffd with the RBJ a1/a2 coefficients
    negated to compensate for that block's add-vs-subtract feedback
    convention.  Pole analysis showed that fix was mathematically stable
    (|pole|=0.9999), yet the notch still caused total signal loss when
    enabled in practice -- so rather than guess at the exact internal
    convention a third time, this implementation writes the RBJ difference
    equation directly:

        y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]

    with NO GNU Radio IIR block involved at all, removing any possibility
    of a convention mismatch.  Same math, same stable pole placement,
    guaranteed-correct implementation.
    """
    def __init__(self, sample_rate=48000.0, f0=60.0, Q=6.0):
        # DEBUGGING NOTE (ringing/ghosting investigation): Q was 30
        # (2Hz bandwidth), which pole analysis showed decays to ~99%
        # only after ~800ms -- long enough for a loud transient's
        # ringing tail to bleed into and duplicate several subsequent
        # syllables, closely matching the reported "burst, echo,
        # fainter echo" symptom.  Q=6 (10Hz bandwidth) still safely
        # avoids speech fundamentals (which start ~85Hz+) while cutting
        # the ringing tail to ~160ms, a ~5x reduction.  This is the
        # highest-confidence, most conservative fix from this session's
        # investigation; if ringing is still audible after this change,
        # a lower Q (e.g. 4) or a shorter test tone should isolate
        # whether other blocks (AGC, envelope followers) also
        # contribute -- see the accompanying batch-plan notes.
        gr.sync_block.__init__(self, "Notch Filter",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False
        self._sr = float(sample_rate)
        self._f0 = float(f0)
        self._Q  = float(Q)
        self._x1 = 0.0; self._x2 = 0.0
        self._y1 = 0.0; self._y2 = 0.0
        self._recompute()

    def _recompute(self):
        w0    = 2.0 * math.pi * self._f0 / self._sr
        alpha = math.sin(w0) / (2.0 * self._Q)
        cw    = math.cos(w0)
        a0    = 1.0 + alpha
        self._b0 = 1.0 / a0
        self._b1 = -2.0 * cw / a0
        self._b2 = 1.0 / a0
        self._a1 = -2.0 * cw / a0
        self._a2 = (1.0 - alpha) / a0

    def set_enabled(self, e):
        self._enabled = bool(e)
        if e:
            # Clear filter state on enable -- avoids any stale-state
            # transient carried over from a previous session.
            self._x1 = 0.0; self._x2 = 0.0
            self._y1 = 0.0; self._y2 = 0.0

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0
            return len(in0)
        b0, b1, b2 = self._b0, self._b1, self._b2
        a1, a2     = self._a1, self._a2
        x1, x2, y1, y2 = self._x1, self._x2, self._y1, self._y2
        for i in range(len(in0)):
            x0 = float(in0[i])
            y0 = b0*x0 + b1*x1 + b2*x2 - a1*y1 - a2*y2
            out[i] = y0
            x2, x1 = x1, x0
            y2, y1 = y1, y0
        self._x1, self._x2, self._y1, self._y2 = x1, x2, y1, y2
        return len(in0)


class SchmittFilter(gr.sync_block):
    """
    Schmitt trigger hysteresis: snaps output to +0.5 / -0.5 once the signal
    crosses upper / lower thresholds.  Eliminates noise-driven toggling near
    zero -- ZCP only fires when the signal makes a decisive crossing.
    """
    def __init__(self, hi=0.01, lo=-0.01):
        gr.sync_block.__init__(self, "Schmitt",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled = False
        self._hi      = float(hi)
        self._lo      = float(lo)
        self._state   = -0.5   # start in the low state

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0; return len(in0)
        hi, lo, state = self._hi, self._lo, self._state
        for i in range(len(in0)):
            s = float(in0[i])
            if   s > hi: state =  0.5
            elif s < lo: state = -0.5
            out[i] = state
        self._state = state
        return len(in0)


class SpectralSubtractor(gr.sync_block):
    """
    Estimates the background noise floor during quiet periods and applies
    a Wiener-filter-inspired gain that suppresses near-noise-floor signals.
    Reduces ZCR contribution from room noise and microphone hiss.

    DEBUGGING NOTE (ringing/ghosting investigation): the gain used to have
    a hard floor of 0.2 ("never full silence" -- a legitimate, deliberate
    technique in general-purpose audio denoising, avoiding the harsh
    on/off "musical noise" artifacts an aggressive gate can produce).  But
    for THIS application, feeding a zero-crossing pulse generator that
    fires on any nonzero crossing regardless of how small, a gain that
    can never reach true zero means the signal can never go genuinely
    silent -- letting a low-level residual through continuously, which
    the pulse generator then dutifully turns into real, if faint,
    RF pulses.

    This was invisible for a long time because two OTHER gates
    (Noise Gate, Envelope Follower) used to run by default alongside this
    one, both capable of reaching a true hard zero -- as long as EITHER
    of them fully zeroed the signal before it reached here, 0.0 * 0.2 is
    still 0.0, so the floor never mattered in practice.  Envelope
    Follower's default was changed to OFF earlier in this development
    session (to avoid all three noise/silence filters running
    simultaneously) -- removing that redundancy and letting this floor's
    effect become directly visible for the first time.  Fixed at the
    root instead of restoring the redundant gate: floor removed entirely
    so this stage can reach true silence on its own, regardless of which
    other filters happen to be enabled.
    """
    def __init__(self, sample_rate=48000):
        gr.sync_block.__init__(self, "Spectral Sub",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled  = False
        self._a_fast   = 1.0 - math.exp(-1.0 / (sample_rate * 0.005))  # 5ms
        self._a_noise  = 1.0 - math.exp(-1.0 / (sample_rate * 2.0))    # 2s
        self._env      = 0.0
        self._noise    = 1e-8

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0; return len(in0)
        af, an, env, noise = (self._a_fast, self._a_noise,
                              self._env,    self._noise)
        for i in range(len(in0)):
            s   = float(in0[i])
            env = af * abs(s) + (1.0 - af) * env
            # Update noise floor only during quiet periods
            if env < noise * 2.0:
                noise = an * env + (1.0 - an) * noise
            # Wiener gain: 0 at noise floor, approaches 1 as signal >> noise.
            # No floor -- can reach true zero (see class docstring).
            snr  = env / (noise + 1e-10)
            gain = snr / (snr + 1.0)
            out[i] = s * gain
        self._env, self._noise = env, noise
        return len(in0)


class FricativeSuppressor(gr.sync_block):
    """
    Attenuates unvoiced/fricative segments (s, f, sh, th and consonant
    release bursts) using a local zero-crossing-rate estimate as a cheap
    voicing detector.  Fricatives are essentially filtered noise -- no
    real periodicity -- and have by far the highest ZCR of anything in
    speech.  Voiced content (vowels, most consonants) is quasi-periodic,
    driven by vocal fold vibration at F0, and its ZCR is bounded by pitch.
    Nothing else in the chain distinguishes these two classes; everything
    else keys off amplitude (Noise Gate, Envelope Follower), a static
    noise floor (Spectral Subtraction), or reshapes the waveform envelope
    (HWR, Schmitt, Hilbert).  This filter targets the single worst ZCR
    contributor in natural speech directly, rather than shaping around it.

    Detection runs on the RAW incoming signal (before HWR/Schmitt/Hilbert
    remove the very periodicity information this filter needs), so it
    must sit early in the chain, upstream of those waveform-reshaping
    stages -- see the Signal Conditioning grouping in the chain order.

    Gain is a soft ramp between zcr_lo and zcr_hi, not a hard gate, to
    avoid audible on/off artifacts at the voiced/unvoiced boundary.
    """
    def __init__(self, sample_rate=48000, tc=0.010,
                zcr_lo=0.08, zcr_hi=0.25, min_gain=0.15):
        gr.sync_block.__init__(self, "Fricative Suppressor",
                               in_sig=[np.float32], out_sig=[np.float32])
        self._enabled  = False
        self._alpha    = 1.0 - math.exp(-1.0 / (sample_rate * tc))
        self._zcr_lo   = float(zcr_lo)    # below this -> full pass (voiced)
        self._zcr_hi   = float(zcr_hi)    # above this -> min_gain (fricative)
        self._min_gain = float(min_gain)  # floor gain, never full silence
        self._zcr      = 0.0
        self._prev     = 0.0

    def set_enabled(self, e): self._enabled = bool(e)

    def work(self, input_items, output_items):
        in0, out = input_items[0], output_items[0]
        if not self._enabled:
            out[:] = in0; return len(in0)
        a, zlo, zhi, gmin = self._alpha, self._zcr_lo, self._zcr_hi, self._min_gain
        zcr, prev = self._zcr, self._prev
        for i in range(len(in0)):
            s = float(in0[i])
            crossed = 1.0 if (s >= 0.0) != (prev >= 0.0) else 0.0
            zcr = a * crossed + (1.0 - a) * zcr
            prev = s
            if zcr <= zlo:
                gain = 1.0
            elif zcr >= zhi:
                gain = gmin
            else:
                t = (zcr - zlo) / (zhi - zlo)
                gain = 1.0 - t * (1.0 - gmin)
            out[i] = s * gain
        self._zcr, self._prev = zcr, prev
        return len(in0)



# =============================================================================


def _cleanup_orphans():
    """
    Kill any previous OpenV2K python processes and stale temp WAV files.
    Graceful: SIGTERM first, then SIGKILL after a 500ms grace period.
    Also removes temp WAVs so the GR wavfile_source starts clean.
    """
    import signal as _sig
    import time   as _time

    # Kill previous OpenV2K python3 processes (not ourselves)
    try:
        import subprocess as _sp
        r = _sp.run(['pgrep', '-f', 'OpenV2K'],
                    capture_output=True, text=True, timeout=3)
        pids = [int(p) for p in r.stdout.split() if p.strip()]
        pids = [p for p in pids if p != os.getpid()]
        for pid in pids:
            try: os.kill(pid, _sig.SIGTERM)
            except: pass
        if pids:
            _time.sleep(0.5)           # 500ms grace period
            for pid in pids:
                try: os.kill(pid, _sig.SIGKILL)
                except: pass
        if pids:
            print("OpenV2K: cleaned up {} orphaned process(es).".format(
                len(pids)))
    except Exception:
        pass

    # Remove stale temp WAVs so wavfile_source never reads old data
    for path in ['/tmp/openv2k_espeak.wav', '/tmp/openv2k_espeak_raw.wav']:
        try: os.remove(path)
        except: pass
    """Suppress QSocketNotifier non-Qt-thread warning from GR audio.source.
    The warning also causes the first mouse click to be swallowed."""
    import sys as _sys
    def _handler(msg_type, context, msg):
        if 'QSocketNotifier' in msg:
            return
        if msg_type >= 2:
            print(msg, file=_sys.stderr)
    QtCore.qInstallMessageHandler(_handler)


class _EspeakBox(QtWidgets.QTextEdit):
    """QTextEdit that triggers Generate Voice on Enter instead of a newline."""
    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            btn = self.property("generate_btn")
            if btn is not None and btn.isEnabled():
                btn.click()
        else:
            super().keyPressEvent(event)


class SwapPanel(QtWidgets.QWidget):
    """
    A panel that can show a solid grey overlay when 'inactive' (used for
    the Mic/eSpeak input-source swap panels and the TX/Save output
    panels).

    The panel is a single flat solid-grey fill, right up to (and 1px
    past, on the SwapButton-facing side) its own edges.  No feathering --
    the old top/bottom "stacked box" step gradient was removed since it
    no longer meshes visually with the new SwapButton-side fade.  The 1px
    overshoot on the divider_side edge closes a rounding gap that showed
    up between this panel's own rect and the neighbouring SwapButton's
    gradient (visible as a thin sliver of background colour between the
    two when they should butt up against each other exactly).
    """
    def __init__(self, parent=None, divider_side='right'):
        super().__init__(parent)
        self._dim_active = False
        self._dim_color = QtGui.QColor("#b8b8b8")
        self._divider_side = divider_side   # 'left' or 'right' -- which
                                             # edge of this panel faces
                                             # its SwapButton; that edge
                                             # is extended 1px to close
                                             # the rounding gap

    def set_dimmed(self, dimmed):
        self._dim_active = bool(dimmed)
        self.update()

    def paintEvent(self, event):
        if self._dim_active:
            p = QtGui.QPainter(self)
            r = self.rect()
            if self._divider_side == 'left':
                r = r.adjusted(-1, 0, 0, 0)
            else:
                r = r.adjusted(0, 0, 1, 0)
            p.fillRect(r, self._dim_color)
        super().paintEvent(event)


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

    def set_label_text(self, text):
        """Update the header text and recompute font metrics for retranslation."""
        self._text = text
        fm = QtGui.QFontMetrics(self._font)
        self._tw = fm.horizontalAdvance(text)
        self.update()

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
    """
    The small round toggle sitting between each panel pair (Mic/eSpeak,
    TX/Save), used to swap which one is active.

    Also draws the fade effect for whichever neighbouring panel is
    currently disabled: solid grey at the edge facing that panel,
    transitioning to background colour by this widget's own centre line
    (the "divider line" that visually bisects it).  This is drawn in
    SwapButton's OWN paintEvent -- which Qt renders BEFORE the child
    QPushButton paints on top of it -- so the fade sits entirely behind
    the clickable circle and never obstructs it.  The neighbouring
    SwapPanel itself stays 100% solid grey right up to its own edge; all
    of the fade lives here instead.
    """
    BTN_D = 30; W = 44
    clicked = QtCore.pyqtSignal()
    _DIM_COLOR = QtGui.QColor("#b8b8b8")
    _BG_COLOR  = QtGui.QColor("#FFFFFF")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.W)
        self._left_dimmed = False
        self._right_dimmed = False
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0,0,0,0); vbox.setSpacing(0)
        vbox.addStretch(1)
        r = self.BTN_D // 2
        self._btn = QtWidgets.QPushButton("<|>")
        self._btn.setFixedSize(self.BTN_D, self.BTN_D)
        self._btn.setStyleSheet(
            # Radial gradient offset toward the upper-left simulates a
            # light source hitting a domed/raised surface: bright
            # highlight near the top-left, settling to the base light
            # blue, darkening slightly toward the outer edge.
            "QPushButton {{"
            "  background: qradialgradient(cx:0.35, cy:0.3, radius:0.85,"
            "    fx:0.35, fy:0.3,"
            "    stop:0 #F3FBFD, stop:0.5 #ADD8E6, stop:1 #8AC4DC);"
            "  color:#1c4f8a; border-radius:{r}px; font-weight:bold;"
            "  font-size:8pt; padding:0px;"
            "  border: 1px solid #7FB0C8; }}"
            "QPushButton:hover {{"
            "  background: qradialgradient(cx:0.35, cy:0.3, radius:0.85,"
            "    fx:0.35, fy:0.3,"
            "    stop:0 #FFFFFF, stop:0.5 #bfe6f5, stop:1 #9bcfe0); }}"
            "QPushButton:pressed {{"
            # Pressed: flatter/darker gradient with the highlight point
            # moved to lower-right, reading as "pushed in" rather than
            # raised -- opposite light direction from the resting state.
            "  background: qradialgradient(cx:0.65, cy:0.7, radius:0.85,"
            "    fx:0.65, fy:0.7,"
            "    stop:0 #cfe9f2, stop:0.6 #9bcfe0, stop:1 #7FB0C8);"
            "  border: 1px solid #6699B3; }}".format(r=r))
        # Real drop shadow underneath -- offset down-right, soft blur --
        # reinforces the raised/domed look from the gradient above.
        _btn_shadow = QtWidgets.QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(8)
        _btn_shadow.setOffset(2, 2)
        _btn_shadow.setColor(QtGui.QColor(0, 0, 0, 110))
        self._btn.setGraphicsEffect(_btn_shadow)
        self._btn.clicked.connect(self.clicked.emit)
        vbox.addWidget(self._btn, 0, QtCore.Qt.AlignHCenter)
        vbox.addStretch(1)

    def set_left_dimmed(self, dimmed):
        self._left_dimmed = bool(dimmed)
        self.update()

    def set_right_dimmed(self, dimmed):
        self._right_dimmed = bool(dimmed)
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect()
        cx = r.width() // 2
        c, bg = self._DIM_COLOR, self._BG_COLOR

        if self._left_dimmed:
            grad = QtGui.QLinearGradient(r.left(), 0, cx, 0)
            grad.setColorAt(0.0, c); grad.setColorAt(1.0, bg)
            # Extended 1px past r.left() to close a rounding gap against
            # the neighbouring disabled panel's own (also 1px-extended) edge.
            p.fillRect(QtCore.QRect(r.left() - 1, r.top(), cx - r.left() + 1, r.height()), grad)
        if self._right_dimmed:
            grad = QtGui.QLinearGradient(cx, 0, r.right(), 0)
            grad.setColorAt(0.0, bg); grad.setColorAt(1.0, c)
            # Extended 1px past r.right() for the same reason.
            p.fillRect(QtCore.QRect(cx, r.top(), r.right() - cx + 1, r.height()), grad)

        p.setPen(QtGui.QPen(QtGui.QColor("#888"), 1))
        mid = self.height()//2; hd = self.BTN_D//2
        p.drawLine(cx, 0, cx, mid-hd); p.drawLine(cx, mid+hd, cx, self.height())


# =============================================================================
#  Audio level meter
# =============================================================================

class SegmentedMeter(QtWidgets.QWidget):
    """
    Vertical LED-bargraph meter: N discrete segments, each with a FIXED
    colour tied to its own ABSOLUTE value threshold -- not the standard
    QProgressBar approach, where a QSS chunk gradient is scoped to the
    filled portion's OWN geometry (0.0-1.0 relative to whatever's
    currently filled), which is why even a low reading can show red right
    at its own small top edge regardless of the actual value.

    Default 8 segments over a 0-8% range: segments 1-4 green (0-4%),
    5-6 yellow (5-6%), 7-8 red (7-8%).  Each segment shows its assigned
    colour once the value reaches it, and goes dark/black otherwise --
    segments don't blend or fade, they're either lit or off.

    Uses an EXPLICIT fixed height (segment height x n + gap x (n-1))
    rather than stretching to fill whatever space the layout gives it.
    Without this, the widget's height was entirely at the mercy of
    surrounding layout recalculation -- during Generate Voice, some
    sibling content's size hint would shift by a pixel or two, which
    (with nothing anchoring this widget's own height) let the whole
    Signal Processing row, including the unrelated Optional Filters
    column next to it, visibly stretch and pop back.  A fixed height
    can't fluctuate regardless of what changes elsewhere.
    """
    SEGMENT_H = 19   # px per segment, excluding gaps -- nearly double the
                     # previous 10px, per request (was shrunk too far)

    def __init__(self, n_segments=8, max_value=8.0, parent=None):
        super().__init__(parent)
        self._n = n_segments
        self._max = max_value
        self._value = 0.0
        self._gap = 1   # was 2px -- reduced per request, shrinks total
                        # height by (n-1)*1 = 7px for the default 8 segments
        self.setMinimumWidth(20)
        total_h = self._n * self.SEGMENT_H + (self._n - 1) * self._gap
        self.setFixedHeight(total_h)

    def set_value(self, v):
        v = max(0.0, min(self._max, v))
        if v != self._value:
            self._value = v
            self.update()

    def _segment_color(self, seg_num):
        # seg_num counts 1..n from the bottom.  Maps to value thresholds
        # rather than the segment's position within the widget, so the
        # colour zones are independent of n/max choices.
        threshold = seg_num / float(self._n) * self._max
        if threshold <= 4.0:
            return QtGui.QColor("#27ae60")   # green
        elif threshold <= 6.0:
            return QtGui.QColor("#f1c40f")   # yellow
        else:
            return QtGui.QColor("#e74c3c")   # red

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        r = self.rect()
        n = self._n
        gap = self._gap
        # Gaps sit ONLY between adjacent segments -- segment 1's bottom
        # touches r.bottom() exactly and segment n's top touches r.top()
        # exactly, so there's no leftover uncoloured strip at either edge
        # (an earlier formula subtracted the gap from every segment's
        # own height without compensating, leaving an unpainted band
        # right at the widget's bottom edge that showed through as
        # background white).
        total_gap = gap * (n - 1)
        seg_h = (r.height() - total_gap) / float(n)
        lit = int(round((self._value / self._max) * n)) if self._max > 0 else 0
        p.setPen(QtCore.Qt.NoPen)
        for i in range(n):
            seg_num = i + 1
            seg_bottom = r.bottom() - (seg_num - 1) * (seg_h + gap)
            seg_top = seg_bottom - seg_h
            seg_rect = QtCore.QRectF(r.left(), seg_top, r.width(), seg_h)
            color = self._segment_color(seg_num) if seg_num <= lit \
                    else QtGui.QColor("#000000")
            p.fillRect(seg_rect, color)
        p.setPen(QtGui.QPen(QtGui.QColor("#444"), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(QtCore.QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5))


class PulseHeaderWidget(QtWidgets.QWidget):
    """
    Lightweight animated oscilloscope-trace background behind the
    OpenV2K title: a single continuous stroked line, like a pen plotting
    a square wave.  During silence it rides flat along the baseline; at
    each pulse it draws straight up, across a flat top, straight back
    down, then continues along the baseline.

    Still cheap to render: the whole trace for one full sequence is
    built ONCE at construction as a single QPainterPath of straight
    line segments (no curves, no per-frame rebuilding) -- only its
    on-screen TRANSLATION changes each frame, tiled and scrolled via
    modulo.

    Represented as a list of (is_pulse, width_px) segments rather than a
    fixed per-tick array -- needed to support gaps that aren't whole
    multiples of one tick (occasional half-tick and tick-and-a-half
    silence gaps, see _generate_bitstream), which a uniform tick-indexed
    array couldn't express.

    Bitstream: generated ONCE with Python's built-in random module,
    unseeded so it's genuinely different every launch.  The generator
    keeps the final (pulse + silence) pair whole rather than truncating
    mid-pair, so the sequence always ends in silence -- since it also
    always STARTS on a pulse, this guarantees the minimum-silence rule
    holds even at the seam where one loop of the animation rolls into
    the next.

    Pulse tops reach this widget's own top edge -- which coincides with
    the actual window's top edge, since the main layout's top margin is
    set to 0 specifically so this alignment is exact (a QPainter can
    never draw outside its own widget's bounds, so this was the only
    way to make that literally true rather than a guess).
    """
    TICK_PX = 8              # base unit for silence-gap sizing
    PULSE_WIDTH_PX = 6       # was TICK_PX (8) -- pulse width slightly
                            # reduced, now distinct from the tick unit
    N_TICKS = 200            # generation-length target, in tick units

    # Continuous alternation between a DENSE phase (weighted toward more
    # pulses) and a SPARSE phase (weighted toward more silence) --
    # simulating the bursty, uneven look of a real digital signal trace
    # rather than one flat, uniform random pattern throughout.  Same
    # simple technique both directions: reuse the same randint(min, max)
    # call everywhere, just shift the range toward smaller values for
    # DENSE or larger values for SPARSE -- no separate weighting scheme.
    DENSE_MIN_SILENCE  = 1
    DENSE_MAX_SILENCE  = 2    # shifted down -- denser
    SPARSE_MIN_SILENCE = 2
    SPARSE_MAX_SILENCE = 6    # shifted up -- sparser

    HALF_TICK_PROB = 0.20        # ~20% of gaps are a half tick
    TICK_AND_HALF_PROB = 0.15    # ~15% of gaps are a tick and a half
                                 # (remaining ~65% use the phase's own
                                 # min/max random range above)
    HALF_TICK_PROB_DENSE = HALF_TICK_PROB * 1.30   # ~30% more common
                                                   # during the dense
                                                   # phase specifically

    # The bitstream is generated once as a spatial pattern (not live),
    # so millisecond durations are converted to pixel distances using a
    # px/ms ratio empirically measured in an earlier pass (simulated
    # real generation and measured actual phase-to-phase spacing against
    # a target, rather than trusting a theoretical estimate -- the
    # theoretical version measured ~38% off when checked).  Reused here
    # rather than re-deriving from scratch.  Approximate, not an exact
    # real-time guarantee -- acceptable given simplicity matters more
    # than precision for this effect.
    DENSE_PHASE_PX  = 140.0    # ~2000ms
    SPARSE_PHASE_PX = 105.0    # ~1500ms

    BASELINE_Y_PX = 44.0   # toward the bottom edge of the Event Log/Ref
                          # buttons.  The 2x2 ref cluster's own height is
                          # confirmed exactly from code (20+2+20=42px);
                          # 44px accounts for it likely sitting
                          # vertically centred within this row.  An
                          # estimate -- nudge directly if it doesn't
                          # land exactly once rendered.  NOTE: the whole
                          # animation is shifted down 2px in paintEvent,
                          # so this baseline actually renders at ~46px --
                          # the widget's own height was increased to
                          # 49px (from the header construction code) so
                          # the shifted baseline's 3px-wide stroke has
                          # room to render without clipping against the
                          # widget's bottom edge.
    LINE_COLOR = QtGui.QColor(220, 220, 220)   # lightest grey from the
                                                # wave palette
    LINE_WIDTH_PX = 3
    SCROLL_PERIOD_S = 20.0 / 1.20   # was 20.0 -- 20% faster

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0 = time.monotonic()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(40)   # ~25fps -- smooth without excessive CPU use
        self._segments = self._generate_bitstream()
        self._trace = self._build_trace_path()   # built once, reused
                                                  # every frame -- only
                                                  # its translation
                                                  # changes per paint

    def _generate_bitstream(self):
        """List of (is_pulse, width_px) segments: a PULSE_WIDTH_PX-wide
        pulse, then a silence gap, repeated until at least N_TICKS worth
        of width is covered.  Generated once at construction (not
        per-frame) and reused for every scroll loop.  Unseeded, so it's
        genuinely different every launch -- never the same pattern
        twice.

        Continuously alternates between a DENSE phase (~2000ms, weighted
        toward more pulses) and a SPARSE phase (~1500ms, weighted toward
        more silence), simulating the uneven, bursty look of a real
        digital signal rather than one flat uniform pattern.  Both
        phases use the exact same randint(min, max) call and the exact
        same half-tick/tick-and-a-half fractional check -- only the
        range and the half-tick probability shift between phases, no
        separate weighting scheme needed for either direction.

        Half-tick gaps run ~30% more often during the dense phase
        specifically (HALF_TICK_PROB_DENSE vs the normal HALF_TICK_PROB)
        -- everything else about gap selection is identical between the
        two phases, just with different min/max ranges.

        Always appends a complete (pulse, silence) pair per loop
        iteration, never a lone trailing pulse -- so the sequence always
        ends in silence.  Combined with always STARTING on a pulse, this
        guarantees the minimum-silence rule holds even at the seam where
        one loop of the animation rolls into the next."""
        rng = random.Random()   # no seed -- auto-seeds from OS entropy,
                                # so this is genuinely different every
                                # launch, not the same pattern replayed
        segments = []
        total_w = 0.0
        target_w = self.N_TICKS * self.TICK_PX
        dist_in_phase = 0.0
        dense = True   # start dense, alternates with sparse thereafter
        while total_w < target_w:
            segments.append((True, self.PULSE_WIDTH_PX))
            total_w += self.PULSE_WIDTH_PX

            if dense:
                min_s, max_s = self.DENSE_MIN_SILENCE, self.DENSE_MAX_SILENCE
                half_p = self.HALF_TICK_PROB_DENSE
            else:
                min_s, max_s = self.SPARSE_MIN_SILENCE, self.SPARSE_MAX_SILENCE
                half_p = self.HALF_TICK_PROB
            roll = rng.random()
            if roll < half_p:
                gap_ticks = 0.5
            elif roll < half_p + self.TICK_AND_HALF_PROB:
                gap_ticks = 1.5
            else:
                gap_ticks = float(rng.randint(min_s, max_s))
            gap_px = gap_ticks * self.TICK_PX
            segments.append((False, gap_px))
            total_w += gap_px

            dist_in_phase += self.PULSE_WIDTH_PX + gap_px
            phase_len = self.DENSE_PHASE_PX if dense else self.SPARSE_PHASE_PX
            if dist_in_phase >= phase_len:
                dense = not dense
                dist_in_phase = 0.0
        return segments

    def _build_trace_path(self):
        """One continuous oscilloscope-style trace for the full
        sequence: baseline, straight up at a pulse, flat across the
        top, straight back down, continue along the baseline.  Starts
        and ends exactly at baseline level so consecutive tiled repeats
        connect seamlessly with no visible seam."""
        baseline_y = self.BASELINE_Y_PX
        top_y = 0.0
        path = QtGui.QPainterPath()
        path.moveTo(0.0, baseline_y)
        x = 0.0
        for is_pulse, width_px in self._segments:
            if is_pulse:
                path.lineTo(x, top_y)
                path.lineTo(x + width_px, top_y)
                path.lineTo(x + width_px, baseline_y)
            else:
                path.lineTo(x + width_px, baseline_y)
            x += width_px
        return path

    def paintEvent(self, event):
        p = QtGui.QPainter(self)   # no antialiasing -- sharp edges suit
                                    # a digital-signal look and are
                                    # cheaper to render than smoothed ones
        p.translate(0, 2)   # whole animation shifted down 2px
        r = self.rect()
        seq_w = sum(width for _, width in self._segments)
        elapsed = time.monotonic() - self._t0
        offset = (elapsed / self.SCROLL_PERIOD_S) * seq_w
        offset = offset % seq_w

        pen = QtGui.QPen(self.LINE_COLOR, self.LINE_WIDTH_PX)
        pen.setJoinStyle(QtCore.Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)   # stroke only -- no fill, this is
                                        # a line trace, not solid boxes

        start_x = -seq_w + offset   # same "-period + offset" rightward-
                                    # scroll convention the wave used
        n_repeats = int(r.width() / seq_w) + 3
        for rep in range(n_repeats):
            base_x = start_x + rep * seq_w
            if base_x > r.width() or base_x + seq_w < 0:
                continue   # this whole repeat is off-screen -- skip it
            p.save()
            p.translate(base_x, 0)
            p.drawPath(self._trace)
            p.restore()
        super().paintEvent(event)


class HorizontalSegmentedMeter(QtWidgets.QWidget):
    """
    Horizontal counterpart to SegmentedMeter (see that class) for the
    Live Microphone level -- same LED-bargraph design, fixed per-segment
    colours tied to absolute dB thresholds, but fills left-to-right
    instead of bottom-to-top, and ~3x the segment count (24 vs 8) since
    it covers a full 60dB range rather than an 8% one.

    This also replaces the old QProgressBar-based bar, which had the
    same bug the original duty-cycle meter had before it was rebuilt:
    a QSS chunk gradient scoped to the FILLED portion's own geometry
    rather than the widget's absolute value range, so a low reading
    could show colour meant for a much louder one.

    Colour thresholds: green -60dB to -18dB, yellow -18dB to -6dB, red
    -6dB to 0dB.  -6dB (not a fresh -9dB assumption) because that's what
    this app's own prior code already used in two independent places --
    the old gradient's stops (70%/90% of the 60dB range) and the
    dB-label's colour-switch logic in _update_displays -- both landing
    on the same -6dB boundary.
    """
    SEGMENT_GAP = 1
    N_SEGMENTS = 24   # ~3x SegmentedMeter's 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value_db = -60.0
        self.setFixedHeight(16)   # matches the old bar's height
        self.setMinimumWidth(100)

    def set_level_db(self, db):
        db = max(-60.0, min(0.0, db))
        if db != self._value_db:
            self._value_db = db
            self.update()

    def freeze(self):
        self.set_level_db(-60.0)

    @staticmethod
    def _segment_color(threshold_db):
        if threshold_db <= -18.0:
            return QtGui.QColor("#27ae60")   # green
        elif threshold_db <= -6.0:
            return QtGui.QColor("#f39c12")   # yellow/orange
        else:
            return QtGui.QColor("#e74c3c")   # red

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        r = self.rect()
        n = self.N_SEGMENTS
        gap = self.SEGMENT_GAP
        total_gap = gap * (n - 1)
        # Integer pixel math throughout -- the previous QRectF version
        # computed each segment's left edge as a float
        # (seg_num * (seg_w+gap)), and since seg_w rarely divides the
        # available width evenly, accumulated rounding error could make
        # one particular gap rasterize 2px wide instead of the intended
        # 1px.  Distributing the integer-division remainder across the
        # first few segments (making them 1px wider) guarantees every
        # segment lands on an exact whole pixel and every gap is
        # genuinely, consistently 1px -- no drift possible.
        avail_w = r.width() - total_gap
        base_w = avail_w // n
        remainder = avail_w % n
        lit = int(round(((self._value_db + 60.0) / 60.0) * n))
        p.setPen(QtCore.Qt.NoPen)
        x = r.left()
        for i in range(n):
            seg_num = i + 1   # 1 = leftmost
            this_w = base_w + (1 if i < remainder else 0)
            seg_rect = QtCore.QRect(x, r.top(), this_w, r.height())
            if seg_num <= lit:
                threshold_db = -60.0 + (seg_num / float(n)) * 60.0
                color = self._segment_color(threshold_db)
            else:
                color = QtGui.QColor("#000000")
            p.fillRect(seg_rect, color)
            x += this_w + gap
        p.setPen(QtGui.QPen(QtGui.QColor("#444"), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))


class LevelMeter(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(6,0,0,0); vbox.setSpacing(1)
        self._bar = HorizontalSegmentedMeter()
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
        self._bar.set_level_db(db)

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
        self._label = lbl
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0,0,0,0); row.setSpacing(4)
        row.addWidget(lbl); row.addWidget(self._slider); row.addWidget(self._readout)
        self._slider.valueChanged.connect(self._on_change)

    def set_label_text(self, text):
        """Update the slider's label text for retranslation."""
        self._label.setText("<b>{}</b>".format(text))

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
    ESPEAK_SILENCE_SEC = 0.1    # 100ms silence each end; 1s caused AGC gain
    # to ramp up 3.4x during the quiet lead, clipping speech on arrival.
    _DISABLED_BG       = QtGui.QColor("#b8b8b8")
    BTN_H              = 42   # was 58; -8px top and bottom per user request
    # Hypothetical microwave amplifier power tiers (Watts) for the Power
    # Calculation display -- illustrative spec-sheet reference points, NOT
    # connected to the app's actual weak HackRF TX Power (1mW/2mW) setting.
    _POWER_LEVELS_W    = [1500, 4000]
    # Multiscript input filter: Latin (+accents incl. Vietnamese/Romanian),
    # Cyrillic (Russian, Ukrainian, Bulgarian, Serbian), Arabic (covers Urdu
    # and Persian, which share the Arabic script block), Devanagari (Hindi +
    # Marathi), Bengali, Gurmukhi (Punjabi), Tamil, Telugu, Hiragana/Katakana,
    # CJK Unified Ideographs, Hangul (Korean), plus space.  Indonesian,
    # Malay, Swahili, Turkish, Portuguese, Polish, Dutch, Hungarian, Czech,
    # Croatian, Lithuanian, Finnish, Bosnian, Danish, and Slovak all use
    # standard Latin ranges already covered -- no extra range needed.
    _ESPEAK_ALLOWED_RE = re.compile(
        r'[^a-zA-Z '
        r'\u00B7'              # Middle dot (Catalan l.l digraph)
        r'\u00C0-\u00FF'      # Latin-1 Supplement: accented Latin letters
        r'\u0100-\u024F'      # Latin Extended-A/B (incl. Romanian s,t-comma)
        r'\u0300-\u036F'      # Combining Diacritical Marks (Vietnamese)
        r'\u0370-\u03FF'      # Greek
        r'\u0400-\u04FF'      # Cyrillic (Russian, Ukrainian, Bulgarian, Serbian)
        r'\u0600-\u06FF'      # Arabic (also covers Urdu, Persian/Farsi)
        r'\u0900-\u097F'      # Devanagari (Hindi, Marathi)
        r'\u0980-\u09FF'      # Bengali
        r'\u0A00-\u0A7F'      # Gurmukhi (Punjabi)
        r'\u0B80-\u0BFF'      # Tamil
        r'\u0C00-\u0C7F'      # Telugu
        r'\u1E00-\u1EFF'      # Latin Extended Additional (Vietnamese)
        r'\u3040-\u309F'      # Hiragana
        r'\u30A0-\u30FF'      # Katakana
        r'\u4E00-\u9FFF'      # CJK Unified Ideographs (Kanji / Hanzi)
        r'\uAC00-\uD7A3'      # Hangul Syllables (Korean)
        r']')

    # NOTE: tx_license / save_description text is looked up fresh via _tr()
    # wherever it's used (widget creation and _retranslate_ui), never cached
    # as a class attribute -- a cached value would never update when the
    # user switches languages at runtime.

    def __init__(self):
        gr.top_block.__init__(self, "OpenV2K", catch_exceptions=True)
        QtWidgets.QMainWindow.__init__(self)
        # DEVELOPER (Claude): the date below goes stale easily -- it was
        # last correct several versions ago.  Before saving ANY new
        # version, check the actual current date first (not the date in
        # this string, which is exactly the value being corrected), then
        # update both the date AND the version number together.
        # Format: YYYY/M/D
        self.setWindowTitle("OpenV2K (2026/8/16 - Version 154)")
        self.setFixedWidth(580)

        self._hackrf_found, self._hackrf_info = detect_hackrf()
        self._write_silence_wav(self.ESPEAK_WAV)

        self._pulse_us           = 100.0
        self._hpf_hz             = 100.0
        self._lpf_hz             = 2300.0
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
        # Suppress QSocketNotifier warning: audio.source emits it via C++
        # fprintf(stderr) when the audio device is opened -- fd-level redirect
        # is the only reliable intercept.  Wrapping build+connect, not start().
        _saved = os.dup(2)
        _null  = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_null, 2)
        try:
            self._build_blocks()
            self._connect_blocks()
        finally:
            os.dup2(_saved, 2)
            os.close(_saved)
            os.close(_null)

        # Start MBROLA warm-up immediately so the binary is ready before
        # the user clicks Generate Voice for the first time.
        self._prime_mbrola_async()

        # Signal Conditioning: Notch defaults OFF -- eSpeak TTS (the
        # default input source) has no AC mains hum to remove, so there's
        # nothing for it to do there.  It's now auto-toggled ON/OFF by
        # _cb_audio_swap() instead: ON when Live Microphone becomes the
        # active input (real mic hardware genuinely can pick up mains
        # hum), OFF again when switching back to eSpeak TTS.  This
        # initial state matches eSpeak being the default active input.
        # Pre-emph stays OFF deliberately: it's a stable FIR filter with no
        # bug, but its whole purpose is a +6dB/oct HIGH-frequency boost,
        # which directly fights this app's goal of LOWERING zero-crossing
        # rate.  Available for intelligibility-over-duty-cycle use cases.
        self._chk_notch.setChecked(False)
        self._chk_preemph.setChecked(False)
        self._chk_deemph.setChecked(False)
        self._chk_fricative.setChecked(False)
        self._chk_f1bandpass.setChecked(False)
        self._chk_decimator.setChecked(True)
        self._chk_noisegate.setChecked(True)
        self._chk_env_follow.setChecked(False)
        self._chk_spectral_sub.setChecked(True)
        self._chk_hwrect.setChecked(True)
        self._chk_schmitt.setChecked(True)
        self._chk_hilbert_env.setChecked(False)  # OFF -- mutually exclusive with Schmitt

        self._update_power_calc()   # initial values before the first timer tick

        self._level_timer = QtCore.QTimer()
        self._level_timer.timeout.connect(self._update_displays)
        self._level_timer.start(100)

        self._log("Ready")

    # =========================================================================
    #  Event Log -- timestamped append, thread-safe
    # =========================================================================

    def _build_mbrola_tooltip(self):
        """Build the MBROLA checkbox tooltip using current locale state.
        Factored out so both initial construction and _retranslate_ui()
        (on language switch) produce an identical, up-to-date tooltip."""
        if _LOCALE_MBROLA_OK:
            status = "Available ({})".format(_LOCALE_MBROLA_CODE)
        elif _LOCALE_MBROLA_CODE:
            status = ("Not installed -- sudo apt install "
                     "mbrola mbrola-{}").format(_LOCALE_MBROLA_CODE)
        else:
            status = _tr("no_mbrola_voice")
        return "{}\n\nStatus: {}".format(_tr("tt_mbrola"), status)

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

    def _cb_language_changed(self, index):
        """Fired when the user picks a language from the top-left combobox.
        Updates _CURRENT_LANG (and the derived espeak/MBROLA voice globals),
        then retranslates every visible widget in place."""
        global _CURRENT_LANG
        code = self._lang_combo.itemData(index)
        if not code or code == _CURRENT_LANG:
            return
        _CURRENT_LANG = code
        _recompute_locale_voices()
        self._populate_accent_combo()   # new language may have different accents
        self._retranslate_ui()
        self._log("Language switched: {}".format(_LANG_NAMES.get(code, code)))

    def _populate_accent_combo(self):
        """
        Fill the accent combobox with the current language's genuine MBROLA
        accent options (if any), and show it only when there's an actual
        choice to make (2+ accents).  For every other language it's fully
        hidden -- not just disabled -- so it never occupies row width and
        the language combobox never gets squeezed.  Called at construction
        and again whenever the language selector changes.
        """
        self._accent_combo.blockSignals(True)
        self._accent_combo.clear()
        accents = _MBROLA_ACCENTS.get(_CURRENT_LANG)
        if accents and len(accents) > 1:
            for label, code in accents:
                self._accent_combo.addItem(label, code)
            # Pre-select whichever accent matches the language's current
            # default code (index 0 by construction, but look it up
            # properly in case the default ever changes).
            idx = self._accent_combo.findData(_LOCALE_MBROLA_CODE)
            self._accent_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._accent_combo.setEnabled(True)
            self._accent_combo.setVisible(True)
            self._accent_combo.setToolTip(
                _tr("tt_accent").format(
                    _LANG_NAMES_EN.get(_CURRENT_LANG, _CURRENT_LANG)))
        else:
            self._accent_combo.setVisible(False)
        self._accent_combo.blockSignals(False)

    def _cb_accent_changed(self, index):
        """
        Fired when the user picks a different regional accent.  Overrides
        the active MBROLA voice code directly (bypassing the language's
        default from _MBROLA_VOICE_MAP) so every existing consumer of
        _LOCALE_MBROLA_CODE / _LOCALE_MBROLA_OK -- the checkbox tooltip and
        the eSpeak command builder -- picks up the new accent automatically.
        The checkbox is enabled+checked whenever this specific accent's
        voice pack is actually installed on disk, exactly like switching
        to a whole new language does; it's disabled only when the pack
        genuinely isn't installed yet (see the log line below for the
        exact install command in that case).
        """
        global _LOCALE_MBROLA_CODE, _LOCALE_MBROLA_OK
        code = self._accent_combo.itemData(index)
        if not code:
            return
        _LOCALE_MBROLA_CODE = code
        _LOCALE_MBROLA_OK   = _check_mbrola_voice(code)
        self._chk_mbrola.setToolTip(self._build_mbrola_tooltip())
        self._chk_mbrola.setEnabled(_LOCALE_MBROLA_OK)
        self._chk_mbrola.setChecked(_LOCALE_MBROLA_OK)
        if _LOCALE_MBROLA_OK:
            self._log("MBROLA accent: {} ({}) -- installed".format(
                self._accent_combo.currentText(), code))
        else:
            self._log("MBROLA accent: {} ({}) -- not installed, "
                     "run: sudo apt install mbrola-{}".format(
                         self._accent_combo.currentText(), code, code))

    def _retranslate_ui(self):
        """
        Update every translatable widget's displayed text in place after a
        language switch.  GNU Radio blocks and their connections are
        completely unaffected -- this only touches Qt widget text/tooltip
        properties, so it's safe to call at any time, including mid-session.
        """
        # Title row
        self._log_btn.setText(_tr("event_log"))
        # Re-sync the combobox cap now that the button's translated text
        # (and therefore its natural width) may have changed length.
        self._lang_combo.setMaximumWidth(self._log_btn.sizeHint().width())
        self._title_lbl.setText(
            "<h3 style='margin:0;'>"
            "<a href='https://github.com/OpenV2K'"
            " style='color:#2a6ebb; text-decoration:none;'>OpenV2K</a>"
            "</h3><small>{}</small>".format(_tr("app_subtitle")))

        # Section headers (custom-painted widgets)
        self._hdr_audio.set_label_text(_tr("section_audio_input"))
        self._hdr_sigproc.set_label_text(_tr("section_signal_processing"))
        self._hdr_output.set_label_text(_tr("section_output"))

        # Audio Input section
        self._mic_sub_lbl.setText(_tr("live_microphone"))
        self._mic_desc_lbl.setText(_tr("mic_level_desc"))
        self._btn_mute.setText(
            _tr("mic_muted") if self._btn_mute.isChecked() else _tr("mic_live"))
        self._es_title_lbl.setText(_tr("espeak_tts"))
        self._chk_mbrola.setText(_tr("mbrola"))
        self._chk_mbrola.setToolTip(self._build_mbrola_tooltip())
        self._chk_mbrola.setEnabled(_LOCALE_MBROLA_OK)
        if not _LOCALE_MBROLA_OK:
            # Disabled AND unchecked -- otherwise a box left checked before
            # switching to a formant-only language would appear stuck
            # (visually checked, but unclickable since it's disabled).
            self._chk_mbrola.setChecked(False)
        else:
            # This language has a real MBROLA voice -- default to checked,
            # same as the initial construction default.
            self._chk_mbrola.setChecked(True)
        self._btn_generate.setText(_tr("generate_voice"))
        self._espeak_input.setPlaceholderText(_tr("placeholder_hello"))

        # Signal Processing section
        self._sl_pulse.set_label_text(_tr("slider_pulse"))
        self._sl_hpf.set_label_text(_tr("slider_hpf"))
        self._sl_lpf.set_label_text(_tr("slider_lpf"))
        self._opt_box.setTitle(_tr("optional_filters"))

        # Power Calculation section (now its own top-level section)
        self._hdr_power_calc.set_label_text(_tr("power_calc_title"))
        self._hdr_power_calc.setToolTip(_tr("power_calc_summary"))
        self._power_calc_box.setToolTip(_tr("power_calc_summary"))
        self._power_reset_btn.setText(_tr("power_reset"))
        self._update_power_calc()   # rebuilds all three rows with new prefix text
        for h, key in self._opt_col_headers:
            h.setText(_tr(key))
        self._chk_notch.setText(_tr("filt_notch"))
        self._chk_notch.setToolTip(_tr("tt_notch"))
        self._chk_preemph.setText(_tr("filt_preemph"))
        self._chk_preemph.setToolTip(_tr("tt_preemph"))
        self._chk_deemph.setText(_tr("filt_deemph"))
        self._chk_deemph.setToolTip(_tr("tt_deemph"))
        self._chk_fricative.setText(_tr("filt_fricative"))
        self._chk_fricative.setToolTip(_tr("tt_fricative"))
        self._chk_f1bandpass.setText(_tr("filt_f1bandpass"))
        self._chk_f1bandpass.setToolTip(_tr("tt_f1bandpass"))
        self._chk_decimator.setText(_tr("filt_decimate"))
        self._chk_decimator.setToolTip(_tr("tt_decimate"))
        self._chk_noisegate.setText(_tr("filt_noisegate"))
        self._chk_noisegate.setToolTip(_tr("tt_noisegate"))
        self._chk_env_follow.setText(_tr("filt_envfollow"))
        self._chk_env_follow.setToolTip(_tr("tt_envfollow"))
        self._chk_spectral_sub.setText(_tr("filt_specsub"))
        self._chk_spectral_sub.setToolTip(_tr("tt_specsub"))
        self._chk_hwrect.setText(_tr("filt_hwrect"))
        self._chk_hwrect.setToolTip(_tr("tt_hwrect"))
        self._chk_schmitt.setText(_tr("filt_schmitt"))
        self._chk_schmitt.setToolTip(_tr("tt_schmitt"))
        self._chk_hilbert_env.setText(_tr("filt_hilbert"))
        self._chk_hilbert_env.setToolTip(_tr("tt_hilbert"))
        self._duty_cycle_lbl.setText(_tr("duty_cycle_label"))

        # Output section -- Transmitter
        self._freq_lbl.setText(_tr("transmitter_freq"))
        self._pwr_lbl.setText(_tr("transmitter_pwr"))
        self._btn_tx.setText(
            _tr("tx_enabled") if self._btn_tx.isChecked() else _tr("tx_disabled"))
        self._lic_lbl.setText(
            "<a href='https://en.wikipedia.org/wiki/"
            "Amateur_radio_frequency_allocations#ITU_Region_2'"
            " style='color:#555; text-decoration:none;'>"
            "<b>{}</b></a>".format(_tr("tx_license")))

        # Output section -- Save to Disk
        self._save_hdr_lbl.setText(_tr("save_to_disk"))
        self._save_path_lbl.setText(_tr("save_description"))
        self._btn_record.setText(
            _tr("recording") if self._btn_record.isChecked() else _tr("record_iq"))
        self._chk_waterfall.setText(_tr("waterfall_checkbox"))

        # Event Log overlay
        self._ovl_hdr_lbl.setText(_tr("event_log_title"))

    # =========================================================================
    #  GUI helpers
    # =========================================================================

    def _set_panel_active(self, panel, active):
        panel.setEnabled(active)
        panel.set_dimmed(not active)

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
                " border-top: 4px solid #6fdb9d;"
                " border-left: 4px solid #6fdb9d;"
                " border-right: 3px solid #145a32;"
                " border-bottom: 3px solid #145a32;"
                " font-weight:bold; }"
                "QPushButton:hover { background-color:#2ecc71; }"
                "QPushButton:pressed {"
                # Pressed: bevel direction inverted -- shadow now on
                # top/left, highlight on bottom/right -- reads as pushed in.
                " background-color:#1e8449;"
                " border-top: 4px solid #145a32;"
                " border-left: 4px solid #145a32;"
                " border-right: 3px solid #6fdb9d;"
                " border-bottom: 3px solid #6fdb9d; }"
                "QPushButton:disabled { background-color:#555555;"
                " color:#999999; border-color:#555555; }")

    @staticmethod
    def _style_red():
        return ("QPushButton { background-color:#c0392b; color:white;"
                " border-top: 4px solid #ec7063;"
                " border-left: 4px solid #ec7063;"
                " border-right: 3px solid #78281f;"
                " border-bottom: 3px solid #78281f;"
                " font-weight:bold; }"
                "QPushButton:hover { background-color:#e74c3c; }"
                "QPushButton:pressed {"
                " background-color:#922b21;"
                " border-top: 4px solid #78281f;"
                " border-left: 4px solid #78281f;"
                " border-right: 3px solid #ec7063;"
                " border-bottom: 3px solid #ec7063; }"
                "QPushButton:disabled { background-color:#555555;"
                " color:#999999; border-color:#555555; }")

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
        vbox.setContentsMargins(12,0,12,12); vbox.setSpacing(0)

        # ---- Title row (NEVER covered by the overlay) ----------------------
        # The title frame is a named widget so we can mapTo() its bottom edge.
        self._title_frame = QtWidgets.QWidget()
        tr = QtWidgets.QHBoxLayout(self._title_frame)
        tr.setContentsMargins(0,0,0,0); tr.setSpacing(8)

        # Language selector combobox -- top-left, above the Event Log button.
        # Sorted by native name so each language is easy to find by eye.
        # Width is capped to match the (now-compact) Event Log button below
        # it -- see setMaximumWidth() call after the button is built.  A
        # capped QComboBox still shows the FULL text of every entry in its
        # dropdown popup; only the closed-box display elides with "..." if
        # the currently selected language's name is longer than the cap.
        self._lang_combo = QtWidgets.QComboBox()
        self._lang_combo.setStyleSheet(
            "QComboBox { font-size:7pt; padding:2px 3px; }")
        for code in sorted(_LANG_NAMES, key=lambda c: _LANG_NAMES[c]):
            display = "{}  ({})".format(_LANG_NAMES[code], _LANG_NAMES_EN[code])
            self._lang_combo.addItem(display, code)
        _cur_idx = self._lang_combo.findData(_CURRENT_LANG)
        if _cur_idx >= 0:
            self._lang_combo.setCurrentIndex(_cur_idx)
        self._lang_combo.currentIndexChanged.connect(self._cb_language_changed)

        if not _TRANSLATIONS_XML_LOADED:
            # Translations.xml wasn't found or failed to parse next to
            # this script -- _CURRENT_LANG already resolved to 'en' via
            # _detect_locale()'s existing fallback (it only accepts codes
            # present in _TRANSLATIONS, which is English-only in this
            # case), so the combobox is already showing/selecting
            # English above.  Lock it so the user can't pick a language
            # this app has no translation table for.
            self._lang_combo.setEnabled(False)
            self._lang_combo.setToolTip(
                "Translations.xml not found -- only English is available.")

        # Accent combobox -- appears to the RIGHT of the language combobox,
        # but only when the selected language has more than one genuine
        # MBROLA national/regional accent (English, Spanish, Portuguese,
        # French).  For every other language it's fully hidden (not just
        # disabled) so it never takes up row width and never squishes the
        # language combobox, which always keeps its original full size.
        self._ACCENT_W = 50
        self._accent_combo = QtWidgets.QComboBox()
        self._accent_combo.setStyleSheet(
            "QComboBox { font-size:7pt; padding:2px 3px; }")
        self._accent_combo.setFixedWidth(self._ACCENT_W)
        self._accent_combo.setVisible(False)   # hidden until populated
        self._accent_combo.currentIndexChanged.connect(self._cb_accent_changed)

        # "Event Log" button -- rounded, blue, top-left corner.
        # Padding and font trimmed from the original (4px 10px / 9pt) to
        # shrink the button roughly 1cm narrower.  The button always sizes
        # to its own text (QPushButton never wraps or clips), so every
        # language's translated "Event Log" label stays fully readable --
        # only the surrounding whitespace shrinks, not the text itself.
        self._log_btn = QtWidgets.QPushButton(_tr("event_log"))
        self._log_btn.setCheckable(True)
        self._log_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #2a6ebb; color: white;"
            "  border-radius: 8px; font-weight: bold;"
            "  padding: 3px 5px; font-size: 8pt; }"
            "QPushButton:checked {"
            "  background-color: #1c4f8a; }"
            "QPushButton:hover {"
            "  background-color: #3a7ebb; }"
            "QPushButton:checked:hover {"
            "  background-color: #245f9a; }")
        self._log_btn.toggled.connect(self._toggle_event_log)

        # Language combobox is always the button's full natural width --
        # never reduced to make room for the accent box, which instead
        # extends the row further right only when it's actually visible.
        self._lang_combo.setMaximumWidth(self._log_btn.sizeHint().width())

        self._populate_accent_combo()   # sets initial visibility + items

        lang_row = QtWidgets.QHBoxLayout()
        lang_row.setContentsMargins(0,0,0,0); lang_row.setSpacing(3)
        lang_row.addWidget(self._lang_combo)
        lang_row.addWidget(self._accent_combo)

        # Stack the language/accent row above the Event Log button
        log_col = QtWidgets.QVBoxLayout()
        log_col.setContentsMargins(0,0,0,0); log_col.setSpacing(6)
        log_col.addLayout(lang_row)
        log_col.addWidget(self._log_btn)
        tr.addLayout(log_col)

        # OpenV2K clickable title (centred in remaining space), with an
        # animated greyscale wave background behind it.
        self._title_lbl = QtWidgets.QLabel(
            "<h3 style='margin:0;'>"
            "<a href='https://github.com/OpenV2K'"
            " style='color:#2a6ebb; text-decoration:none;'>OpenV2K</a>"
            "</h3><small>{}</small>".format(_tr("app_subtitle")))
        title = self._title_lbl
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setOpenExternalLinks(True)
        title.setStyleSheet("background: transparent;")
        # Word-wrap so longer translated subtitles wrap to a second line
        # instead of expanding the title row width in the fixed-width window.
        title.setWordWrap(True)
        # White drop shadow, offset down-right, zero blur -- gives the
        # text an embossed/pressed-in look against the moving pulse
        # background behind it (a dark shadow would read as raised
        # instead; a light one offset this way reads as recessed).
        _title_shadow = QtWidgets.QGraphicsDropShadowEffect()
        _title_shadow.setColor(QtGui.QColor(255, 255, 255, 255))
        _title_shadow.setOffset(1.5, 1.5)
        _title_shadow.setBlurRadius(0)   # zero -- genuinely sharp edge,
                                         # not a soft glow
        title.setGraphicsEffect(_title_shadow)

        self._title_wave = PulseHeaderWidget()
        self._title_wave.setFixedHeight(49)   # was 46 -- the minimum
                                              # increase needed so the
                                              # shifted baseline's own
                                              # 3px stroke doesn't clip
                                              # against the widget's
                                              # bottom edge (see fix note
                                              # in PulseHeaderWidget)
        _title_wave_vbox = QtWidgets.QVBoxLayout(self._title_wave)
        _title_wave_vbox.setContentsMargins(0,0,0,0)
        _title_wave_vbox.addWidget(title)
        tr.addWidget(self._title_wave, 1)

        # 2x2 reference button cluster -- top-right of window.
        # Sized independently of self._log_btn (previously tied to its
        # sizeHint, which broke once the Event Log button was shrunk --
        # the 36px-minimum RefA-D buttons no longer fit their container).
        # Fixed dimensions restore the original comfortable spacing.
        _refs = [
            ("RefA", "https://www.amazon.com/Auditory-Effects-Microwave-Radiation-James/dp/3030645436"),
            ("RefB", "https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques"),
            ("RefC", "https://web.archive.org/web/20160910133313/http://www.mitchelleffect.com/1973_voice_to_skull.pdf"),
            ("RefD", "https://www.reddit.com/r/OpenV2K/comments/1g69tey/exodus_12ghz_solid_state_high_pulse_power/"),
        ]
        ref_frame = QtWidgets.QWidget()
        ref_grid  = QtWidgets.QGridLayout(ref_frame)
        ref_grid.setContentsMargins(0, 2, 0, 0); ref_grid.setSpacing(2)
        _REF_BTN_W = 40   # fixed, independent of the Event Log button's size
        for i, (lbl, url) in enumerate(_refs):
            rb = QtWidgets.QPushButton(lbl)
            rb.setFixedSize(_REF_BTN_W, 20)
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
        ref_frame.setFixedWidth(_REF_BTN_W * 2 + 2)   # 2 cols + 2px spacing
        tr.addWidget(ref_frame)

        vbox.addWidget(self._title_frame)
        vbox.addSpacing(6)

        # =====================================================================
        # Audio Input
        # =====================================================================
        self._hdr_audio = SectionHeader(_tr("section_audio_input"))
        vbox.addWidget(self._hdr_audio)
        vbox.addSpacing(0)
        audio_row = QtWidgets.QHBoxLayout(); audio_row.setSpacing(0)

        self._mic_panel = SwapPanel(divider_side='right')  # left member of its pair -- button sits on its right
        self._mic_panel.setAutoFillBackground(True)
        mic_vbox = QtWidgets.QVBoxLayout(self._mic_panel)
        mic_vbox.setContentsMargins(0,4,4,4); mic_vbox.setSpacing(2)

        # Header row: "Live Microphone" label + live dB readout on the same line
        mic_hdr_row = QtWidgets.QHBoxLayout()
        mic_hdr_row.setContentsMargins(6,0,0,0); mic_hdr_row.setSpacing(4)
        self._mic_sub_lbl = QtWidgets.QLabel(_tr("live_microphone"))
        mic_sub = self._mic_sub_lbl
        mic_sub.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(mic_sub)
        mic_hdr_row.addWidget(mic_sub, 1)
        self._level_db_lbl = QtWidgets.QLabel("-60.0 dB")
        self._level_db_lbl.setFont(QtGui.QFont("Monospace", 8))
        self._level_db_lbl.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._level_db_lbl.setStyleSheet("color:#27ae60;")
        mic_hdr_row.addWidget(self._level_db_lbl)
        mic_vbox.addLayout(mic_hdr_row)

        # Description (wider: fills to button edge)
        self._mic_desc_lbl = QtWidgets.QLabel(_tr("mic_level_desc"))
        meter_lbl = self._mic_desc_lbl
        meter_lbl.setStyleSheet("color:#777; font-size:9px;")
        meter_lbl.setWordWrap(True)
        meter_lbl.setContentsMargins(6,0,0,0)
        meter_lbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                QtWidgets.QSizePolicy.Preferred)
        mic_vbox.addWidget(meter_lbl)

        # Meter -- 5px below description
        mic_vbox.addSpacing(5)
        self._level_meter = LevelMeter()
        self._level_meter.freeze()
        mic_vbox.addWidget(self._level_meter)

        # Stretch pushes Mic button down to roughly align with Generate Voice
        mic_vbox.addStretch(1)

        self._btn_mute = QtWidgets.QPushButton(_tr("mic_muted"))
        self._btn_mute.setCheckable(True); self._btn_mute.setChecked(True)
        self._btn_mute.setMinimumHeight(self.BTN_H)
        self._btn_mute.setStyleSheet(self._style_red())
        self._btn_mute.toggled.connect(self._cb_mute)
        _mic_btn_row = QtWidgets.QHBoxLayout()
        _mic_btn_row.setContentsMargins(12, 0, 12, 0)
        _mic_btn_row.addWidget(self._btn_mute)
        mic_vbox.addLayout(_mic_btn_row)
        # 10px of real trailing height -- the disabled grey rectangle's own
        # bottom edge extends into this, with room left for the 5px feather.
        mic_vbox.addSpacing(10)
        audio_row.addWidget(self._mic_panel, 1)

        self._audio_swap = SwapButton(parent=self)
        self._audio_swap.clicked.connect(self._cb_audio_swap)
        audio_row.addWidget(self._audio_swap)

        self._es_panel = SwapPanel(divider_side='left')  # right member of its pair -- button sits on its left
        self._es_panel.setAutoFillBackground(True)
        es_vbox = QtWidgets.QVBoxLayout(self._es_panel)
        es_vbox.setContentsMargins(4,4,0,4); es_vbox.setSpacing(0)

        es_hdr = QtWidgets.QHBoxLayout()
        es_hdr.setContentsMargins(0,0,6,0)
        self._es_title_lbl = QtWidgets.QLabel(_tr("espeak_tts"))
        es_title = self._es_title_lbl
        es_title.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(es_title)
        es_hdr.addWidget(es_title)
        es_hdr.addSpacing(10)    # breathing room before MBROLA checkbox

        # MBROLA toggle -- uses recorded phoneme diphones for more natural speech
        self._chk_mbrola = QtWidgets.QCheckBox(_tr("mbrola"))
        self._chk_mbrola.setStyleSheet("color:black; font-size:9px;")
        self._keep_black(self._chk_mbrola)
        self._chk_mbrola.setToolTip(self._build_mbrola_tooltip())
        if not _LOCALE_MBROLA_OK:
            self._chk_mbrola.setEnabled(False)
            if _CURRENT_LANG != 'en':
                self._log(_tr("no_mbrola_voice"))
        else:
            self._chk_mbrola.setChecked(True)   # on by default when installed
        self._keep_black(self._chk_mbrola)
        es_hdr.addWidget(self._chk_mbrola)
        es_hdr.addStretch(1)
        self._char_counter = QtWidgets.QLabel("0/140")
        self._char_counter.setFont(QtGui.QFont("Monospace",8))
        self._char_counter.setAlignment(
            QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
        self._char_counter.setStyleSheet("color:#777;")
        es_hdr.addWidget(self._char_counter)
        es_vbox.addLayout(es_hdr)
        es_vbox.addSpacing(8)

        self._espeak_input = _EspeakBox()
        self._espeak_input.setPlaceholderText(_tr("placeholder_hello"))
        self._espeak_input.setMinimumHeight(50)
        self._espeak_input.setMaximumHeight(54)
        self._espeak_input.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff)
        self._espeak_input.textChanged.connect(self._on_espeak_text_changed)
        _input_row = QtWidgets.QHBoxLayout()
        _input_row.setContentsMargins(0,0,6,0)
        _input_row.addWidget(self._espeak_input)
        es_vbox.addLayout(_input_row)
        es_vbox.addSpacing(8)

        self._btn_generate = QtWidgets.QPushButton(_tr("generate_voice"))
        self._btn_generate.setMinimumHeight(self.BTN_H)
        self._btn_generate.setStyleSheet(self._style_green())
        self._btn_generate.clicked.connect(self._cb_generate_espeak)
        # Wire Enter key: store button reference in the input widget property
        self._espeak_input.setProperty("generate_btn", self._btn_generate)
        _gen_btn_row = QtWidgets.QHBoxLayout()
        _gen_btn_row.setContentsMargins(12, 0, 12, 0)
        _gen_btn_row.addWidget(self._btn_generate)
        es_vbox.addLayout(_gen_btn_row)

        self._espeak_status = QtWidgets.QLabel("")   # kept as attribute, not shown
        es_vbox.addStretch()
        # 10px of real trailing height, matching the Mic panel -- the
        # disabled grey rectangle's bottom edge extends into this, with
        # room left for the 5px feather.
        es_vbox.addSpacing(10)
        audio_row.addWidget(self._es_panel, 1)
        vbox.addLayout(audio_row)
        vbox.addSpacing(0)   # trimmed to 0 -- also closes the 2px gap
                             # reported above the Signal Processing band

        # =====================================================================
        # Signal Processing
        # =====================================================================
        self._hdr_sigproc = SectionHeader(_tr("section_signal_processing"))
        vbox.addWidget(self._hdr_sigproc)

        sp_row = QtWidgets.QHBoxLayout()
        sp_row.setSpacing(0); sp_row.setContentsMargins(0,0,0,0)

        left_sp = QtWidgets.QWidget()
        left_vbox = QtWidgets.QVBoxLayout(left_sp)
        left_vbox.setContentsMargins(0,4,10,4); left_vbox.setSpacing(2)

        left_vbox.addSpacing(5)   # sliders sit 5px lower than section header
        self._sl_pulse = LabelledSlider(_tr("slider_pulse"), 25, 150, 5, self._pulse_us,
            fmt="{:.0f} \u00b5s", callback=self._cb_pulse, tick_steps=5)
        left_vbox.addWidget(self._sl_pulse)
        self._sl_hpf = LabelledSlider(_tr("slider_hpf"), 80, 160, 20, self._hpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_hpf, tick_steps=1)
        left_vbox.addWidget(self._sl_hpf)
        self._sl_lpf = LabelledSlider(_tr("slider_lpf"), 900, 3600, 100, self._lpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_lpf, tick_steps=1)
        left_vbox.addWidget(self._sl_lpf)

        self._opt_box = QtWidgets.QGroupBox(_tr("optional_filters"))
        opt_box = self._opt_box
        opt_box.setStyleSheet(
            "QGroupBox { font-size:9pt; } QCheckBox { font-size:9pt; }"
            "QLabel#hdr { font-size:8pt; font-weight:bold; color:#2a6ebb;"
            " padding-bottom:2px; }")
        opt_layout = QtWidgets.QGridLayout(); opt_layout.setSpacing(1)
        # Explicit margins -- bottom trimmed 6px so it matches the right
        # edge's whitespace instead of using QGroupBox's larger default.
        opt_layout.setContentsMargins(9, 9, 9, 3)
        opt_layout.setColumnStretch(0, 1)
        opt_layout.setColumnStretch(1, 1)
        opt_layout.setColumnStretch(2, 1)

        # -- Column headers -------------------------------------------------
        _HS = "font-size:8pt; font-weight:bold; color:#2a6ebb; padding-bottom:2px;"
        self._opt_col_headers = []
        for col, key in enumerate(
                ["col_signal_conditioning", "col_noise_silence", "col_zcr_shaping"]):
            h = QtWidgets.QLabel(_tr(key)); h.setStyleSheet(_HS)
            self._opt_col_headers.append((h, key))
            opt_layout.addWidget(h, 0, col)

        # -- Column 0: Signal Conditioning (always-safe, always compatible) --
        self._chk_notch = QtWidgets.QCheckBox(_tr("filt_notch"))
        self._chk_notch.setToolTip(_tr("tt_notch"))
        self._chk_notch.toggled.connect(self._toggle_notch)
        opt_layout.addWidget(self._chk_notch, 1, 0)

        self._chk_preemph = QtWidgets.QCheckBox(_tr("filt_preemph"))
        self._chk_preemph.setToolTip(_tr("tt_preemph"))
        self._chk_preemph.toggled.connect(self._cb_preemph_toggled)
        opt_layout.addWidget(self._chk_preemph, 2, 0)

        self._chk_deemph = QtWidgets.QCheckBox(_tr("filt_deemph"))
        self._chk_deemph.setToolTip(_tr("tt_deemph"))
        self._chk_deemph.toggled.connect(self._cb_deemph_toggled)
        opt_layout.addWidget(self._chk_deemph, 3, 0)

        self._chk_fricative = QtWidgets.QCheckBox(_tr("filt_fricative"))
        self._chk_fricative.setToolTip(_tr("tt_fricative"))
        self._chk_fricative.toggled.connect(self._toggle_fricative)
        opt_layout.addWidget(self._chk_fricative, 4, 0)

        self._chk_f1bandpass = QtWidgets.QCheckBox(_tr("filt_f1bandpass"))
        self._chk_f1bandpass.setToolTip(_tr("tt_f1bandpass"))
        self._chk_f1bandpass.toggled.connect(self._toggle_f1bandpass)
        opt_layout.addWidget(self._chk_f1bandpass, 5, 0)

        self._chk_decimator = QtWidgets.QCheckBox(_tr("filt_decimate"))
        self._chk_decimator.setToolTip(_tr("tt_decimate"))
        self._chk_decimator.toggled.connect(self._toggle_decimator)
        opt_layout.addWidget(self._chk_decimator, 6, 0)

        # -- Column 1: Noise / Silence Gating -----------------------------
        self._chk_noisegate = QtWidgets.QCheckBox(_tr("filt_noisegate"))
        self._chk_noisegate.setToolTip(_tr("tt_noisegate"))
        self._chk_noisegate.toggled.connect(self._toggle_noisegate)
        opt_layout.addWidget(self._chk_noisegate, 1, 1)

        self._chk_env_follow = QtWidgets.QCheckBox(_tr("filt_envfollow"))
        self._chk_env_follow.setToolTip(_tr("tt_envfollow"))
        self._chk_env_follow.toggled.connect(self._toggle_env_follow)
        opt_layout.addWidget(self._chk_env_follow, 2, 1)

        self._chk_spectral_sub = QtWidgets.QCheckBox(_tr("filt_specsub"))
        self._chk_spectral_sub.setToolTip(_tr("tt_specsub"))
        self._chk_spectral_sub.toggled.connect(self._toggle_spectral_sub)
        opt_layout.addWidget(self._chk_spectral_sub, 3, 1)

        # -- Column 2: ZCR Shaping -----------------------------------------
        # NOTE: Schmitt and Hilbert Envelope are mutually exclusive.
        # Schmitt outputs constant-amplitude (+/-0.5) -- HilbertEnv would then
        # see a flat envelope and produce zero output.  Choosing one
        # auto-unchecks the other.
        self._chk_hwrect = QtWidgets.QCheckBox(_tr("filt_hwrect"))
        self._chk_hwrect.setToolTip(_tr("tt_hwrect"))
        self._chk_hwrect.toggled.connect(self._toggle_hwrect)
        opt_layout.addWidget(self._chk_hwrect, 1, 2)

        self._chk_schmitt = QtWidgets.QCheckBox(_tr("filt_schmitt"))
        self._chk_schmitt.setToolTip(_tr("tt_schmitt"))
        self._chk_schmitt.toggled.connect(self._cb_schmitt_toggled)
        opt_layout.addWidget(self._chk_schmitt, 2, 2)

        self._chk_hilbert_env = QtWidgets.QCheckBox(_tr("filt_hilbert"))
        self._chk_hilbert_env.setToolTip(_tr("tt_hilbert"))
        self._chk_hilbert_env.toggled.connect(self._cb_hilbert_env_toggled)
        opt_layout.addWidget(self._chk_hilbert_env, 3, 2)

        opt_box.setLayout(opt_layout)
        left_vbox.addWidget(opt_box)
        left_vbox.addStretch()
        sp_row.addWidget(left_sp, 4)
        sp_row.addWidget(self._vline())

        dc_panel = QtWidgets.QWidget()
        dc_vbox  = QtWidgets.QVBoxLayout(dc_panel)
        dc_vbox.setContentsMargins(4,2,4,6); dc_vbox.setSpacing(0)

        # Live and Peak meters side by side (Live on the left, Peak on
        # the right), with a vertical divider line at the exact centre
        # point between them.  Both use SegmentedMeter (see class above)
        # instead of QProgressBar, which fixes a real bug where the old
        # gradient's colour stops were scoped to the filled chunk's own
        # geometry rather than the bar's absolute value range -- meaning
        # even a low reading could show red right at its own small top
        # edge.
        meters_row = QtWidgets.QHBoxLayout()
        meters_row.setContentsMargins(0,0,0,0); meters_row.setSpacing(0)

        font_lbl = QtGui.QFont("Monospace", 9); font_lbl.setBold(True)
        font_r   = QtGui.QFont("Monospace", 9); font_r.setBold(True)

        # -- Live column (left): existing readout kept --
        live_col = QtWidgets.QVBoxLayout(); live_col.setSpacing(0)
        live_col.addSpacing(4)   # whitespace above the labels
        live_lbl = QtWidgets.QLabel("Live")
        live_lbl.setFont(font_lbl); live_lbl.setStyleSheet("color:black;")
        live_lbl.setAlignment(QtCore.Qt.AlignCenter)
        live_col.addWidget(live_lbl)
        self._dc_readout = QtWidgets.QLabel("--.-%")
        self._dc_readout.setFont(font_r)
        self._dc_readout.setAlignment(QtCore.Qt.AlignCenter)
        self._dc_readout.setStyleSheet("color:black;")
        live_col.addWidget(self._dc_readout)   # directly under label
        live_col.addSpacing(12)   # was 8 -- +4px, moves meter down per request
        self._dc_live_meter = SegmentedMeter(n_segments=8, max_value=8.0)
        live_bar_row = QtWidgets.QHBoxLayout()
        live_bar_row.setContentsMargins(0,0,0,0); live_bar_row.setSpacing(0)
        live_bar_row.addStretch()
        live_bar_row.addWidget(self._dc_live_meter)
        live_bar_row.addStretch()
        live_col.addLayout(live_bar_row)   # no stretch -- meter now has a
                                            # fixed height of its own
        live_col.addSpacing(6)   # guaranteed whitespace below the meter --
                                  # not left purely to leftover stretch,
                                  # since the taller fixed meter leaves
                                  # less slack for that to reliably provide
        live_col.addStretch(1)   # any additional leftover space also
                                  # goes below, not into the meter
        meters_row.addLayout(live_col, 1)

        # Vertical divider -- sits exactly at the midpoint since live_col
        # and peak_col share equal stretch factor (1).  Spans meters_row's
        # full height, which itself stretches to fill from the section's
        # very top down to the horizontal divider below.
        vline = QtWidgets.QFrame()
        vline.setFrameShape(QtWidgets.QFrame.VLine)
        vline.setFrameShadow(QtWidgets.QFrame.Plain)
        vline.setStyleSheet("color:#999;")
        meters_row.addWidget(vline)

        # -- Peak column (right): label, numeric readout, own meter --
        # holding the highest value seen until 10s of inactivity.
        peak_col = QtWidgets.QVBoxLayout(); peak_col.setSpacing(0)
        peak_col.addSpacing(4)   # whitespace above the labels
        peak_lbl = QtWidgets.QLabel("Peak")
        peak_lbl.setFont(font_lbl); peak_lbl.setStyleSheet("color:black;")
        peak_lbl.setAlignment(QtCore.Qt.AlignCenter)
        peak_col.addWidget(peak_lbl)
        self._dc_peak_readout = QtWidgets.QLabel("--.-%")
        self._dc_peak_readout.setFont(font_r)
        self._dc_peak_readout.setAlignment(QtCore.Qt.AlignCenter)
        self._dc_peak_readout.setStyleSheet("color:black;")
        peak_col.addWidget(self._dc_peak_readout)   # directly under label
        peak_col.addSpacing(12)   # was 8 -- +4px, moves meter down per request
        self._dc_peak_meter = SegmentedMeter(n_segments=8, max_value=8.0)
        peak_bar_row = QtWidgets.QHBoxLayout()
        peak_bar_row.setContentsMargins(0,0,0,0); peak_bar_row.setSpacing(0)
        peak_bar_row.addStretch()
        peak_bar_row.addWidget(self._dc_peak_meter)
        peak_bar_row.addStretch()
        peak_col.addLayout(peak_bar_row)   # no stretch -- fixed-height meter
        peak_col.addSpacing(6)   # guaranteed whitespace below the meter,
                                  # matching Live
        peak_col.addStretch(1)   # any additional leftover space also
                                  # goes below, not into the meter
        meters_row.addLayout(peak_col, 1)

        dc_vbox.addLayout(meters_row, 1)

        # Horizontal divider, directly above "Duty Cycle" -- now spans the
        # FULL width, left edge to right edge, built as two equal-stretch
        # line segments that meet exactly at the vertical divider's
        # x-position (since live_col/peak_col share equal stretch factor
        # 1, same as this row's own two halves).
        hline_row = QtWidgets.QHBoxLayout()
        hline_row.setContentsMargins(0,0,0,0); hline_row.setSpacing(0)
        hline_left = QtWidgets.QFrame()
        hline_left.setFrameShape(QtWidgets.QFrame.HLine)
        hline_left.setFrameShadow(QtWidgets.QFrame.Plain)
        hline_left.setStyleSheet("color:#999;")
        hline_row.addWidget(hline_left, 1)
        hline = QtWidgets.QFrame()
        hline.setFrameShape(QtWidgets.QFrame.HLine)
        hline.setFrameShadow(QtWidgets.QFrame.Plain)
        hline.setStyleSheet("color:#999;")
        hline_row.addWidget(hline, 1)
        dc_vbox.addLayout(hline_row)
        dc_vbox.addSpacing(4)

        # Peak-hold state: latches the highest Live reading seen, resets
        # to 0 automatically after 10s with no activity (see
        # _update_displays for the tracking logic).
        self._dc_peak_value = 0.0
        self._dc_peak_last_active = time.monotonic()

        # "Duty Cycle" is centred on dc_panel's full width, which -- since
        # live_col/peak_col share equal stretch and dc_vbox's margins are
        # symmetric (4,4) -- lands it exactly on the vertical divider.
        self._duty_cycle_lbl = QtWidgets.QLabel(_tr("duty_cycle_label"))
        dc_lbl = self._duty_cycle_lbl
        font_dc = QtGui.QFont("Monospace",9); font_dc.setBold(True)
        dc_lbl.setFont(font_dc); dc_lbl.setStyleSheet("color:black;")
        dc_lbl.setAlignment(QtCore.Qt.AlignCenter); dc_lbl.setWordWrap(False)
        dc_vbox.addWidget(dc_lbl)
        sp_row.addWidget(dc_panel,1)
        vbox.addLayout(sp_row)

        # =====================================================================
        # Output
        # =====================================================================
        self._hdr_output = SectionHeader(_tr("section_output"))
        vbox.addWidget(self._hdr_output)
        vbox.addSpacing(0)
        output_row = QtWidgets.QHBoxLayout(); output_row.setSpacing(0)

        self._tx_panel = SwapPanel(divider_side='right')  # left member of its pair -- button sits on its right
        self._tx_panel.setAutoFillBackground(True)
        self._tx_panel.setMinimumHeight(150)
        tx_vbox = QtWidgets.QVBoxLayout(self._tx_panel)
        tx_vbox.setContentsMargins(0,0,4,4); tx_vbox.setSpacing(0)

        hdr_row = QtWidgets.QHBoxLayout(); hdr_row.setContentsMargins(6,0,0,0)
        tx_hdr = QtWidgets.QLabel(
            "<span style='font-weight:bold; color:black;'>SDR Transmitter</span>")
        tx_hdr.setContentsMargins(0,0,0,0)
        tx_hdr.setStyleSheet("margin:0; padding:0;")
        self._keep_black(tx_hdr)
        hdr_row.addWidget(tx_hdr)
        self._hw_lbl = QtWidgets.QLabel(self._hackrf_info)
        self._hw_lbl.setFont(QtGui.QFont("Monospace",7))
        self._hw_lbl.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
        self._hw_lbl.setStyleSheet(
            "color:#27ae60;" if self._hackrf_found else "color:#e74c3c;")
        hdr_row.addWidget(self._hw_lbl)
        tx_vbox.addLayout(hdr_row)
        tx_vbox.addSpacing(0)   # dropdowns moved up another 10px

        # Frequency and TX Power side by side -- now above the description
        combos_row = QtWidgets.QHBoxLayout()
        combos_row.setSpacing(4)   # tightened -- freq_col's own right-shift
                                    # already adds visual separation

        freq_col = QtWidgets.QVBoxLayout(); freq_col.setSpacing(0)
        freq_col.setContentsMargins(6,0,0,0)   # Frequency column moved 6px right
        self._freq_lbl = QtWidgets.QLabel(_tr("transmitter_freq"))
        freq_lbl = self._freq_lbl
        freq_lbl.setStyleSheet("font-size:8pt; color:#777;")
        freq_col.addWidget(freq_lbl)
        self._freq_combo = QtWidgets.QComboBox()
        self._freq_combo.setStyleSheet("QComboBox { padding: 1px 2px; }")
        self._freq_combo.addItem("425 MHz  (70cm)", self.FREQ_70CM)
        self._freq_combo.addItem("1300 MHz (23cm)", self.FREQ_23CM)
        self._freq_combo.setCurrentIndex(1)
        self._freq_combo.currentIndexChanged.connect(self._cb_freq_combo)
        freq_col.addWidget(self._freq_combo)
        combos_row.addLayout(freq_col)

        pwr_col = QtWidgets.QVBoxLayout(); pwr_col.setSpacing(0)
        self._pwr_lbl = QtWidgets.QLabel(_tr("transmitter_pwr"))
        pwr_lbl = self._pwr_lbl
        pwr_lbl.setStyleSheet("font-size:8pt; color:#777;")
        pwr_col.addWidget(pwr_lbl)
        self._pwr_combo = QtWidgets.QComboBox()
        self._pwr_combo.setStyleSheet("QComboBox { padding: 1px 2px; }")
        self._pwr_combo.addItem("1 mW", self.AMP_1MW)
        self._pwr_combo.addItem("2 mW", self.AMP_2MW)
        self._pwr_combo.currentIndexChanged.connect(self._cb_pwr_combo)
        pwr_col.addWidget(self._pwr_combo)
        combos_row.addLayout(pwr_col)

        tx_vbox.addLayout(combos_row)

        # TX button moved down 8px, then another 4px (12px total).
        tx_vbox.addSpacing(12)
        self._btn_tx = QtWidgets.QPushButton(_tr("tx_disabled"))
        self._btn_tx.setCheckable(True); self._btn_tx.setChecked(True)
        self._btn_tx.setMinimumHeight(self.BTN_H)
        self._btn_tx.setStyleSheet(self._style_red())
        self._btn_tx.toggled.connect(self._cb_tx_toggle)
        _tx_btn_row = QtWidgets.QHBoxLayout()
        _tx_btn_row.setContentsMargins(12, 0, 12, 0)
        _tx_btn_row.addWidget(self._btn_tx)
        tx_vbox.addLayout(_tx_btn_row)

        # License text moved down another 4px (now 8px total below button).
        tx_vbox.addSpacing(8)
        self._lic_lbl = QtWidgets.QLabel(
            "<a href='https://en.wikipedia.org/wiki/"
            "Amateur_radio_frequency_allocations#ITU_Region_2'"
            " style='color:#555; text-decoration:none;'>"
            "<b>{}</b></a>".format(_tr("tx_license")))
        lic_lbl = self._lic_lbl
        lic_lbl.setOpenExternalLinks(True)
        lic_lbl.setStyleSheet("font-size:9px;")
        lic_lbl.setWordWrap(True)
        lic_lbl.setContentsMargins(6,0,0,0)
        tx_vbox.addWidget(lic_lbl)
        output_row.addWidget(self._tx_panel, 1)

        self._out_swap = SwapButton(parent=self)
        self._out_swap.clicked.connect(self._cb_output_swap)
        output_row.addWidget(self._out_swap)

        self._save_panel = SwapPanel(divider_side='left')  # right member of its pair -- button sits on its left
        self._save_panel.setAutoFillBackground(True)
        self._save_panel.setMinimumHeight(150)
        save_vbox = QtWidgets.QVBoxLayout(self._save_panel)
        save_vbox.setContentsMargins(4,4,0,5); save_vbox.setSpacing(4)

        self._save_hdr_lbl = QtWidgets.QLabel(_tr("save_to_disk"))
        save_hdr = self._save_hdr_lbl
        save_hdr.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(save_hdr)
        save_vbox.addWidget(save_hdr)

        self._save_path_lbl = QtWidgets.QLabel(_tr("save_description"))
        self._save_path_lbl.setStyleSheet(
            "color:#777; font-size:9px; margin-left:10px; margin-top:0px;")
        self._save_path_lbl.setWordWrap(True)
        self._save_path_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        # Locked to the full description's height (10 lines @ 11px font) so
        # swapping to the short one-line recording filename during Generate
        # Voice never shrinks this label -- and therefore never shrinks the
        # whole Save-to-Disk panel or shifts the Output section around it.
        self._save_path_lbl.setMinimumHeight(50)   # tighter -- blank line removed
        save_vbox.addWidget(self._save_path_lbl)
        save_vbox.addSpacing(4)

        self._btn_record = QtWidgets.QPushButton(_tr("record_iq"))
        self._btn_record.setCheckable(True); self._btn_record.setChecked(False)
        self._btn_record.setMinimumHeight(self.BTN_H)
        self._btn_record.setStyleSheet(self._style_green())
        self._btn_record.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._btn_record.toggled.connect(self._cb_record_toggle)
        _rec_btn_row = QtWidgets.QHBoxLayout()
        _rec_btn_row.setContentsMargins(12, 0, 12, 0)
        _rec_btn_row.addWidget(self._btn_record)
        save_vbox.addLayout(_rec_btn_row)

        self._chk_waterfall = QtWidgets.QCheckBox(_tr("waterfall_checkbox"))
        self._chk_waterfall.setChecked(True)
        self._chk_waterfall.setStyleSheet("color:black;")
        self._keep_black(self._chk_waterfall)
        if not _MPL_OK:
            self._chk_waterfall.setEnabled(False)
            self._chk_waterfall.setText("Waterfall (pip3 install matplotlib)")
        save_vbox.addWidget(self._chk_waterfall)

        output_row.addWidget(self._save_panel, 1)
        vbox.addLayout(output_row)

        # =====================================================================
        # High Power Microwave Calculator -- below Output, at the very
        # bottom.  About half the height of the section's previous
        # incarnation: tighter margins/spacing, a 2-line summary instead
        # of a paragraph, and a compact 3-line data box.
        # =====================================================================
        self._hdr_power_calc = SectionHeader(_tr("power_calc_title"))
        self._hdr_power_calc.setToolTip(_tr("power_calc_summary"))
        vbox.addWidget(self._hdr_power_calc)
        vbox.addSpacing(0)

        pc_section = QtWidgets.QWidget()
        pc_section.setAutoFillBackground(True)
        pc_section.setStyleSheet("background-color: #E3F2FA;")  # light cerulean blue
        pc_section_vbox = QtWidgets.QVBoxLayout(pc_section)
        # Tighter now that the always-visible summary label is gone --
        # the description is a tooltip instead (hover the header or the
        # box below to see it), so the box moves up and the window
        # shrinks by the same amount.
        pc_section_vbox.setContentsMargins(10, 2, 10, 4)
        pc_section_vbox.setSpacing(0)

        # Border removed per request -- same internal layout/positions,
        # just no visible frame.  Background is transparent so the
        # section's own cerulean blue shows through underneath.
        self._power_calc_box = QtWidgets.QGroupBox()
        self._power_calc_box.setToolTip(_tr("power_calc_summary"))
        self._power_calc_box.setStyleSheet(
            "QGroupBox { font-size:9pt; margin-top:0px; border: none;"
            " background: transparent; }")
        pc_box_hbox = QtWidgets.QHBoxLayout(self._power_calc_box)
        # Top margin trimmed from 4 to 1 -- QGroupBox's default style also
        # reserves space for a title even with none set, hence the
        # margin-top:0px override above.  Still enough room for the three
        # 11px text lines at their current size.
        # Bottom margin stretched out (top stays tight) -- the window itself
        # grows to make room, giving the 3 text lines and Reset button
        # more breathing room without touching the already-tightened top.
        # Box height is now determined by the 3 text lines: 6px from top
        # edge to first line, 6px from third line to bottom edge, matching
        # the Reset button's clearance on all three of its exposed sides
        # (top/right/bottom -- left is text, not box edge).
        pc_box_hbox.setContentsMargins(8, 6, 6, 6); pc_box_hbox.setSpacing(6)

        pc_text_vbox = QtWidgets.QVBoxLayout()
        pc_text_vbox.setSpacing(1)

        self._power_count_lbl = QtWidgets.QLabel()
        self._power_count_lbl.setStyleSheet("font-size:11px; color:#333;")
        self._power_count_lbl.setWordWrap(True)
        pc_text_vbox.addWidget(self._power_count_lbl)

        self._power_total_lbl = QtWidgets.QLabel()
        self._power_total_lbl.setStyleSheet("font-size:11px; color:#333;")
        self._power_total_lbl.setWordWrap(True)
        pc_text_vbox.addWidget(self._power_total_lbl)

        self._power_recommended_lbl = QtWidgets.QLabel()
        self._power_recommended_lbl.setStyleSheet("font-size:11px; color:#333;")
        self._power_recommended_lbl.setWordWrap(True)
        pc_text_vbox.addWidget(self._power_recommended_lbl)

        pc_box_hbox.addLayout(pc_text_vbox, 1)

        # Reset -- large rounded-square button, light blue, filling the
        # right end of the box (spans the box's full height via the
        # surrounding QHBoxLayout, rather than being a small inline link).
        self._power_reset_btn = QtWidgets.QPushButton(_tr("power_reset"))
        self._power_reset_btn.setFixedWidth(91)   # 30% wider (70 -> 91);
                                                    # only left edge moves,
                                                    # since text_vbox (its
                                                    # stretchy left neighbor)
                                                    # absorbs the growth
        self._power_reset_btn.setFixedHeight(39)  # top edge moved down 5px;
                                                    # bottom-aligned below so
                                                    # only the top moves
        self._power_reset_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #ADD8E6; color: #1c4f8a;"
            "  border-radius: 10px; font-weight: bold; font-size: 9pt; }"
            "QPushButton:hover { background-color: #bfe6f5; }"
            "QPushButton:pressed { background-color: #9bcfe0; }")
        self._power_reset_btn.clicked.connect(self._cb_power_reset)
        pc_box_hbox.addWidget(self._power_reset_btn, 0, QtCore.Qt.AlignBottom)

        pc_section_vbox.addWidget(self._power_calc_box)
        vbox.addWidget(pc_section)

        # ---- Initial panel states ------------------------------------------
        self._set_panel_active(self._mic_panel,  False)
        self._set_panel_active(self._es_panel,   True)
        self._set_panel_active(self._tx_panel,   False)
        self._set_panel_active(self._save_panel, True)
        self._audio_swap.set_left_dimmed(True);  self._audio_swap.set_right_dimmed(False)
        self._out_swap.set_left_dimmed(True);    self._out_swap.set_right_dimmed(False)

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

        self._ovl_hdr_lbl = QtWidgets.QLabel(_tr("event_log_title"))
        ovl_hdr = self._ovl_hdr_lbl
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
        # fbtaps=+0.999 (not -0.999) so the pole under GR's ADD convention
        # lands near z=+1 (DC), sharpening the rolloff right at 0Hz, instead
        # of near z=-1 (Nyquist) where it did nothing useful.  The [1,-1]
        # feedforward zero already nulls true DC on its own either way, so
        # this bug was silent (not signal-killing) but shaped the wrong
        # part of the spectrum -- same sign-convention issue as the notch.
        self.dc_blocker  = DCBlocker(sr)
        # Notch now implemented as a standalone Python biquad (NotchFilter
        # class above) instead of gr_filter.iir_filter_ffd -- see that
        # class's docstring for why: the iir_filter_ffd version was
        # mathematically verified stable but still caused total signal
        # loss in practice, so this removes all dependency on correctly
        # guessing that block's internal feedback convention.
        self.notch      = NotchFilter(sr)
        self.pre_emph   = gr_filter.fir_filter_fff(1,[1.0])
        # De-emphasis: the literal inverse of pre-emphasis -- a one-pole
        # leaky integrator that tilts the spectrum TOWARD the fundamental
        # instead of away from it, reducing high-frequency ZCR contribution.
        # y[n] = x[n] + 0.5*y[n-1] when active (pole at z=0.5, well inside
        # the unit circle -- stable).  Bypass: fbtaps=[0.0] -> y[n]=x[n].
        self.de_emph    = gr_filter.iir_filter_ffd([1.0],[0.0],True)
        # F1 formant-locked bandpass: restricts audio to ~300-900Hz, the
        # typical first-formant range across vowels and speaker genders.
        # Aggressive -- strips consonant detail and F2/F3 -- but guarantees
        # a large ZCR reduction since almost nothing outside F1 survives.
        # FIR (fir_filter_fff), so always stable regardless of taps.
        self.f1_bandpass = gr_filter.fir_filter_fff(1,[1.0])
        # Fricative suppressor: see FricativeSuppressor class docstring.
        self.fricative_sup = FricativeSuppressor(sr)
        self.noise_gate   = SimpleNoiseGate(threshold_db=-30.0, window=480)
        self.env_follower = EnvelopeFollower(sr)
        self.spectral_sub = SpectralSubtractor(sr)
        self.decimator    = Decimator(sr)
        self.hwrect       = HalfWaveRectifier()
        self.schmitt      = SchmittFilter()
        self.hilbert_env  = HilbertEnvelopeExtractor(sr)
        self.hpf = gr_filter.fir_filter_fff(
            1, firdes.high_pass(1,sr,self._hpf_hz,50,_WIN_HAMMING,6.76))
        self.lpf = gr_filter.fir_filter_fff(
            1, firdes.low_pass(1,sr,self._lpf_hz,200,_WIN_HAMMING,6.76))
        self.agc = analog.agc_ff(1e-4,0.5,1.0); self.agc.set_max_gain(65536)
        self.zcp      = ZeroCrossPulse(sr,self._pulse_us)
        # alpha=5e-5 -> ~417ms time constant at 48kHz.
        # Fast enough: "one" (300ms) reaches ~51% of steady-state, clearly visible.
        # Stable enough: probe decays only 2% between Schmitt pulses, no spiking.
        # (2e-5 was too slow; 5e-4 was too fast and caused spiking.)
        self.dc_probe = analog.probe_avg_mag_sqrd_f(0, 5e-5)
        self.mult     = blocks.multiply_const_ff(self._amplitude)
        # Boxcar (sample-and-hold) upsampling taps: each input sample is
        # repeated RESAMP_INTERP times rather than sinc-interpolated.
        # The default Kaiser-windowed sinc FIR rounds pulse edges over many
        # samples; boxcar preserves rectangular shape with ~500ns transitions.
        # DC gain = sum(taps)/interpolation = INTERP/INTERP = 1.0 (unity).
        _boxcar = [1.0] * self.RESAMP_INTERP
        self.resampler = gr_filter.rational_resampler_fff(
            interpolation=self.RESAMP_INTERP, decimation=self.RESAMP_DECIM,
            taps=_boxcar)
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
        self.connect(self.lpf,        self.f1_bandpass)
        self.connect(self.f1_bandpass, self.fricative_sup)
        self.connect(self.fricative_sup, self.pre_emph)
        self.connect(self.pre_emph,   self.de_emph)
        self.connect(self.de_emph,      self.agc)
        self.connect(self.agc,          self.noise_gate)
        self.connect(self.noise_gate,   self.env_follower)
        self.connect(self.env_follower, self.spectral_sub)
        self.connect(self.spectral_sub, self.decimator)
        self.connect(self.decimator,    self.hwrect)
        self.connect(self.hwrect,       self.schmitt)
        self.connect(self.schmitt,      self.hilbert_env)
        self.connect(self.hilbert_env,  self.zcp)
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
        if dc < 0.05: dc = 0.0   # clamp noise floor -- prevents visual spiking
        dc_clamped = min(8.0, max(0.0, dc))   # meter scale tops out at 8%
        self._dc_live_meter.set_value(dc_clamped)
        self._dc_readout.setText("{:4.1f}%".format(max(0.0,dc)))

        # Peak-hold: latch the highest Live reading seen, reset to 0
        # automatically after 10s with no activity.  "Activity" is any
        # reading above the same noise floor used above.
        now = time.monotonic()
        if dc > 0.05:
            self._dc_peak_last_active = now
            if dc_clamped > self._dc_peak_value:
                self._dc_peak_value = dc_clamped
        elif now - self._dc_peak_last_active > 10.0:
            self._dc_peak_value = 0.0
        self._dc_peak_meter.set_value(self._dc_peak_value)
        self._dc_peak_readout.setText("{:4.1f}%".format(self._dc_peak_value))

        self._update_power_calc()   # keeps the rolling pulse counter live

    # =========================================================================
    #  Callbacks
    # =========================================================================

    def _update_power_calc(self):
        """
        Refreshes all three Power Calculation rows.  Called on every
        pulse-width slider move (immediate math update), every 100ms
        display tick (keeps the rolling pulse counters live), once per
        Generate Voice press (Last Action count reset), and once after a
        language switch so the translated label prefixes stay in sync.

        Joule values use dense fixed-decimal formatting: ##.##J (@1.5kW),
        compact enough to avoid word-wrap in longer languages while
        staying easier to scan at a glance than scientific notation.
        """
        count       = self.zcp.get_pulse_count()
        last_action = self.zcp.get_last_action_count()
        pulse_s     = self._pulse_us * 1e-6

        def _tag(p_w):
            # {:g} drops trailing zeros so 1500W reads "1.5kW", not "2kW"
            # (which {:.0f} would round it to) or "1.500kW".
            return "{:.0f}W".format(p_w) if p_w < 1000 else \
                  "{:g}kW".format(p_w / 1000.0)

        def _fmt_j(value, p_w):
            return "{:.2f}J (@{})".format(value, _tag(p_w))

        # Row 1: Session Pulse Count, plus Last Action Pulse Count (pulses
        # since the most recent Generate Voice press) -- separated by
        # several spaces.
        self._power_count_lbl.setText(
            "{} {}      {} {}".format(
                _tr("power_session_count"), count,
                _tr("power_last_action_count"), last_action))

        # "Point Blank" wattage to hit a ~16mJ/pulse target at the CURRENT
        # pulse width: P = Energy / pulse_duration.  At exactly this
        # wattage, energy-per-pulse is by definition target_j, so the
        # recommended tier's total energy simplifies to count*target_j.
        target_j = 0.016   # 16 mJ
        p_point_blank = target_j / pulse_s if pulse_s > 0 else 0.0
        recommended_total_j = count * target_j

        # Row 2: Total Energy Output -- Recommended tier first, then the
        # two fixed hypothetical amplifier tiers (1.5kW, 4kW).
        total_parts = ["{:.2f}J (@Ideal)".format(recommended_total_j)]
        total_parts += [_fmt_j(count * pulse_s * p_w, p_w)
                        for p_w in self._POWER_LEVELS_W]
        self._power_total_lbl.setText(
            "{} {}".format(_tr("power_total_energy"), ",    ".join(total_parts)))

        # Row 3: Recommended amplifier output at three reference distances.
        # No antenna gain assumed -- a directional horn genuinely can
        # reduce the transmitter power needed for a given power density
        # at range (that's what EIRP means), but real SME literature on
        # horn-waveguide setups still pairs them with thousands of watts,
        # not the dramatically reduced figures gain math alone would
        # suggest.  Rather than assert a specific gain figure this app
        # can't verify against real hardware, this shows the plain
        # isotropic (no-gain) figure at each distance and leaves the
        # standard inverse-square dB-per-doubling adjustment to the
        # reader, if they want to reason about a specific antenna's gain
        # themselves.
        #
        # @Source is the raw target-energy/pulse-duration figure above --
        # power delivered with no free-space spreading loss (no
        # meaningful far-field pattern at essentially zero range).
        # @50cm/@1m use the isotropic-radiator power-density formula,
        # S(r) = P/(4*pi*r^2), rearranged to solve for the transmitter
        # power needed to reproduce that power density at distance r:
        # P(r) = P_source * 4*pi*r^2.
        p_50cm = p_point_blank * 4.0 * math.pi * (0.5 ** 2)
        p_1m   = p_point_blank * 4.0 * math.pi * (1.0 ** 2)
        self._power_recommended_lbl.setText(
            "{} {:.0f}W (@Source),   {:.0f}W (@50cm),   {:.0f}W (@1m)".format(
                _tr("power_recommended"), p_point_blank, p_50cm, p_1m))

    def _cb_power_reset(self, _href=None):
        """Reset button clicked -- zero both the session and last-action
        pulse counters."""
        self.zcp.reset_pulse_count()
        self.zcp.reset_last_action_count()
        self._update_power_calc()
        self._log("Power Calculation reset")

    def _cb_pulse(self, v):
        self._pulse_us = v; self.zcp.set_pulse_width_us(v)
        self._update_power_calc()
        self._log("Pulse width: {:.0f} \u00b5s".format(v))

    def _cb_hpf(self, v):
        self._hpf_hz = v
        self.hpf.set_taps(firdes.high_pass(1, self.AUDIO_RATE, v, 50,
                                            _WIN_HAMMING, 6.76))
        self._log("HPF: {:.0f} Hz".format(v))

    def _cb_lpf(self, v):
        self._lpf_hz = v
        self.lpf.set_taps(firdes.low_pass(1, self.AUDIO_RATE, v, 200,
                                           _WIN_HAMMING, 6.76))
        self._log("LPF: {:.0f} Hz".format(v))

    def _toggle_notch(self, e):
        self.notch.set_enabled(e)
        self._log("Filter {} -- 50/60 Hz Notch".format(
            "ON" if e else "off"))

    def _cb_preemph_toggled(self, checked):
        """Enable Pre-emphasis; if turning on, uncheck the opposing De-emphasis.
        [1, -0.9375] attenuates 180 Hz to ~7.5% -- too low for pitch=20.
        Use [1, -0.5] instead: 180 Hz -> ~50%, keeps speech above Schmitt."""
        self.pre_emph.set_taps([1.0, -0.5] if checked else [1.0])
        self._log("Filter {} -- Pre-emphasis".format("ON" if checked else "off"))
        if checked and self._chk_deemph.isChecked():
            self._chk_deemph.blockSignals(True)
            self._chk_deemph.setChecked(False)
            self._chk_deemph.blockSignals(False)
            self.de_emph.set_taps([1.0], [0.0])
            self._log("Filter off -- De-emphasis (mutex)")

    def _cb_deemph_toggled(self, checked):
        """Enable De-emphasis; if turning on, uncheck the opposing Pre-emphasis.
        Inverse of pre-emphasis: y[n] = x[n] + 0.5*y[n-1], a one-pole leaky
        integrator tilting the spectrum toward the fundamental instead of
        away from it -- reduces high-frequency ZCR contribution."""
        self.de_emph.set_taps([1.0], [0.5] if checked else [0.0])
        self._log("Filter {} -- De-emphasis".format("ON" if checked else "off"))
        if checked and self._chk_preemph.isChecked():
            self._chk_preemph.blockSignals(True)
            self._chk_preemph.setChecked(False)
            self._chk_preemph.blockSignals(False)
            self.pre_emph.set_taps([1.0])
            self._log("Filter off -- Pre-emphasis (mutex)")

    def _toggle_fricative(self, e):
        self.fricative_sup.set_enabled(e)
        self._log("Filter {} -- Fricative Suppressor".format(
            "ON" if e else "off"))

    def _toggle_f1bandpass(self, e):
        # ~300-900Hz passband covers F1 across vowels and speaker genders.
        # 100Hz transition width matches the HPF/LPF convention already
        # used elsewhere in this chain.
        taps = (firdes.band_pass(1, self.AUDIO_RATE, 300, 900, 100,
                                 _WIN_HAMMING, 6.76) if e else [1.0])
        self.f1_bandpass.set_taps(taps)
        self._log("Filter {} -- F1 Formant Bandpass".format(
            "ON" if e else "off"))

    def _toggle_noisegate(self, e):
        self.noise_gate.set_enabled(e)
        self._log("Filter {} -- Noise Gate".format("ON" if e else "off"))
        self._enforce_noise_silence_mutex()

    def _toggle_env_follow(self, e):
        self.env_follower.set_enabled(e)
        self._log("Filter {} -- Envelope Follower".format("ON" if e else "off"))
        self._enforce_noise_silence_mutex()

    def _toggle_hwrect(self, e):
        self.hwrect.set_enabled(e)
        self._log("Filter {} -- Half-wave Rect.".format("ON" if e else "off"))

    def _toggle_hilbert_env(self, e):
        self.hilbert_env.set_enabled(e)
        self._log("Filter {} -- Hilbert Envelope".format("ON" if e else "off"))

    def _toggle_decimator(self, e):
        self.decimator.set_enabled(e)
        self._log("Filter {} -- Downsample/Decimate".format("ON" if e else "off"))

    def _toggle_schmitt(self, e):
        self.schmitt.set_enabled(e)
        self._log("Filter {} -- Schmitt Trigger".format("ON" if e else "off"))

    def _toggle_spectral_sub(self, e):
        self.spectral_sub.set_enabled(e)
        self._log("Filter {} -- Spectral Subtraction".format(
            "ON" if e else "off"))
        self._enforce_noise_silence_mutex()

    def _enforce_noise_silence_mutex(self):
        """
        Noise Gate, Envelope Follower, and Spectral Subtraction are meant
        to be used in pairs, not all three together (their tooltips say
        as much).  If toggling any of the three would leave all three
        checked at once, uncheck Envelope Follower specifically -- it's
        the one most redundant with either of the other two individually.
        """
        if (self._chk_noisegate.isChecked() and self._chk_env_follow.isChecked()
                and self._chk_spectral_sub.isChecked()):
            self._chk_env_follow.blockSignals(True)
            self._chk_env_follow.setChecked(False)
            self._chk_env_follow.blockSignals(False)
            self.env_follower.set_enabled(False)
            self._log("Filter off -- Envelope Follower (avoids all three "
                      "noise/silence filters at once)")

    def _cb_schmitt_toggled(self, checked):
        """Enable Schmitt; if turning on, uncheck the incompatible HilbertEnv."""
        self.schmitt.set_enabled(checked)
        self._log("Filter {} -- Schmitt Trigger".format("ON" if checked else "off"))
        if checked and self._chk_hilbert_env.isChecked():
            self._chk_hilbert_env.blockSignals(True)
            self._chk_hilbert_env.setChecked(False)
            self._chk_hilbert_env.blockSignals(False)
            self.hilbert_env.set_enabled(False)
            self._log("Filter off -- Hilbert Envelope (mutex)")

    def _cb_hilbert_env_toggled(self, checked):
        """Enable HilbertEnv; if turning on, uncheck the incompatible Schmitt."""
        self.hilbert_env.set_enabled(checked)
        self._log("Filter {} -- Hilbert Envelope".format("ON" if checked else "off"))
        if checked and self._chk_schmitt.isChecked():
            self._chk_schmitt.blockSignals(True)
            self._chk_schmitt.setChecked(False)
            self._chk_schmitt.blockSignals(False)
            self.schmitt.set_enabled(False)
            self._log("Filter off -- Schmitt Trigger (mutex)")

    def _cb_audio_swap(self):
        self._audio_left_active = not self._audio_left_active
        if self._audio_left_active:
            self._set_panel_active(self._mic_panel,True)
            self._set_panel_active(self._es_panel,False)
            self._audio_swap.set_left_dimmed(False)
            self._audio_swap.set_right_dimmed(True)
            self.mic_gate.set_k(1.0); self.espeak_gate.set_k(0.0)
            self._btn_mute.setChecked(True)
            self._btn_mute.setText(_tr("mic_muted"))
            self._btn_mute.setStyleSheet(self._style_red())
            self.mute_gate.set_k(0.0); self._muted=True
            self._log("Input: Live Microphone (muted)")
            # Real mic hardware can genuinely pick up AC mains hum;
            # eSpeak's synthetic audio never has any, so auto-enable the
            # Notch filter now that the mic is the active input.
            if not self._chk_notch.isChecked():
                self._chk_notch.setChecked(True)   # fires _toggle_notch
        else:
            self._set_panel_active(self._mic_panel,False)
            self._set_panel_active(self._es_panel,True)
            self._audio_swap.set_left_dimmed(True)
            self._audio_swap.set_right_dimmed(False)
            self.mic_gate.set_k(0.0); self.espeak_gate.set_k(1.0)
            self._level_meter.freeze()
            self._level_db_lbl.setText("-60.0 dB")
            self._level_db_lbl.setStyleSheet(
                "color:#27ae60; font-family:Monospace; font-size:8px;")
            self._log("Input: eSpeak TTS")
            # Switching back to eSpeak TTS -- no mains hum to remove, so
            # auto-disable the Notch filter again.
            if self._chk_notch.isChecked():
                self._chk_notch.setChecked(False)   # fires _toggle_notch

    def _cb_output_swap(self):
        self._output_left_active = not self._output_left_active
        if self._output_left_active:
            self._hw_lbl.setText(self._hackrf_info)
            self._hw_lbl.setStyleSheet(
                "color:#27ae60;" if self._hackrf_found else "color:#e74c3c;")
            self._set_panel_active(self._tx_panel,True)
            self._set_panel_active(self._save_panel,False)
            self._out_swap.set_left_dimmed(False)
            self._out_swap.set_right_dimmed(True)
            self.tx_gate.set_k((0+0j))
            self._btn_tx.setChecked(True)
            self._btn_tx.setText(_tr("tx_disabled"))
            self._btn_tx.setStyleSheet(self._style_red())
            self._log("Output: HackRF Transmitter (disabled)")
        else:
            self.tx_gate.set_k((0+0j))
            if not self._btn_tx.isChecked(): self._btn_tx.setChecked(True)
            self._set_panel_active(self._tx_panel,False)
            self._set_panel_active(self._save_panel,True)
            self._out_swap.set_left_dimmed(True)
            self._out_swap.set_right_dimmed(False)
            self._log("Output: Save to Disk")

    def _cb_freq_combo(self,idx):
        self._freq_hz=self._freq_combo.itemData(idx)
        if self._hackrf_found: self.hackrf.set_center_freq(self._freq_hz,0)

    def _cb_pwr_combo(self,idx):
        self._amplitude=self._pwr_combo.itemData(idx)
        self.mult.set_k(self._amplitude)

    def _cb_mute(self,muted):
        self._muted=muted; self.mute_gate.set_k(0.0 if muted else 1.0)
        self._btn_mute.setText(_tr("mic_muted") if muted else _tr("mic_live"))
        self._btn_mute.setStyleSheet(
            self._style_red() if muted else self._style_green())
        self._log("Microphone muted" if muted else "Microphone live -- monitoring")

    def _cb_tx_toggle(self,disabled):
        if disabled:
            self.tx_gate.set_k((0+0j))
            self._btn_tx.setText(_tr("tx_disabled"))
            self._btn_tx.setStyleSheet(self._style_red())
            self._log("Transmitter disabled")
        else:
            self.tx_gate.set_k((1+0j))
            self._btn_tx.setText(_tr("tx_enabled"))
            self._btn_tx.setStyleSheet(self._style_green())
            self._log("Transmitting on {:.0f} MHz".format(self._freq_hz/1e6))

    def _on_espeak_text_changed(self):
        raw=self._espeak_input.toPlainText().replace('\n',' ')
        clean=self._ESPEAK_ALLOWED_RE.sub('',raw)[:140]
        if clean!=raw:
            self._espeak_input.blockSignals(True)
            pos=self._espeak_input.textCursor().position()
            self._espeak_input.setPlainText(clean)
            cur=self._espeak_input.textCursor()
            cur.setPosition(min(pos,len(clean)))
            self._espeak_input.setTextCursor(cur)
            self._espeak_input.blockSignals(False)
        self._char_counter.setText("{}/140".format(len(clean)))

    def _cb_generate_espeak(self):
        text = self._espeak_input.toPlainText().strip().replace('\n',' ')
        text = self._ESPEAK_ALLOWED_RE.sub('', text)[:140]
        # DIAGNOSTIC: always log so we can confirm clicks are reaching this
        # function even on the first press.  Check the Event Log.
        self._log("Generate Voice clicked -- text='{}' ({} chars)".format(
            text[:24], len(text)))
        self._update_power_calc()
        if not text:
            self._espeak_input.setPlaceholderText(_tr("placeholder_enter_text"))
            return

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

        # Build espeak command
        use_mbrola = _LOCALE_MBROLA_OK and self._chk_mbrola.isChecked()
        cmd = [cmd_found]
        if use_mbrola:
            # MBROLA: -p (pitch) disrupts diphone synthesis -- omit it.
            # Voice code matches the detected OS locale (e.g. mb-de6, mb-fr4).
            cmd += ['-v', 'mb-{}'.format(_LOCALE_MBROLA_CODE),
                    '-a', '200', '-s', '130']
        else:
            # Formant synthesis in the detected locale's language.
            # pitch 20 reduces ZCR; speed 130 < default 175.
            cmd += ['-v', _LOCALE_ESPEAK_VOICE, '-p', '20', '-s', '130']
        cmd += ['-w', self.ESPEAK_RAW, text]

        # Ensure espeak-ng can locate the MBROLA voice data at synthesis time
        env = os.environ.copy()
        env.setdefault('MBROLA', '/usr/share/mbrola')

        self._log("eSpeak cmd: {}".format(' '.join(cmd)), in_progress=True)

        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=15, env=env)
        if r.returncode != 0:
            self._log("ERROR eSpeak: {}".format(r.stderr.strip()[:100]))
            return
        # Surface any warnings (e.g. mbrola binary missing at synthesis time)
        if r.stderr.strip():
            self._log("eSpeak warn: {}".format(r.stderr.strip()[:100]))
        # Verify output file was written with non-trivial content
        if not os.path.exists(self.ESPEAK_RAW) or \
                os.path.getsize(self.ESPEAK_RAW) < 200:
            self._log("ERROR: No audio generated -- "
                      "check mbrola binary (sudo apt install mbrola)")
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

        # 1 second of silence on each end:
        #   lead  -- clean IQ pre-roll before the pulse train starts
        #   trail -- keeps the loop gate from closing mid-pulse
        #   total duration = 1s + speech + 1s; average duty cycle stays ~2-4%
        pad = np.zeros(int(self.AUDIO_RATE * self.ESPEAK_SILENCE_SEC),
                       dtype=np.float32)
        samples = np.concatenate([pad, samples, pad])

        # Total one-shot duration in ms (speech + silence padding)
        total_ms = int(len(samples) / self.AUDIO_RATE * 1000)

        self._write_samples_wav(self.ESPEAK_WAV, samples, self.AUDIO_RATE)

        # Diagnostic: verify WAV has actual speech content (RMS > 0 = speech)
        try:
            with wave.open(self.ESPEAK_WAV, 'r') as _wf:
                _d = np.frombuffer(_wf.readframes(_wf.getnframes()),
                                   dtype=np.int16).astype(np.float32)
            _rms = float(np.sqrt(np.mean(_d**2))) if len(_d) > 0 else 0.0
            self._log("WAV: {:.0f}ms  {:.0f} samples  RMS={:.0f} "
                      "(0=silent, >500=speech)".format(
                          len(_d) / self.AUDIO_RATE * 1000, len(_d), _rms))
        except Exception as _e:
            self._log("WAV check: {}".format(_e))

        # Hot-swap espeak source AND open gates atomically inside the lock so
        # there is no window where the scheduler runs on the new source with
        # mute_gate still at 0.0, which would cause all samples to be zeroed.
        try:
            self.lock()
            try:
                self.disconnect(self.espeak_src, self.espeak_gate)
                self.espeak_src = blocks.wavfile_source(self.ESPEAK_WAV, True)
                self.connect(self.espeak_src, self.espeak_gate)
                # Reset AGC gain to 1.0 before speech arrives.
                # With mute_gate=0 between presses, AGC receives zeros and
                # ramps its gain up to ~3.4x during silence -- clipping
                # the first speech frames and causing inconsistent output.
                self.agc.set_gain(1.0)
                # Gates set BEFORE unlock so the scheduler sees them on resume
                self.espeak_gate.set_k(1.0)
                self.mic_gate.set_k(0.0)
                self.mute_gate.set_k(1.0)
                # Reset the Last TTS Action counter HERE, right as audio
                # actually starts flowing -- resetting it earlier (at the
                # button click) left a window during espeak synthesis where
                # residual/silence state could tick the counter to 1 before
                # real audio ever arrived.
                self.zcp.reset_last_action_count()
            finally:
                self.unlock()   # always unlock -- prevents flow graph staying locked
        except Exception as e:
            self._log("ERROR GR reload: {}".format(e))
            return

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
        self.espeak_gate.set_k(0.0)   # close espeak -- no loop heard
        self.mute_gate.set_k(0.0)     # close mute gate -- stops any audio-src
        # noise from leaking through ZCP and appearing in the IQ recording /
        # waterfall active-region detection after playback ends.
        self._log("eSpeak playback complete")
        if self._espeak_auto_record and self._btn_record.isChecked():
            self._espeak_auto_record = False
            self._btn_record.setChecked(False)   # auto-stop recording
        else:
            self._espeak_auto_record = False

    def _cb_record_toggle(self,recording):
        if recording:
            stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            self._record_path=os.path.expanduser('~/OpenV2K_{}.iq'.format(stamp))
            try:
                self.lock()
                try:
                    self.disconnect(self.f2c,self.iq_recorder)
                    self.iq_recorder=blocks.file_sink(
                        gr.sizeof_gr_complex,self._record_path)
                    self.connect(self.f2c,self.iq_recorder)
                finally:
                    self.unlock()   # always unlock
            except Exception as e:
                self._log("ERROR starting record: {}".format(e)); return
            self._btn_record.setText(_tr("recording"))
            self._btn_record.setStyleSheet(self._style_red())
            self._save_path_lbl.setText(os.path.basename(self._record_path))
            self._log("Recording IQ to disk",in_progress=True)
        else:
            try:
                self.lock()
                try:
                    self.disconnect(self.f2c,self.iq_recorder)
                    self.iq_recorder=blocks.null_sink(gr.sizeof_gr_complex)
                    self.connect(self.f2c,self.iq_recorder)
                finally:
                    self.unlock()   # always unlock
            except Exception as e:
                self._log("ERROR stopping record: {}".format(e))
            self._btn_record.setText(_tr("record_iq"))
            self._btn_record.setStyleSheet(self._style_green())
            self._save_path_lbl.setText(_tr("save_description"))
            self._log("Recording stopped")
            if self._chk_waterfall.isChecked() and self._record_path and _MPL_OK:
                self._log("Generating waterfall graph image",in_progress=True)
                QtWidgets.QApplication.processEvents()
                t=threading.Thread(target=self._generate_waterfall,
                                   args=(self._record_path,),daemon=True)
                t.start()

    def _generate_waterfall(self, iq_path):
        try:
            data = np.fromfile(iq_path, dtype=np.complex64)
            if len(data) < 256:
                self._log("Waterfall: recording too short"); return

            sr       = self.HACKRF_RATE
            fft_size = 64
            # Fixed hop = 32 samples = 16 us/frame.
            # A 100 us pulse always spans 100/16 = 6.25 frames regardless
            # of recording length.  Image width scales instead of hop.
            hop     = 32
            step_us = hop / sr * 1e6   # 16.0 us

            # ---- Locate the FULL active region ------------------------------
            mag    = np.abs(data)
            thresh = max(mag.max() * 0.05, 1e-9)
            active = np.where(mag > thresh)[0]
            if len(active) == 0:
                self._log("Waterfall: no signal found"); return

            pre   = int(sr * 0.001)
            post  = int(sr * 0.001)
            start = max(0, active[0]  - pre)
            end   = min(len(data), active[-1] + post)
            chunk = data[start:end]
            if len(chunk) < fft_size:
                self._log("Waterfall: active window too short"); return

            # Warn and cap very long recordings (> 8 s active) before
            # building the spectrogram array to bound memory usage.
            MAX_S = 3.0
            if len(chunk) > int(sr * MAX_S):
                self._log(
                    "Waterfall: active region > {:.0f}s, "
                    "truncated to first {:.0f}s".format(MAX_S, MAX_S))
                chunk = chunk[:int(sr * MAX_S)]
                end   = start + len(chunk)

            # ---- Spectrogram (vectorised -- no Python loop) -----------------
            win  = np.hanning(fft_size).astype(np.float32)
            n_fr = (len(chunk) - fft_size) // hop
            # sliding_window_view gives overlapping frames in one call;
            # np.fft.fft(axis=1) transforms all frames simultaneously.
            # 50-100x faster than a Python for-loop for large n_fr.
            from numpy.lib.stride_tricks import sliding_window_view
            frames = sliding_window_view(chunk, fft_size)[::hop][:n_fr]
            spec   = (10.0 * np.log10(
                np.fft.fftshift(
                    np.abs(np.fft.fft(frames * win, axis=1))**2,
                    axes=1) + 1e-10)).astype(np.float32)

            t0_ms  = start / sr * 1000.0
            t1_ms  = (start + len(chunk)) / sr * 1000.0
            dur_ms = t1_ms - t0_ms

            # ---- Proportional image width -----------------------------------
            # Target: 10 px/ms so each 100 us pulse maps to ~1 pixel.
            # The image widens for longer recordings; viewers can scroll.
            # 40px/ms -> 100us pulse = 4px, 25us pulse = 1px.
            # Images scale with duration; viewers scroll horizontally.
            PX_PER_MS = 40.0
            DPI        = 150
            FIG_H      = 6.0      # 6in height to bound memory on wide images
            width_px   = max(1500, int(dur_ms * PX_PER_MS))
            fig_w      = width_px / DPI   # inches

            self._log(
                "Waterfall: {:.0f}ms active  |  {}x{} px  |  "
                "{:.1f}px/ms  (~1px per 100us pulse)"
                .format(dur_ms, width_px, int(FIG_H * DPI), PX_PER_MS))

            # ---- Amplitude envelope -----------------------------------------
            t_env = (np.arange(len(chunk)) + start) / sr * 1000.0

            # ---- Plot -------------------------------------------------------
            fig, (ax1, ax2) = plt.subplots(
                2, 1, figsize=(fig_w, FIG_H),
                gridspec_kw={'height_ratios': [3, 1]},
                sharex=True)

            fig.suptitle(
                'OpenV2K Pulse Waterfall  --  {}\n'
                '{:.0f} ms active  |  hop={:.0f} us  |  '
                '{:.0f} px/ms  (100us=4px, 25us=1px)  |  {}x{} px'
                .format(os.path.basename(iq_path),
                        dur_ms, step_us,
                        PX_PER_MS, width_px, int(FIG_H * DPI)),
                fontsize=9)

            # interpolation='nearest' prevents anti-alias blurring of
            # narrow pulse streaks -- each pulse stays ~1 pixel wide.
            ax1.imshow(spec.T, aspect='auto', origin='lower',
                       extent=[t0_ms, t1_ms, -sr/2/1e6, sr/2/1e6],
                       cmap='inferno', interpolation='nearest')
            ax1.set_ylabel('Freq offset (MHz)')
            plt.colorbar(ax1.images[0], ax=ax1, label='Power (dB)',
                         fraction=0.02, pad=0.01)

            ax2.plot(t_env, mag[start:end], color='#2a6ebb', linewidth=0.3)
            ax2.set_xlabel('Time (ms)')
            ax2.set_ylabel('|IQ|')
            ax2.set_xlim(t0_ms, t1_ms)

            plt.tight_layout()
            png = iq_path.replace('.iq', '.png')
            plt.savefig(png, dpi=DPI, bbox_inches='tight')
            plt.close(fig)
            subprocess.Popen(['xdg-open', png],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
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

    def _start_suppressed(self):
        """Start the GR flow graph. stderr suppression is now handled at
        build time (wrapping _build_blocks in __init__) where audio.source
        actually opens the device and emits the QSocketNotifier warning."""
        self.start()

    def _prime_mbrola_async(self):
        """Warm up espeak-ng in a background thread using FORMANT synthesis
        in the detected locale's language (not MBROLA) so there is no risk
        of sharing MBROLA temp files or pipes with the first real synthesis
        the user triggers."""
        def _prime():
            import tempfile
            for cmd in ['espeak-ng', 'espeak']:
                try:
                    with tempfile.NamedTemporaryFile(suffix='.wav',
                                                    delete=True) as f:
                        subprocess.run(
                            [cmd, '-v', _LOCALE_ESPEAK_VOICE,
                             '-p', '20', '-s', '130', '-a', '0',
                             '-w', f.name, 'a'],
                            capture_output=True, timeout=10)
                    break
                except (FileNotFoundError, Exception):
                    continue
        threading.Thread(target=_prime, daemon=True).start()

    def closeEvent(self,event):
        self._level_timer.stop(); self.stop(); self.wait(); event.accept()


# =============================================================================
#  Entry point
# =============================================================================

def main():
    _cleanup_orphans()   # kill previous OpenV2K instances, remove stale WAVs
    # Suppress Wayland "does not support QWindow::requestActivate()" noise
    # that appears when combo box popups open on Wayland compositors.
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.wayland*=false')
    check_prerequisites()   # terminal report; exits if critical deps missing
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("OpenV2K")
    # QSocketNotifier suppression is handled at the fd level inside __init__
    # wrapping _build_blocks() -- no separate message-filter call needed.
    tb = OpenV2K(); tb.show()
    # Defer GR start until the Qt event loop is running.
    # Use _start_suppressed so the QSocketNotifier noise is silenced at
    # the fd level, and MBROLA gets a warm-up call before first use.
    QtCore.QTimer.singleShot(0, tb._start_suppressed)

    def _zero_power_calc_baseline():
        # Defensive: guarantees the Session Pulse Count / Last TTS Action /
        # Total Energy Output readings start at a clean 0, in case any IIR
        # filter startup transient produced a spurious crossing before the
        # flow graph settled.  300ms after start is well past any such
        # transient.
        tb.zcp.reset_pulse_count()
        tb.zcp.reset_last_action_count()
        tb._update_power_calc()
    QtCore.QTimer.singleShot(300, _zero_power_calc_baseline)

    def _quit(sig=None,frame=None):
        tb.stop(); tb.wait(); app.quit()

    signal.signal(signal.SIGINT,  _quit)
    signal.signal(signal.SIGTERM, _quit)
    tick = QtCore.QTimer(); tick.start(200)
    tick.timeout.connect(lambda: None)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
