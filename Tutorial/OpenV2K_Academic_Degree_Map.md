# Degrees Required to Fully Comprehend OpenV2K Software

## Framing

The honest, upfront answer: **no single degree covers this project.** OpenV2K sits at
the intersection of at least five genuinely distinct academic disciplines — software
engineering, digital signal processing, RF/communications engineering, phonetics and
linguistics, and (for the project's underlying premise specifically) bioelectromagnetics.
A person with any one of these backgrounds would find large parts of the codebase
either opaque or take-on-faith. Full comprehension realistically requires either a
graduate-level *interdisciplinary* background, or a small team.

The list below maps specific degree levels and specialties to the parts of the app they
unlock, roughly in the order a person would need them to go from "can read the code" to
"understands why every design decision was made, including the ones we debugged
together this session."

---

## Associate's Degrees (AAS) — Foundational / Technician Level

| Degree | Specialty | Unlocks |
|---|---|---|
| AAS, Computer Programming | General software development | Basic Python syntax, control flow, reading the simpler GUI event handlers and file I/O — enough to follow the code's *shape*, not its *reasoning* |
| AAS, Electronics Engineering Technology | General electronics | Reading an oscilloscope-style trace (relevant background for the pulse-waterfall visualizations we built), basic USB/hardware I/O concepts for the HackRF device detection |
| AAS, Telecommunications / Radio & Broadcast Technology | RF technician-level | Basic antenna and frequency concepts, why an amateur radio license is legally required before the TX button does anything real |

At this level, someone could operate the GUI, follow the checkbox logic, and understand
*that* filters exist — but not *why* a given filter's Q factor or pole placement matters.

---

## Bachelor's Degrees — Where Real Comprehension Starts

| Degree | Specialty | Unlocks |
|---|---|---|
| BS, Computer Science | Software engineering / HCI | The full PyQt5 application architecture: custom `QPainter`-based widgets (`SegmentedMeter`, `PulseHeaderWidget`, `SwapButton`), threading for non-blocking audio playback, `QGraphicsEffect` layering, the XML-based translation-loading system with its English-only fallback, and the `gr.sync_block` subclassing pattern used for every custom DSP block |
| BS, Electrical Engineering — Signals & Systems / DSP track | Digital signal processing | Z-transforms and pole-zero analysis (directly what we used to diagnose the notch filter's ~800ms ringing tail), FIR vs. IIR filter design, the Nyquist theorem and resampling theory (the boxcar-vs-windowed-sinc resampler discussion), difference equations for the custom `DCBlocker`, `NotchFilter`, `SchmittFilter` |
| BS, Electrical Engineering — RF/Communications track | Radio-frequency engineering | IQ (in-phase/quadrature) signal representation, the `float_to_complex` conversion stage, HackRF sink configuration, basic link-budget and antenna concepts underlying the frequency and TX power controls |
| BA/BS, Linguistics — Phonetics & Phonology track | Acoustic and articulatory phonetics | Why fricatives have the highest zero-crossing rate in speech (`FricativeSuppressor`), what a first formant is and why it clusters around 300-900Hz (`F1BandpassFilter`), why "one" sustains a regular ~628Hz pattern at its nasal ending while "two" doesn't — this is the exact question we spent an evening debugging, and it's genuinely an acoustic-phonetics question, not a software one |
| BFA/BS, Graphic Design or Digital Media | Visual/UI design | Color contrast and legibility (the "waves are invisible against the background" debugging), typography and embossing effects, translating a CSS/SVG wave-divider concept into `QPainterPath` geometry |

A bachelor's-level generalist with strong CS fundamentals could maintain the *codebase*.
They could not, on their own, explain why a Q=30 notch filter produces a specific
ringing time constant, or why "ton" and "one" should share a phonetic tail — those
require the DSP and linguistics tracks respectively.

---

## Master's Degrees — Where the Deeper "Why" Lives

| Degree | Specialty | Unlocks |
|---|---|---|
| MS, Electrical Engineering — DSP/Communications specialization | Advanced filter theory | Wiener-filter-style spectral subtraction (the `SpectralSubtractor`'s gain floor, and why removing it fixed a real leakage bug), envelope detection and the Hilbert transform, rigorous pole-magnitude-to-ringing-time derivations at the level we actually did this session — an undergrad DSP course teaches the *tools*; this is where you'd learn to reach for them unprompted |
| MS/MA, Computational Linguistics or Speech & Language Processing | Speech synthesis systems | Why eSpeak's formant synthesis and MBROLA's diphone/concatenative synthesis produce structurally different audio for the same text, and how to design a locale-to-voice mapping system across languages with genuinely different phonetic inventories (the accent-combobox logic) |
| MEng/MS, Biomedical Engineering — Bioelectromagnetics or Neural Engineering focus | EM-tissue interaction | The physics underlying the project's actual premise: how pulsed RF energy is hypothesized to couple into auditory perception via thermoelastic expansion — this is the first level at which someone could explain *why* pulse width and duty cycle were chosen the way they were, not just *that* they were |

---

## PhD Level — Full, Research-Grade Comprehension

| Degree | Specialty | Unlocks |
|---|---|---|
| PhD, Biophysics / Auditory Neuroscience — bioelectromagnetics specialization | Original research literature on RF-to-auditory transduction | Genuine command of the thermoelastic-expansion mechanism first characterized by Sharp and Grove's 1975 work and the broader microwave-auditory-effect (Frey effect) literature — this is the only level at which someone could evaluate, rather than take on faith, whether the app's signal design should theoretically produce the intended effect at all |
| PhD, Electrical Engineering — RF/antenna theory or advanced signal processing | Near/far-field radiation physics; filter stability theory | Rigorous treatment of antenna gain and near-vs-far-field power falloff (notably, we deliberately *removed* an antenna-gain assumption from the power calculator earlier in this project specifically because it wasn't backed by this level of analysis) and exhaustive, non-empirical proof of filter stability rather than the pole-magnitude spot-checks we did |

---

## Summary

| If you had to pick the *smallest* set of degrees that together cover the whole stack | |
|---|---|
| **BS Computer Science** | for the application itself |
| **MS Electrical Engineering (DSP)** | for the entire signal chain and the ringing investigation |
| **MS/MA Linguistics or Computational Linguistics** | for the translation system and phonetic behavior |
| **PhD-level Biophysics/Bioelectromagnetics** | for the premise the whole project rests on |

A few honest caveats: the mathematics underlying the DSP work (complex analysis for
Z-transforms, trigonometry, exponential-decay calculus, and the probability theory
behind this session's weighted-RNG pulse generator) doesn't need its own line — it's
standard content *within* the EE curriculum, not a separate degree. And amateur radio
licensing, mentioned throughout the Output section, is a certification administered by
national regulators (the FCC in the US), not an academic degree at all — genuinely
necessary to *operate* the transmit functionality legally, but orthogonal to
*understanding* it.
