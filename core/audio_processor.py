import os
import subprocess
from pydub import AudioSegment
import numpy as np
import random
import logging
from scipy.io import wavfile

class AudioEngine:
    def __init__(self, temp_dir="assets/downloads"):
        self.temp_dir = temp_dir
        self.voices =['en-US-ChristopherNeural', 'en-US-GuyNeural', 'en-US-EricNeural', 'en-GB-RyanNeural', 'en-US-JennyNeural']

    def synthesize_speech(self, text, output_filename="tts_raw.mp3"):
        path = os.path.join(self.temp_dir, output_filename)
        voice = random.choice(self.voices)
        
        try:
            # Using microsoft edge-tts from bash, the best open tool today
            subprocess.run(["edge-tts", "--voice", voice, "--text", text, "--write-media", path], check=True)
            return self._obfuscate_humanize(path)
        except Exception as e:
            logging.error(f"Voice error: {e}")
            return None

    def _obfuscate_humanize(self, filepath):
        # Shifts Pitch & speed mathematically avoiding "Duplicate Content AI Spam Check"
        sound = AudioSegment.from_file(filepath)
        
        # Slight dynamic length modifier
        speed_factor = random.uniform(0.95, 1.05)
        new_frame_rate = int(sound.frame_rate * speed_factor)
        mod_sound = sound._spawn(sound.raw_data, overrides={'frame_rate': new_frame_rate}).set_frame_rate(sound.frame_rate)
        
        # Export processed secure audio
        out_path = filepath.replace("_raw.mp3", "_final.mp3")
        mod_sound.export(out_path, format="mp3")
        return out_path

    def generate_sfx(self):
        """ Creates royalty-free sounds MATHEMATICALLY - Zero download limits. """
        fs = 44100
        # Ding (Answer reward sound)
        t_ding = np.linspace(0, 0.5, int(fs*0.5), endpoint=False)
        ding_freq = 800 * np.exp(-t_ding * 10)  # Bell curve fading envelope
        ding_wav = np.sin(2 * np.pi * ding_freq * t_ding) * (1.0 - t_ding*2)
        ding_path = os.path.join(self.temp_dir, "ding.wav")
        wavfile.write(ding_path, fs, (ding_wav * 32767).astype(np.int16))
        
        # Ticking Clock for Timer (Quick harsh short pops)
        t_tick = np.linspace(0, 0.05, int(fs*0.05), endpoint=False)
        tick_wav = np.sin(2 * np.pi * 300 * t_tick) * (np.random.random(len(t_tick))*0.5) 
        tick_path = os.path.join(self.temp_dir, "tick.wav")
        wavfile.write(tick_path, fs, (tick_wav * 32767).astype(np.int16))

        return {"ding": ding_path, "tick": tick_path}
