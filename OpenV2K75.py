#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: Unlicense
# This is free and unencumbered software released into the public domain.
#
# OpenV2K75.py -- Zero-Crossing Pulse Transmitter
# ================================================
# Requirements:
#   sudo apt install gnuradio gr-osmosdr hackrf python3-pyqt5 espeak-ng
#   pip3 install matplotlib --break-system-packages
# Usage:
#   python3 OpenV2K75.py

import sys
import os
import re
import math
import wave
import signal
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
    'col_signal_conditioning':    'Signal Conditioning',
    'col_noise_silence':          'Noise / Silence',
    'col_zcr_shaping':            'ZCR Shaping',
    'filt_notch':                 '50/60 Hz Notch',
    'filt_preemph':               'Pre-emphasis',
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
    'duty_summary':                'Avg: 2-4%\nMax: 10%\n>6% over spec',
    'duty_cycle_label':            'Pulse Duty Cycle',
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
        ' \n'
        'At 2 MHz sample rate: approx 16 MB/sec.\n'
        'A 30 second capture uses about 480 MB.\n'
        'Plan your storage before long recordings.\n'
        ' \n'
        'Waterfall: short-time FFT via numpy,\n'
        'rendered with matplotlib inferno map.\n'
        'Opens automatically in system viewer.',
    'record_iq':                   'Record IQ',
    'recording':                   'Recording...',
    'waterfall_checkbox':          'Generate Waterfall Graph Image',
    'event_log':                   'Event Log',
    'event_log_title':             '  OpenV2K  Event Log',
    'no_mbrola_voice':
        'No MBROLA voice available for this language -- '
        'using eSpeak formant synthesis instead.',
},

'de': {
    'section_audio_input':        'Audioeingang',
    'section_signal_processing':  'Signalverarbeitung',
    'section_output':             'Ausgabe',
    'live_microphone':            'Live-Mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Audio-Wellenform Nulldurchgang-Pulsgenerator',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofonpegel: -45 dB in Stille, -18 dB beim Sprechen anstreben.\n'
        'Einstellen unter: Systemeinstellungen > Sound > Eingang.',
    'mic_muted':                  'Mikro: STUMM',
    'mic_live':                   'Mikro: LIVE',
    'generate_voice':             'Stimme erzeugen',
    'placeholder_hello':          'Hallo Welt',
    'placeholder_enter_text':     'Text hier eingeben',
    'optional_filters':           'Optionale Filter',
    'col_signal_conditioning':    'Signalaufbereitung',
    'col_noise_silence':          'Rauschen / Stille',
    'col_zcr_shaping':            'ZCR-Formung',
    'filt_notch':                 '50/60 Hz Notch',
    'filt_preemph':               'Pre-Emphase',
    'filt_decimate':              'Downsampling / Dezimierung',
    'filt_noisegate':             'Rauschsperre',
    'filt_envfollow':             'Hüllkurvenfolger',
    'filt_specsub':               'Spektrale Subtraktion',
    'filt_hwrect':                'Einweggleichrichtung',
    'filt_schmitt':                'Schmitt-Trigger',
    'filt_hilbert':                'Hilbert-Hüllkurve',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'TPF (Hz)',
    'duty_summary':                'Mittel: 2-4%\nMax: 10%\n>6% außerhalb Spez.',
    'duty_cycle_label':            'Puls-Tastgrad',
    'transmitter_freq':            'Frequenz:',
    'transmitter_pwr':             'Sendeleistung:',
    'tx_disabled':                 'TX: AUS',
    'tx_enabled':                  'TX: EIN',
    'tx_license':
        'Für das Senden auf diesen Frequenzen ist eine gültige '
        'Amateurfunklizenz erforderlich. '
        'Prüfen Sie Ihren nationalen Frequenzplan.',
    'save_to_disk':                'Auf Datenträger speichern',
    'save_description':
        'Speichert rohe IQ-Abtastwerte als complex64-Binärdatei.\n'
        'Zwei Kanäle: I (Realteil) und Q (Imaginärteil).\n'
        'Kompatibel mit GNU Radio, inspectrum,\n'
        'GQRX und SDR# für die Offline-Analyse.\n'
        ' \n'
        'Bei 2 MHz Abtastrate: ca. 16 MB/s.\n'
        'Eine 30-Sekunden-Aufnahme benötigt ca. 480 MB.\n'
        'Speicherplatz vor langen Aufnahmen einplanen.\n'
        ' \n'
        'Waterfall: Short-Time-FFT mit numpy,\n'
        'gerendert mit der Inferno-Farbkarte von matplotlib.\n'
        'Öffnet automatisch im Systembetrachter.',
    'record_iq':                   'IQ aufnehmen',
    'recording':                   'Aufnahme läuft...',
    'waterfall_checkbox':          'Waterfall-Grafik erzeugen',
    'event_log':                   'Ereignisprotokoll',
    'event_log_title':             '  OpenV2K  Ereignisprotokoll',
    'no_mbrola_voice':
        'Keine MBROLA-Stimme für diese Sprache verfügbar -- '
        'verwende stattdessen eSpeak-Formantsynthese.',
},

'fr': {
    'section_audio_input':        'Entrée audio',
    'section_signal_processing':  'Traitement du signal',
    'section_output':             'Sortie',
    'live_microphone':            'Microphone en direct',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Générateur d\'impulsions à passage par zéro',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Niveau micro : -45 dB au silence, viser -18 dB en parlant.\n'
        'Réglage : Paramètres système > Son > Entrée.',
    'mic_muted':                  'Micro : COUPÉ',
    'mic_live':                   'Micro : ACTIF',
    'generate_voice':             'Générer la voix',
    'placeholder_hello':          'Bonjour le monde',
    'placeholder_enter_text':     'Entrez du texte ici',
    'optional_filters':           'Filtres optionnels',
    'col_signal_conditioning':    'Conditionnement du signal',
    'col_noise_silence':          'Bruit / Silence',
    'col_zcr_shaping':            'Mise en forme ZCR',
    'filt_notch':                 'Filtre coupe-bande 50/60 Hz',
    'filt_preemph':               'Pré-accentuation',
    'filt_decimate':               'Sous-échantillonnage / Décimation',
    'filt_noisegate':             'Portillon de bruit',
    'filt_envfollow':             "Suiveur d'enveloppe",
    'filt_specsub':               'Soustraction spectrale',
    'filt_hwrect':                'Redressement demi-onde',
    'filt_schmitt':                'Déclencheur de Schmitt',
    'filt_hilbert':                'Enveloppe de Hilbert',
    'slider_pulse':                'Impulsion (\u00b5s)',
    'slider_hpf':                  'FPH (Hz)',
    'slider_lpf':                  'FPB (Hz)',
    'duty_summary':                'Moy : 2-4%\nMax : 10%\n>6% hors spec.',
    'duty_cycle_label':            "Rapport cyclique d'impulsion",
    'transmitter_freq':            'Fréquence :',
    'transmitter_pwr':             'Puissance TX :',
    'tx_disabled':                 'TX : DÉSACTIVÉ',
    'tx_enabled':                  'TX : ACTIVÉ',
    'tx_license':
        "Une licence de radioamateur valide est requise pour émettre "
        "sur ces fréquences. "
        "Vérifiez votre plan de bandes national.",
    'save_to_disk':                'Enregistrer sur disque',
    'save_description':
        'Enregistre les échantillons IQ bruts en binaire complex64.\n'
        'Deux canaux : I (réel) et Q (imaginaire).\n'
        'Compatible avec GNU Radio, inspectrum,\n'
        'GQRX et SDR# pour analyse hors ligne.\n'
        ' \n'
        "À 2 MHz d'échantillonnage : environ 16 Mo/s.\n"
        'Un enregistrement de 30 secondes utilise environ 480 Mo.\n'
        "Prévoyez l'espace de stockage avant les longs enregistrements.\n"
        ' \n'
        'Waterfall : FFT à court terme via numpy,\n'
        'rendu avec la palette inferno de matplotlib.\n'
        'Ouverture automatique dans la visionneuse système.',
    'record_iq':                   'Enregistrer IQ',
    'recording':                   'Enregistrement...',
    'waterfall_checkbox':          "Générer l'image waterfall",
    'event_log':                   "Journal d'événements",
    'event_log_title':             "  OpenV2K  Journal d'événements",
    'no_mbrola_voice':
        "Aucune voix MBROLA disponible pour cette langue -- "
        "utilisation de la synthèse formantique eSpeak à la place.",
},

'es': {
    'section_audio_input':        'Entrada de audio',
    'section_signal_processing':  'Procesamiento de señal',
    'section_output':             'Salida',
    'live_microphone':            'Micrófono en vivo',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generador de pulsos por cruce por cero',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Nivel de micrófono: -45 dB en silencio, buscar -18 dB al hablar.\n'
        'Ajustar en: Configuración del sistema > Sonido > Entrada.',
    'mic_muted':                  'Mic: SILENCIADO',
    'mic_live':                   'Mic: EN VIVO',
    'generate_voice':             'Generar voz',
    'placeholder_hello':          'Hola Mundo',
    'placeholder_enter_text':     'Escriba texto aquí',
    'optional_filters':           'Filtros opcionales',
    'col_signal_conditioning':    'Acondicionamiento de señal',
    'col_noise_silence':          'Ruido / Silencio',
    'col_zcr_shaping':            'Conformado ZCR',
    'filt_notch':                 'Filtro rechazo 50/60 Hz',
    'filt_preemph':               'Preénfasis',
    'filt_decimate':               'Submuestreo / Diezmado',
    'filt_noisegate':             'Puerta de ruido',
    'filt_envfollow':             'Seguidor de envolvente',
    'filt_specsub':               'Sustracción espectral',
    'filt_hwrect':                'Rectificación media onda',
    'filt_schmitt':                'Disparador Schmitt',
    'filt_hilbert':                'Envolvente de Hilbert',
    'slider_pulse':                'Pulso (\u00b5s)',
    'slider_hpf':                  'FPA (Hz)',
    'slider_lpf':                  'FPB (Hz)',
    'duty_summary':                'Prom: 2-4%\nMáx: 10%\n>6% fuera de rango',
    'duty_cycle_label':            'Ciclo de trabajo del pulso',
    'transmitter_freq':            'Frecuencia:',
    'transmitter_pwr':             'Potencia TX:',
    'tx_disabled':                 'TX: DESACTIVADO',
    'tx_enabled':                  'TX: ACTIVADO',
    'tx_license':
        'Se requiere una licencia válida de radioaficionado para '
        'transmitir en estas frecuencias. '
        'Verifique su plan de bandas nacional.',
    'save_to_disk':                'Guardar en disco',
    'save_description':
        'Guarda muestras IQ sin procesar en binario complex64.\n'
        'Dos canales: I (real) y Q (imaginario).\n'
        'Compatible con GNU Radio, inspectrum,\n'
        'GQRX y SDR# para análisis sin conexión.\n'
        ' \n'
        'A 2 MHz de muestreo: aprox. 16 MB/seg.\n'
        'Una captura de 30 segundos usa unos 480 MB.\n'
        'Planifique el almacenamiento antes de grabaciones largas.\n'
        ' \n'
        'Waterfall: FFT de corto plazo vía numpy,\n'
        'renderizado con el mapa inferno de matplotlib.\n'
        'Se abre automáticamente en el visor del sistema.',
    'record_iq':                   'Grabar IQ',
    'recording':                   'Grabando...',
    'waterfall_checkbox':          'Generar imagen waterfall',
    'event_log':                   'Registro de eventos',
    'event_log_title':             '  OpenV2K  Registro de eventos',
    'no_mbrola_voice':
        'No hay voz MBROLA disponible para este idioma -- '
        'se usará la síntesis de formantes de eSpeak en su lugar.',
},

'it': {
    'section_audio_input':        'Ingresso audio',
    'section_signal_processing':  'Elaborazione del segnale',
    'section_output':             'Uscita',
    'live_microphone':            'Microfono dal vivo',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generatore di impulsi a incrocio zero',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Livello microfono: -45 dB in silenzio, puntare a -18 dB parlando.\n'
        'Regolare in: Impostazioni di sistema > Audio > Ingresso.',
    'mic_muted':                  'Mic: MUTO',
    'mic_live':                   'Mic: ATTIVO',
    'generate_voice':             'Genera voce',
    'placeholder_hello':          'Ciao Mondo',
    'placeholder_enter_text':     'Inserisci il testo qui',
    'optional_filters':           'Filtri opzionali',
    'col_signal_conditioning':    'Condizionamento del segnale',
    'col_noise_silence':          'Rumore / Silenzio',
    'col_zcr_shaping':            'Modellazione ZCR',
    'filt_notch':                 'Notch 50/60 Hz',
    'filt_preemph':               'Pre-enfasi',
    'filt_decimate':               'Sottocampionamento / Decimazione',
    'filt_noisegate':             'Gate del rumore',
    'filt_envfollow':             'Inseguitore di inviluppo',
    'filt_specsub':               'Sottrazione spettrale',
    'filt_hwrect':                "Raddrizzamento a semionda",
    'filt_schmitt':                'Trigger di Schmitt',
    'filt_hilbert':                'Inviluppo di Hilbert',
    'slider_pulse':                'Impulso (\u00b5s)',
    'slider_hpf':                  'FPA (Hz)',
    'slider_lpf':                  'FPB (Hz)',
    'duty_summary':                'Media: 2-4%\nMax: 10%\n>6% fuori specifica',
    'duty_cycle_label':            "Duty cycle dell'impulso",
    'transmitter_freq':            'Frequenza:',
    'transmitter_pwr':             'Potenza TX:',
    'tx_disabled':                 'TX: DISATTIVO',
    'tx_enabled':                  'TX: ATTIVO',
    'tx_license':
        'È richiesta una licenza radioamatoriale valida per trasmettere '
        'su queste frequenze. '
        'Verificare il proprio piano di banda nazionale.',
    'save_to_disk':                'Salva su disco',
    'save_description':
        'Salva campioni IQ grezzi come binario complex64.\n'
        'Due canali: I (reale) e Q (immaginario).\n'
        'Compatibile con GNU Radio, inspectrum,\n'
        'GQRX e SDR# per analisi offline.\n'
        ' \n'
        'A 2 MHz di campionamento: circa 16 MB/sec.\n'
        'Una cattura di 30 secondi usa circa 480 MB.\n'
        'Pianificare lo spazio di archiviazione prima di registrazioni lunghe.\n'
        ' \n'
        'Waterfall: FFT a breve termine tramite numpy,\n'
        'renderizzato con la mappa inferno di matplotlib.\n'
        'Si apre automaticamente nel visualizzatore di sistema.',
    'record_iq':                   'Registra IQ',
    'recording':                   'Registrazione...',
    'waterfall_checkbox':          'Genera immagine waterfall',
    'event_log':                   'Registro eventi',
    'event_log_title':             '  OpenV2K  Registro eventi',
    'no_mbrola_voice':
        'Nessuna voce MBROLA disponibile per questa lingua -- '
        'verrà usata la sintesi formantica di eSpeak.',
},

'sv': {
    'section_audio_input':        'Ljudingång',
    'section_signal_processing':  'Signalbehandling',
    'section_output':             'Utgång',
    'live_microphone':            'Live-mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nollgenomgångs-pulsgenerator för ljudvågform',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofonnivå: -45 dB i tystnad, sikta på -18 dB vid tal.\n'
        'Justera i: Systeminställningar > Ljud > Ingång.',
    'mic_muted':                  'Mik: TYST',
    'mic_live':                   'Mik: LIVE',
    'generate_voice':             'Generera röst',
    'placeholder_hello':          'Hej Världen',
    'placeholder_enter_text':     'Skriv text här',
    'optional_filters':           'Valfria filter',
    'col_signal_conditioning':    'Signalkonditionering',
    'col_noise_silence':          'Brus / Tystnad',
    'col_zcr_shaping':            'ZCR-formning',
    'filt_notch':                 '50/60 Hz spärrfilter',
    'filt_preemph':               'Pre-emfas',
    'filt_decimate':               'Nedsampling / Decimering',
    'filt_noisegate':             'Brusgrind',
    'filt_envfollow':             'Envelopföljare',
    'filt_specsub':               'Spektral subtraktion',
    'filt_hwrect':                'Halvvågslikriktning',
    'filt_schmitt':                'Schmitt-trigger',
    'filt_hilbert':                'Hilbert-envelopp',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Medel: 2-4%\nMax: 10%\n>6% över spec',
    'duty_cycle_label':            'Pulsens driftcykel',
    'transmitter_freq':            'Frekvens:',
    'transmitter_pwr':             'TX-effekt:',
    'tx_disabled':                 'TX: AV',
    'tx_enabled':                  'TX: PÅ',
    'tx_license':
        'Ett giltigt amatörradiotillstånd krävs för att sända på dessa '
        'frekvenser. '
        'Kontrollera din nationella bandplan.',
    'save_to_disk':                'Spara till disk',
    'save_description':
        'Sparar råa IQ-samplingar som complex64-binärdata.\n'
        'Två kanaler: I (real) och Q (imaginär).\n'
        'Kompatibel med GNU Radio, inspectrum,\n'
        'GQRX och SDR# för offlineanalys.\n'
        ' \n'
        'Vid 2 MHz samplingsfrekvens: ca 16 MB/sek.\n'
        'En 30-sekundersinspelning använder ca 480 MB.\n'
        'Planera lagringsutrymmet före långa inspelningar.\n'
        ' \n'
        'Waterfall: korttids-FFT via numpy,\n'
        'renderad med matplotlibs inferno-färgkarta.\n'
        'Öppnas automatiskt i systemvisaren.',
    'record_iq':                   'Spela in IQ',
    'recording':                   'Spelar in...',
    'waterfall_checkbox':          'Generera waterfall-bild',
    'event_log':                   'Händelselogg',
    'event_log_title':             '  OpenV2K  Händelselogg',
    'no_mbrola_voice':
        'Ingen MBROLA-röst tillgänglig för detta språk -- '
        'använder eSpeaks formantsyntes istället.',
},

'no': {
    'section_audio_input':        'Lydinngang',
    'section_signal_processing':  'Signalbehandling',
    'section_output':             'Utgang',
    'live_microphone':            'Live-mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nullgjennomgangs-pulsgenerator for lydbølgeform',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofonnivå: -45 dB i stillhet, sikt mot -18 dB når du snakker.\n'
        'Juster i: Systeminnstillinger > Lyd > Inngang.',
    'mic_muted':                  'Mik: DEMPET',
    'mic_live':                   'Mik: LIVE',
    'generate_voice':             'Generer stemme',
    'placeholder_hello':          'Hei Verden',
    'placeholder_enter_text':     'Skriv tekst her',
    'optional_filters':           'Valgfrie filtre',
    'col_signal_conditioning':    'Signalkondisjonering',
    'col_noise_silence':          'Støy / Stillhet',
    'col_zcr_shaping':            'ZCR-forming',
    'filt_notch':                 '50/60 Hz sperrefilter',
    'filt_preemph':               'Pre-emfase',
    'filt_decimate':               'Nedsampling / Desimering',
    'filt_noisegate':             'Støysperre',
    'filt_envfollow':             'Envelopfølger',
    'filt_specsub':               'Spektral subtraksjon',
    'filt_hwrect':                'Halvbølgelikeretting',
    'filt_schmitt':                'Schmitt-trigger',
    'filt_hilbert':                'Hilbert-envelope',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Snitt: 2-4%\nMaks: 10%\n>6% over spec',
    'duty_cycle_label':            'Pulsens driftssyklus',
    'transmitter_freq':            'Frekvens:',
    'transmitter_pwr':             'TX-effekt:',
    'tx_disabled':                 'TX: AV',
    'tx_enabled':                  'TX: PÅ',
    'tx_license':
        'Gyldig amatørradiolisens kreves for å sende på disse '
        'frekvensene. '
        'Sjekk din nasjonale båndplan.',
    'save_to_disk':                'Lagre til disk',
    'save_description':
        'Lagrer rå IQ-samples som complex64-binærdata.\n'
        'To kanaler: I (reell) og Q (imaginær).\n'
        'Kompatibel med GNU Radio, inspectrum,\n'
        'GQRX og SDR# for offline-analyse.\n'
        ' \n'
        'Ved 2 MHz samplingsrate: ca 16 MB/sek.\n'
        'En 30-sekunders opptak bruker ca 480 MB.\n'
        'Planlegg lagringsplass før lange opptak.\n'
        ' \n'
        'Waterfall: korttids-FFT via numpy,\n'
        'rendret med matplotlibs inferno-fargekart.\n'
        'Åpnes automatisk i systemviseren.',
    'record_iq':                   'Ta opp IQ',
    'recording':                   'Tar opp...',
    'waterfall_checkbox':          'Generer waterfall-bilde',
    'event_log':                   'Hendelseslogg',
    'event_log_title':             '  OpenV2K  Hendelseslogg',
    'no_mbrola_voice':
        'Ingen MBROLA-stemme tilgjengelig for dette språket -- '
        'bruker eSpeaks formantsyntese i stedet.',
},

