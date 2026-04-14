import time
import numpy as np
import teletype_protocol

class TeletypeDecoder:
    def __init__(self, samp_rate):
        self.samp_rate = samp_rate
        self.t_buffer = []
        self.last_busy_time = 0
        self.receiving = False
        # THE FIX: Removed tail_samples_count completely

    def process(self, samples, channel_busy):
        """Accumulates the full packet, tolerating RF fading and letting the DSP handle the tail."""
        if channel_busy:
            self.receiving = True
            self.last_busy_time = time.time()
            self.t_buffer.append(samples)
            return None
        else:
            if self.receiving:
                self.t_buffer.append(samples)
                
                # HANG TIME: Wait for 1.0 solid second of silence before ending the packet
                if (time.time() - self.last_busy_time) > 1.0:
                    self.receiving = False
                    
                    if len(self.t_buffer) > 0:
                        full_waveform = np.concatenate(self.t_buffer)

                        # ========================================================
                        # THE FIX: We NO LONGER trim the tail! 
                        # Our Magnitude AM Demodulator is powerful enough to decode 
                        # deeply faded signals, and it will naturally ignore the 
                        # dead static at the end of the recording.
                        # ========================================================
                        
                        # Trim the Hardware Power-On "Pop" (keep this!)
                        front_trim = int(self.samp_rate * 0.15)
                        if len(full_waveform) > front_trim:
                            full_waveform = full_waveform[front_trim:]
                            
                        # Pass the full, intact wave to the DSP
                        completed_packet = teletype_protocol.decode_fsk_packet(full_waveform, self.samp_rate)
                        
                        # Clear memory and reset state
                        self.t_buffer = []
                        return completed_packet
                        
            return None