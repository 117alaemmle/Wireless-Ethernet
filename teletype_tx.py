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
            
        samples, _ = teletype_protocol.generate_fsk_signal(packet, self.samp_rate)
        
        chunk_size = 1048576 
        
        try:
            self.sdr.tx_destroy_buffer()
        except Exception:
            pass
            
        self.sdr.tx_buffer_size = chunk_size
        
        for i in range(0, len(samples), chunk_size):
            chunk = samples[i:i+chunk_size]
            
            if len(chunk) < chunk_size:
                pad = np.zeros(chunk_size - len(chunk), dtype=np.complex128)
                chunk = np.concatenate((chunk, pad))
                
            self.sdr.tx(chunk)
            
        # ========================================================
        # THE FIX: DMA Queue Drain Time
        # The SDR kernel holds up to 4 buffers in memory. If we 
        # destroy the buffer instantly, it deletes the last 2 seconds 
        # of audio! We must sleep to let the hardware finish radiating.
        # ========================================================
        drain_time = (chunk_size / self.samp_rate) * 4
        time.sleep(drain_time)
            
        self.sdr.tx_destroy_buffer()
        
        if self.set_led:
            self.set_led("TX", "gray")