'ru': {
    'section_audio_input':        'Аудиовход',
    'section_signal_processing':  'Обработка сигнала',
    'section_output':             'Выход',
    'live_microphone':            'Живой микрофон',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Генератор импульсов пересечения нуля',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Уровень микрофона: -45 дБ в тишине, стремитесь к -18 дБ при речи.\n'
        'Настройка: Системные настройки > Звук > Вход.',
    'mic_muted':                  'Мик: ВЫКЛ',
    'mic_live':                   'Мик: ЖИВОЙ',
    'generate_voice':             'Создать голос',
    'placeholder_hello':          'Привет, мир',
    'placeholder_enter_text':     'Введите текст здесь',
    'optional_filters':           'Дополнительные фильтры',
    'col_signal_conditioning':    'Кондиционирование сигнала',
    'col_noise_silence':          'Шум / Тишина',
    'col_zcr_shaping':            'Формирование ZCR',
    'filt_notch':                 'Режекторный фильтр 50/60 Гц',
    'filt_preemph':               'Предыскажение',
    'filt_decimate':               'Даунсемплинг / Децимация',
    'filt_noisegate':             'Шумовой затвор',
    'filt_envfollow':             'Следящий за огибающей',
    'filt_specsub':               'Спектральное вычитание',
    'filt_hwrect':                'Однополупериодное выпрямление',
    'filt_schmitt':                'Триггер Шмитта',
    'filt_hilbert':                'Огибающая Гильберта',
    'slider_pulse':                'Импульс (мкс)',
    'slider_hpf':                  'ФВЧ (Гц)',
    'slider_lpf':                  'ФНЧ (Гц)',
    'duty_summary':                'Сред: 2-4%\nМакс: 10%\n>6% вне нормы',
    'duty_cycle_label':            'Скважность импульса',
    'transmitter_freq':            'Частота:',
    'transmitter_pwr':             'Мощность TX:',
    'tx_disabled':                 'TX: ВЫКЛ',
    'tx_enabled':                  'TX: ВКЛ',
    'tx_license':
        'Для передачи на этих частотах требуется действующая '
        'лицензия радиолюбителя. '
        'Проверьте свой национальный частотный план.',
    'save_to_disk':                'Сохранить на диск',
    'save_description':
        'Сохраняет необработанные IQ-выборки в бинарном формате complex64.\n'
        'Два канала: I (действительная часть) и Q (мнимая часть).\n'
        'Совместимо с GNU Radio, inspectrum,\n'
        'GQRX и SDR# для автономного анализа.\n'
        ' \n'
        'При частоте дискретизации 2 МГц: около 16 МБ/сек.\n'
        '30-секундная запись занимает около 480 МБ.\n'
        'Планируйте место на диске перед длинными записями.\n'
        ' \n'
        'Waterfall: кратковременное БПФ через numpy,\n'
        'отрисовано цветовой картой inferno из matplotlib.\n'
        'Открывается автоматически в системном просмотрщике.',
    'record_iq':                   'Записать IQ',
    'recording':                   'Запись...',
    'waterfall_checkbox':          'Создать изображение waterfall',
    'event_log':                   'Журнал событий',
    'event_log_title':             '  OpenV2K  Журнал событий',
    'no_mbrola_voice':
        'Голос MBROLA для этого языка недоступен -- '
        'вместо него используется формантный синтез eSpeak.',
},

'hi': {
    'section_audio_input':        'ऑडियो इनपुट',
    'section_signal_processing':  'सिग्नल प्रोसेसिंग',
    'section_output':             'आउटपुट',
    'live_microphone':            'लाइव माइक्रोफ़ोन',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'शून्य-क्रॉसिंग पल्स जनरेटर',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'माइक स्तर: शांति में -45 dB, बोलते समय -18 dB का लक्ष्य रखें।\n'
        'सिस्टम सेटिंग्स > ध्वनि > इनपुट में समायोजित करें।',
    'mic_muted':                  'माइक: म्यूट',
    'mic_live':                   'माइक: लाइव',
    'generate_voice':             'आवाज़ बनाएं',
    'placeholder_hello':          'नमस्ते दुनिया',
    'placeholder_enter_text':     'यहाँ टेक्स्ट लिखें',
    'optional_filters':           'वैकल्पिक फ़िल्टर',
    'col_signal_conditioning':    'सिग्नल कंडीशनिंग',
    'col_noise_silence':          'शोर / मौन',
    'col_zcr_shaping':            'ZCR आकार देना',
    'filt_notch':                 '50/60 Hz नॉच फ़िल्टर',
    'filt_preemph':               'प्री-एम्फैसिस',
    'filt_decimate':               'डाउनसैंपलिंग / डेसिमेशन',
    'filt_noisegate':             'नॉइज़ गेट',
    'filt_envfollow':             'एनवेलप फॉलोअर',
    'filt_specsub':               'स्पेक्ट्रल सबट्रैक्शन',
    'filt_hwrect':                'हाफ-वेव रेक्टिफिकेशन',
    'filt_schmitt':                'श्मिट ट्रिगर',
    'filt_hilbert':                'हिल्बर्ट एनवेलप',
    'slider_pulse':                'पल्स (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'औसत: 2-4%\nअधिकतम: 10%\n>6% सीमा से बाहर',
    'duty_cycle_label':            'पल्स ड्यूटी साइकिल',
    'transmitter_freq':            'आवृत्ति:',
    'transmitter_pwr':             'TX पावर:',
    'tx_disabled':                 'TX: बंद',
    'tx_enabled':                  'TX: चालू',
    'tx_license':
        'इन आवृत्तियों पर प्रसारण के लिए एक वैध शौकिया रेडियो लाइसेंस '
        'आवश्यक है। '
        'अपनी राष्ट्रीय बैंड योजना की जाँच करें।',
    'save_to_disk':                'डिस्क में सहेजें',
    'save_description':
        'कच्चे IQ नमूनों को complex64 बाइनरी के रूप में सहेजता है।\n'
        'दो चैनल: I (वास्तविक) और Q (काल्पनिक)।\n'
        'GNU Radio, inspectrum,\n'
        'GQRX और SDR# के साथ संगत, ऑफ़लाइन विश्लेषण हेतु।\n'
        ' \n'
        '2 MHz सैंपल दर पर: लगभग 16 MB/सेकंड।\n'
        '30 सेकंड की रिकॉर्डिंग लगभग 480 MB लेती है।\n'
        'लंबी रिकॉर्डिंग से पहले संग्रहण स्थान की योजना बनाएं।\n'
        ' \n'
        'Waterfall: numpy के माध्यम से शॉर्ट-टाइम FFT,\n'
        'matplotlib के inferno मानचित्र के साथ रेंडर किया गया।\n'
        'सिस्टम व्यूअर में स्वचालित रूप से खुलता है।',
    'record_iq':                   'IQ रिकॉर्ड करें',
    'recording':                   'रिकॉर्डिंग हो रही है...',
    'waterfall_checkbox':          'Waterfall छवि बनाएं',
    'event_log':                   'इवेंट लॉग',
    'event_log_title':             '  OpenV2K  इवेंट लॉग',
    'no_mbrola_voice':
        'इस भाषा के लिए कोई MBROLA आवाज़ उपलब्ध नहीं है -- '
        'इसके बजाय eSpeak फॉर्मेंट सिंथेसिस का उपयोग किया जा रहा है।',
},

'ja': {
    'section_audio_input':        'オーディオ入力',
    'section_signal_processing':  '信号処理',
    'section_output':             '出力',
    'live_microphone':            'ライブマイク',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'ゼロクロス パルス ジェネレーター',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'マイクレベル: 無音時-45dB、発話時は-18dBを目安に。\n'
        '設定: システム設定 > サウンド > 入力。',
    'mic_muted':                  'マイク: ミュート',
    'mic_live':                   'マイク: ライブ',
    'generate_voice':             '音声を生成',
    'placeholder_hello':          'こんにちは世界',
    'placeholder_enter_text':     'ここにテキストを入力',
    'optional_filters':           'オプションフィルター',
    'col_signal_conditioning':    '信号コンディショニング',
    'col_noise_silence':          'ノイズ / 無音',
    'col_zcr_shaping':            'ZCR整形',
    'filt_notch':                 '50/60Hz ノッチフィルター',
    'filt_preemph':               'プリエンファシス',
    'filt_decimate':               'ダウンサンプリング / 間引き',
    'filt_noisegate':             'ノイズゲート',
    'filt_envfollow':             'エンベロープフォロワー',
    'filt_specsub':               'スペクトル減算',
    'filt_hwrect':                '半波整流',
    'filt_schmitt':                'シュミットトリガー',
    'filt_hilbert':                'ヒルベルトエンベロープ',
    'slider_pulse':                'パルス (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                '平均: 2-4%\n最大: 10%\n>6%は規定超過',
    'duty_cycle_label':            'パルスデューティ比',
    'transmitter_freq':            '周波数:',
    'transmitter_pwr':             'TX出力:',
    'tx_disabled':                 'TX: 無効',
    'tx_enabled':                  'TX: 有効',
    'tx_license':
        'これらの周波数で送信するには有効なアマチュア無線免許が'
        '必要です。'
        '自国のバンドプランを確認してください。',
    'save_to_disk':                'ディスクに保存',
    'save_description':
        '生のIQサンプルをcomplex64バイナリとして保存します。\n'
        '2チャンネル: I（実部）とQ（虚部）。\n'
        'GNU Radio、inspectrum、\n'
        'GQRX、SDR#と互換性があり、オフライン解析が可能です。\n'
        ' \n'
        '2MHzサンプリング時: 約16MB/秒。\n'
        '30秒の録音で約480MB使用します。\n'
        '長時間録音の前に保存容量を確認してください。\n'
        ' \n'
        'Waterfall: numpyによる短時間FFT、\n'
        'matplotlibのinfernoカラーマップで描画。\n'
        'システムビューアで自動的に開きます。',
    'record_iq':                   'IQを録音',
    'recording':                   '録音中...',
    'waterfall_checkbox':          'Waterfall画像を生成',
    'event_log':                   'イベントログ',
    'event_log_title':             '  OpenV2K  イベントログ',
    'no_mbrola_voice':
        'この言語で利用可能なMBROLA音声がありません -- '
        '代わりにeSpeakのフォルマント合成を使用します。',
},

'zh': {
    'section_audio_input':        '音频输入',
    'section_signal_processing':  '信号处理',
    'section_output':             '输出',
    'live_microphone':            '实时麦克风',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                '过零脉冲发生器',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        '麦克风电平：静音时-45 dB，说话时目标为-18 dB。\n'
        '在系统设置 > 声音 > 输入中调整。',
    'mic_muted':                  '麦克风：静音',
    'mic_live':                   '麦克风：实时',
    'generate_voice':             '生成语音',
    'placeholder_hello':          '你好，世界',
    'placeholder_enter_text':     '在此输入文本',
    'optional_filters':           '可选滤波器',
    'col_signal_conditioning':    '信号调理',
    'col_noise_silence':          '噪声 / 静音',
    'col_zcr_shaping':            'ZCR整形',
    'filt_notch':                 '50/60 Hz 陷波滤波器',
    'filt_preemph':               '预加重',
    'filt_decimate':               '降采样 / 抽取',
    'filt_noisegate':             '噪声门',
    'filt_envfollow':             '包络跟随器',
    'filt_specsub':               '频谱减法',
    'filt_hwrect':                '半波整流',
    'filt_schmitt':                '施密特触发器',
    'filt_hilbert':                '希尔伯特包络',
    'slider_pulse':                '脉冲 (µs)',
    'slider_hpf':                  '高通滤波器 (Hz)',
    'slider_lpf':                  '低通滤波器 (Hz)',
    'duty_summary':                '平均: 2-4%\n最大: 10%\n>6% 超出规范',
    'duty_cycle_label':            '脉冲占空比',
    'transmitter_freq':            '频率：',
    'transmitter_pwr':             'TX 功率：',
    'tx_disabled':                 'TX：已禁用',
    'tx_enabled':                  'TX：已启用',
    'tx_license':
        '在这些频率上发射需要有效的业余无线电执照。'
        '请核实您所在国家的频段规划。',
    'save_to_disk':                '保存到磁盘',
    'save_description':
        '将原始IQ采样保存为complex64二进制格式。\n'
        '两个通道：I（实部）和Q（虚部）。\n'
        '兼容GNU Radio、inspectrum、\n'
        'GQRX和SDR#，可用于离线分析。\n'
        ' \n'
        '在2 MHz采样率下：约16 MB/秒。\n'
        '30秒的录制约占用480 MB。\n'
        '长时间录制前请规划好存储空间。\n'
        ' \n'
        'Waterfall：通过numpy进行短时FFT，\n'
        '使用matplotlib的inferno色图渲染。\n'
        '自动在系统查看器中打开。',
    'record_iq':                   '录制IQ',
    'recording':                   '录制中...',
    'waterfall_checkbox':          '生成瀑布图',
    'event_log':                   '事件日志',
    'event_log_title':             '  OpenV2K  事件日志',
    'no_mbrola_voice':
        '该语言没有可用的MBROLA语音 -- '
        '将改用eSpeak共振峰合成。',
},

'ar': {
    'section_audio_input':        'إدخال الصوت',
    'section_signal_processing':  'معالجة الإشارة',
    'section_output':             'الإخراج',
    'live_microphone':            'ميكروفون مباشر',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'مولد نبضات عبور الصفر',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'مستوى الميكروفون: -45 ديسيبل في الصمت، استهدف -18 ديسيبل عند التحدث.\n'
        'اضبط من: إعدادات النظام > الصوت > الإدخال.',
    'mic_muted':                  'الميكروفون: مكتوم',
    'mic_live':                   'الميكروفون: مباشر',
    'generate_voice':             'إنشاء صوت',
    'placeholder_hello':          'مرحبا بالعالم',
    'placeholder_enter_text':     'أدخل النص هنا',
    'optional_filters':           'مرشحات اختيارية',
    'col_signal_conditioning':    'تهيئة الإشارة',
    'col_noise_silence':          'ضوضاء / صمت',
    'col_zcr_shaping':            'تشكيل ZCR',
    'filt_notch':                 'مرشح إزالة 50/60 هرتز',
    'filt_preemph':               'التركيز المسبق',
    'filt_decimate':               'تقليل المعدل / التخفيض',
    'filt_noisegate':             'بوابة الضوضاء',
    'filt_envfollow':             'متتبع الغلاف',
    'filt_specsub':               'الطرح الطيفي',
    'filt_hwrect':                'التقويم نصف الموجة',
    'filt_schmitt':                'مشغل شميت',
    'filt_hilbert':                'غلاف هيلبرت',
    'slider_pulse':                'النبضة (µs)',
    'slider_hpf':                  'مرشح تمرير عالٍ (Hz)',
    'slider_lpf':                  'مرشح تمرير منخفض (Hz)',
    'duty_summary':                'المتوسط: 2-4%\nالحد الأقصى: 10%\n>6% خارج المواصفة',
    'duty_cycle_label':            'دورة عمل النبضة',
    'transmitter_freq':            'التردد:',
    'transmitter_pwr':             'طاقة الإرسال:',
    'tx_disabled':                 'الإرسال: معطل',
    'tx_enabled':                  'الإرسال: مفعّل',
    'tx_license':
        'يلزم ترخيص راديو هواة ساري المفعول للإرسال على هذه '
        'الترددات. '
        'تحقق من خطة النطاق الترددي الوطنية لديك.',
    'save_to_disk':                'الحفظ على القرص',
    'save_description':
        'يحفظ عينات IQ الخام كملف ثنائي complex64.\n'
        'قناتان: I (الجزء الحقيقي) و Q (الجزء التخيلي).\n'
        'متوافق مع GNU Radio و inspectrum\n'
        'و GQRX و SDR# للتحليل دون اتصال.\n'
        ' \n'
        'عند معدل عينات 2 ميجاهرتز: حوالي 16 ميجابايت/ثانية.\n'
        'يستخدم تسجيل مدته 30 ثانية حوالي 480 ميجابايت.\n'
        'خطط لمساحة التخزين قبل التسجيلات الطويلة.\n'
        ' \n'
        'Waterfall: تحويل فورييه قصير المدى عبر numpy،\n'
        'يُعرض باستخدام خريطة inferno من matplotlib.\n'
        'يفتح تلقائيًا في عارض النظام.',
    'record_iq':                   'تسجيل IQ',
    'recording':                   'جارٍ التسجيل...',
    'waterfall_checkbox':          'إنشاء صورة Waterfall',
    'event_log':                   'سجل الأحداث',
    'event_log_title':             '  OpenV2K  سجل الأحداث',
    'no_mbrola_voice':
        'لا يوجد صوت MBROLA متاح لهذه اللغة -- '
        'سيتم استخدام تخليق الصيغ الرنانة من eSpeak بدلاً من ذلك.',
},

'bn': {
    'section_audio_input':        'অডিও ইনপুট',
    'section_signal_processing':  'সিগন্যাল প্রসেসিং',
    'section_output':             'আউটপুট',
    'live_microphone':            'লাইভ মাইক্রোফোন',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'শূন্য-ক্রসিং পালস জেনারেটর',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'মাইক লেভেল: নীরবতায় -৪৫ dB, কথা বলার সময় -১৮ dB লক্ষ্য রাখুন।\n'
        'সমন্বয় করুন: সিস্টেম সেটিংস > সাউন্ড > ইনপুট।',
    'mic_muted':                  'মাইক: মিউট',
    'mic_live':                   'মাইক: লাইভ',
    'generate_voice':             'ভয়েস তৈরি করুন',
    'placeholder_hello':          'ওহে বিশ্ব',
    'placeholder_enter_text':     'এখানে টেক্সট লিখুন',
    'optional_filters':           'ঐচ্ছিক ফিল্টার',
    'col_signal_conditioning':    'সিগন্যাল কন্ডিশনিং',
    'col_noise_silence':          'শব্দ / নীরবতা',
    'col_zcr_shaping':            'ZCR শেপিং',
    'filt_notch':                 '৫০/৬০ Hz নচ ফিল্টার',
    'filt_preemph':               'প্রি-এমফ্যাসিস',
    'filt_decimate':              'ডাউনস্যাম্পলিং / ডেসিমেশন',
    'filt_noisegate':             'নয়েজ গেট',
    'filt_envfollow':             'এনভেলপ ফলোয়ার',
    'filt_specsub':               'স্পেকট্রাল সাবট্রাকশন',
    'filt_hwrect':                'হাফ-ওয়েভ রেকটিফিকেশন',
    'filt_schmitt':               'শ্মিট ট্রিগার',
    'filt_hilbert':               'হিলবার্ট এনভেলপ',
    'slider_pulse':               'পালস (µs)',
    'slider_hpf':                 'HPF (Hz)',
    'slider_lpf':                 'LPF (Hz)',
    'duty_summary':               'গড়: ২-৪%\nসর্বোচ্চ: ১০%\n>৬% সীমার বাইরে',
    'duty_cycle_label':           'পালস ডিউটি সাইকেল',
    'transmitter_freq':           'ফ্রিকোয়েন্সি:',
    'transmitter_pwr':            'TX পাওয়ার:',
    'tx_disabled':                'TX: নিষ্ক্রিয়',
    'tx_enabled':                 'TX: সক্রিয়',
    'tx_license':
        'এই ফ্রিকোয়েন্সিতে সম্প্রচারের জন্য একটি বৈধ অ্যামেচার রেডিও '
        'লাইসেন্স প্রয়োজন। '
        'আপনার জাতীয় ব্যান্ড প্ল্যান যাচাই করুন।',
    'save_to_disk':               'ডিস্কে সংরক্ষণ করুন',
    'save_description':
        'কাঁচা IQ নমুনা complex64 বাইনারি হিসেবে সংরক্ষণ করে।\n'
        'দুটি চ্যানেল: I (বাস্তব) এবং Q (কাল্পনিক)।\n'
        'GNU Radio, inspectrum,\n'
        'GQRX এবং SDR#-এর সাথে সামঞ্জস্যপূর্ণ, অফলাইন বিশ্লেষণের জন্য।\n'
        ' \n'
        '২ MHz স্যাম্পল রেটে: প্রায় ১৬ MB/সেকেন্ড।\n'
        '৩০ সেকেন্ডের রেকর্ডিং প্রায় ৪৮০ MB ব্যবহার করে।\n'
        'দীর্ঘ রেকর্ডিংয়ের আগে সংরক্ষণাগার পরিকল্পনা করুন।\n'
        ' \n'
        'Waterfall: numpy-এর মাধ্যমে শর্ট-টাইম FFT,\n'
        'matplotlib-এর inferno ম্যাপ দিয়ে রেন্ডার করা।\n'
        'সিস্টেম ভিউয়ারে স্বয়ংক্রিয়ভাবে খোলে।',
    'record_iq':                  'IQ রেকর্ড করুন',
    'recording':                  'রেকর্ডিং চলছে...',
    'waterfall_checkbox':         'Waterfall ছবি তৈরি করুন',
    'event_log':                  'ইভেন্ট লগ',
    'event_log_title':            '  OpenV2K  ইভেন্ট লগ',
    'no_mbrola_voice':
        'এই ভাষার জন্য কোনো MBROLA ভয়েস উপলব্ধ নেই -- '
        'পরিবর্তে eSpeak ফরম্যান্ট সিন্থেসিস ব্যবহার করা হচ্ছে।',
},

