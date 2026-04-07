import time
import numpy as np
import teletype_protocol

class TeletypeDecoder:
    def __init__(self, samp_rate):
        self.samp_rate = samp_rate
        self.t_buffer = []
        self.last_busy_time = 0
        self.receiving = False

    def process(self, samples, channel_busy):
        """Accumulates the full packet, tolerating RF fading and buffer dropouts."""
        if channel_busy:
            self.receiving = True
            self.last_busy_time = time.time()
            self.t_buffer.append(samples)
            return None
        else:
            if self.receiving:
                # The signal just dropped below the threshold. 
                # Keep appending samples to maintain perfect mathematical timing 
                # in case it was just a micro-dropout.
                self.t_buffer.append(samples)
                
                # HANG TIME: Wait for 1.0 solid second of silence before ending the packet
                if (time.time() - self.last_busy_time) > 1.0:
                    self.receiving = False
                    
                    if len(self.t_buffer) > 0:
                        # Concatenate and decode ONLY after we are certain it's over
                        full_waveform = np.concatenate(self.t_buffer)
                        completed_packet = teletype_protocol.decode_fsk_packet(full_waveform, self.samp_rate)
                        
                        # Clear memory
                        self.t_buffer = []
                        return completed_packet
                        
            return None