# OpenV2K

*An Open-Source, Software-Defined Platform for Audio-Driven Pulse-Modulated RF Waveform Generation*

Project Summary — Prepared for Academic Review

## Overview

OpenV2K is an open-source software application that converts arbitrary audio — including natural speech — into a pulse-modulated radio-frequency (RF) waveform, transmitted via a software-defined radio (SDR). The project's signal design is directly inspired by the historical microwave-auditory-effect (MAE) literature, most notably Sharp and Grove's 1975 demonstration that appropriately pulse-modulated microwave energy could convey intelligible words, building on Frey's earlier characterization of the effect. OpenV2K is a **signal-generation and waveform-design tool**, not a validated bioeffects exposure system — that distinction, and its implications, are addressed directly in the *Hardware, Power, and Regulatory Scope* section below.

The application is built on **GNU Radio** for its real-time DSP signal chain, **HackRF One** as its SDR front end, and a **PyQt5** graphical interface for real-time parametric control. The complete source is publicly available on GitHub at [https://github.com/OpenV2K](https://github.com/OpenV2K).

## Pulse Modulation Architecture — The Core Contribution

The feature most directly relevant to pulsed-microwave bioeffects research is OpenV2K's **zero-crossing pulse generator**: rather than producing a fixed-rate pulse train (a simple PRF generator), the software derives pulse *timing* directly from the zero-crossings of a processed audio signal. The result is an RF pulse train whose temporal structure carries the information content of the source audio — conceptually the same audio-to-pulse-timing transduction problem addressed in the original MAE intelligibility work, implemented here as a real-time, fully reconfigurable software pipeline rather than fixed hardware.

### Key parameters exposed for experimental control

- **Pulse width** — continuously adjustable from 25–150µs. Pulse width is a well-established salient parameter in the RF-hearing literature, and OpenV2K exposes it as a live, first-class control rather than a fixed hardware constant.
- **Carrier frequency** — independently tunable via the SDR across amateur-band allocations, decoupled from the pulse-modulation pattern, allowing carrier frequency and pulse structure to be varied as separate experimental variables.
- **Duty cycle** — not fixed, but an emergent property of the source audio and the active signal-conditioning stages (below); a real-time segmented duty-cycle meter provides live telemetry, directly relevant to average-power and thermal-load considerations in pulsed-RF exposure design.
- **Pulse edge shape** — the resampling stage that upsamples the pulse train to RF bandwidth deliberately uses a boxcar (rectangular) reconstruction filter rather than a smoothed windowed-sinc filter, preserving sharp pulse edges through to the RF front end rather than allowing them to round off — a deliberate design choice to keep pulse rise-time characteristics intact.

## Signal Conditioning Pipeline

Between the raw audio source and the pulse generator, OpenV2K implements a cascade of independently togglable DSP stages, each of which reshapes which acoustic-phonetic features of the source audio actually drive pulse generation. This gives a researcher fine-grained control over which components of speech (e.g., voiced vs. unvoiced content, specific formant bands, transient bursts) are translated into the RF pulse pattern, rather than treating the audio-to-pulse transduction as a black box:

- DC blocking and 50/60Hz mains-hum rejection (adaptive, auto-enabled for live-microphone input only)
- Pre-/de-emphasis (selectable spectral tilt)
- Fricative suppression, using local zero-crossing-rate estimation as a voicing detector
- First-formant (F1) bandpass isolation (~300–900Hz)
- Noise gating, envelope following, and Wiener-style spectral subtraction (mutually exclusive, to avoid over-processing)
- Half-wave rectification, Schmitt-trigger hysteresis, and Hilbert-envelope extraction as alternative zero-crossing shaping strategies

Each stage's effect on the resulting pulse train is immediately visible in the application's live duty-cycle telemetry and can be captured for offline analysis (below), making the pipeline suitable for systematic, parametric study of how specific acoustic features map onto RF pulse structure.

## Data Provenance and Validation Tooling

Recognizing that credible use in a research context depends on being able to verify exactly what was transmitted, OpenV2K includes:

- Raw IQ recording to disk as complex64 binary, compatible with GNU Radio, inspectrum, GQRX, and SDR# for independent offline analysis.
- Automatic spectrogram (waterfall) generation from recorded IQ data, with threshold-based active-region detection.
- A built-in checksum/validation check that compares the detected active-pulse-region duration against the source audio's own measured active duration, logged automatically to an event log — a lightweight but genuine data-integrity safeguard, added specifically to catch discrepancies between intended and transmitted pulse timing.

*This validation tooling was exercised directly during development: an apparent pulse-train irregularity was investigated methodically (version-history comparison, filter pole-stability analysis, and direct spectrogram inspection) before being correctly attributed to legitimate speech content rather than a signal-chain defect — illustrating the kind of empirical rigor the tooling is intended to support.*

## Software Architecture

The application is implemented as a single-process GNU Radio flowgraph with a PyQt5 front end:

- Custom GNU Radio blocks (implemented as Python `gr.sync_block` subclasses) for each DSP stage listed above, including a from-scratch direct-form biquad notch filter and DC blocker, written to eliminate a coefficient-convention ambiguity found in GNU Radio's built-in IIR block.
- A rational resampler bridging the 48kHz audio-rate pulse train to 2MHz complex baseband for RF transmission.
- A 49-language internationalized interface (with locale-aware formant-synthesis and diphone-synthesis voice selection via eSpeak NG and MBROLA) for accessibility to non-English-speaking collaborators.
- Full source, version history, and this project's own development record are openly available, supporting independent review and reproducibility.

## Hardware, Power, and Regulatory Scope

**This section is included deliberately and should be read carefully by any reviewer evaluating the project's relevance to bioeffects research.**

OpenV2K transmits using a **HackRF One**, a general-purpose, open-source SDR transceiver, operated at power levels as low as 1mW and configured for use within amateur radio frequency allocations. The application requires a valid amateur radio license before transmission is possible and displays this requirement in the interface. At these power levels and with this hardware, **OpenV2K has not produced, and is not represented as having produced, any measured or claimed bioeffect**. Its value to a bioeffects research program is as a *waveform design and prototyping tool* — a flexible, inexpensive, fully open platform for designing and characterizing candidate pulse-modulation schemes (pulse width, duty cycle, edge shape, audio-derived timing structure) prior to their use on separately validated, purpose-built, appropriately powered RF exposure systems.

## Potential Relevance to Ongoing Research

Given a research focus on the effects of pulsed microwave energy on the brain, the aspects of OpenV2K most likely to be of direct interest are:

- A real-time, software-reconfigurable pulse-modulation engine in which pulse width, timing, and edge characteristics are independently controllable parameters rather than fixed hardware constants.
- A signal-conditioning pipeline that allows systematic isolation of which acoustic-phonetic features of speech drive pulse generation.
- Built-in data provenance and validation tooling supporting reproducible, independently verifiable waveform characterization.
- A fully open codebase, permitting direct inspection, modification, and extension by a research collaborator rather than reliance on closed or proprietary signal-generation hardware.

---

**Prepared by:** Michael Eby Barr

**Project repository:** [https://github.com/OpenV2K](https://github.com/OpenV2K)

**Contact:** mikebarr@tuta.com
