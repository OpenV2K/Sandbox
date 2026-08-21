# Home Users: Insights in Audio-Driven Pulse Modulation

OpenV2K is an open-source software application that converts arbitrary audio — including natural speech — into a pulse-modulated radio-frequency (RF) waveform, generated and analyzed through a software-defined radio (SDR) signal chain. The project's signal design is directly inspired by the historical microwave-auditory-effect (MAE) literature, most [notably Sharp and Grove's 1975 demonstration](https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques) that appropriately pulse-modulated microwave energy could convey intelligible words, building on Frey's earlier characterization of the effect. **OpenV2K is a signal-generation and waveform-design tool**, not a bioeffects exposure system.  
  
## What This Actually Is, For a Home User

For nearly everyone running this — which is exactly how it's meant to be used — OpenV2K is a thought experiment, not a demonstration. Generate a pulse train from spoken audio, open the resulting spectrogram, and look at it: a clean, structured, audio-timed pulse pattern, visibly distinct. **No SDR needs to be attached** for this to be worth doing. The exercise is to look at that pattern and reason, about what pulse-modulated microwave energy carrying that same structure would represent.  
Reflect on the [historical precedent of Sharp and Grove's 1975 feat](https://en.wikipedia.org/wiki/Signal_modulation#Miscellaneous_modulation_techniques), while using this software at home.  
  
**Reproducing the actual microwave-auditory effect requires power levels, exposure control, dosimetry, and safety oversight this software does not provide and was never designed to provide.** That work belongs at PhD-staffed microwave exposure facilities with the instrumentation and institutional review to do it responsibly. OpenV2K's contribution stops at the waveform: a legitimate, inspectable, open-source answer to "what would the signal look like".