'pt': {
    'section_audio_input':        'Entrada de Áudio',
    'section_signal_processing':  'Processamento de Sinal',
    'section_output':             'Saída',
    'live_microphone':            'Microfone ao Vivo',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Gerador de pulsos por cruzamento de zero',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Nível do microfone: -45 dB em silêncio, buscar -18 dB ao falar.\n'
        'Ajustar em: Definições do sistema > Som > Entrada.',
    'mic_muted':                  'Mic: SILENCIADO',
    'mic_live':                   'Mic: AO VIVO',
    'generate_voice':             'Gerar voz',
    'placeholder_hello':          'Olá Mundo',
    'placeholder_enter_text':     'Digite o texto aqui',
    'optional_filters':           'Filtros opcionais',
    'col_signal_conditioning':    'Condicionamento de sinal',
    'col_noise_silence':          'Ruído / Silêncio',
    'col_zcr_shaping':            'Formatação ZCR',
    'filt_notch':                 'Filtro rejeita-faixa 50/60 Hz',
    'filt_preemph':               'Pré-ênfase',
    'filt_decimate':              'Subamostragem / Dizimação',
    'filt_noisegate':             'Porta de ruído',
    'filt_envfollow':             'Seguidor de envoltória',
    'filt_specsub':               'Subtração espectral',
    'filt_hwrect':                'Retificação de meia onda',
    'filt_schmitt':                'Disparador de Schmitt',
    'filt_hilbert':                'Envoltória de Hilbert',
    'slider_pulse':                'Pulso (\u00b5s)',
    'slider_hpf':                  'FPA (Hz)',
    'slider_lpf':                  'FPB (Hz)',
    'duty_summary':                'Média: 2-4%\nMáx: 10%\n>6% fora da especificação',
    'duty_cycle_label':            'Ciclo de trabalho do pulso',
    'transmitter_freq':            'Frequência:',
    'transmitter_pwr':             'Potência TX:',
    'tx_disabled':                 'TX: DESATIVADO',
    'tx_enabled':                  'TX: ATIVADO',
    'tx_license':
        'É necessária uma licença válida de rádio amador para transmitir '
        'nestas frequências. '
        'Verifique o seu plano nacional de bandas.',
    'save_to_disk':                'Guardar no disco',
    'save_description':
        'Guarda amostras IQ em bruto como binário complex64.\n'
        'Dois canais: I (real) e Q (imaginário).\n'
        'Compatível com GNU Radio, inspectrum,\n'
        'GQRX e SDR# para análise offline.\n'
        ' \n'
        'A 2 MHz de amostragem: aprox. 16 MB/seg.\n'
        'Uma captura de 30 segundos usa cerca de 480 MB.\n'
        'Planeie o armazenamento antes de gravações longas.\n'
        ' \n'
        'Waterfall: FFT de curta duração via numpy,\n'
        'renderizado com o mapa inferno do matplotlib.\n'
        'Abre automaticamente no visualizador do sistema.',
    'record_iq':                   'Gravar IQ',
    'recording':                   'A gravar...',
    'waterfall_checkbox':          'Gerar imagem waterfall',
    'event_log':                   'Registo de eventos',
    'event_log_title':             '  OpenV2K  Registo de eventos',
    'no_mbrola_voice':
        'Nenhuma voz MBROLA disponível para este idioma -- '
        'a usar síntese formântica do eSpeak em alternativa.',
},

'ur': {
    'section_audio_input':        'آڈیو ان پٹ',
    'section_signal_processing':  'سگنل پروسیسنگ',
    'section_output':             'آؤٹ پٹ',
    'live_microphone':            'لائیو مائیکروفون',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'زیرو کراسنگ پلس جنریٹر',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'مائیک لیول: خاموشی میں -45 dB، بولتے وقت -18 dB کا ہدف رکھیں۔\n'
        'ایڈجسٹ کریں: سسٹم سیٹنگز > ساؤنڈ > ان پٹ۔',
    'mic_muted':                  'مائیک: خاموش',
    'mic_live':                   'مائیک: لائیو',
    'generate_voice':             'آواز بنائیں',
    'placeholder_hello':          'ہیلو ورلڈ',
    'placeholder_enter_text':     'یہاں متن لکھیں',
    'optional_filters':           'اختیاری فلٹرز',
    'col_signal_conditioning':    'سگنل کنڈیشننگ',
    'col_noise_silence':          'شور / خاموشی',
    'col_zcr_shaping':            'ZCR شیپنگ',
    'filt_notch':                 '50/60 ہرٹز ناچ فلٹر',
    'filt_preemph':               'پری ایمفیسس',
    'filt_decimate':              'ڈاؤن سیمپلنگ / ڈیسیمیشن',
    'filt_noisegate':             'نوائز گیٹ',
    'filt_envfollow':             'اینویلپ فالوور',
    'filt_specsub':               'اسپیکٹرل سبٹریکشن',
    'filt_hwrect':                'ہاف ویو ریکٹیفیکیشن',
    'filt_schmitt':                'شمٹ ٹرگر',
    'filt_hilbert':                'ہلبرٹ اینویلپ',
    'slider_pulse':                'پلس (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'اوسط: 2-4%\nزیادہ سے زیادہ: 10%\n>6% حد سے باہر',
    'duty_cycle_label':            'پلس ڈیوٹی سائیکل',
    'transmitter_freq':            'فریکوئنسی:',
    'transmitter_pwr':             'TX پاور:',
    'tx_disabled':                 'TX: غیر فعال',
    'tx_enabled':                  'TX: فعال',
    'tx_license':
        'ان فریکوئنسیوں پر ٹرانسمٹ کرنے کے لیے ایک درست ایمیچور ریڈیو '
        'لائسنس درکار ہے۔ '
        'اپنا قومی بینڈ پلان چیک کریں۔',
    'save_to_disk':                'ڈسک میں محفوظ کریں',
    'save_description':
        'خام IQ نمونے complex64 بائنری کے طور پر محفوظ کرتا ہے۔\n'
        'دو چینلز: I (حقیقی) اور Q (تصوراتی)۔\n'
        'GNU Radio، inspectrum،\n'
        'GQRX اور SDR# کے ساتھ ہم آہنگ، آف لائن تجزیے کے لیے۔\n'
        ' \n'
        '2 MHz سیمپل ریٹ پر: تقریباً 16 MB/سیکنڈ۔\n'
        '30 سیکنڈ کی ریکارڈنگ تقریباً 480 MB استعمال کرتی ہے۔\n'
        'طویل ریکارڈنگ سے پہلے اسٹوریج کی منصوبہ بندی کریں۔\n'
        ' \n'
        'Waterfall: numpy کے ذریعے شارٹ ٹائم FFT،\n'
        'matplotlib کے inferno نقشے سے پیش کیا گیا۔\n'
        'سسٹم ویور میں خودکار طور پر کھلتا ہے۔',
    'record_iq':                   'IQ ریکارڈ کریں',
    'recording':                   'ریکارڈنگ ہو رہی ہے...',
    'waterfall_checkbox':          'Waterfall تصویر بنائیں',
    'event_log':                   'ایونٹ لاگ',
    'event_log_title':             '  OpenV2K  ایونٹ لاگ',
    'no_mbrola_voice':
        'اس زبان کے لیے کوئی MBROLA آواز دستیاب نہیں ہے -- '
        'اس کے بجائے eSpeak فارمینٹ ترکیب استعمال کی جا رہی ہے۔',
},

'id': {
    'section_audio_input':        'Input Audio',
    'section_signal_processing':  'Pemrosesan Sinyal',
    'section_output':             'Output',
    'live_microphone':            'Mikrofon Langsung',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generator pulsa persilangan nol',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Level mikrofon: -45 dB saat diam, targetkan -18 dB saat berbicara.\n'
        'Sesuaikan di: Pengaturan Sistem > Suara > Input.',
    'mic_muted':                  'Mic: DIBISUKAN',
    'mic_live':                   'Mic: LANGSUNG',
    'generate_voice':             'Buat Suara',
    'placeholder_hello':          'Halo Dunia',
    'placeholder_enter_text':     'Ketik teks di sini',
    'optional_filters':           'Filter opsional',
    'col_signal_conditioning':    'Pengondisian sinyal',
    'col_noise_silence':          'Derau / Diam',
    'col_zcr_shaping':            'Pembentukan ZCR',
    'filt_notch':                 'Filter notch 50/60 Hz',
    'filt_preemph':               'Pra-penekanan',
    'filt_decimate':              'Downsampling / Desimasi',
    'filt_noisegate':             'Gerbang derau',
    'filt_envfollow':             'Pengikut amplop',
    'filt_specsub':               'Pengurangan spektral',
    'filt_hwrect':                'Penyearahan setengah gelombang',
    'filt_schmitt':                'Pemicu Schmitt',
    'filt_hilbert':                'Amplop Hilbert',
    'slider_pulse':                'Pulsa (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Rata-rata: 2-4%\nMaks: 10%\n>6% di luar spesifikasi',
    'duty_cycle_label':            'Siklus kerja pulsa',
    'transmitter_freq':            'Frekuensi:',
    'transmitter_pwr':             'Daya TX:',
    'tx_disabled':                 'TX: NONAKTIF',
    'tx_enabled':                  'TX: AKTIF',
    'tx_license':
        'Lisensi radio amatir yang sah diperlukan untuk memancarkan pada '
        'frekuensi ini. '
        'Periksa rencana pita nasional Anda.',
    'save_to_disk':                'Simpan ke disk',
    'save_description':
        'Menyimpan sampel IQ mentah sebagai biner complex64.\n'
        'Dua kanal: I (nyata) dan Q (imajiner).\n'
        'Kompatibel dengan GNU Radio, inspectrum,\n'
        'GQRX, dan SDR# untuk analisis offline.\n'
        ' \n'
        'Pada laju sampel 2 MHz: sekitar 16 MB/detik.\n'
        'Rekaman 30 detik menggunakan sekitar 480 MB.\n'
        'Rencanakan penyimpanan sebelum rekaman panjang.\n'
        ' \n'
        'Waterfall: FFT waktu-singkat via numpy,\n'
        'dirender dengan peta warna inferno matplotlib.\n'
        'Terbuka otomatis di penampil sistem.',
    'record_iq':                   'Rekam IQ',
    'recording':                   'Merekam...',
    'waterfall_checkbox':          'Buat gambar waterfall',
    'event_log':                   'Log Peristiwa',
    'event_log_title':             '  OpenV2K  Log Peristiwa',
    'no_mbrola_voice':
        'Tidak ada suara MBROLA yang tersedia untuk bahasa ini -- '
        'menggunakan sintesis formant eSpeak sebagai gantinya.',
},

'ms': {
    'section_audio_input':        'Input Audio',
    'section_signal_processing':  'Pemprosesan Isyarat',
    'section_output':             'Output',
    'live_microphone':            'Mikrofon Langsung',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Penjana denyut persilangan sifar',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Tahap mikrofon: -45 dB dalam senyap, sasarkan -18 dB semasa bercakap.\n'
        'Laraskan di: Tetapan Sistem > Bunyi > Input.',
    'mic_muted':                  'Mic: SENYAP',
    'mic_live':                   'Mic: LANGSUNG',
    'generate_voice':             'Jana Suara',
    'placeholder_hello':          'Helo Dunia',
    'placeholder_enter_text':     'Taip teks di sini',
    'optional_filters':           'Penapis pilihan',
    'col_signal_conditioning':    'Pelarasan isyarat',
    'col_noise_silence':          'Bunyi bising / Senyap',
    'col_zcr_shaping':            'Pembentukan ZCR',
    'filt_notch':                 'Penapis notch 50/60 Hz',
    'filt_preemph':               'Pra-penekanan',
    'filt_decimate':              'Persampelan bawah / Persepuluhan',
    'filt_noisegate':             'Get bunyi bising',
    'filt_envfollow':             'Pengikut sampul',
    'filt_specsub':               'Penolakan spektrum',
    'filt_hwrect':                'Penerusan separuh gelombang',
    'filt_schmitt':                'Pencetus Schmitt',
    'filt_hilbert':                'Sampul Hilbert',
    'slider_pulse':                'Denyut (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Purata: 2-4%\nMaks: 10%\n>6% di luar spesifikasi',
    'duty_cycle_label':            'Kitaran tugas denyut',
    'transmitter_freq':            'Frekuensi:',
    'transmitter_pwr':             'Kuasa TX:',
    'tx_disabled':                 'TX: DILUMPUHKAN',
    'tx_enabled':                  'TX: DIAKTIFKAN',
    'tx_license':
        'Lesen radio amatur yang sah diperlukan untuk menghantar pada '
        'frekuensi ini. '
        'Semak pelan jalur negara anda.',
    'save_to_disk':                'Simpan ke cakera',
    'save_description':
        'Menyimpan sampel IQ mentah sebagai binari complex64.\n'
        'Dua saluran: I (nyata) dan Q (khayalan).\n'
        'Serasi dengan GNU Radio, inspectrum,\n'
        'GQRX, dan SDR# untuk analisis luar talian.\n'
        ' \n'
        'Pada kadar sampel 2 MHz: lebih kurang 16 MB/saat.\n'
        'Rakaman 30 saat menggunakan lebih kurang 480 MB.\n'
        'Rancang storan sebelum rakaman panjang.\n'
        ' \n'
        'Waterfall: FFT masa-pendek melalui numpy,\n'
        'dipaparkan dengan peta warna inferno matplotlib.\n'
        'Dibuka secara automatik dalam pemapar sistem.',
    'record_iq':                   'Rakam IQ',
    'recording':                   'Merakam...',
    'waterfall_checkbox':          'Jana imej waterfall',
    'event_log':                   'Log Peristiwa',
    'event_log_title':             '  OpenV2K  Log Peristiwa',
    'no_mbrola_voice':
        'Tiada suara MBROLA tersedia untuk bahasa ini -- '
        'menggunakan sintesis formant eSpeak sebagai gantinya.',
},

'sw': {
    'section_audio_input':        'Ingizo la Sauti',
    'section_signal_processing':  'Uchakataji wa Mawimbi',
    'section_output':             'Matokeo',
    'live_microphone':            'Kipaza Sauti cha Moja kwa Moja',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Jenereta ya mipigo ya kuvuka sifuri',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Kiwango cha maikrofoni: -45 dB kimya, lenga -18 dB unapoongea.\n'
        'Rekebisha: Mipangilio ya Mfumo > Sauti > Ingizo.',
    'mic_muted':                  'Maik: KIMYA',
    'mic_live':                   'Maik: HAI',
    'generate_voice':             'Tengeneza Sauti',
    'placeholder_hello':          'Habari Dunia',
    'placeholder_enter_text':     'Andika maandishi hapa',
    'optional_filters':           'Vichujio vya hiari',
    'col_signal_conditioning':    'Uwekaji wa mawimbi',
    'col_noise_silence':          'Kelele / Ukimya',
    'col_zcr_shaping':            'Uundaji wa ZCR',
    'filt_notch':                 'Kichujio cha notch 50/60 Hz',
    'filt_preemph':               'Msisitizo wa awali',
    'filt_decimate':              'Upunguzaji sampuli / Ukatishaji',
    'filt_noisegate':             'Lango la kelele',
    'filt_envfollow':             'Kifuatiliaji cha bahasha',
    'filt_specsub':               'Utoaji wa spektra',
    'filt_hwrect':                'Unyoosho wa nusu-wimbi',
    'filt_schmitt':                'Kizindua Schmitt',
    'filt_hilbert':                'Bahasha ya Hilbert',
    'slider_pulse':                'Mpigo (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Wastani: 2-4%\nUpeo: 10%\n>6% nje ya kiwango',
    'duty_cycle_label':            'Mzunguko wa kazi wa mpigo',
    'transmitter_freq':            'Marudio:',
    'transmitter_pwr':             'Nguvu ya TX:',
    'tx_disabled':                 'TX: IMEZIMWA',
    'tx_enabled':                  'TX: IMEWASHWA',
    'tx_license':
        'Leseni halali ya redio ya amateur inahitajika kusambaza kwenye '
        'marudio haya. '
        'Angalia mpango wa bendi wa kitaifa wako.',
    'save_to_disk':                'Hifadhi kwenye diski',
    'save_description':
        'Huhifadhi sampuli ghafi za IQ kama binary ya complex64.\n'
        'Njia mbili: I (halisi) na Q (ya kufikirika).\n'
        'Inaendana na GNU Radio, inspectrum,\n'
        'GQRX, na SDR# kwa uchambuzi wa nje ya mtandao.\n'
        ' \n'
        'Kwa kiwango cha sampuli cha 2 MHz: takriban 16 MB/sekunde.\n'
        'Kurekodi kwa sekunde 30 hutumia takriban 480 MB.\n'
        'Panga hifadhi kabla ya kurekodi kwa muda mrefu.\n'
        ' \n'
        'Waterfall: FFT ya muda mfupi kupitia numpy,\n'
        'imeonyeshwa kwa ramani ya rangi ya inferno ya matplotlib.\n'
        'Inafunguka kiotomatiki kwenye kitazamaji cha mfumo.',
    'record_iq':                   'Rekodi IQ',
    'recording':                   'Inarekodi...',
    'waterfall_checkbox':          'Tengeneza picha ya waterfall',
    'event_log':                   'Kumbukumbu za Matukio',
    'event_log_title':             '  OpenV2K  Kumbukumbu za Matukio',
    'no_mbrola_voice':
        'Hakuna sauti ya MBROLA inayopatikana kwa lugha hii -- '
        'inatumia usanisi wa formant wa eSpeak badala yake.',
},

'tr': {
    'section_audio_input':        'Ses Girişi',
    'section_signal_processing':  'Sinyal İşleme',
    'section_output':             'Çıkış',
    'live_microphone':            'Canlı Mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Sıfır geçişli darbe üreteci',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofon seviyesi: sessizlikte -45 dB, konuşurken -18 dB hedefleyin.\n'
        'Ayarla: Sistem Ayarları > Ses > Giriş.',
    'mic_muted':                  'Mik: SESSİZ',
    'mic_live':                   'Mik: CANLI',
    'generate_voice':             'Ses Oluştur',
    'placeholder_hello':          'Merhaba Dünya',
    'placeholder_enter_text':     'Metni buraya girin',
    'optional_filters':           'İsteğe bağlı filtreler',
    'col_signal_conditioning':    'Sinyal koşullandırma',
    'col_noise_silence':          'Gürültü / Sessizlik',
    'col_zcr_shaping':            'ZCR şekillendirme',
    'filt_notch':                 '50/60 Hz çentik filtresi',
    'filt_preemph':               'Ön vurgu',
    'filt_decimate':               'Alt örnekleme / Ondalıklama',
    'filt_noisegate':             'Gürültü kapısı',
    'filt_envfollow':             'Zarf takipçisi',
    'filt_specsub':               'Spektral çıkarma',
    'filt_hwrect':                'Yarım dalga doğrultma',
    'filt_schmitt':                'Schmitt tetikleyici',
    'filt_hilbert':                'Hilbert zarfı',
    'slider_pulse':                'Darbe (\u00b5s)',
    'slider_hpf':                  'YGF (Hz)',
    'slider_lpf':                  'AGF (Hz)',
    'duty_summary':                'Ort: %2-4\nMaks: %10\n>%6 spesifikasyon dışı',
    'duty_cycle_label':            'Darbe çalışma döngüsü',
    'transmitter_freq':            'Frekans:',
    'transmitter_pwr':             'TX Gücü:',
    'tx_disabled':                 'TX: DEVRE DIŞI',
    'tx_enabled':                  'TX: ETKİN',
    'tx_license':
        'Bu frekanslarda yayın yapmak için geçerli bir amatör telsiz '
        'lisansı gereklidir. '
        'Ulusal bant planınızı kontrol edin.',
    'save_to_disk':                'Diske kaydet',
    'save_description':
        'Ham IQ örneklerini complex64 ikili biçiminde kaydeder.\n'
        'İki kanal: I (gerçek) ve Q (sanal).\n'
        'GNU Radio, inspectrum,\n'
        'GQRX ve SDR# ile uyumlu, çevrimdışı analiz için.\n'
        ' \n'
        '2 MHz örnekleme hızında: yaklaşık 16 MB/saniye.\n'
        '30 saniyelik bir kayıt yaklaşık 480 MB kullanır.\n'
        'Uzun kayıtlardan önce depolama alanını planlayın.\n'
        ' \n'
        'Waterfall: numpy ile kısa süreli FFT,\n'
        'matplotlib inferno renk haritasıyla oluşturulur.\n'
        'Sistem görüntüleyicisinde otomatik olarak açılır.',
    'record_iq':                   'IQ Kaydet',
    'recording':                   'Kaydediliyor...',
    'waterfall_checkbox':          'Waterfall görüntüsü oluştur',
    'event_log':                   'Olay Günlüğü',
    'event_log_title':             '  OpenV2K  Olay Günlüğü',
    'no_mbrola_voice':
        'Bu dil için MBROLA sesi mevcut değil -- '
        'bunun yerine eSpeak formant sentezi kullanılıyor.',
},

