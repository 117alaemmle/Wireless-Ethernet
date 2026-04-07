import time
import numpy as np

class EthernetDecoder:
    def __init__(self, samp_rate, unit_time):
        self.samp_rate = samp_rate
        self.unit_time = unit_time
        self.buffer = []
        self.last_busy_time = 0
        self.receiving = False

    def process(self, samples, channel_busy):
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
                        return self.decode_packet(full_waveform)
            return None
            
    def decode_packet(self, waveform):
        """Slices the waveform into chips and reassembles the ASCII bytes."""
        waveform = waveform - np.mean(waveform)

        half_unit = self.unit_time / 2.0
        samples_per_chip = int(self.samp_rate * half_unit)
        
        # 1. Extract the power envelope
        envelope = np.abs(waveform)
        
        # Smooth it to remove raw RF ripples
        # window = int(self.samp_rate * 0.005) 
        # envelope = np.convolve(envelope, np.ones(window)/window, mode='same')

        #========================================================
        # The 100 kHz carrier cycle is only 10 samples long. A window of 50 
        # smooths it perfectly, dropping the math from 10 Billion operations 
        # down to a few million. It will execute instantly!
        # ========================================================
        window = 50 
        envelope = np.convolve(envelope, np.ones(window)/window, mode='same')
        
        # 2. Dynamic Thresholding based on this specific packet's peak volume
        max_pwr = np.max(envelope)
        if max_pwr < 100: 
            return None # Ignore dead air
        threshold = max_pwr * 0.5
        
        # 3. Find the very first sample that crosses the threshold
        # In our sync bit "1" (encoded as 0->1), this finds the start of the '1' chip.
        crossings = np.where(envelope > threshold)[0]
        if len(crossings) == 0:
            return None
            
        first_high_idx = None
        for idx in crossings:
            # Check a point exactly half a chip (20ms) ahead
            check_idx = idx + int(samples_per_chip * 0.5)
            if check_idx < len(envelope) and envelope[check_idx] > threshold:
                first_high_idx = idx # We found the true solid tone!
                break
                
        if first_high_idx is None:
            return None # Packet was just a burst of static
        
        # 4. Jump forward to the center of the FIRST DATA CHIP
        # first_high_idx is the start of the second half of the sync bit.
        # Adding 1.5 chips puts us exactly in the middle of the next chip!
        current_idx = first_high_idx + int(samples_per_chip * 1.5)
        
        bits = ""
        while current_idx + samples_per_chip < len(envelope):
            # Sample the power in the middle of both chips for the current bit
            chip1_pwr = envelope[current_idx]
            chip2_pwr = envelope[current_idx + samples_per_chip]
            
            c1 = 1 if chip1_pwr > threshold else 0
            c2 = 1 if chip2_pwr > threshold else 0
            
            # Manchester Decoding logic
            if c1 == 1 and c2 == 0:
                bits += "0" # High-to-Low transition
            elif c1 == 0 and c2 == 1:
                bits += "1" # Low-to-High transition
            else:
                # Manchester Violation (e.g., two highs in a row). 
                # This means the packet ended, or interference destroyed the signal.
                break 
                
            # Jump ahead 2 chips to the start of the next bit
            current_idx += samples_per_chip * 2
            
        # 5. Convert binary blocks back to text
        decoded_text = ""
        for i in range(0, len(bits), 8):
            byte = bits[i:i+8]
            if len(byte) == 8:
                decoded_text += chr(int(byte, 2))
                
        return decoded_text if decoded_text else None