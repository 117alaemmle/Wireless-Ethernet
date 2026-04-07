import time
import numpy as np
import teletype_protocol

class TeletypeDecoder:
    def __init__(self, samp_rate):
        self.samp_rate = samp_rate
        self.t_buffer = []
        self.last_busy_time = 0
        self.receiving = False
        self.tail_samples_count = 0  # THE FIX: Track exact static samples

    def process(self, samples, channel_busy):
        """Accumulates the full packet, tolerating RF fading and trimming static cleanly."""
        if channel_busy:
            self.receiving = True
            self.last_busy_time = time.time()
            self.t_buffer.append(samples)
            self.tail_samples_count = 0  # Reset static counter while signal is strong
            return None
        else:
            if self.receiving:
                self.t_buffer.append(samples)
                self.tail_samples_count += len(samples)  # Count exactly how much static we add
                
                # HANG TIME: Wait for 1.0 solid second of silence before ending the packet
                if (time.time() - self.last_busy_time) > 1.0:
                    self.receiving = False
                    
                    if len(self.t_buffer) > 0:
                        full_waveform = np.concatenate(self.t_buffer)

                        #Apply DC blocker globally to remove the LO leakage.
                       # full_waveform = full_waveform - np.mean(full_waveform)

                        # 1. Trim the static squelch tail (from our previous fix)
                        if self.tail_samples_count > 0 and len(full_waveform) > self.tail_samples_count:
                            full_waveform = full_waveform[:-self.tail_samples_count]
                        
                        # 2. THE NEW FIX: Trim the Hardware Power-On "Pop"
                        # We have a 1.3-second warmup tone, so we safely delete the first 
                        # 0.5 seconds (500,000 samples) of chaotic turn-on transient noise.
                        front_trim = int(self.samp_rate * 0.15)
                        if len(full_waveform) > front_trim:
                            full_waveform = full_waveform[front_trim:]
                            
                        # 3. Pass the pristine, trimmed wave to the DSP
                            
                        completed_packet = teletype_protocol.decode_fsk_packet(full_waveform, self.samp_rate)
                        
                        # Clear memory and reset state
                        self.t_buffer = []
                        self.tail_samples_count = 0
                        return completed_packet
                        
            return None