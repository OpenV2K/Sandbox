**Installation: *Environment Setup***  
1. Install Ubuntu 26.04:  
   https://ubuntu.com/desktop/docs/en/latest/tutorial/install-ubuntu-desktop/
2. Download OpenV2K Python app:  
   https://raw.githubusercontent.com/OpenV2K/Sandbox/refs/heads/main/OpenV2K160.py
3. Optional: Download Language Translations XML file:  
   https://raw.githubusercontent.com/OpenV2K/Sandbox/refs/heads/main/Translations.xml
4. Open Terminal, Navigate to Downloads folder, Execute with Python:  
   ```user@MachineName:~/Downloads$ python3 OpenV2K160.py```
5. Install dependencies: First app run, you'll be prompted to install required packages:  
   ```sudo apt install gnuradio gr-osmosdr hackrf python3-pyqt5 python3-numpy espeak-ng```  
   ```pip3 install matplotlib --break-system-packages```  
   ```sudo apt install mbrola mbrola-us1```  
  
**GUI Introduction: *Understanding the Signal Chain***  
When you generate a spectrogram, you're seeing what **would-have-been** output via SDR.  
There are four functional modes. The signal always logically flows from GUI top to GUI bottom.  
  
| Input: eSpeak TTS,<br>Output: Generate Spectrogram                                                       | Input: Live Microphone,<br>Output: Generate Spectrogram                                                      | Input: eSpeak TTS,<br>Output: SDR Pulse Modulation                                                 | Input: Live Microphone,<br>Output: SDR Pulse Modulation                                                |
|----------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/1TTSToDiskSpectrogram.png" width="220"/> | <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/2LiveMicToDiskSpectrogram.png" width="220"/> | <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/4TTSToSDROutput.png" width="220"/> | <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/3LiveMicToSDROutput.png" width="220"/> |