'vi': {
    'section_audio_input':        'Đầu Vào Âm Thanh',
    'section_signal_processing':  'Xử Lý Tín Hiệu',
    'section_output':             'Đầu Ra',
    'live_microphone':            'Micro Trực Tiếp',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Bộ tạo xung điểm không',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mức micro: -45 dB khi im lặng, hướng tới -18 dB khi nói.\n'
        'Điều chỉnh tại: Cài đặt hệ thống > Âm thanh > Đầu vào.',
    'mic_muted':                  'Mic: TẮT TIẾNG',
    'mic_live':                   'Mic: TRỰC TIẾP',
    'generate_voice':             'Tạo Giọng Nói',
    'placeholder_hello':          'Xin Chào Thế Giới',
    'placeholder_enter_text':     'Nhập văn bản tại đây',
    'optional_filters':           'Bộ lọc tùy chọn',
    'col_signal_conditioning':    'Điều hòa tín hiệu',
    'col_noise_silence':          'Nhiễu / Im lặng',
    'col_zcr_shaping':            'Định hình ZCR',
    'filt_notch':                 'Bộ lọc chặn dải 50/60 Hz',
    'filt_preemph':               'Tiền nhấn mạnh',
    'filt_decimate':               'Giảm mẫu / Thập phân hóa',
    'filt_noisegate':             'Cổng nhiễu',
    'filt_envfollow':             'Bộ theo dõi đường bao',
    'filt_specsub':               'Trừ phổ',
    'filt_hwrect':                'Chỉnh lưu bán sóng',
    'filt_schmitt':                'Bộ kích hoạt Schmitt',
    'filt_hilbert':                'Đường bao Hilbert',
    'slider_pulse':                'Xung (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'TB: 2-4%\nTối đa: 10%\n>6% ngoài thông số',
    'duty_cycle_label':            'Chu kỳ hoạt động xung',
    'transmitter_freq':            'Tần số:',
    'transmitter_pwr':             'Công suất TX:',
    'tx_disabled':                 'TX: TẮT',
    'tx_enabled':                  'TX: BẬT',
    'tx_license':
        'Cần có giấy phép vô tuyến nghiệp dư hợp lệ để phát trên các tần '
        'số này. '
        'Kiểm tra kế hoạch băng tần quốc gia của bạn.',
    'save_to_disk':                'Lưu vào đĩa',
    'save_description':
        'Lưu các mẫu IQ thô dưới dạng nhị phân complex64.\n'
        'Hai kênh: I (thực) và Q (ảo).\n'
        'Tương thích với GNU Radio, inspectrum,\n'
        'GQRX và SDR# để phân tích ngoại tuyến.\n'
        ' \n'
        'Ở tốc độ lấy mẫu 2 MHz: khoảng 16 MB/giây.\n'
        'Bản ghi 30 giây sử dụng khoảng 480 MB.\n'
        'Lên kế hoạch lưu trữ trước khi ghi âm dài.\n'
        ' \n'
        'Waterfall: FFT thời gian ngắn qua numpy,\n'
        'hiển thị bằng bảng màu inferno của matplotlib.\n'
        'Tự động mở trong trình xem hệ thống.',
    'record_iq':                   'Ghi IQ',
    'recording':                   'Đang ghi...',
    'waterfall_checkbox':          'Tạo hình ảnh waterfall',
    'event_log':                   'Nhật Ký Sự Kiện',
    'event_log_title':             '  OpenV2K  Nhật Ký Sự Kiện',
    'no_mbrola_voice':
        'Không có giọng MBROLA khả dụng cho ngôn ngữ này -- '
        'sử dụng tổng hợp formant eSpeak thay thế.',
},

'ko': {
    'section_audio_input':        '오디오 입력',
    'section_signal_processing':  '신호 처리',
    'section_output':             '출력',
    'live_microphone':            '실시간 마이크',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                '제로크로싱 펄스 생성기',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        '마이크 레벨: 무음 시 -45dB, 말할 때 -18dB를 목표로 하세요.\n'
        '조정: 시스템 설정 > 소리 > 입력.',
    'mic_muted':                  '마이크: 음소거',
    'mic_live':                   '마이크: 실시간',
    'generate_voice':             '음성 생성',
    'placeholder_hello':          '안녕하세요 세계',
    'placeholder_enter_text':     '여기에 텍스트 입력',
    'optional_filters':           '선택적 필터',
    'col_signal_conditioning':    '신호 컨디셔닝',
    'col_noise_silence':          '노이즈 / 무음',
    'col_zcr_shaping':            'ZCR 성형',
    'filt_notch':                 '50/60Hz 노치 필터',
    'filt_preemph':               '프리엠퍼시스',
    'filt_decimate':               '다운샘플링 / 데시메이션',
    'filt_noisegate':             '노이즈 게이트',
    'filt_envfollow':             '엔벨로프 팔로워',
    'filt_specsub':               '스펙트럴 차감',
    'filt_hwrect':                '반파 정류',
    'filt_schmitt':                '슈미트 트리거',
    'filt_hilbert':                '힐베르트 엔벨로프',
    'slider_pulse':                '펄스 (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                '평균: 2-4%\n최대: 10%\n>6%는 규격 초과',
    'duty_cycle_label':            '펄스 듀티 사이클',
    'transmitter_freq':            '주파수:',
    'transmitter_pwr':             'TX 출력:',
    'tx_disabled':                 'TX: 비활성화',
    'tx_enabled':                  'TX: 활성화',
    'tx_license':
        '이 주파수에서 송신하려면 유효한 아마추어 무선 면허가 필요합니다. '
        '국가 대역 계획을 확인하세요.',
    'save_to_disk':                '디스크에 저장',
    'save_description':
        '원시 IQ 샘플을 complex64 바이너리로 저장합니다.\n'
        '두 채널: I(실수부)와 Q(허수부).\n'
        'GNU Radio, inspectrum,\n'
        'GQRX, SDR#와 호환되며 오프라인 분석에 사용됩니다.\n'
        ' \n'
        '2MHz 샘플링 속도에서: 약 16MB/초.\n'
        '30초 녹음은 약 480MB를 사용합니다.\n'
        '긴 녹음 전에 저장 공간을 계획하세요.\n'
        ' \n'
        'Waterfall: numpy를 통한 단시간 FFT,\n'
        'matplotlib의 inferno 컬러맵으로 렌더링됩니다.\n'
        '시스템 뷰어에서 자동으로 열립니다.',
    'record_iq':                   'IQ 녹음',
    'recording':                   '녹음 중...',
    'waterfall_checkbox':          'Waterfall 이미지 생성',
    'event_log':                   '이벤트 로그',
    'event_log_title':             '  OpenV2K  이벤트 로그',
    'no_mbrola_voice':
        '이 언어에 사용 가능한 MBROLA 음성이 없습니다 -- '
        '대신 eSpeak 포먼트 합성을 사용합니다.',
},

'fa': {
    'section_audio_input':        'ورودی صدا',
    'section_signal_processing':  'پردازش سیگنال',
    'section_output':             'خروجی',
    'live_microphone':            'میکروفون زنده',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'تولیدکننده پالس عبور از صفر',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'سطح میکروفون: در سکوت -45 دسی‌بل، هنگام صحبت -18 دسی‌بل را هدف قرار دهید.\n'
        'تنظیم در: تنظیمات سیستم > صدا > ورودی.',
    'mic_muted':                  'میکروفون: بی‌صدا',
    'mic_live':                   'میکروفون: زنده',
    'generate_voice':             'تولید صدا',
    'placeholder_hello':          'سلام دنیا',
    'placeholder_enter_text':     'متن را اینجا وارد کنید',
    'optional_filters':           'فیلترهای اختیاری',
    'col_signal_conditioning':    'شرطی‌سازی سیگنال',
    'col_noise_silence':          'نویز / سکوت',
    'col_zcr_shaping':            'شکل‌دهی ZCR',
    'filt_notch':                 'فیلتر ناچ 50/60 هرتز',
    'filt_preemph':               'پیش‌تأکید',
    'filt_decimate':               'کاهش نرخ نمونه / تقلیل',
    'filt_noisegate':             'دروازه نویز',
    'filt_envfollow':             'دنبال‌کننده پوش',
    'filt_specsub':               'تفریق طیفی',
    'filt_hwrect':                'یکسوسازی نیم‌موج',
    'filt_schmitt':                'تریگر اشمیت',
    'filt_hilbert':                'پوش هیلبرت',
    'slider_pulse':                'پالس (µs)',
    'slider_hpf':                  'فیلتر بالاگذر (Hz)',
    'slider_lpf':                  'فیلتر پایین‌گذر (Hz)',
    'duty_summary':                'میانگین: 2-4%\nحداکثر: 10%\n>6% خارج از مشخصات',
    'duty_cycle_label':            'ضریب کاری پالس',
    'transmitter_freq':            'فرکانس:',
    'transmitter_pwr':             'توان TX:',
    'tx_disabled':                 'TX: غیرفعال',
    'tx_enabled':                  'TX: فعال',
    'tx_license':
        'برای ارسال در این فرکانس‌ها به یک مجوز رادیو آماتور معتبر نیاز '
        'است. '
        'برنامه باند ملی خود را بررسی کنید.',
    'save_to_disk':                'ذخیره در دیسک',
    'save_description':
        'نمونه‌های خام IQ را به صورت باینری complex64 ذخیره می‌کند.\n'
        'دو کانال: I (حقیقی) و Q (موهومی).\n'
        'سازگار با GNU Radio، inspectrum،\n'
        'GQRX و SDR# برای تحلیل آفلاین.\n'
        ' \n'
        'در نرخ نمونه‌برداری 2 مگاهرتز: حدود 16 مگابایت بر ثانیه.\n'
        'یک ضبط 30 ثانیه‌ای حدود 480 مگابایت استفاده می‌کند.\n'
        'قبل از ضبط‌های طولانی، فضای ذخیره‌سازی را برنامه‌ریزی کنید.\n'
        ' \n'
        'Waterfall: FFT کوتاه‌مدت از طریق numpy،\n'
        'با نقشه رنگی inferno از matplotlib رندر شده.\n'
        'به‌طور خودکار در نمایشگر سیستم باز می‌شود.',
    'record_iq':                   'ضبط IQ',
    'recording':                   'در حال ضبط...',
    'waterfall_checkbox':          'ایجاد تصویر waterfall',
    'event_log':                   'گزارش رویداد',
    'event_log_title':             '  OpenV2K  گزارش رویداد',
    'no_mbrola_voice':
        'هیچ صدای MBROLA برای این زبان در دسترس نیست -- '
        'در عوض از سنتز فورمنت eSpeak استفاده می‌شود.',
},

'pa': {
    'section_audio_input':        'ਆਡੀਓ ਇਨਪੁਟ',
    'section_signal_processing':  'ਸਿਗਨਲ ਪ੍ਰੋਸੈਸਿੰਗ',
    'section_output':             'ਆਉਟਪੁੱਟ',
    'live_microphone':            'ਲਾਈਵ ਮਾਈਕ੍ਰੋਫ਼ੋਨ',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'ਜ਼ੀਰੋ-ਕਰਾਸਿੰਗ ਪਲਸ ਜਨਰੇਟਰ',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'ਮਾਈਕ ਪੱਧਰ: ਚੁੱਪ ਵਿੱਚ -45 dB, ਬੋਲਦੇ ਸਮੇਂ -18 dB ਦਾ ਟੀਚਾ ਰੱਖੋ।\n'
        'ਵਿਵਸਥਿਤ ਕਰੋ: ਸਿਸਟਮ ਸੈਟਿੰਗਾਂ > ਧੁਨੀ > ਇਨਪੁਟ।',
    'mic_muted':                  'ਮਾਈਕ: ਮਿਊਟ',
    'mic_live':                   'ਮਾਈਕ: ਲਾਈਵ',
    'generate_voice':             'ਆਵਾਜ਼ ਬਣਾਓ',
    'placeholder_hello':          'ਹੈਲੋ ਵਰਲਡ',
    'placeholder_enter_text':     'ਇੱਥੇ ਟੈਕਸਟ ਲਿਖੋ',
    'optional_filters':           'ਵਿਕਲਪਿਕ ਫਿਲਟਰ',
    'col_signal_conditioning':    'ਸਿਗਨਲ ਕੰਡੀਸ਼ਨਿੰਗ',
    'col_noise_silence':          'ਸ਼ੋਰ / ਚੁੱਪ',
    'col_zcr_shaping':            'ZCR ਸ਼ੇਪਿੰਗ',
    'filt_notch':                 '50/60 Hz ਨੌਚ ਫਿਲਟਰ',
    'filt_preemph':               'ਪ੍ਰੀ-ਐਂਫੈਸਿਸ',
    'filt_decimate':               'ਡਾਊਨਸੈਂਪਲਿੰਗ / ਡੈਸੀਮੇਸ਼ਨ',
    'filt_noisegate':             'ਨੌਇਜ਼ ਗੇਟ',
    'filt_envfollow':             'ਐਨਵੈਲਪ ਫਾਲੋਅਰ',
    'filt_specsub':               'ਸਪੈਕਟ੍ਰਲ ਸਬਟਰੈਕਸ਼ਨ',
    'filt_hwrect':                'ਹਾਫ-ਵੇਵ ਰੈਕਟੀਫਿਕੇਸ਼ਨ',
    'filt_schmitt':                'ਸ਼ਮਿਟ ਟਰਿਗਰ',
    'filt_hilbert':                'ਹਿਲਬਰਟ ਐਨਵੈਲਪ',
    'slider_pulse':                'ਪਲਸ (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'ਔਸਤ: 2-4%\nਵੱਧ ਤੋਂ ਵੱਧ: 10%\n>6% ਸੀਮਾ ਤੋਂ ਬਾਹਰ',
    'duty_cycle_label':            'ਪਲਸ ਡਿਊਟੀ ਸਾਈਕਲ',
    'transmitter_freq':            'ਫ੍ਰੀਕੁਐਂਸੀ:',
    'transmitter_pwr':             'TX ਪਾਵਰ:',
    'tx_disabled':                 'TX: ਅਯੋਗ',
    'tx_enabled':                  'TX: ਸਮਰੱਥ',
    'tx_license':
        'ਇਹਨਾਂ ਫ੍ਰੀਕੁਐਂਸੀਆਂ \'ਤੇ ਪ੍ਰਸਾਰਣ ਲਈ ਇੱਕ ਵੈਧ ਸ਼ੌਕੀਆ ਰੇਡੀਓ '
        'ਲਾਇਸੰਸ ਦੀ ਲੋੜ ਹੈ। '
        'ਆਪਣੀ ਰਾਸ਼ਟਰੀ ਬੈਂਡ ਯੋਜਨਾ ਦੀ ਜਾਂਚ ਕਰੋ।',
    'save_to_disk':                'ਡਿਸਕ ਵਿੱਚ ਸੰਭਾਲੋ',
    'save_description':
        'ਕੱਚੇ IQ ਨਮੂਨਿਆਂ ਨੂੰ complex64 ਬਾਈਨਰੀ ਵਜੋਂ ਸੰਭਾਲਦਾ ਹੈ।\n'
        'ਦੋ ਚੈਨਲ: I (ਅਸਲ) ਅਤੇ Q (ਕਾਲਪਨਿਕ)।\n'
        'GNU Radio, inspectrum,\n'
        'GQRX, ਅਤੇ SDR# ਨਾਲ ਅਨੁਕੂਲ, ਆਫਲਾਈਨ ਵਿਸ਼ਲੇਸ਼ਣ ਲਈ।\n'
        ' \n'
        '2 MHz ਨਮੂਨਾ ਦਰ \'ਤੇ: ਲਗਭਗ 16 MB/ਸਕਿੰਟ।\n'
        '30 ਸਕਿੰਟ ਦੀ ਰਿਕਾਰਡਿੰਗ ਲਗਭਗ 480 MB ਵਰਤਦੀ ਹੈ।\n'
        'ਲੰਬੀ ਰਿਕਾਰਡਿੰਗ ਤੋਂ ਪਹਿਲਾਂ ਸਟੋਰੇਜ ਦੀ ਯੋਜਨਾ ਬਣਾਓ।\n'
        ' \n'
        'Waterfall: numpy ਰਾਹੀਂ ਸ਼ਾਰਟ-ਟਾਈਮ FFT,\n'
        'matplotlib ਦੇ inferno ਨਕਸ਼ੇ ਨਾਲ ਰੈਂਡਰ ਕੀਤਾ ਗਿਆ।\n'
        'ਸਿਸਟਮ ਵਿਊਅਰ ਵਿੱਚ ਆਪਣੇ ਆਪ ਖੁੱਲ੍ਹਦਾ ਹੈ।',
    'record_iq':                   'IQ ਰਿਕਾਰਡ ਕਰੋ',
    'recording':                   'ਰਿਕਾਰਡਿੰਗ ਹੋ ਰਹੀ ਹੈ...',
    'waterfall_checkbox':          'Waterfall ਚਿੱਤਰ ਬਣਾਓ',
    'event_log':                   'ਇਵੈਂਟ ਲੌਗ',
    'event_log_title':             '  OpenV2K  ਇਵੈਂਟ ਲੌਗ',
    'no_mbrola_voice':
        'ਇਸ ਭਾਸ਼ਾ ਲਈ ਕੋਈ MBROLA ਆਵਾਜ਼ ਉਪਲਬਧ ਨਹੀਂ ਹੈ -- '
        'ਇਸਦੀ ਬਜਾਏ eSpeak ਫਾਰਮੈਂਟ ਸਿੰਥੇਸਿਸ ਵਰਤੀ ਜਾ ਰਹੀ ਹੈ।',
},

'te': {
    'section_audio_input':        'ఆడియో ఇన్‌పుట్',
    'section_signal_processing':  'సిగ్నల్ ప్రాసెసింగ్',
    'section_output':             'అవుట్‌పుట్',
    'live_microphone':            'లైవ్ మైక్రోఫోన్',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'జీరో-క్రాసింగ్ పల్స్ జనరేటర్',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'మైక్ స్థాయి: నిశ్శబ్దంలో -45 dB, మాట్లాడేటప్పుడు -18 dB లక్ష్యంగా పెట్టుకోండి.\n'
        'సర్దుబాటు చేయండి: సిస్టమ్ సెట్టింగ్‌లు > సౌండ్ > ఇన్‌పుట్.',
    'mic_muted':                  'మైక్: మ్యూట్',
    'mic_live':                   'మైక్: లైవ్',
    'generate_voice':             'వాయిస్ సృష్టించండి',
    'placeholder_hello':          'హలో వరల్డ్',
    'placeholder_enter_text':     'ఇక్కడ టెక్స్ట్ నమోదు చేయండి',
    'optional_filters':           'ఐచ్ఛిక ఫిల్టర్‌లు',
    'col_signal_conditioning':    'సిగ్నల్ కండిషనింగ్',
    'col_noise_silence':          'శబ్దం / నిశ్శబ్దం',
    'col_zcr_shaping':            'ZCR షేపింగ్',
    'filt_notch':                 '50/60 Hz నాచ్ ఫిల్టర్',
    'filt_preemph':               'ప్రి-ఎంఫసిస్',
    'filt_decimate':               'డౌన్‌శాంప్లింగ్ / డెసిమేషన్',
    'filt_noisegate':             'నాయిస్ గేట్',
    'filt_envfollow':             'ఎన్వలప్ ఫాలోవర్',
    'filt_specsub':               'స్పెక్ట్రల్ సబ్‌ట్రాక్షన్',
    'filt_hwrect':                'హాఫ్-వేవ్ రెక్టిఫికేషన్',
    'filt_schmitt':                'ష్మిట్ ట్రిగ్గర్',
    'filt_hilbert':                'హిల్బర్ట్ ఎన్వలప్',
    'slider_pulse':                'పల్స్ (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'సగటు: 2-4%\nగరిష్టం: 10%\n>6% పరిమితి దాటింది',
    'duty_cycle_label':            'పల్స్ డ్యూటీ సైకిల్',
    'transmitter_freq':            'ఫ్రీక్వెన్సీ:',
    'transmitter_pwr':             'TX పవర్:',
    'tx_disabled':                 'TX: నిలిపివేయబడింది',
    'tx_enabled':                  'TX: ప్రారంభించబడింది',
    'tx_license':
        'ఈ ఫ్రీక్వెన్సీలలో ప్రసారం చేయడానికి చెల్లుబాటు అయ్యే ఔత్సాహిక '
        'రేడియో లైసెన్స్ అవసరం. '
        'మీ జాతీయ బ్యాండ్ ప్రణాళికను తనిఖీ చేయండి.',
    'save_to_disk':                'డిస్క్‌కు సేవ్ చేయండి',
    'save_description':
        'ముడి IQ నమూనాలను complex64 బైనరీగా సేవ్ చేస్తుంది.\n'
        'రెండు ఛానెల్‌లు: I (వాస్తవ) మరియు Q (కల్పిత).\n'
        'GNU Radio, inspectrum,\n'
        'GQRX మరియు SDR#తో అనుకూలం, ఆఫ్‌లైన్ విశ్లేషణ కోసం.\n'
        ' \n'
        '2 MHz నమూనా రేటు వద్ద: సుమారు 16 MB/సెకను.\n'
        '30 సెకన్ల రికార్డింగ్ సుమారు 480 MB ఉపయోగిస్తుంది.\n'
        'దీర్ఘ రికార్డింగ్‌లకు ముందు నిల్వను ప్లాన్ చేయండి.\n'
        ' \n'
        'Waterfall: numpy ద్వారా షార్ట్-టైమ్ FFT,\n'
        'matplotlib యొక్క inferno మ్యాప్‌తో రెండర్ చేయబడింది.\n'
        'సిస్టమ్ వ్యూయర్‌లో స్వయంచాలకంగా తెరుచుకుంటుంది.',
    'record_iq':                   'IQ రికార్డ్ చేయండి',
    'recording':                   'రికార్డింగ్ జరుగుతోంది...',
    'waterfall_checkbox':          'Waterfall చిత్రాన్ని సృష్టించండి',
    'event_log':                   'ఈవెంట్ లాగ్',
    'event_log_title':             '  OpenV2K  ఈవెంట్ లాగ్',
    'no_mbrola_voice':
        'ఈ భాష కోసం MBROLA వాయిస్ అందుబాటులో లేదు -- '
        'బదులుగా eSpeak ఫార్మంట్ సింథసిస్ ఉపయోగించబడుతోంది.',
},

