import numpy as np
import teletype_protocol
import time

class TeletypeTransmitter:
    def __init__(self, sdr, samp_rate, log_callback, led_callback):
        self.sdr = sdr
        self.samp_rate = samp_rate
        # We store references to the GUI's functions so we can update the UI from here
        self.log = log_callback
        self.set_led = led_callback

    def transmit(self, target, my_address, msg):
        """Encodes and streams an FSK message to the ADALM-PLUTO hardware."""
        packet = f"{target}{my_address}{msg}"
        
        if self.log:
            self.log(f"-> Tele-Typing {target}: {msg}")
        if self.set_led:
            self.set_led("TX", "red")
            
        # 1. Generate the continuous math wave
        samples, _ = teletype_protocol.generate_fsk_signal(packet, self.samp_rate)
        
        # ========================================================
        # THE FIX: Safe Chunking
        # We use a 1 Mega-Sample chunk (about 0.5 seconds of audio).
        # This prevents Errno -27 (RAM Overflow) on long messages!
        # ========================================================
        chunk_size = 1048576 
        
        try:
            self.sdr.tx_destroy_buffer()
        except Exception:
            pass
            
        self.sdr.tx_buffer_size = chunk_size
        
        for i in range(0, len(samples), chunk_size):
            chunk = samples[i:i+chunk_size]
            
            # Pad the final chunk so the buffer size remains perfectly static
            if len(chunk) < chunk_size:
                pad = np.zeros(chunk_size - len(chunk), dtype=np.complex128)
                chunk = np.concatenate((chunk, pad))
                
            self.sdr.tx(chunk)
            
        self.sdr.tx_destroy_buffer()
        
        if self.set_led:
            self.set_led("TX", "gray")