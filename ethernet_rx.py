import time
import numpy as np

class EthernetDecoder:
    def __init__(self, samp_rate, unit_time):
        self.samp_rate = samp_rate
        self.unit_time = unit_time
        self.half_unit = unit_time / 2.0
        self.samples_per_chip = int(samp_rate * self.half_unit)
        
        # State Machine Variables
        self.receiving = False
        self.carryover_samples = np.array([], dtype=np.complex128)
        self.current_bit_stream = ""
        self.sync_found = False
        self.last_idx = 0

    def process(self, samples, channel_busy, current_threshold=100):
        """Processes a single buffer and returns any newly decoded text."""
        if not channel_busy and not self.receiving:
            return None # Channel is quiet, do nothing

        # 1. Start of Packet Detection
        if channel_busy and not self.receiving:
            self.receiving = True
            self.sync_found = False
            self.current_bit_stream = ""
            self.carryover_samples = samples # Start fresh
        else:
            # Append new samples to our "working" window
            self.carryover_samples = np.concatenate((self.carryover_samples, samples))

        # 2. Baseband Processing (Downconvert and Filter)
        # Shift the 100 kHz carrier down to 0 Hz.
        t = np.arange(len(self.carryover_samples)) / self.samp_rate
        baseband = self.carryover_samples * np.exp(-1j * 2 * np.pi * 100000.0 * t)
        
        # Low-Pass Filter
        window = 50
        smoothed = np.convolve(baseband, np.ones(window)/window, mode='same')
        
        # Extract the perfectly clean power envelope
        envelope = np.abs(smoothed)
        
        max_pwr = np.percentile(envelope, 95)
        if max_pwr < current_threshold:
            return None

        # 3. Find Sync (Only if we haven't found it for this packet yet)
        if not self.sync_found:
            sync_threshold = max_pwr * 0.5
            crossings = np.where(envelope > sync_threshold)[0]
            if len(crossings) == 0:
                return None
                
            first_high_idx = None
            for idx in crossings:
                check_idx = idx + int(self.samples_per_chip * 0.5)
                if check_idx < len(envelope) and envelope[check_idx] > sync_threshold:
                    first_high_idx = idx 
                    break
                    
            if first_high_idx is None:
                return None
            
            self.sync_found = True
            self.last_idx = first_high_idx + int(self.samples_per_chip * 1.5)

        # 4. Stream Slicer
        new_bits = ""
        window_size = int(self.samples_per_chip * 0.2)
        squelch_threshold = max_pwr * 0.2
        
        while self.last_idx + self.samples_per_chip + window_size < len(envelope):
            # Average the power across the wide window
            chip1_pwr = np.mean(envelope[self.last_idx - window_size : self.last_idx + window_size])
            chip2_pwr = np.mean(envelope[self.last_idx + self.samples_per_chip - window_size : self.last_idx + self.samples_per_chip + window_size])
            
            # Differential Comparison
            if chip1_pwr < squelch_threshold and chip2_pwr < squelch_threshold:
                new_bits += "0" 
            elif chip1_pwr > chip2_pwr:
                new_bits += "0"  # High -> Low
            else:
                new_bits += "1"  # Low -> High
                
            self.last_idx += self.samples_per_chip * 2
            
        # 5. Maintain Carryover
        # Keep only the samples we haven't decoded yet for the next buffer
        self.carryover_samples = self.carryover_samples[self.last_idx:]
        self.last_idx = 0 
        
        self.current_bit_stream += new_bits
        
        # 6. Convert full bytes
        return self.bits_to_text()

    def bits_to_text(self):
        """Translates completed 8-bit blocks into characters."""
        text = ""
        while len(self.current_bit_stream) >= 8:
            byte_bits = self.current_bit_stream[:8]
            self.current_bit_stream = self.current_bit_stream[8:]
            
            # Only convert to text if the byte isn't a null padding byte
            if byte_bits != "00000000":
                text += chr(int(byte_bits, 2))
                
        return text if text else None