'mr': {
    'section_audio_input':        'ऑडिओ इनपुट',
    'section_signal_processing':  'सिग्नल प्रोसेसिंग',
    'section_output':             'आउटपुट',
    'live_microphone':            'लाइव्ह मायक्रोफोन',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'शून्य-क्रॉसिंग पल्स जनरेटर',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'माइक पातळी: शांततेत -45 dB, बोलताना -18 dB चे लक्ष्य ठेवा.\n'
        'समायोजित करा: सिस्टम सेटिंग्ज > ध्वनी > इनपुट.',
    'mic_muted':                  'माइक: म्यूट',
    'mic_live':                   'माइक: लाइव्ह',
    'generate_voice':             'आवाज तयार करा',
    'placeholder_hello':          'नमस्कार जग',
    'placeholder_enter_text':     'येथे मजकूर लिहा',
    'optional_filters':           'पर्यायी फिल्टर',
    'col_signal_conditioning':    'सिग्नल कंडिशनिंग',
    'col_noise_silence':          'आवाज / शांतता',
    'col_zcr_shaping':            'ZCR आकार देणे',
    'filt_notch':                 '50/60 Hz नॉच फिल्टर',
    'filt_preemph':               'प्री-एम्फसिस',
    'filt_decimate':               'डाउनसॅम्पलिंग / डेसिमेशन',
    'filt_noisegate':             'नॉइज गेट',
    'filt_envfollow':             'एन्व्हलप फॉलोअर',
    'filt_specsub':               'स्पेक्ट्रल सबट्रॅक्शन',
    'filt_hwrect':                'हाफ-वेव्ह रेक्टिफिकेशन',
    'filt_schmitt':                'श्मिट ट्रिगर',
    'filt_hilbert':                'हिल्बर्ट एन्व्हलप',
    'slider_pulse':                'पल्स (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'सरासरी: 2-4%\nकमाल: 10%\n>6% मर्यादेबाहेर',
    'duty_cycle_label':            'पल्स ड्यूटी सायकल',
    'transmitter_freq':            'फ्रिक्वेन्सी:',
    'transmitter_pwr':             'TX पॉवर:',
    'tx_disabled':                 'TX: निष्क्रिय',
    'tx_enabled':                  'TX: सक्रिय',
    'tx_license':
        'या फ्रिक्वेन्सींवर प्रसारण करण्यासाठी वैध हौशी रेडिओ परवाना '
        'आवश्यक आहे. '
        'तुमची राष्ट्रीय बँड योजना तपासा.',
    'save_to_disk':                'डिस्कवर जतन करा',
    'save_description':
        'कच्चे IQ नमुने complex64 बायनरी म्हणून जतन करते.\n'
        'दोन चॅनेल: I (वास्तविक) आणि Q (काल्पनिक).\n'
        'GNU Radio, inspectrum,\n'
        'GQRX, आणि SDR# सह सुसंगत, ऑफलाइन विश्लेषणासाठी.\n'
        ' \n'
        '2 MHz नमुना दरावर: अंदाजे 16 MB/सेकंद.\n'
        '30 सेकंदांच्या रेकॉर्डिंगसाठी सुमारे 480 MB लागतात.\n'
        'दीर्घ रेकॉर्डिंगपूर्वी साठवण जागेचे नियोजन करा.\n'
        ' \n'
        'Waterfall: numpy द्वारे शॉर्ट-टाइम FFT,\n'
        'matplotlib च्या inferno नकाशासह रेंडर केले.\n'
        'सिस्टम व्ह्यूअरमध्ये आपोआप उघडते.',
    'record_iq':                   'IQ रेकॉर्ड करा',
    'recording':                   'रेकॉर्डिंग सुरू आहे...',
    'waterfall_checkbox':          'Waterfall प्रतिमा तयार करा',
    'event_log':                   'इव्हेंट लॉग',
    'event_log_title':             '  OpenV2K  इव्हेंट लॉग',
    'no_mbrola_voice':
        'या भाषेसाठी कोणताही MBROLA आवाज उपलब्ध नाही -- '
        'त्याऐवजी eSpeak फॉर्मंट संश्लेषण वापरले जात आहे.',
},

'ta': {
    'section_audio_input':        'ஆடியோ உள்ளீடு',
    'section_signal_processing':  'சிக்னல் செயலாக்கம்',
    'section_output':             'வெளியீடு',
    'live_microphone':            'நேரடி மைக்ரோஃபோன்',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'பூஜ்ஜிய கடப்பு துடிப்பு உருவாக்கி',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'மைக் அளவு: அமைதியில் -45 dB, பேசும்போது -18 dB இலக்கு.\n'
        'சரிசெய்யவும்: கணினி அமைப்புகள் > ஒலி > உள்ளீடு.',
    'mic_muted':                  'மைக்: முடக்கப்பட்டது',
    'mic_live':                   'மைக்: நேரடி',
    'generate_voice':             'குரலை உருவாக்கு',
    'placeholder_hello':          'வணக்கம் உலகம்',
    'placeholder_enter_text':     'இங்கே உரையை உள்ளிடவும்',
    'optional_filters':           'விருப்ப வடிகட்டிகள்',
    'col_signal_conditioning':    'சிக்னல் கண்டிஷனிங்',
    'col_noise_silence':          'இரைச்சல் / அமைதி',
    'col_zcr_shaping':            'ZCR வடிவமைப்பு',
    'filt_notch':                 '50/60 Hz நாட்ச் வடிகட்டி',
    'filt_preemph':               'முன் வலியுறுத்தல்',
    'filt_decimate':               'கீழ்மாதிரி எடுத்தல் / டெசிமேஷன்',
    'filt_noisegate':             'இரைச்சல் கேட்',
    'filt_envfollow':             'என்வலப் பின்தொடர்பவர்',
    'filt_specsub':               'நிறமாலை கழித்தல்',
    'filt_hwrect':                'அரை-அலை திருத்தம்',
    'filt_schmitt':                'ஷ்மிட் தூண்டி',
    'filt_hilbert':                'ஹில்பர்ட் என்வலப்',
    'slider_pulse':                'பல்ஸ் (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'சராசரி: 2-4%\nஅதிகபட்சம்: 10%\n>6% வரம்பிற்கு வெளியே',
    'duty_cycle_label':            'பல்ஸ் டியூட்டி சைக்கிள்',
    'transmitter_freq':            'அதிர்வெண்:',
    'transmitter_pwr':             'TX சக்தி:',
    'tx_disabled':                 'TX: முடக்கப்பட்டது',
    'tx_enabled':                  'TX: இயக்கப்பட்டது',
    'tx_license':
        'இந்த அதிர்வெண்களில் ஒளிபரப்ப செல்லுபடியாகும் அமெச்சூர் ரேடியோ '
        'உரிமம் தேவை. '
        'உங்கள் தேசிய பட்டை திட்டத்தை சரிபார்க்கவும்.',
    'save_to_disk':                'வட்டில் சேமி',
    'save_description':
        'மூல IQ மாதிரிகளை complex64 பைனரியாக சேமிக்கிறது.\n'
        'இரண்டு சேனல்கள்: I (உண்மையான) மற்றும் Q (கற்பனையான).\n'
        'GNU Radio, inspectrum,\n'
        'GQRX மற்றும் SDR# உடன் இணக்கமானது, ஆஃப்லைன் பகுப்பாய்வுக்கு.\n'
        ' \n'
        '2 MHz மாதிரி விகிதத்தில்: தோராயமாக 16 MB/வினாடி.\n'
        '30 வினாடி பதிவு தோராயமாக 480 MB பயன்படுத்துகிறது.\n'
        'நீண்ட பதிவுகளுக்கு முன் சேமிப்பகத்தை திட்டமிடவும்.\n'
        ' \n'
        'Waterfall: numpy வழியாக குறுகிய நேர FFT,\n'
        'matplotlib இன் inferno வண்ணப்படத்துடன் வழங்கப்படுகிறது.\n'
        'கணினி பார்வையாளரில் தானாக திறக்கும்.',
    'record_iq':                   'IQ பதிவு செய்',
    'recording':                   'பதிவு செய்யப்படுகிறது...',
    'waterfall_checkbox':          'Waterfall படத்தை உருவாக்கு',
    'event_log':                   'நிகழ்வு பதிவு',
    'event_log_title':             '  OpenV2K  நிகழ்வு பதிவு',
    'no_mbrola_voice':
        'இந்த மொழிக்கு MBROLA குரல் எதுவும் கிடைக்கவில்லை -- '
        'அதற்கு பதிலாக eSpeak ஃபார்மண்ட் தொகுப்பு பயன்படுத்தப்படுகிறது.',
},
'pl': {
    'section_audio_input':        'Wejście audio',
    'section_signal_processing':  'Przetwarzanie sygnału',
    'section_output':             'Wyjście',
    'live_microphone':            'Mikrofon na żywo',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generator impulsów przejścia przez zero',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Poziom mikrofonu: -45 dB w ciszy, celuj w -18 dB podczas mówienia.\n'
        'Dostosuj w: Ustawienia systemu > Dźwięk > Wejście.',
    'mic_muted':                  'Mikrofon: WYCISZONY',
    'mic_live':                   'Mikrofon: NA ŻYWO',
    'generate_voice':             'Generuj głos',
    'placeholder_hello':          'Witaj świecie',
    'placeholder_enter_text':     'Wpisz tekst tutaj',
    'optional_filters':           'Filtry opcjonalne',
    'col_signal_conditioning':    'Kondycjonowanie sygnału',
    'col_noise_silence':          'Szum / Cisza',
    'col_zcr_shaping':            'Kształtowanie ZCR',
    'filt_notch':                 'Filtr zaporowy 50/60 Hz',
    'filt_preemph':               'Preemfaza',
    'filt_decimate':               'Downsampling / Decymacja',
    'filt_noisegate':             'Bramka szumów',
    'filt_envfollow':             'Śledzenie obwiedni',
    'filt_specsub':               'Odejmowanie widmowe',
    'filt_hwrect':                'Prostowanie jednopołówkowe',
    'filt_schmitt':                'Przerzutnik Schmitta',
    'filt_hilbert':                'Obwiednia Hilberta',
    'slider_pulse':                'Impuls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Śr: 2-4%\nMaks: 10%\n>6% poza specyfikacją',
    'duty_cycle_label':            'Wypełnienie impulsu',
    'transmitter_freq':            'Częstotliwość:',
    'transmitter_pwr':             'Moc TX:',
    'tx_disabled':                 'TX: WYŁĄCZONY',
    'tx_enabled':                  'TX: WŁĄCZONY',
    'tx_license':
        'Do nadawania na tych częstotliwościach wymagana jest ważna '
        'licencja radioamatorska. '
        'Sprawdź swój krajowy plan pasm.',
    'save_to_disk':                'Zapisz na dysku',
    'save_description':
        'Zapisuje surowe próbki IQ jako binarny complex64.\n'
        'Dwa kanały: I (rzeczywisty) i Q (urojony).\n'
        'Kompatybilne z GNU Radio, inspectrum,\n'
        'GQRX i SDR# do analizy offline.\n'
        ' \n'
        'Przy próbkowaniu 2 MHz: ok. 16 MB/s.\n'
        '30-sekundowe nagranie zajmuje ok. 480 MB.\n'
        'Zaplanuj miejsce na dysku przed długimi nagraniami.\n'
        ' \n'
        'Waterfall: krótkoczasowe FFT przez numpy,\n'
        'renderowane mapą kolorów inferno z matplotlib.\n'
        'Otwiera się automatycznie w przeglądarce systemowej.',
    'record_iq':                   'Nagraj IQ',
    'recording':                   'Nagrywanie...',
    'waterfall_checkbox':          'Generuj obraz waterfall',
    'event_log':                   'Dziennik zdarzeń',
    'event_log_title':             '  OpenV2K  Dziennik zdarzeń',
    'no_mbrola_voice':
        'Brak dostępnego głosu MBROLA dla tego języka -- '
        'używana jest zamiast tego synteza formantowa eSpeak.',
},

'ro': {
    'section_audio_input':        'Intrare audio',
    'section_signal_processing':  'Procesare semnal',
    'section_output':             'Ieșire',
    'live_microphone':            'Microfon live',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generator de impulsuri la trecerea prin zero',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Nivel microfon: -45 dB în liniște, țintește -18 dB când vorbești.\n'
        'Ajustează în: Setări sistem > Sunet > Intrare.',
    'mic_muted':                  'Mic: MUT',
    'mic_live':                   'Mic: LIVE',
    'generate_voice':             'Generează voce',
    'placeholder_hello':          'Salut Lume',
    'placeholder_enter_text':     'Introduceți textul aici',
    'optional_filters':           'Filtre opționale',
    'col_signal_conditioning':    'Condiționarea semnalului',
    'col_noise_silence':          'Zgomot / Liniște',
    'col_zcr_shaping':            'Modelare ZCR',
    'filt_notch':                 'Filtru notch 50/60 Hz',
    'filt_preemph':               'Preaccentuare',
    'filt_decimate':               'Subeșantionare / Decimare',
    'filt_noisegate':             'Poartă de zgomot',
    'filt_envfollow':             'Urmăritor de anvelopă',
    'filt_specsub':               'Scădere spectrală',
    'filt_hwrect':                'Redresare semi-undă',
    'filt_schmitt':                'Declanșator Schmitt',
    'filt_hilbert':                'Anvelopă Hilbert',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'FTS (Hz)',
    'slider_lpf':                  'FTJ (Hz)',
    'duty_summary':                'Med: 2-4%\nMax: 10%\n>6% peste specificație',
    'duty_cycle_label':            'Factor de umplere puls',
    'transmitter_freq':            'Frecvență:',
    'transmitter_pwr':             'Putere TX:',
    'tx_disabled':                 'TX: DEZACTIVAT',
    'tx_enabled':                  'TX: ACTIVAT',
    'tx_license':
        'Este necesară o licență radioamator valabilă pentru a transmite '
        'pe aceste frecvențe. '
        'Verificați planul național de benzi.',
    'save_to_disk':                'Salvează pe disc',
    'save_description':
        'Salvează eșantioanele IQ brute ca binar complex64.\n'
        'Două canale: I (real) și Q (imaginar).\n'
        'Compatibil cu GNU Radio, inspectrum,\n'
        'GQRX și SDR# pentru analiză offline.\n'
        ' \n'
        'La o rată de eșantionare de 2 MHz: aprox. 16 MB/sec.\n'
        'O înregistrare de 30 de secunde folosește aprox. 480 MB.\n'
        'Planificați spațiul de stocare înainte de înregistrări lungi.\n'
        ' \n'
        'Waterfall: FFT pe termen scurt prin numpy,\n'
        'randat cu harta de culori inferno din matplotlib.\n'
        'Se deschide automat în vizualizatorul de sistem.',
    'record_iq':                   'Înregistrează IQ',
    'recording':                   'Se înregistrează...',
    'waterfall_checkbox':          'Generează imagine waterfall',
    'event_log':                   'Jurnal de evenimente',
    'event_log_title':             '  OpenV2K  Jurnal de evenimente',
    'no_mbrola_voice':
        'Nicio voce MBROLA disponibilă pentru această limbă -- '
        'se folosește în schimb sinteza formantică eSpeak.',
},

'nl': {
    'section_audio_input':        'Audio-invoer',
    'section_signal_processing':  'Signaalverwerking',
    'section_output':             'Uitvoer',
    'live_microphone':            'Live microfoon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nuldoorgang-pulsgenerator',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Microfoonniveau: -45 dB in stilte, streef naar -18 dB bij spreken.\n'
        'Aanpassen in: Systeeminstellingen > Geluid > Invoer.',
    'mic_muted':                  'Mic: GEDEMPT',
    'mic_live':                   'Mic: LIVE',
    'generate_voice':             'Stem genereren',
    'placeholder_hello':          'Hallo Wereld',
    'placeholder_enter_text':     'Typ hier tekst',
    'optional_filters':           'Optionele filters',
    'col_signal_conditioning':    'Signaalconditionering',
    'col_noise_silence':          'Ruis / Stilte',
    'col_zcr_shaping':            'ZCR-vormgeving',
    'filt_notch':                 '50/60 Hz notchfilter',
    'filt_preemph':               'Pre-emphasis',
    'filt_decimate':               'Downsampling / Decimatie',
    'filt_noisegate':             'Ruispoort',
    'filt_envfollow':             'Envelopvolger',
    'filt_specsub':               'Spectrale aftrekking',
    'filt_hwrect':                'Halvegolfgelijkrichting',
    'filt_schmitt':                'Schmitt-trigger',
    'filt_hilbert':                'Hilbert-envelope',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Gem: 2-4%\nMax: 10%\n>6% buiten specificatie',
    'duty_cycle_label':            'Pulsarbeidscyclus',
    'transmitter_freq':            'Frequentie:',
    'transmitter_pwr':             'TX-vermogen:',
    'tx_disabled':                 'TX: UITGESCHAKELD',
    'tx_enabled':                  'TX: INGESCHAKELD',
    'tx_license':
        'Een geldige radioamateurvergunning is vereist om te zenden op '
        'deze frequenties. '
        'Controleer uw nationale bandplan.',
    'save_to_disk':                'Opslaan op schijf',
    'save_description':
        'Slaat ruwe IQ-samples op als complex64 binair.\n'
        'Twee kanalen: I (reëel) en Q (imaginair).\n'
        'Compatibel met GNU Radio, inspectrum,\n'
        'GQRX en SDR# voor offline analyse.\n'
        ' \n'
        'Bij 2 MHz samplerate: ca. 16 MB/sec.\n'
        'Een opname van 30 seconden gebruikt ca. 480 MB.\n'
        'Plan opslagruimte voor lange opnames.\n'
        ' \n'
        'Waterfall: korte-tijd FFT via numpy,\n'
        'weergegeven met de inferno-kleurenkaart van matplotlib.\n'
        'Opent automatisch in de systeemviewer.',
    'record_iq':                   'IQ opnemen',
    'recording':                   'Opname bezig...',
    'waterfall_checkbox':          'Waterfall-afbeelding genereren',
    'event_log':                   'Gebeurtenislogboek',
    'event_log_title':             '  OpenV2K  Gebeurtenislogboek',
    'no_mbrola_voice':
        'Geen MBROLA-stem beschikbaar voor deze taal -- '
        'gebruikt in plaats daarvan eSpeak-formantsynthese.',
},

'hu': {
    'section_audio_input':        'Hangbemenet',
    'section_signal_processing':  'Jelfeldolgozás',
    'section_output':             'Kimenet',
    'live_microphone':            'Élő mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nullátmenet-impulzusgenerátor',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofonszint: csendben -45 dB, beszéd közben -18 dB legyen a cél.\n'
        'Beállítás: Rendszerbeállítások > Hang > Bemenet.',
    'mic_muted':                  'Mikrofon: NÉMÍTVA',
    'mic_live':                   'Mikrofon: ÉLŐ',
    'generate_voice':             'Hang generálása',
    'placeholder_hello':          'Helló Világ',
    'placeholder_enter_text':     'Írja ide a szöveget',
    'optional_filters':           'Opcionális szűrők',
    'col_signal_conditioning':    'Jelkondicionálás',
    'col_noise_silence':          'Zaj / Csend',
    'col_zcr_shaping':            'ZCR alakítás',
    'filt_notch':                 '50/60 Hz zárószűrő',
    'filt_preemph':               'Pre-emfázis',
    'filt_decimate':               'Alulmintavételezés / Decimálás',
    'filt_noisegate':             'Zajkapu',
    'filt_envfollow':             'Burkológörbe-követő',
    'filt_specsub':               'Spektrális kivonás',
    'filt_hwrect':                'Félhullámú egyenirányítás',
    'filt_schmitt':                'Schmitt-trigger',
    'filt_hilbert':                'Hilbert-burkológörbe',
    'slider_pulse':                'Impulzus (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Átlag: 2-4%\nMax: 10%\n>6% specifikáción kívül',
    'duty_cycle_label':            'Impulzus kitöltési tényező',
    'transmitter_freq':            'Frekvencia:',
    'transmitter_pwr':             'TX teljesítmény:',
    'tx_disabled':                 'TX: LETILTVA',
    'tx_enabled':                  'TX: ENGEDÉLYEZVE',
    'tx_license':
        'Ezeken a frekvenciákon való adáshoz érvényes rádióamatőr '
        'engedély szükséges. '
        'Ellenőrizze nemzeti sávtervét.',
    'save_to_disk':                'Mentés lemezre',
    'save_description':
        'Nyers IQ mintákat ment complex64 bináris formátumban.\n'
        'Két csatorna: I (valós) és Q (képzetes).\n'
        'Kompatibilis a GNU Radio, inspectrum,\n'
        'GQRX és SDR# programokkal offline elemzéshez.\n'
        ' \n'
        '2 MHz mintavételi sebességnél: kb. 16 MB/mp.\n'
        'Egy 30 másodperces felvétel kb. 480 MB-ot használ.\n'
        'Tervezze meg a tárhelyet hosszú felvételek előtt.\n'
        ' \n'
        'Waterfall: rövid idejű FFT numpy-n keresztül,\n'
        'a matplotlib inferno színtérképével renderelve.\n'
        'Automatikusan megnyílik a rendszer megjelenítőjében.',
    'record_iq':                   'IQ rögzítése',
    'recording':                   'Felvétel...',
    'waterfall_checkbox':          'Waterfall kép generálása',
    'event_log':                   'Eseménynapló',
    'event_log_title':             '  OpenV2K  Eseménynapló',
    'no_mbrola_voice':
        'Nincs elérhető MBROLA hang ehhez a nyelvhez -- '
        'helyette eSpeak formáns szintézist használ.',
},

