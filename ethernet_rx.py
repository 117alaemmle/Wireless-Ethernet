import time
import numpy as np

class EthernetDecoder:
    def __init__(self, samp_rate, unit_time):
        self.samp_rate = samp_rate
        self.unit_time = unit_time
        self.buffer = []
        self.last_busy_time = 0
        self.receiving = False

    def process(self, samples, channel_busy, current_threshold=100):
        """Accumulates the OOK packet and decodes the Manchester bits."""
        if channel_busy:
            self.receiving = True
            self.last_busy_time = time.time()
            self.buffer.append(samples)
            return None
        else:
            if self.receiving:
                self.buffer.append(samples)
                
                # Hang time: Wait 0.5s to ensure the packet is truly over
                if (time.time() - self.last_busy_time) > 0.5: 
                    self.receiving = False
                    
                    if len(self.buffer) > 0:
                        full_waveform = np.concatenate(self.buffer)
                        self.buffer = []
                        # Pass the threshold to the decoder
                        return self.decode_packet(full_waveform, current_threshold)
            return None
            
    def decode_packet(self, waveform, current_threshold):
        """Slices the waveform into chips and reassembles the ASCII bytes."""
       # 1. Shift the 100 kHz carrier down to 0 Hz.
        # This pushes the other radio's LO Leakage down to -100 kHz.
        t = np.arange(len(waveform)) / self.samp_rate
        baseband = waveform * np.exp(-1j * 2 * np.pi * 100000.0 * t)
        
        # 2. Low-Pass Filter
        # A window of 50 averages exactly 5 full cycles of the -100 kHz interference, 
        # mathematically canceling the leakage to zero instantly!
        window = 50
        smoothed = np.convolve(baseband, np.ones(window)/window, mode='same')
        
        # 3. Extract the perfectly clean power envelope
        envelope = np.abs(smoothed)
        
        half_unit = self.unit_time / 2.0
        samples_per_chip = int(self.samp_rate * half_unit)
        
        # 4. ROBUST THRESHOLDING
        # Use the 95th percentile to completely ignore massive, split-second static pops
        max_pwr = np.percentile(envelope, 95)
        if max_pwr < current_threshold: 
            return None 
        
        threshold = max_pwr * 0.5
        
        # 5. Find the true Sync Bit
        crossings = np.where(envelope > threshold)[0]
        if len(crossings) == 0:
            return None
            
        first_high_idx = None
        for idx in crossings:
            check_idx = idx + int(samples_per_chip * 0.5)
            if check_idx < len(envelope) and envelope[check_idx] > threshold:
                first_high_idx = idx 
                break
                
        if first_high_idx is None:
            return None 

        # 6. ROBUST DATA SLICER
        current_idx = first_high_idx + int(samples_per_chip * 1.5)
        bits = ""
        
        # Look at a wide 20% chunk of the center of the chip to absorb noise
        window_size = int(samples_per_chip * 0.2) 
        
        while current_idx + samples_per_chip + window_size < len(envelope):
            
            # Average the power across the wide window
            chip1_pwr = np.mean(envelope[current_idx - window_size : current_idx + window_size])
            chip2_pwr = np.mean(envelope[current_idx + samples_per_chip - window_size : current_idx + samples_per_chip + window_size])
            
            c1 = 1 if chip1_pwr > threshold else 0
            c2 = 1 if chip2_pwr > threshold else 0
            
            # Manchester Decoding
            if c1 == 1 and c2 == 0:
                bits += "0" 
            elif c1 == 0 and c2 == 1:
                bits += "1" 
            else:
                # If static destroys a bit, DO NOT DELETE THE PACKET! 
                # Just guess '0' to keep the timeline perfectly synced for the next letter.
                bits += "0" 
                
            current_idx += samples_per_chip * 2
            
        # 7. Convert binary blocks back to text
        decoded_text = ""
        for i in range(0, len(bits), 8):
            byte = bits[i:i+8]
            if len(byte) == 8:
                decoded_text += chr(int(byte, 2))
                
        return decoded_text if decoded_text else None