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
        
        # ========================================================
        # THE FIX: Gapless Transmission (The Ethernet Method)
        # Destroy old buffers and dynamically push the entire array
        # at once to guarantee mathematically perfect phase continuity!
        # ========================================================
        try:
            self.sdr.tx_destroy_buffer()
        except Exception:
            pass
            
        # Dynamically allocate the SDR buffer to swallow the entire FSK wave
        self.sdr.tx_buffer_size = len(samples)
        
        # Fire it in one solid, uninterrupted beam
        self.sdr.tx(samples)
        
        # Manually wait for the radio to physically finish playing
        tx_duration = len(samples) / self.samp_rate
        time.sleep(tx_duration)
            
        # Clean up the hardware buffer after the stream finishes
        self.sdr.tx_destroy_buffer()
        
        # Turn off the GUI light
        if self.set_led:
            self.set_led("TX", "gray")