'el': {
    'section_audio_input':        'Είσοδος ήχου',
    'section_signal_processing':  'Επεξεργασία σήματος',
    'section_output':             'Έξοδος',
    'live_microphone':            'Ζωντανό μικρόφωνο',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Γεννήτρια παλμών μηδενικής διέλευσης',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Επίπεδο μικροφώνου: -45 dB σε ησυχία, στόχος -18 dB όταν μιλάτε.\n'
        'Ρύθμιση: Ρυθμίσεις συστήματος > Ήχος > Είσοδος.',
    'mic_muted':                  'Μικ: ΣΙΓΗ',
    'mic_live':                   'Μικ: ΖΩΝΤΑΝΑ',
    'generate_voice':             'Δημιουργία φωνής',
    'placeholder_hello':          'Γεια σου Κόσμε',
    'placeholder_enter_text':     'Εισαγάγετε κείμενο εδώ',
    'optional_filters':           'Προαιρετικά φίλτρα',
    'col_signal_conditioning':    'Διαμόρφωση σήματος',
    'col_noise_silence':          'Θόρυβος / Σιωπή',
    'col_zcr_shaping':            'Διαμόρφωση ZCR',
    'filt_notch':                 'Φίλτρο εγκοπής 50/60 Hz',
    'filt_preemph':               'Προέμφαση',
    'filt_decimate':               'Υποδειγματοληψία / Αποδεκάτωση',
    'filt_noisegate':             'Πύλη θορύβου',
    'filt_envfollow':             'Ανιχνευτής περιβάλλουσας',
    'filt_specsub':               'Φασματική αφαίρεση',
    'filt_hwrect':                'Ανόρθωση ημιπεριόδου',
    'filt_schmitt':                'Σκανδάλη Schmitt',
    'filt_hilbert':                'Περιβάλλουσα Hilbert',
    'slider_pulse':                'Παλμός (µs)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Μέσος: 2-4%\nΜέγ: 10%\n>6% εκτός προδιαγραφών',
    'duty_cycle_label':            'Κύκλος λειτουργίας παλμού',
    'transmitter_freq':            'Συχνότητα:',
    'transmitter_pwr':             'Ισχύς TX:',
    'tx_disabled':                 'TX: ΑΠΕΝΕΡΓΟΠΟΙΗΜΕΝΟ',
    'tx_enabled':                  'TX: ΕΝΕΡΓΟΠΟΙΗΜΕΝΟ',
    'tx_license':
        'Απαιτείται έγκυρη άδεια ραδιοερασιτέχνη για εκπομπή σε αυτές τις '
        'συχνότητες. '
        'Ελέγξτε το εθνικό σχέδιο ζωνών σας.',
    'save_to_disk':                'Αποθήκευση στο δίσκο',
    'save_description':
        'Αποθηκεύει ακατέργαστα δείγματα IQ ως δυαδικό complex64.\n'
        'Δύο κανάλια: I (πραγματικό) και Q (φανταστικό).\n'
        'Συμβατό με GNU Radio, inspectrum,\n'
        'GQRX και SDR# για ανάλυση εκτός σύνδεσης.\n'
        ' \n'
        'Σε ρυθμό δειγματοληψίας 2 MHz: περίπου 16 MB/δευτ.\n'
        'Μια εγγραφή 30 δευτερολέπτων χρησιμοποιεί περίπου 480 MB.\n'
        'Σχεδιάστε τον αποθηκευτικό χώρο πριν από μεγάλες εγγραφές.\n'
        ' \n'
        'Waterfall: σύντομης διάρκειας FFT μέσω numpy,\n'
        'απεικονισμένο με τον χρωματικό χάρτη inferno του matplotlib.\n'
        'Ανοίγει αυτόματα στο πρόγραμμα προβολής του συστήματος.',
    'record_iq':                   'Εγγραφή IQ',
    'recording':                   'Γίνεται εγγραφή...',
    'waterfall_checkbox':          'Δημιουργία εικόνας waterfall',
    'event_log':                   'Αρχείο καταγραφής συμβάντων',
    'event_log_title':             '  OpenV2K  Αρχείο καταγραφής συμβάντων',
    'no_mbrola_voice':
        'Δεν υπάρχει διαθέσιμη φωνή MBROLA για αυτή τη γλώσσα -- '
        'χρησιμοποιείται αντ\' αυτού σύνθεση φορμάντων eSpeak.',
},

'cs': {
    'section_audio_input':        'Zvukový vstup',
    'section_signal_processing':  'Zpracování signálu',
    'section_output':             'Výstup',
    'live_microphone':            'Živý mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generátor pulzů průchodu nulou',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Úroveň mikrofonu: -45 dB v tichu, při mluvení cílte na -18 dB.\n'
        'Upravte v: Nastavení systému > Zvuk > Vstup.',
    'mic_muted':                  'Mikrofon: ZTLUMEN',
    'mic_live':                   'Mikrofon: ŽIVĚ',
    'generate_voice':             'Generovat hlas',
    'placeholder_hello':          'Ahoj světe',
    'placeholder_enter_text':     'Sem napište text',
    'optional_filters':           'Volitelné filtry',
    'col_signal_conditioning':    'Úprava signálu',
    'col_noise_silence':          'Šum / Ticho',
    'col_zcr_shaping':            'Tvarování ZCR',
    'filt_notch':                 'Pásmová zádrž 50/60 Hz',
    'filt_preemph':               'Preemfáze',
    'filt_decimate':               'Podvzorkování / Decimace',
    'filt_noisegate':             'Šumová brána',
    'filt_envfollow':             'Sledovač obálky',
    'filt_specsub':               'Spektrální odečítání',
    'filt_hwrect':                'Jednocestné usměrnění',
    'filt_schmitt':                'Schmittův klopný obvod',
    'filt_hilbert':                'Hilbertova obálka',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Průměr: 2-4%\nMax: 10%\n>6% mimo specifikaci',
    'duty_cycle_label':            'Střída pulzu',
    'transmitter_freq':            'Frekvence:',
    'transmitter_pwr':             'Výkon TX:',
    'tx_disabled':                 'TX: VYPNUTO',
    'tx_enabled':                  'TX: ZAPNUTO',
    'tx_license':
        'K vysílání na těchto frekvencích je vyžadována platná '
        'radioamatérská licence. '
        'Zkontrolujte svůj národní pásmový plán.',
    'save_to_disk':                'Uložit na disk',
    'save_description':
        'Ukládá syrové IQ vzorky jako binární complex64.\n'
        'Dva kanály: I (reálný) a Q (imaginární).\n'
        'Kompatibilní s GNU Radio, inspectrum,\n'
        'GQRX a SDR# pro offline analýzu.\n'
        ' \n'
        'Při vzorkovací frekvenci 2 MHz: cca 16 MB/s.\n'
        '30sekundový záznam zabere přibližně 480 MB.\n'
        'Před dlouhým nahráváním naplánujte úložný prostor.\n'
        ' \n'
        'Waterfall: krátkodobá FFT přes numpy,\n'
        'vykreslená barevnou mapou inferno z matplotlib.\n'
        'Automaticky se otevře v systémovém prohlížeči.',
    'record_iq':                   'Nahrát IQ',
    'recording':                   'Nahrávání...',
    'waterfall_checkbox':          'Vygenerovat obrázek waterfall',
    'event_log':                   'Protokol událostí',
    'event_log_title':             '  OpenV2K  Protokol událostí',
    'no_mbrola_voice':
        'Pro tento jazyk není k dispozici žádný hlas MBROLA -- '
        'místo toho se používá formantová syntéza eSpeak.',
},

'hr': {
    'section_audio_input':        'Audio ulaz',
    'section_signal_processing':  'Obrada signala',
    'section_output':             'Izlaz',
    'live_microphone':            'Mikrofon uživo',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generator impulsa prijelaza kroz nulu',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Razina mikrofona: -45 dB u tišini, ciljajte -18 dB tijekom govora.\n'
        'Prilagodite u: Postavke sustava > Zvuk > Ulaz.',
    'mic_muted':                  'Mikrofon: UTIŠAN',
    'mic_live':                   'Mikrofon: UŽIVO',
    'generate_voice':             'Generiraj glas',
    'placeholder_hello':          'Pozdrav svijete',
    'placeholder_enter_text':     'Unesite tekst ovdje',
    'optional_filters':           'Neobavezni filtri',
    'col_signal_conditioning':    'Kondicioniranje signala',
    'col_noise_silence':          'Šum / Tišina',
    'col_zcr_shaping':            'Oblikovanje ZCR',
    'filt_notch':                 'Pojasno-nepropusni filtar 50/60 Hz',
    'filt_preemph':               'Predisponiranje',
    'filt_decimate':               'Podzorkovanje / Decimacija',
    'filt_noisegate':             'Šumni vrata',
    'filt_envfollow':             'Slijednik omotnice',
    'filt_specsub':               'Spektralno oduzimanje',
    'filt_hwrect':                'Poluvalno ispravljanje',
    'filt_schmitt':                'Schmittov okidač',
    'filt_hilbert':                'Hilbertova omotnica',
    'slider_pulse':                'Impuls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Prosjek: 2-4%\nMaks: 10%\n>6% izvan specifikacije',
    'duty_cycle_label':            'Radni ciklus impulsa',
    'transmitter_freq':            'Frekvencija:',
    'transmitter_pwr':             'TX snaga:',
    'tx_disabled':                 'TX: ONEMOGUĆEN',
    'tx_enabled':                  'TX: OMOGUĆEN',
    'tx_license':
        'Za odašiljanje na ovim frekvencijama potrebna je valjana '
        'radioamaterska dozvola. '
        'Provjerite svoj nacionalni plan pojasa.',
    'save_to_disk':                'Spremi na disk',
    'save_description':
        'Sprema sirove IQ uzorke kao binarni complex64.\n'
        'Dva kanala: I (realni) i Q (imaginarni).\n'
        'Kompatibilno s GNU Radio, inspectrum,\n'
        'GQRX i SDR# za offline analizu.\n'
        ' \n'
        'Pri brzini uzorkovanja 2 MHz: oko 16 MB/s.\n'
        '30-sekundno snimanje koristi oko 480 MB.\n'
        'Planirajte prostor za pohranu prije dugih snimanja.\n'
        ' \n'
        'Waterfall: kratkotrajni FFT putem numpy,\n'
        'prikazan inferno kartom boja iz matplotlib.\n'
        'Automatski se otvara u sistemskom pregledniku.',
    'record_iq':                   'Snimi IQ',
    'recording':                   'Snimanje...',
    'waterfall_checkbox':          'Generiraj waterfall sliku',
    'event_log':                   'Zapisnik događaja',
    'event_log_title':             '  OpenV2K  Zapisnik događaja',
    'no_mbrola_voice':
        'Nema dostupnog MBROLA glasa za ovaj jezik -- '
        'umjesto toga koristi se eSpeak formantna sinteza.',
},

'lt': {
    'section_audio_input':        'Garso įvestis',
    'section_signal_processing':  'Signalo apdorojimas',
    'section_output':             'Išvestis',
    'live_microphone':            'Tiesioginis mikrofonas',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nulinio kirtimo impulsų generatorius',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofono lygis: -45 dB tyloje, kalbant siekite -18 dB.\n'
        'Reguliuokite: Sistemos nustatymai > Garsas > Įvestis.',
    'mic_muted':                  'Mikrofonas: NUTILDYTAS',
    'mic_live':                   'Mikrofonas: TIESIOGIAI',
    'generate_voice':             'Generuoti balsą',
    'placeholder_hello':          'Sveikas, pasauli',
    'placeholder_enter_text':     'Įveskite tekstą čia',
    'optional_filters':           'Pasirenkami filtrai',
    'col_signal_conditioning':    'Signalo kondicionavimas',
    'col_noise_silence':          'Triukšmas / Tyla',
    'col_zcr_shaping':            'ZCR formavimas',
    'filt_notch':                 '50/60 Hz kerpantis filtras',
    'filt_preemph':               'Iš anksto akcentavimas',
    'filt_decimate':               'Diskretizavimo mažinimas / Decimacija',
    'filt_noisegate':             'Triukšmo vartai',
    'filt_envfollow':             'Apgaubties sekiklis',
    'filt_specsub':               'Spektrinis atėmimas',
    'filt_hwrect':                'Pusbangis lyginimas',
    'filt_schmitt':                'Schmito trigeris',
    'filt_hilbert':                'Hilberto apgaubtis',
    'slider_pulse':                'Impulsas (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Vid: 2-4%\nMaks: 10%\n>6% viršija normą',
    'duty_cycle_label':            'Impulso darbo ciklas',
    'transmitter_freq':            'Dažnis:',
    'transmitter_pwr':             'TX galia:',
    'tx_disabled':                 'TX: IŠJUNGTAS',
    'tx_enabled':                  'TX: ĮJUNGTAS',
    'tx_license':
        'Norint siųsti šiais dažniais, būtina galiojanti radijo mėgėjo '
        'licencija. '
        'Patikrinkite savo šalies dažnių juostų planą.',
    'save_to_disk':                'Įrašyti į diską',
    'save_description':
        'Įrašo neapdorotus IQ pavyzdžius kaip complex64 dvejetainį.\n'
        'Du kanalai: I (realusis) ir Q (menamasis).\n'
        'Suderinama su GNU Radio, inspectrum,\n'
        'GQRX ir SDR# neprisijungus prie tinklo analizei.\n'
        ' \n'
        'Esant 2 MHz diskretizavimo dažniui: apie 16 MB/sek.\n'
        '30 sekundžių įrašas užima apie 480 MB.\n'
        'Prieš ilgus įrašus suplanuokite saugyklos vietą.\n'
        ' \n'
        'Waterfall: trumpalaikis FFT per numpy,\n'
        'atvaizduojamas matplotlib inferno spalvų žemėlapiu.\n'
        'Automatiškai atsidaro sistemos peržiūros priemonėje.',
    'record_iq':                   'Įrašyti IQ',
    'recording':                   'Įrašoma...',
    'waterfall_checkbox':          'Generuoti waterfall vaizdą',
    'event_log':                   'Įvykių žurnalas',
    'event_log_title':             '  OpenV2K  Įvykių žurnalas',
    'no_mbrola_voice':
        'Šiai kalbai nėra prieinamo MBROLA balso -- '
        'vietoj to naudojama eSpeak formantų sintezė.',
},

'uk': {
    'section_audio_input':        'Аудіовхід',
    'section_signal_processing':  'Обробка сигналу',
    'section_output':             'Вихід',
    'live_microphone':            'Мікрофон наживо',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Генератор імпульсів переходу через нуль',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Рівень мікрофона: -45 дБ у тиші, прагніть -18 дБ під час розмови.\n'
        'Налаштуйте: Системні налаштування > Звук > Вхід.',
    'mic_muted':                  'Мік: ВИМКНЕНО',
    'mic_live':                   'Мік: НАЖИВО',
    'generate_voice':             'Створити голос',
    'placeholder_hello':          'Привіт, світ',
    'placeholder_enter_text':     'Введіть текст тут',
    'optional_filters':           'Додаткові фільтри',
    'col_signal_conditioning':    'Кондиціонування сигналу',
    'col_noise_silence':          'Шум / Тиша',
    'col_zcr_shaping':            'Формування ZCR',
    'filt_notch':                 'Режекторний фільтр 50/60 Гц',
    'filt_preemph':               'Попереднє підкреслення',
    'filt_decimate':               'Даунсемплінг / Децимація',
    'filt_noisegate':             'Шумовий затвор',
    'filt_envfollow':             'Стеження за обвідною',
    'filt_specsub':               'Спектральне віднімання',
    'filt_hwrect':                'Однопівперіодне випрямлення',
    'filt_schmitt':                'Тригер Шмітта',
    'filt_hilbert':                'Обвідна Гільберта',
    'slider_pulse':                'Імпульс (мкс)',
    'slider_hpf':                  'ФВЧ (Гц)',
    'slider_lpf':                  'ФНЧ (Гц)',
    'duty_summary':                'Сер: 2-4%\nМакс: 10%\n>6% поза нормою',
    'duty_cycle_label':            'Шпаруватість імпульсу',
    'transmitter_freq':            'Частота:',
    'transmitter_pwr':             'Потужність TX:',
    'tx_disabled':                 'TX: ВИМКНЕНО',
    'tx_enabled':                  'TX: УВІМКНЕНО',
    'tx_license':
        'Для передачі на цих частотах потрібна чинна ліцензія '
        'радіоаматора. '
        'Перевірте свій національний частотний план.',
    'save_to_disk':                'Зберегти на диск',
    'save_description':
        'Зберігає необроблені IQ-семпли у бінарному форматі complex64.\n'
        'Два канали: I (дійсна частина) і Q (уявна частина).\n'
        'Сумісно з GNU Radio, inspectrum,\n'
        'GQRX і SDR# для автономного аналізу.\n'
        ' \n'
        'При частоті дискретизації 2 МГц: близько 16 МБ/с.\n'
        '30-секундний запис займає близько 480 МБ.\n'
        'Плануйте місце на диску перед довгими записами.\n'
        ' \n'
        'Waterfall: короткочасне FFT через numpy,\n'
        'відображено кольоровою картою inferno з matplotlib.\n'
        'Відкривається автоматично в системному переглядачі.',
    'record_iq':                   'Записати IQ',
    'recording':                   'Запис...',
    'waterfall_checkbox':          'Створити зображення waterfall',
    'event_log':                   'Журнал подій',
    'event_log_title':             '  OpenV2K  Журнал подій',
    'no_mbrola_voice':
        'Немає доступного голосу MBROLA для цієї мови -- '
        'натомість використовується формантний синтез eSpeak.',
},

'ca': {
    'section_audio_input':        'Entrada d\'àudio',
    'section_signal_processing':  'Processament de senyal',
    'section_output':             'Sortida',
    'live_microphone':            'Micròfon en directe',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generador de polsos de creuament per zero',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Nivell del micròfon: -45 dB en silenci, apunta a -18 dB en parlar.\n'
        'Ajusta a: Configuració del sistema > So > Entrada.',
    'mic_muted':                  'Mic: SILENCIAT',
    'mic_live':                   'Mic: EN DIRECTE',
    'generate_voice':             'Genera la veu',
    'placeholder_hello':          'Hola Món',
    'placeholder_enter_text':     'Escriu el text aquí',
    'optional_filters':           'Filtres opcionals',
    'col_signal_conditioning':    'Condicionament del senyal',
    'col_noise_silence':          'Soroll / Silenci',
    'col_zcr_shaping':            'Modelatge ZCR',
    'filt_notch':                 'Filtre de rebuig 50/60 Hz',
    'filt_preemph':               'Preèmfasi',
    'filt_decimate':               'Submostreig / Delmació',
    'filt_noisegate':             'Porta de soroll',
    'filt_envfollow':             'Seguidor d\'envolupant',
    'filt_specsub':               'Sostracció espectral',
    'filt_hwrect':                'Rectificació de mitja ona',
    'filt_schmitt':                'Disparador de Schmitt',
    'filt_hilbert':                'Envolupant de Hilbert',
    'slider_pulse':                'Polsos (\u00b5s)',
    'slider_hpf':                  'FPA (Hz)',
    'slider_lpf':                  'FPB (Hz)',
    'duty_summary':                'Mitjana: 2-4%\nMàx: 10%\n>6% fora d\'especificació',
    'duty_cycle_label':            'Cicle de treball del pols',
    'transmitter_freq':            'Freqüència:',
    'transmitter_pwr':             'Potència TX:',
    'tx_disabled':                 'TX: DESACTIVAT',
    'tx_enabled':                  'TX: ACTIVAT',
    'tx_license':
        'Cal una llicència vàlida de radioafeccionat per transmetre en '
        'aquestes freqüències. '
        'Verifiqueu el vostre pla de bandes nacional.',
    'save_to_disk':                'Desa al disc',
    'save_description':
        'Desa mostres IQ en brut com a binari complex64.\n'
        'Dos canals: I (real) i Q (imaginari).\n'
        'Compatible amb GNU Radio, inspectrum,\n'
        'GQRX i SDR# per a anàlisi fora de línia.\n'
        ' \n'
        'A una freqüència de mostreig de 2 MHz: aprox. 16 MB/seg.\n'
        'Una captura de 30 segons utilitza uns 480 MB.\n'
        'Planifiqueu l\'emmagatzematge abans de gravacions llargues.\n'
        ' \n'
        'Waterfall: FFT de curta durada via numpy,\n'
        'representat amb el mapa de color inferno de matplotlib.\n'
        'S\'obre automàticament al visualitzador del sistema.',
    'record_iq':                   'Enregistra IQ',
    'recording':                   'Enregistrant...',
    'waterfall_checkbox':          'Genera imatge waterfall',
    'event_log':                   'Registre d\'esdeveniments',
    'event_log_title':             '  OpenV2K  Registre d\'esdeveniments',
    'no_mbrola_voice':
        'No hi ha cap veu MBROLA disponible per a aquest idioma -- '
        'en el seu lloc s\'utilitza la síntesi de formants d\'eSpeak.',
},

