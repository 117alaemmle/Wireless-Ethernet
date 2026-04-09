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
        """Simulates 'Dumb' OSI Layer 2 Ethernet Hardware. Best-effort delivery only."""
        
        # Standard Ethernet is 64 bytes minimum. 
        # Your overhead is 14 bytes: target(3) + src(3) + crc32(8).
        # Therefore, the msg payload must be at least 50 bytes.
        MIN_PAYLOAD = 50
        if len(msg) < MIN_PAYLOAD:
            msg = msg.ljust(MIN_PAYLOAD, '\x00')
        
        # 1. Build the Packet and Hardware CRC
        packet_core = f"{target}{my_address}{msg}"
        crc32_hex = f"{zlib.crc32(packet_core.encode()) & 0xFFFFFFFF:08x}"
        packet = packet_core + crc32_hex 
            
        # 2. Pre-Compute the Waveform 
        rf_wave = ethernet_protocol.generate_manchester_signal(packet, self.samp_rate, self.unit_time)
        
        # 3. Add the DMA Flush Pad and compress to 64-bit
        flush_pad = np.zeros(int(self.samp_rate * 0.5), dtype=np.complex64)
        rf_wave = np.concatenate((np.complex64(rf_wave), flush_pad))

        # --- CSMA/CA: Listen Before Talk ---
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
                break # Channel claimed!

        # ========================================================
        # INSTANT TRANSMISSION (Gapless One-Shot)
        # ========================================================
        if self.set_led:
            self.set_led("TX", "red")
            
        try:
            self.sdr.tx_destroy_buffer()
        except Exception:
            pass
            
        # Hand the exact array size to the hardware
        self.sdr.tx_buffer_size = len(rf_wave)
        tx_duration = len(rf_wave) / self.samp_rate
        
        start_tx_time = time.time()
        
        # Fire the buffer (This blocks Python while playing)
        self.sdr.tx(rf_wave)
        
        # --- THE SMART STOPWATCH ---
        elapsed = time.time() - start_tx_time
        remaining_time = tx_duration - elapsed
        if remaining_time > 0:
            time.sleep(remaining_time)
        
        self.sdr.tx_destroy_buffer()
        
        if self.set_led:
            self.set_led("TX", "gray")