import numpy as np
import teletype_protocol

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
        
        # Trigger the GUI updates
        if self.log:
            self.log(f"-> Tele-Typing {target}: {msg}")
        if self.set_led:
            self.set_led("TX", "red")
            
        # 1. Generate the entire continuous math wave
        samples, _ = teletype_protocol.generate_fsk_signal(packet, self.samp_rate)
        
        # 2. Break it into hardware-safe 131ms chunks to prevent RAM allocation crashes
        chunk_size = 131072 
        
        for i in range(0, len(samples), chunk_size):
            chunk = samples[i:i+chunk_size]
            
            # If it's the final chunk, pad it with zeros to keep the buffer size identical.
            # This forces the driver to reuse the same memory address, eliminating RF gaps.
            if len(chunk) < chunk_size:
                pad = np.zeros(chunk_size - len(chunk), dtype=np.complex128)
                chunk = np.concatenate((chunk, pad))
                
            # Push to the radio (Blocking call acts as a hardware metronome)
            self.sdr.tx(chunk)
            
        # Clean up the hardware buffer after the stream finishes
        self.sdr.tx_destroy_buffer()
        
        # Turn off the GUI light
        if self.set_led:
            self.set_led("TX", "gray")