'fi': {
    'section_audio_input':        'Äänen sisääntulo',
    'section_signal_processing':  'Signaalinkäsittely',
    'section_output':             'Ulostulo',
    'live_microphone':            'Suora mikrofoni',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nollanylitys-pulssigeneraattori',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofonin taso: -45 dB hiljaisuudessa, tavoittele -18 dB puhuessa.\n'
        'Säädä: Järjestelmäasetukset > Ääni > Sisääntulo.',
    'mic_muted':                  'Mikki: VAIENNETTU',
    'mic_live':                   'Mikki: SUORA',
    'generate_voice':             'Luo ääni',
    'placeholder_hello':          'Hei maailma',
    'placeholder_enter_text':     'Kirjoita teksti tähän',
    'optional_filters':           'Valinnaiset suodattimet',
    'col_signal_conditioning':    'Signaalin ehdollistus',
    'col_noise_silence':          'Kohina / Hiljaisuus',
    'col_zcr_shaping':            'ZCR-muotoilu',
    'filt_notch':                 '50/60 Hz noodisuodatin',
    'filt_preemph':               'Esikorostus',
    'filt_decimate':               'Alinäytteistys / Desimointi',
    'filt_noisegate':             'Kohinaportti',
    'filt_envfollow':             'Verhokäyrän seuraaja',
    'filt_specsub':               'Spektrivähennys',
    'filt_hwrect':                'Puoliaaltotasasuuntaus',
    'filt_schmitt':                'Schmitt-liipaisin',
    'filt_hilbert':                'Hilbert-verhokäyrä',
    'slider_pulse':                'Pulssi (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Ka: 2-4%\nMaks: 10%\n>6% yli rajan',
    'duty_cycle_label':            'Pulssin täyttösuhde',
    'transmitter_freq':            'Taajuus:',
    'transmitter_pwr':             'TX-teho:',
    'tx_disabled':                 'TX: POIS PÄÄLTÄ',
    'tx_enabled':                  'TX: PÄÄLLÄ',
    'tx_license':
        'Näillä taajuuksilla lähettäminen edellyttää voimassaolevaa '
        'radioamatöörilupaa. '
        'Tarkista kansallinen taajuussuunnitelmasi.',
    'save_to_disk':                'Tallenna levylle',
    'save_description':
        'Tallentaa raa\'at IQ-näytteet complex64-binäärinä.\n'
        'Kaksi kanavaa: I (reaali) ja Q (imaginaari).\n'
        'Yhteensopiva GNU Radion, inspectrumin,\n'
        'GQRX:n ja SDR#:n kanssa offline-analyysiin.\n'
        ' \n'
        '2 MHz näytteenottotaajuudella: noin 16 Mt/s.\n'
        '30 sekunnin tallennus käyttää noin 480 Mt.\n'
        'Suunnittele tallennustila ennen pitkiä tallennuksia.\n'
        ' \n'
        'Waterfall: lyhytaikainen FFT numpyn kautta,\n'
        'renderöity matplotlibin inferno-värikartalla.\n'
        'Avautuu automaattisesti järjestelmän katseluohjelmassa.',
    'record_iq':                   'Tallenna IQ',
    'recording':                   'Tallennetaan...',
    'waterfall_checkbox':          'Luo waterfall-kuva',
    'event_log':                   'Tapahtumaloki',
    'event_log_title':             '  OpenV2K  Tapahtumaloki',
    'no_mbrola_voice':
        'Tälle kielelle ei ole saatavilla MBROLA-ääntä -- '
        'käytetään sen sijaan eSpeakin formanttisynteesiä.',
},

'bg': {
    'section_audio_input':        'Аудио вход',
    'section_signal_processing':  'Обработка на сигнала',
    'section_output':             'Изход',
    'live_microphone':            'Микрофон на живо',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Генератор на импулси при пресичане на нула',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Ниво на микрофона: -45 dB в тишина, стремете се към -18 dB при говор.\n'
        'Настройте в: Системни настройки > Звук > Вход.',
    'mic_muted':                  'Мик: ИЗКЛЮЧЕН ЗВУК',
    'mic_live':                   'Мик: НА ЖИВО',
    'generate_voice':             'Генерирай глас',
    'placeholder_hello':          'Здравей свят',
    'placeholder_enter_text':     'Въведете текст тук',
    'optional_filters':           'Незадължителни филтри',
    'col_signal_conditioning':    'Кондициониране на сигнала',
    'col_noise_silence':          'Шум / Тишина',
    'col_zcr_shaping':            'Оформяне на ZCR',
    'filt_notch':                 'Режекторен филтър 50/60 Hz',
    'filt_preemph':               'Предварително ударение',
    'filt_decimate':               'Намаляване на честотата / Децимация',
    'filt_noisegate':             'Шумов гейт',
    'filt_envfollow':             'Следач на обвивката',
    'filt_specsub':               'Спектрално изваждане',
    'filt_hwrect':                'Еднополупериодно изправяне',
    'filt_schmitt':                'Тригер на Шмит',
    'filt_hilbert':                'Обвивка на Хилберт',
    'slider_pulse':                'Импулс (мкс)',
    'slider_hpf':                  'ФВЧ (Hz)',
    'slider_lpf':                  'ФНЧ (Hz)',
    'duty_summary':                'Средно: 2-4%\nМакс: 10%\n>6% извън нормата',
    'duty_cycle_label':            'Работен цикъл на импулса',
    'transmitter_freq':            'Честота:',
    'transmitter_pwr':             'Мощност TX:',
    'tx_disabled':                 'TX: ИЗКЛЮЧЕН',
    'tx_enabled':                  'TX: ВКЛЮЧЕН',
    'tx_license':
        'За предаване на тези честоти е необходим валиден любителски '
        'радио лиценз. '
        'Проверете националния си честотен план.',
    'save_to_disk':                'Запази на диска',
    'save_description':
        'Запазва необработени IQ проби като бинарен complex64.\n'
        'Два канала: I (реален) и Q (имагинерен).\n'
        'Съвместимо с GNU Radio, inspectrum,\n'
        'GQRX и SDR# за офлайн анализ.\n'
        ' \n'
        'При честота на дискретизация 2 MHz: около 16 MB/сек.\n'
        '30-секунден запис използва около 480 MB.\n'
        'Планирайте съхранението преди дълги записи.\n'
        ' \n'
        'Waterfall: краткотрайно FFT чрез numpy,\n'
        'изобразено с цветовата карта inferno на matplotlib.\n'
        'Отваря се автоматично в системния визуализатор.',
    'record_iq':                   'Запиши IQ',
    'recording':                   'Записва се...',
    'waterfall_checkbox':          'Генерирай изображение waterfall',
    'event_log':                   'Дневник на събитията',
    'event_log_title':             '  OpenV2K  Дневник на събитията',
    'no_mbrola_voice':
        'Няма наличен MBROLA глас за този език -- '
        'вместо това се използва формантен синтез на eSpeak.',
},

'sr': {
    'section_audio_input':        'Аудио улаз',
    'section_signal_processing':  'Обрада сигнала',
    'section_output':             'Излаз',
    'live_microphone':            'Микрофон уживо',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Генератор импулса преласка кроз нулу',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Ниво микрофона: -45 dB у тишини, циљајте -18 dB током говора.\n'
        'Подесите у: Системска подешавања > Звук > Улаз.',
    'mic_muted':                  'Мик: УТИШАН',
    'mic_live':                   'Мик: УЖИВО',
    'generate_voice':             'Генериши глас',
    'placeholder_hello':          'Здраво свете',
    'placeholder_enter_text':     'Унесите текст овде',
    'optional_filters':           'Опциони филтери',
    'col_signal_conditioning':    'Кондиционирање сигнала',
    'col_noise_silence':          'Шум / Тишина',
    'col_zcr_shaping':            'Обликовање ZCR',
    'filt_notch':                 'Режекциони филтер 50/60 Hz',
    'filt_preemph':               'Предакцентовање',
    'filt_decimate':               'Подузорковање / Децимација',
    'filt_noisegate':             'Шумна капија',
    'filt_envfollow':             'Пратилац обвојнице',
    'filt_specsub':               'Спектрално одузимање',
    'filt_hwrect':                'Полуталасно исправљање',
    'filt_schmitt':                'Шмитов окидач',
    'filt_hilbert':                'Хилбертова обвојница',
    'slider_pulse':                'Импулс (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Просек: 2-4%\nМакс: 10%\n>6% изван спецификације',
    'duty_cycle_label':            'Радни циклус импулса',
    'transmitter_freq':            'Фреквенција:',
    'transmitter_pwr':             'TX снага:',
    'tx_disabled':                 'TX: ОНЕМОГУЋЕН',
    'tx_enabled':                  'TX: ОМОГУЋЕН',
    'tx_license':
        'За емитовање на овим фреквенцијама потребна је важећа '
        'аматерска радио дозвола. '
        'Проверите свој национални план опсега.',
    'save_to_disk':                'Сачувај на диск',
    'save_description':
        'Чува сирове IQ узорке као бинарни complex64.\n'
        'Два канала: I (реални) и Q (имагинарни).\n'
        'Компатибилно са GNU Radio, inspectrum,\n'
        'GQRX и SDR# за офлајн анализу.\n'
        ' \n'
        'При брзини узорковања од 2 MHz: око 16 MB/сек.\n'
        '30-секундно снимање користи око 480 MB.\n'
        'Планирајте простор за складиштење пре дугих снимака.\n'
        ' \n'
        'Waterfall: краткотрајни FFT преко numpy,\n'
        'приказан inferno мапом боја из matplotlib.\n'
        'Аутоматски се отвара у системском прегледачу.',
    'record_iq':                   'Сними IQ',
    'recording':                   'Снимање...',
    'waterfall_checkbox':          'Генериши waterfall слику',
    'event_log':                   'Дневник догађаја',
    'event_log_title':             '  OpenV2K  Дневник догађаја',
    'no_mbrola_voice':
        'Нема доступног MBROLA гласа за овај језик -- '
        'уместо тога користи се eSpeak формантна синтеза.',
},

'bs': {
    'section_audio_input':        'Audio ulaz',
    'section_signal_processing':  'Obrada signala',
    'section_output':             'Izlaz',
    'live_microphone':            'Mikrofon uživo',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generator impulsa prelaska kroz nulu',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Nivo mikrofona: -45 dB u tišini, ciljajte -18 dB tokom govora.\n'
        'Podesite u: Sistemske postavke > Zvuk > Ulaz.',
    'mic_muted':                  'Mikrofon: UTIŠAN',
    'mic_live':                   'Mikrofon: UŽIVO',
    'generate_voice':             'Generiši glas',
    'placeholder_hello':          'Zdravo svijete',
    'placeholder_enter_text':     'Unesite tekst ovdje',
    'optional_filters':           'Opcioni filteri',
    'col_signal_conditioning':    'Kondicioniranje signala',
    'col_noise_silence':          'Šum / Tišina',
    'col_zcr_shaping':            'Oblikovanje ZCR',
    'filt_notch':                 'Rezekcioni filter 50/60 Hz',
    'filt_preemph':               'Preakcentovanje',
    'filt_decimate':               'Poduzorkovanje / Decimacija',
    'filt_noisegate':             'Šumna kapija',
    'filt_envfollow':             'Pratilac omotnice',
    'filt_specsub':               'Spektralno oduzimanje',
    'filt_hwrect':                'Poluvalno ispravljanje',
    'filt_schmitt':                'Schmittov okidač',
    'filt_hilbert':                'Hilbertova omotnica',
    'slider_pulse':                'Impuls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Prosjek: 2-4%\nMaks: 10%\n>6% van specifikacije',
    'duty_cycle_label':            'Radni ciklus impulsa',
    'transmitter_freq':            'Frekvencija:',
    'transmitter_pwr':             'TX snaga:',
    'tx_disabled':                 'TX: ONEMOGUĆEN',
    'tx_enabled':                  'TX: OMOGUĆEN',
    'tx_license':
        'Za emitovanje na ovim frekvencijama potrebna je važeća '
        'amaterska radio dozvola. '
        'Provjerite svoj nacionalni plan opsega.',
    'save_to_disk':                'Sačuvaj na disk',
    'save_description':
        'Čuva sirove IQ uzorke kao binarni complex64.\n'
        'Dva kanala: I (realni) i Q (imaginarni).\n'
        'Kompatibilno sa GNU Radio, inspectrum,\n'
        'GQRX i SDR# za offline analizu.\n'
        ' \n'
        'Pri brzini uzorkovanja od 2 MHz: oko 16 MB/sek.\n'
        '30-sekundno snimanje koristi oko 480 MB.\n'
        'Planirajte prostor za pohranu prije dugih snimaka.\n'
        ' \n'
        'Waterfall: kratkotrajni FFT preko numpy,\n'
        'prikazan inferno mapom boja iz matplotlib.\n'
        'Automatski se otvara u sistemskom pregledaču.',
    'record_iq':                   'Snimi IQ',
    'recording':                   'Snimanje...',
    'waterfall_checkbox':          'Generiši waterfall sliku',
    'event_log':                   'Dnevnik događaja',
    'event_log_title':             '  OpenV2K  Dnevnik događaja',
    'no_mbrola_voice':
        'Nema dostupnog MBROLA glasa za ovaj jezik -- '
        'umjesto toga koristi se eSpeak formantna sinteza.',
},

'da': {
    'section_audio_input':        'Lydindgang',
    'section_signal_processing':  'Signalbehandling',
    'section_output':             'Udgang',
    'live_microphone':            'Live mikrofon',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Nulgennemgangs-pulsgenerator',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Mikrofonniveau: -45 dB i stilhed, sigt efter -18 dB når du taler.\n'
        'Juster i: Systemindstillinger > Lyd > Indgang.',
    'mic_muted':                  'Mik: DÆMPET',
    'mic_live':                   'Mik: LIVE',
    'generate_voice':             'Generer stemme',
    'placeholder_hello':          'Hej Verden',
    'placeholder_enter_text':     'Skriv tekst her',
    'optional_filters':           'Valgfrie filtre',
    'col_signal_conditioning':    'Signalkonditionering',
    'col_noise_silence':          'Støj / Stilhed',
    'col_zcr_shaping':            'ZCR-formning',
    'filt_notch':                 '50/60 Hz notch-filter',
    'filt_preemph':               'Pre-emphasis',
    'filt_decimate':               'Downsampling / Decimering',
    'filt_noisegate':             'Støjport',
    'filt_envfollow':             'Envelope-følger',
    'filt_specsub':               'Spektral subtraktion',
    'filt_hwrect':                'Halvbølgeensretning',
    'filt_schmitt':                'Schmitt-trigger',
    'filt_hilbert':                'Hilbert-envelope',
    'slider_pulse':                'Puls (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Gns: 2-4%\nMaks: 10%\n>6% over specifikation',
    'duty_cycle_label':            'Pulsens driftscyklus',
    'transmitter_freq':            'Frekvens:',
    'transmitter_pwr':             'TX-effekt:',
    'tx_disabled':                 'TX: DEAKTIVERET',
    'tx_enabled':                  'TX: AKTIVERET',
    'tx_license':
        'Der kræves en gyldig amatørradiolicens for at sende på disse '
        'frekvenser. '
        'Kontroller din nationale båndplan.',
    'save_to_disk':                'Gem på disk',
    'save_description':
        'Gemmer rå IQ-samples som complex64-binærdata.\n'
        'To kanaler: I (reel) og Q (imaginær).\n'
        'Kompatibel med GNU Radio, inspectrum,\n'
        'GQRX og SDR# til offline-analyse.\n'
        ' \n'
        'Ved 2 MHz samplingsrate: ca. 16 MB/sek.\n'
        'En 30-sekunders optagelse bruger ca. 480 MB.\n'
        'Planlæg lagerplads før lange optagelser.\n'
        ' \n'
        'Waterfall: korttids-FFT via numpy,\n'
        'gengivet med matplotlibs inferno-farvekort.\n'
        'Åbnes automatisk i systemets fremviser.',
    'record_iq':                   'Optag IQ',
    'recording':                   'Optager...',
    'waterfall_checkbox':          'Generer waterfall-billede',
    'event_log':                   'Hændelseslog',
    'event_log_title':             '  OpenV2K  Hændelseslog',
    'no_mbrola_voice':
        'Ingen MBROLA-stemme tilgængelig for dette sprog -- '
        'bruger i stedet eSpeaks formantsyntese.',
},

