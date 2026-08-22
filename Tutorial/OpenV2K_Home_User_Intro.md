# Home Users: Insights in Audio-Driven Pulse Modulation

OpenV2K is an open-source software application that converts arbitrary audio — including natural speech — into a pulse-modulated radio-frequency (RF) waveform, generated and analyzed through a software-defined radio (SDR) signal chain. The project's signal design is directly inspired by the historical microwave-auditory-effect (MAE) literature, most [notably Sharp and Grove's 1975 demonstration](https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques) that appropriately pulse-modulated microwave energy could convey intelligible words, building on Frey's earlier characterization of the effect. **OpenV2K is a signal-generation and waveform-design tool**, not a bioeffects exposure system.  

## What This Actually Is, For a Home User

For nearly everyone running this — which is exactly how it's meant to be used — OpenV2K is a thought experiment, not a demonstration. Generate a pulse burst from spoken audio, open the resulting spectrogram, and look at it: a clean, structured, audio-timed pulse pattern, visibly distinct. **No SDR needs to be attached** for this to be worth doing. The exercise is to look at that pattern and reason, about what pulse-modulated microwave energy carrying that same structure would represent.  
Reflect on the [historical precedent of Sharp and Grove's 1975 feat](https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques), while using this software at home.  
  
**Reproducing the microwave-auditory effect requires kiloWatt power levels, exposure control, dosimetry, and safety oversight.** That work belongs at PhD-staffed microwave exposure facilities with the instrumentation and institutional review to do it responsibly. OpenV2K's contribution stops at the waveform: a legitimate, inspectable, open-source answer to "what would the signal look like".  
  
## Five Disciplines, One Codebase

No single academic background covers everything happening under the hood.  
Each specialty below would recognize its own piece (*notice how psychology isn't included, reddit toolsheds?*):

- **Computer Science / Software Engineering** — a full PyQt5 app: custom `QPainter`-based widgets, threaded audio playback, and every DSP stage implemented as its own `gr.sync_block` Python subclass.
- **Electrical Engineering — DSP / Signals & Systems** — a toggleable signal-conditioning chain: a from-scratch direct-form biquad notch filter and DC blocker, Wiener-style spectral subtraction, envelope following, and Schmitt-trigger/Hilbert-envelope zero-crossing shaping, each independently switchable with live duty-cycle telemetry.
- **Electrical Engineering — RF / Communications** — the GNU Radio flowgraph: IQ signal representation, a rational resampler bridging 48kHz audio to 2MHz complex baseband, and HackRF SDR config within amateur-band, license-gated power limits.
- **Linguistics / Computational Linguistics** — integrated eSpeak NG (formant synthesis) and MBROLA (diphone/concatenative synthesis) across 49 languages, with phonetics-aware stages (fricative suppression, F1 bandpass) rather than generic audio filters.
- **Graphic / UI Design** — real-time segmented duty-cycle meters, an animated pulse-trace header, and the waterfall/spectrogram visualization used to inspect the pulse train directly.
