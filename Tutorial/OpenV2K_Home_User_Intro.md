# Home Users: Insights Into Audio-Driven Pulse Modulation

OpenV2K is an open-source software application that converts arbitrary audio — including natural speech — into a pulse-modulated radio-frequency (RF) waveform, generated and analyzed through a software-defined radio (SDR) signal chain. The project's signal design is directly inspired by the historical microwave-auditory-effect (MAE) literature, most notably Sharp and Grove's 1975 demonstration that appropriately pulse-modulated microwave energy could convey intelligible words, building on Frey's earlier characterization of the effect. OpenV2K is a signal-generation and waveform-design tool, not a validated bioeffects exposure system.

## Five Disciplines, One Codebase

No single academic background covers everything happening under the hood. Each specialty below would recognize its own piece:

- **Computer Science / Software Engineering** — a full PyQt5 app: custom `QPainter` widgets, threaded audio, and every DSP stage implemented as its own `gr.sync_block` Python subclass.
- **Electrical Engineering — DSP / Signals & Systems** — a toggleable signal-conditioning chain: a from-scratch direct-form biquad notch filter and DC blocker, Wiener-style spectral subtraction, envelope following, and Schmitt-trigger/Hilbert-envelope zero-crossing shaping, each independently switchable with live duty-cycle telemetry.
- **Electrical Engineering — RF / Communications** — the GNU Radio flowgraph itself: IQ signal representation, a rational resampler bridging 48kHz audio to 2MHz complex baseband, and HackRF SDR configured within amateur-band, license-gated power limits.
- **Linguistics / Computational Linguistics** — integrated eSpeak NG (formant synthesis) and MBROLA (diphone/concatenative synthesis) across 49 languages, with phonetics-aware stages (fricative suppression, F1 bandpass) rather than generic audio filters.
- **Graphic / UI Design** — real-time segmented duty-cycle meters, an animated pulse-trace header, and the waterfall/spectrogram visualization used to inspect the pulse train directly.

## What This Actually Is, For a Home User

For nearly everyone running this — which is exactly how it's meant to be used — OpenV2K is a thought experiment, not a demonstration. Generate a pulse train from spoken audio, open the resulting spectrogram, and look at it: a clean, structured, audio-timed pulse pattern, visibly distinct. No SDR needs to be attached for this to be worth doing. The exercise is to look at that pattern and reason, about what pulse-modulated microwave energy carrying that same structure would represent.  
Consider the [historical precedent of Sharp and Grove's 1975 feat](https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques).  
  
**Reproducing the actual microwave-auditory effect requires power levels, exposure control, dosimetry, and safety oversight this software does not provide and was never designed to provide.** That work belongs at PhD-staffed microwave exposure facilities with the instrumentation and institutional review to do it responsibly — not on a home bench. OpenV2K's contribution stops at the waveform: a legitimate, inspectable, open-source answer to "what would the signal look like,".