'sk': {
    'section_audio_input':        'Zvukový vstup',
    'section_signal_processing':  'Spracovanie signálu',
    'section_output':             'Výstup',
    'live_microphone':            'Živý mikrofón',
    'espeak_tts':                 'eSpeak TTS',
    'app_subtitle':                'Generátor impulzov prechodu nulou',
    'mbrola':                     'MBROLA',
    'mic_level_desc':
        'Úroveň mikrofónu: -45 dB v tichu, pri rozprávaní cieľte na -18 dB.\n'
        'Upravte v: Nastavenia systému > Zvuk > Vstup.',
    'mic_muted':                  'Mikrofón: STLMENÝ',
    'mic_live':                   'Mikrofón: NAŽIVO',
    'generate_voice':             'Generovať hlas',
    'placeholder_hello':          'Ahoj svet',
    'placeholder_enter_text':     'Sem napíšte text',
    'optional_filters':           'Voliteľné filtre',
    'col_signal_conditioning':    'Úprava signálu',
    'col_noise_silence':          'Šum / Ticho',
    'col_zcr_shaping':            'Tvarovanie ZCR',
    'filt_notch':                 'Pásmová zádrž 50/60 Hz',
    'filt_preemph':               'Preemfáza',
    'filt_decimate':               'Podvzorkovanie / Decimácia',
    'filt_noisegate':             'Šumová brána',
    'filt_envfollow':             'Sledovač obálky',
    'filt_specsub':               'Spektrálne odčítanie',
    'filt_hwrect':                'Jednocestné usmernenie',
    'filt_schmitt':                'Schmittov klopný obvod',
    'filt_hilbert':                'Hilbertova obálka',
    'slider_pulse':                'Impulz (\u00b5s)',
    'slider_hpf':                  'HPF (Hz)',
    'slider_lpf':                  'LPF (Hz)',
    'duty_summary':                'Priemer: 2-4%\nMax: 10%\n>6% mimo špecifikácie',
    'duty_cycle_label':            'Strieda impulzu',
    'transmitter_freq':            'Frekvencia:',
    'transmitter_pwr':             'Výkon TX:',
    'tx_disabled':                 'TX: VYPNUTÉ',
    'tx_enabled':                  'TX: ZAPNUTÉ',
    'tx_license':
        'Na vysielanie na týchto frekvenciách je potrebná platná '
        'rádioamatérska licencia. '
        'Skontrolujte svoj národný pásmový plán.',
    'save_to_disk':                'Uložiť na disk',
    'save_description':
        'Ukladá surové IQ vzorky ako binárny complex64.\n'
        'Dva kanály: I (reálny) a Q (imaginárny).\n'
        'Kompatibilné s GNU Radio, inspectrum,\n'
        'GQRX a SDR# pre offline analýzu.\n'
        ' \n'
        'Pri vzorkovacej frekvencii 2 MHz: cca 16 MB/s.\n'
        '30-sekundový záznam zaberie približne 480 MB.\n'
        'Pred dlhým nahrávaním naplánujte úložný priestor.\n'
        ' \n'
        'Waterfall: krátkodobá FFT cez numpy,\n'
        'vykreslená farebnou mapou inferno z matplotlib.\n'
        'Automaticky sa otvorí v systémovom prehliadači.',
    'record_iq':                   'Nahrať IQ',
    'recording':                   'Nahrávanie...',
    'waterfall_checkbox':          'Vygenerovať obrázok waterfall',
    'event_log':                   'Denník udalostí',
    'event_log_title':             '  OpenV2K  Denník udalostí',
    'no_mbrola_voice':
        'Pre tento jazyk nie je k dispozícii žiadny hlas MBROLA -- '
        'namiesto toho sa používa formantová syntéza eSpeak.',
},


}


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
_MBROLA_VOICE_MAP = {
    'en': 'en1',
    'de': 'de6',
    'fr': 'fr4',
    'es': 'es1',
    'it': 'it4',
    'pt': 'pt1',
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

    # MBROLA (optional) -- reports on the voice matching the detected locale
    if _LOCALE_MBROLA_OK:
        print("{}mbrola + {}  (MBROLA synthesis, locale={})".format(
            OK, _LOCALE_MBROLA_CODE, _CURRENT_LANG))
    elif _LOCALE_MBROLA_CODE:
        print("{}mbrola-{}  ->  sudo apt install mbrola mbrola-{}".format(
            WARN, _LOCALE_MBROLA_CODE, _LOCALE_MBROLA_CODE))
    else:
        print("{}no packaged MBROLA voice for locale '{}' -- "
              "using eSpeak formant synthesis".format(WARN, _CURRENT_LANG))

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
            # Wiener gain: 0 at noise floor, approaches 1 as signal >> noise
            snr  = env / (noise + 1e-10)
            gain = max(0.2, snr / (snr + 1.0))   # floor at 0.2, never full silence
            out[i] = s * gain
        self._env, self._noise = env, noise
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
    BTN_H              = 58
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
        # DEVELOPER: update the date string below at the start of every new
        # development session before saving a new version.  Format: YYYY/M/D
        self.setWindowTitle("OpenV2K (2026/8/12 - Version 75)")
        self.setFixedWidth(580)

        self._hackrf_found, self._hackrf_info = detect_hackrf()
        self._write_silence_wav(self.ESPEAK_WAV)

        self._pulse_us           = 100.0
        self._hpf_hz             = 150.0
        self._lpf_hz             = 2200.0
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

        # Signal Conditioning: notch and pre-emph OFF by default.
        # Pre-emph H(z)=1-0.9375z^-1 attenuates 180Hz to ~7.5% -- too low
        # for pitch=20 MBROLA speech to cross the Schmitt hi threshold.
        # Notch IIR (Q=30) can also cause similar suppression near its poles.
        self._chk_notch.setChecked(False)
        self._chk_preemph.setChecked(False)
        self._chk_decimator.setChecked(True)
        self._chk_noisegate.setChecked(True)
        self._chk_env_follow.setChecked(True)
        self._chk_spectral_sub.setChecked(True)
        self._chk_hwrect.setChecked(True)
        self._chk_schmitt.setChecked(True)
        self._chk_hilbert_env.setChecked(False)  # OFF -- mutually exclusive with Schmitt

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
        return (
            "MBROLA: Concatenative diphone synthesis.\n"
            "Uses recorded phoneme segments instead of\n"
            "eSpeak formant synthesis, producing more\n"
            "natural speech with lower zero-crossing rate\n"
            "and a duty cycle closer to human voice.\n"
            "\n"
            "Status: {}".format(status))

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
        self._retranslate_ui()
        self._log("Language switched: {}".format(_LANG_NAMES.get(code, code)))

    def _retranslate_ui(self):
        """
        Update every translatable widget's displayed text in place after a
        language switch.  GNU Radio blocks and their connections are
        completely unaffected -- this only touches Qt widget text/tooltip
        properties, so it's safe to call at any time, including mid-session.
        """
        # Title row
        self._log_btn.setText(_tr("event_log"))
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
        for h, key in self._opt_col_headers:
            h.setText(_tr(key))
        self._chk_notch.setText(_tr("filt_notch"))
        self._chk_preemph.setText(_tr("filt_preemph"))
        self._chk_decimator.setText(_tr("filt_decimate"))
        self._chk_noisegate.setText(_tr("filt_noisegate"))
        self._chk_env_follow.setText(_tr("filt_envfollow"))
        self._chk_spectral_sub.setText(_tr("filt_specsub"))
        self._chk_hwrect.setText(_tr("filt_hwrect"))
        self._chk_schmitt.setText(_tr("filt_schmitt"))
        self._chk_hilbert_env.setText(_tr("filt_hilbert"))
        self._duty_summary_lbl.setText(_tr("duty_summary"))
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

        # Language selector combobox -- top-left, above the Event Log button.
        # Sorted by native name so each language is easy to find by eye.
        self._lang_combo = QtWidgets.QComboBox()
        self._lang_combo.setStyleSheet(
            "QComboBox { font-size:8pt; padding:2px 4px; }")
        for code in sorted(_LANG_NAMES, key=lambda c: _LANG_NAMES[c]):
            display = "{}  ({})".format(_LANG_NAMES[code], _LANG_NAMES_EN[code])
            self._lang_combo.addItem(display, code)
        _cur_idx = self._lang_combo.findData(_CURRENT_LANG)
        if _cur_idx >= 0:
            self._lang_combo.setCurrentIndex(_cur_idx)
        self._lang_combo.currentIndexChanged.connect(self._cb_language_changed)

        # "Event Log" button -- rounded, blue, top-left corner
        self._log_btn = QtWidgets.QPushButton(_tr("event_log"))
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

        # Stack combobox above the Event Log button, 6px gap between them
        log_col = QtWidgets.QVBoxLayout()
        log_col.setContentsMargins(0,0,0,0); log_col.setSpacing(6)
        log_col.addWidget(self._lang_combo)
        log_col.addWidget(self._log_btn)
        tr.addLayout(log_col)

        # OpenV2K clickable title (centred in remaining space)
        self._title_lbl = QtWidgets.QLabel(
            "<h3 style='margin:0;'>"
            "<a href='https://github.com/OpenV2K'"
            " style='color:#2a6ebb; text-decoration:none;'>OpenV2K</a>"
            "</h3><small>{}</small>".format(_tr("app_subtitle")))
        title = self._title_lbl
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setOpenExternalLinks(True)
        # Word-wrap so longer translated subtitles wrap to a second line
        # instead of expanding the title row width in the fixed-width window.
        title.setWordWrap(True)
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
        self._hdr_audio = SectionHeader(_tr("section_audio_input"))
        vbox.addWidget(self._hdr_audio)
        vbox.addSpacing(2)
        audio_row = QtWidgets.QHBoxLayout(); audio_row.setSpacing(0)

        self._mic_panel = QtWidgets.QWidget()
        self._mic_panel.setAutoFillBackground(True)
        mic_vbox = QtWidgets.QVBoxLayout(self._mic_panel)
        mic_vbox.setContentsMargins(0,4,4,4); mic_vbox.setSpacing(2)

        # Header row: "Live Microphone" label + live dB readout on the same line
        mic_hdr_row = QtWidgets.QHBoxLayout()
        mic_hdr_row.setContentsMargins(0,0,0,0); mic_hdr_row.setSpacing(4)
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
        es_vbox.addWidget(self._espeak_input)
        es_vbox.addSpacing(8)

        self._btn_generate = QtWidgets.QPushButton(_tr("generate_voice"))
        self._btn_generate.setMinimumHeight(self.BTN_H)
        self._btn_generate.setStyleSheet(self._style_green())
        self._btn_generate.clicked.connect(self._cb_generate_espeak)
        # Wire Enter key: store button reference in the input widget property
        self._espeak_input.setProperty("generate_btn", self._btn_generate)
        es_vbox.addWidget(self._btn_generate)

        self._espeak_status = QtWidgets.QLabel("")   # kept as attribute, not shown
        es_vbox.addStretch()
        audio_row.addWidget(self._es_panel, 1)
        vbox.addLayout(audio_row)
        vbox.addSpacing(2)

        # =====================================================================
        # Signal Processing
        # =====================================================================
        self._hdr_sigproc = SectionHeader(_tr("section_signal_processing"))
        vbox.addWidget(self._hdr_sigproc)

        sp_row = QtWidgets.QHBoxLayout()
        sp_row.setSpacing(0); sp_row.setContentsMargins(0,0,0,0)

        left_sp = QtWidgets.QWidget()
        left_vbox = QtWidgets.QVBoxLayout(left_sp)
        left_vbox.setContentsMargins(0,8,10,8); left_vbox.setSpacing(4)

        left_vbox.addSpacing(5)   # sliders sit 5px lower than section header
        self._sl_pulse = LabelledSlider(_tr("slider_pulse"), 25, 150, 5, self._pulse_us,
            fmt="{:.0f} \u00b5s", callback=self._cb_pulse, tick_steps=5)
        left_vbox.addWidget(self._sl_pulse)
        self._sl_hpf = LabelledSlider(_tr("slider_hpf"), 100, 300, 10, self._hpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_hpf, tick_steps=5)
        left_vbox.addWidget(self._sl_hpf)
        self._sl_lpf = LabelledSlider(_tr("slider_lpf"), 100, 3000, 100, self._lpf_hz,
            fmt="{:.0f} Hz", callback=self._cb_lpf, tick_steps=5)
        left_vbox.addWidget(self._sl_lpf)

        self._opt_box = QtWidgets.QGroupBox(_tr("optional_filters"))
        opt_box = self._opt_box
        opt_box.setStyleSheet(
            "QGroupBox { font-size:9pt; } QCheckBox { font-size:9pt; }"
            "QLabel#hdr { font-size:8pt; font-weight:bold; color:#2a6ebb;"
            " padding-bottom:2px; }")
        opt_layout = QtWidgets.QGridLayout(); opt_layout.setSpacing(3)
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
        self._chk_notch.setToolTip(
            "Narrow biquad notch filter (Q=30) targeting 50 or 60Hz mains hum\n"
            "and its harmonics.  Compatible with all other filters.")
        self._chk_notch.toggled.connect(self._toggle_notch)
        opt_layout.addWidget(self._chk_notch, 1, 0)

        self._chk_preemph = QtWidgets.QCheckBox(_tr("filt_preemph"))
        self._chk_preemph.setToolTip(
            "+6 dB/octave boost above 1kHz via FIR [1, -0.9375].\n"
            "Sharpens consonants and sibilants.  Compatible with all filters.")
        self._chk_preemph.toggled.connect(self._toggle_preemph)
        opt_layout.addWidget(self._chk_preemph, 2, 0)

        self._chk_decimator = QtWidgets.QCheckBox(_tr("filt_decimate"))
        self._chk_decimator.setToolTip(
            "4kHz IIR anti-alias lowpass before ZCP.  Equivalent to soft\n"
            "decimation from 48kHz to 8kHz -- removes high-harmonic content\n"
            "that generates the most spurious zero crossings.\n"
            "Compatible with all filters.")
        self._chk_decimator.toggled.connect(self._toggle_decimator)
        opt_layout.addWidget(self._chk_decimator, 3, 0)

        # -- Column 1: Noise / Silence Gating -----------------------------
        self._chk_noisegate = QtWidgets.QCheckBox(_tr("filt_noisegate"))
        self._chk_noisegate.setToolTip(
            "Zeros audio when instantaneous RMS power falls below -30dB.\n"
            "Prevents noise and pauses from generating spurious zero crossings.\n"
            "Use with Envelope Follower or Spectral Subtraction, not all three.")
        self._chk_noisegate.toggled.connect(self._toggle_noisegate)
        opt_layout.addWidget(self._chk_noisegate, 1, 1)

        self._chk_env_follow = QtWidgets.QCheckBox(_tr("filt_envfollow"))
        self._chk_env_follow.setToolTip(
            "5ms IIR envelope gate: passes signal above threshold, zeros below.\n"
            "Smoother than Noise Gate -- better preserves phoneme transitions.\n"
            "Use with Noise Gate or Spectral Subtraction, not all three.")
        self._chk_env_follow.toggled.connect(self._toggle_env_follow)
        opt_layout.addWidget(self._chk_env_follow, 2, 1)

        self._chk_spectral_sub = QtWidgets.QCheckBox(_tr("filt_specsub"))
        self._chk_spectral_sub.setToolTip(
            "Estimates noise floor during quiet periods and applies a\n"
            "Wiener gain (floor 0.2) -- suppresses noise-floor ZCR without\n"
            "fully silencing weak phonemes.\n"
            "Compatible with all filters.")
        self._chk_spectral_sub.toggled.connect(self._toggle_spectral_sub)
        opt_layout.addWidget(self._chk_spectral_sub, 3, 1)

        # -- Column 2: ZCR Shaping -----------------------------------------
        # NOTE: Schmitt and Hilbert Envelope are mutually exclusive.
        # Schmitt outputs constant-amplitude (+/-0.5) -- HilbertEnv would then
        # see a flat envelope and produce zero output.  Choosing one
        # auto-unchecks the other.
        self._chk_hwrect = QtWidgets.QCheckBox(_tr("filt_hwrect"))
        self._chk_hwrect.setToolTip(
            "Replaces negatives with -0.05 so only positive-lobe boundaries\n"
            "produce zero crossings.  The -0.05 bias sits below the Schmitt\n"
            "lo threshold (-0.01) so the Schmitt resets between each lobe.\n"
            "Compatible with all filters in this column.")
        self._chk_hwrect.toggled.connect(self._toggle_hwrect)
        opt_layout.addWidget(self._chk_hwrect, 1, 2)

        self._chk_schmitt = QtWidgets.QCheckBox(_tr("filt_schmitt"))
        self._chk_schmitt.setToolTip(
            "Hysteresis: snaps output to +/-0.5 at +/-0.01 thresholds.\n"
            "Eliminates noise jitter near zero -- ZCP fires on decisive\n"
            "threshold crossings only.\n"
            "\n"
            "MUTUALLY EXCLUSIVE with Hilbert Envelope:\n"
            "Schmitt outputs constant amplitude, leaving Hilbert nothing to\n"
            "track.  Selecting this unchecks Hilbert Envelope.")
        self._chk_schmitt.toggled.connect(self._cb_schmitt_toggled)
        opt_layout.addWidget(self._chk_schmitt, 2, 2)

        self._chk_hilbert_env = QtWidgets.QCheckBox(_tr("filt_hilbert"))
        self._chk_hilbert_env.setToolTip(
            "Replaces audio with (envelope - slow_mean): positive during\n"
            "active speech, negative during pauses.  ZCP fires at syllable\n"
            "onset/offset -- very few, rhythmically meaningful pulses.\n"
            "\n"
            "MUTUALLY EXCLUSIVE with Schmitt Trigger:\n"
            "Schmitt outputs constant amplitude, leaving Hilbert nothing to\n"
            "track.  Selecting this unchecks Schmitt Trigger.\n"
            "Also: with Hilbert active, duty-cycle meter reads near-zero\n"
            "(by design -- syllable rate = 2-10 Hz).")
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
        self._duty_summary_lbl = QtWidgets.QLabel(_tr("duty_summary"))
        summary = self._duty_summary_lbl
        summary.setFont(QtGui.QFont("Monospace",7))
        summary.setStyleSheet("color:#777;")
        summary.setAlignment(QtCore.Qt.AlignCenter); summary.setWordWrap(False)
        dc_vbox.addWidget(summary); dc_vbox.addSpacing(4)
        self._duty_cycle_lbl = QtWidgets.QLabel(_tr("duty_cycle_label"))
        dc_lbl = self._duty_cycle_lbl
        font_dc = QtGui.QFont("Monospace",7); font_dc.setBold(True)
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
        tx_vbox.addSpacing(10)   # dropdowns + description 10px lower

        # Frequency and TX Power side by side -- now above the description
        combos_row = QtWidgets.QHBoxLayout()
        combos_row.setSpacing(12)

        freq_col = QtWidgets.QVBoxLayout(); freq_col.setSpacing(2)
        self._freq_lbl = QtWidgets.QLabel(_tr("transmitter_freq"))
        freq_lbl = self._freq_lbl
        freq_lbl.setStyleSheet("font-size:9pt; color:#777;")
        freq_col.addWidget(freq_lbl)
        self._freq_combo = QtWidgets.QComboBox()
        self._freq_combo.addItem("425 MHz  (70cm)", self.FREQ_70CM)
        self._freq_combo.addItem("1300 MHz (23cm)", self.FREQ_23CM)
        self._freq_combo.setCurrentIndex(1)
        self._freq_combo.currentIndexChanged.connect(self._cb_freq_combo)
        freq_col.addWidget(self._freq_combo)
        combos_row.addLayout(freq_col)

        pwr_col = QtWidgets.QVBoxLayout(); pwr_col.setSpacing(2)
        self._pwr_lbl = QtWidgets.QLabel(_tr("transmitter_pwr"))
        pwr_lbl = self._pwr_lbl
        pwr_lbl.setStyleSheet("font-size:9pt; color:#777;")
        pwr_col.addWidget(pwr_lbl)
        self._pwr_combo = QtWidgets.QComboBox()
        self._pwr_combo.addItem("1 mW", self.AMP_1MW)
        self._pwr_combo.addItem("2 mW", self.AMP_2MW)
        self._pwr_combo.currentIndexChanged.connect(self._cb_pwr_combo)
        pwr_col.addWidget(self._pwr_combo)
        combos_row.addLayout(pwr_col)

        tx_vbox.addLayout(combos_row)

        # Description text -- sits slightly below the dropdowns
        tx_vbox.addSpacing(8)
        self._lic_lbl = QtWidgets.QLabel(
            "<a href='https://en.wikipedia.org/wiki/"
            "Amateur_radio_frequency_allocations#ITU_Region_2'"
            " style='color:#555; text-decoration:none;'>"
            "<b>{}</b></a>".format(_tr("tx_license")))
        lic_lbl = self._lic_lbl
        lic_lbl.setOpenExternalLinks(True)
        lic_lbl.setStyleSheet("font-size:10px;")
        lic_lbl.setWordWrap(True)
        tx_vbox.addWidget(lic_lbl)

        # Stretch pushes TX button to the bottom to align with Record IQ
        tx_vbox.addStretch(1)
        tx_vbox.addSpacing(8)
        self._btn_tx = QtWidgets.QPushButton(_tr("tx_disabled"))
        self._btn_tx.setCheckable(True); self._btn_tx.setChecked(True)
        self._btn_tx.setMinimumHeight(self.BTN_H)
        self._btn_tx.setStyleSheet(self._style_red())
        self._btn_tx.toggled.connect(self._cb_tx_toggle)
        tx_vbox.addWidget(self._btn_tx)
        # Space below TX button = checkbox height (~22px) + margin delta (1px)
        # so TX button top aligns with Record IQ button top across the swap panels
        tx_vbox.addSpacing(23)
        output_row.addWidget(self._tx_panel, 1)

        out_swap = SwapButton(parent=self)
        out_swap.clicked.connect(self._cb_output_swap)
        output_row.addWidget(out_swap)

        self._save_panel = QtWidgets.QWidget()
        self._save_panel.setAutoFillBackground(True)
        self._save_panel.setMinimumHeight(240)
        save_vbox = QtWidgets.QVBoxLayout(self._save_panel)
        save_vbox.setContentsMargins(4,4,0,5); save_vbox.setSpacing(4)

        self._save_hdr_lbl = QtWidgets.QLabel(_tr("save_to_disk"))
        save_hdr = self._save_hdr_lbl
        save_hdr.setStyleSheet("font-weight:bold; color:black;")
        self._keep_black(save_hdr)
        save_vbox.addWidget(save_hdr)

        self._save_path_lbl = QtWidgets.QLabel(_tr("save_description"))
        self._save_path_lbl.setStyleSheet(
            "color:#777; font-size:11px; margin-left:10px; margin-top:5px;")
        self._save_path_lbl.setWordWrap(True)
        self._save_path_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        save_vbox.addWidget(self._save_path_lbl)
        save_vbox.addStretch(1)
        save_vbox.addSpacing(8)

        self._btn_record = QtWidgets.QPushButton(_tr("record_iq"))
        self._btn_record.setCheckable(True); self._btn_record.setChecked(False)
        self._btn_record.setMinimumHeight(self.BTN_H)
        self._btn_record.setStyleSheet(self._style_green())
        self._btn_record.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._btn_record.toggled.connect(self._cb_record_toggle)
        save_vbox.addWidget(self._btn_record)

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
        self.dc_blocker  = gr_filter.iir_filter_ffd([1.0,-1.0],[-0.999],True)
        _f0=60.0; _Q=30.0
        _w0=2.0*math.pi*_f0/float(sr); _al=math.sin(_w0)/(2.0*_Q)
        _cw=math.cos(_w0); _a0=1.0+_al
        self._notch_b=[1.0/_a0,-2.0*_cw/_a0,1.0/_a0]
        self._notch_a=[-2.0*_cw/_a0,(1.0-_al)/_a0]
        self.notch      = gr_filter.iir_filter_ffd([1.0],[0.0],True)
        self.pre_emph   = gr_filter.fir_filter_fff(1,[1.0])
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
        self.connect(self.lpf,        self.pre_emph)
        self.connect(self.pre_emph,   self.agc)
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
        self._dc_vbar.setValue(int(min(1000,max(0,dc*100))))
        self._dc_readout.setText("{:4.1f}%".format(max(0.0,dc)))

    # =========================================================================
    #  Callbacks
    # =========================================================================

    def _cb_pulse(self, v):
        self._pulse_us = v; self.zcp.set_pulse_width_us(v)
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
        # Bypass: b=[1], a=[1] (identity).  Active: notch coefficients.
        # Old bypass used a=[0.0] which makes the IIR denominator 0 -- NaN.
        self.notch.set_taps(self._notch_b if e else [1.0],
                            self._notch_a if e else [1.0])
        self._log("Filter {} -- 50/60 Hz Notch".format(
            "ON" if e else "off"))

    def _toggle_preemph(self, e):
        # [1, -0.9375] attenuates 180 Hz to ~7.5% -- too low for pitch=20.
        # Use [1, -0.5] instead: 180 Hz -> ~50%, keeps speech above Schmitt.
        self.pre_emph.set_taps([1.0, -0.5] if e else [1.0])
        self._log("Filter {} -- Pre-emphasis".format("ON" if e else "off"))

    def _toggle_noisegate(self, e):
        self.noise_gate.set_enabled(e)
        self._log("Filter {} -- Noise Gate".format("ON" if e else "off"))

    def _toggle_env_follow(self, e):
        self.env_follower.set_enabled(e)
        self._log("Filter {} -- Envelope Follower".format("ON" if e else "off"))

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
            self.mic_gate.set_k(1.0); self.espeak_gate.set_k(0.0)
            self._btn_mute.setChecked(True)
            self._btn_mute.setText(_tr("mic_muted"))
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
            self._btn_tx.setText(_tr("tx_disabled"))
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

    def _quit(sig=None,frame=None):
        tb.stop(); tb.wait(); app.quit()

    signal.signal(signal.SIGINT,  _quit)
    signal.signal(signal.SIGTERM, _quit)
    tick = QtCore.QTimer(); tick.start(200)
    tick.timeout.connect(lambda: None)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
