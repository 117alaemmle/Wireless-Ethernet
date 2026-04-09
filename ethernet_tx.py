import time
import random
import numpy as np
import ethernet_protocol, zlib

class EthernetTransmitter:
    def __init__(self, sdr, samp_rate, unit_time, log_callback, led_callback, busy_check_callback):
        self.sdr = sdr
        self.samp_rate = samp_rate
        self.unit_time = unit_time
        
        # References to GUI functions
        self.log = log_callback
        self.set_led = led_callback
        self.is_channel_busy = busy_check_callback 

    def transmit(self, target, my_address, msg):
        """Simulates 10BASE5-style Ethernet with CSMA Listen-Before-Talk."""
        
        # ========================================================
        # ETHERNET FRAME CHECK SEQUENCE (FCS)
        # Calculate the CRC-32 of the Address + Payload and append it
        # ========================================================
        packet_core = f"{target}{my_address}{msg}"
        crc32_hex = f"{zlib.crc32(packet_core.encode()) & 0xFFFFFFFF:08x}"
        packet = packet_core + crc32_hex

        
        if self.log:
            self.log(f"-> Ethernet TX to {target}: {msg}")
        #if self.set_led:
        #    self.set_led("TX", "red")
            
        # 1. Generate the waveform before checking to see if the channel is clear. This way we can immediately start transmitting once we claim the channel.
        rf_wave = ethernet_protocol.generate_manchester_signal(packet, self.samp_rate, self.unit_time)
       
       # --- THE DMA FLUSH PAD & 64-BIT COMPRESSION ---
        # Append silence and downcast to 64-bit to save 50% of the SDR's RAM!
        flush_pad = np.zeros(int(self.samp_rate * 0.5), dtype=np.complex64)
        rf_wave = np.concatenate((np.complex64(rf_wave), flush_pad))

        # --- CSMA/CA: Carrier Sense & Collision Avoidance ---
        while True:
            continuous_silence = 0.0
            while continuous_silence < 0.5:
                if self.is_channel_busy():
                    continuous_silence = 0.0 
                else:
                    continuous_silence += 0.05
                time.sleep(0.05)
                
            backoff_time = random.uniform(0.1, 1.5)
            time.sleep(backoff_time)
            
            if not self.is_channel_busy():
                break

        # ========================================================
        # INSTANT TRANSMISSION (Jumbo Chunking!)
        # ========================================================
        if self.set_led:
            self.set_led("TX", "red")
            
        try:
            self.sdr.tx_destroy_buffer()
        except Exception:
            pass
            
        MAX_BUFFER = 2000000 # ~16 MB (Safe for the Pluto's CMA limits)
        
        if len(rf_wave) <= MAX_BUFFER:
            # Fits in memory! Send as a Gapless One-Shot.
            self.sdr.tx_buffer_size = len(rf_wave)
            self.sdr.tx(rf_wave)
        else:
            # Too large for memory! Spoon-feed it in massive "Jumbo Chunks".
            # Because each chunk takes 2 seconds to play, Windows 10 will never stutter!
            self.sdr.tx_buffer_size = MAX_BUFFER
            for i in range(0, len(rf_wave), MAX_BUFFER):
                chunk = rf_wave[i:i+MAX_BUFFER]
                if len(chunk) < MAX_BUFFER:
                    pad = np.zeros(MAX_BUFFER - len(chunk), dtype=np.complex64)
                    chunk = np.concatenate((chunk, pad))
                self.sdr.tx(chunk)
        
        # Hold the thread open while the radio finishes singing
        tx_duration = len(rf_wave) / self.samp_rate
        time.sleep(tx_duration)
        
        self.sdr.tx_destroy_buffer()
        
        if self.set_led:
            self.set_led("TX", "gray")