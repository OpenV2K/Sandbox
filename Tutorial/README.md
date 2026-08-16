Introduction to the software stack, understanding the signal chain, using the GUI.  
  
When you generate a spectrogram, you're seeing what **would-have-been** output via SDR.  
  
There are four functional modes. The signal always flows from GUI top to GUI bottom.  
  
| Input: eSpeak TTS,<br>Output: Generate Spectrogram                                                       | Input: Live Microphone,<br>Output: Generate Spectrogram                                                      | Input: eSpeak TTS,<br>Output: SDR Pulse Modulation                                                 | Input: Live Microphone,<br>Output: SDR Pulse Modulation                                                |
|----------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/1TTSToDiskSpectrogram.png" width="220"/> | <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/2LiveMicToDiskSpectrogram.png" width="220"/> | <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/4TTSToSDROutput.png" width="220"/> | <img src="https://github.com/OpenV2K/Sandbox/blob/main/Tutorial/3LiveMicToSDROutput.png" width="220"/> |
