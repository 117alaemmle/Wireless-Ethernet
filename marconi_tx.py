import time
import random
import threading
import numpy as np
import marconi_audio
import marconi_protocol

class MarconiTransmitter:
    def __init__(self, sdr, samp_rate, unit_time, log_callback, led_callback, busy_check_callback, audio_mode_callback):
        self.sdr = sdr
        self.samp_rate = samp_rate
        self.unit_time = unit_time
        self.morse_dict = marconi_protocol.MORSE_DICT
        
        # References to GUI functions and dynamic states
        self.log = log_callback
        self.set_led = led_callback
        self.is_channel_busy = busy_check_callback
        self.get_audio_mode = audio_mode_callback

    def transmit(self, target, my_address, msg):
        """Builds the mathematical OOK envelope and streams it to the SDR."""
        
        # CSMA: Wait if someone is currently transmitting
        while self.is_channel_busy():
            time.sleep(random.uniform(0.5, 2.0))

        clean_msg = msg[1:] if (len(msg) > 0 and msg[0] in ["C", "F"]) else msg
            
        if self.log:
            self.log(f"-> Keying {target}: {clean_msg}", "tx")
        
        packet = f"{target}{my_address}{clean_msg}"
        
        # 1. Build the mathematical envelope (1 = Tone, 0 = Silence)
        units = []
        for char in packet.upper():
            code = self.morse_dict.get(char, "")
            if code == '/':
                units.extend([0] * 7) # Word gap
            else:
                for sym in code:
                    if sym == '.':
                        units.append(1)
                    elif sym == '-':
                        units.extend([1, 1, 1])
                    units.append(0) # Inter-symbol gap
                units.extend([0, 0]) # Complete the 3-unit inter-character gap
                
        # Pad the end with absolute silence (zeros) so the SDR cyclic buffer 
        # doesn't accidentally repeat the final tone while powering down!
        units.extend([0] * 10)

        # 2. Convert to a mathematically perfect, continuous Complex Waveform
        samples_per_unit = int(self.samp_rate * self.unit_time)
        total_samples = len(units) * samples_per_unit
        
        t = np.arange(total_samples)
        carrier = 0.5 * (np.exp(1j * 2 * np.pi * 0.1 * t)) * 2**14
        
        envelope = np.zeros(total_samples)
        for i, u in enumerate(units):
            if u == 1:
                envelope[i*samples_per_unit : (i+1)*samples_per_unit] = 1.0
                
        rf_wave = carrier * envelope
        
        # 3. Animate the TX light in a background thread
        threading.Thread(target=self._tx_animator, args=(packet,), daemon=True).start()
        
        # 4. Stream to the SDR Hardware in safe chunks (Bypassing Windows Timers entirely!)
        chunk_size = 131072
        for i in range(0, len(rf_wave), chunk_size):
            chunk = rf_wave[i:i+chunk_size]
            if len(chunk) < chunk_size:
                pad = np.zeros(chunk_size - len(chunk), dtype=np.complex128)
                chunk = np.concatenate((chunk, pad))
            self.sdr.tx(chunk)
            
        self.sdr.tx_destroy_buffer()


    def _tx_animator(self, packet):
        """Flashes the TX light perfectly in sync with the physical RF emission."""
        for char in packet.upper():
            code = self.morse_dict.get(char, "")
            if code == '/':
                time.sleep(self.unit_time * 7)
            else:
                for sym in code:
                    dur = 1 if sym == '.' else 3
                    
                    # Turn light ON for the duration of the tone
                    if self.set_led:
                        self.set_led("TX", "red")
                    time.sleep(self.unit_time * dur) 
                    
                    # Turn light OFF for the gap
                    if self.set_led:
                        self.set_led("TX", "gray")
                    time.sleep(self.unit_time) # Inter-symbol gap
                    
                time.sleep(self.unit_time * 2) # Remaining Inter-character gap
                
        # Safety catch to ensure it always turns off at the end
        if self.set_led:
            self.set_led("TX", "gray")