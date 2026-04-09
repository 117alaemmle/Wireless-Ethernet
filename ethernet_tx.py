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
       
        # Append 0.5 seconds of pure silence to the end of the array. 
        # This pushes the CRC out of the hardware queue before the buffer is destroyed!
        flush_pad = np.zeros(int(self.samp_rate * 0.5), dtype=np.complex128)
        rf_wave = np.concatenate((rf_wave, flush_pad))

        # --- CSMA: Carrier Sense Multiple Access ---
        # "Polite" Access: Wait until the channel is clear before starting.
        while True:
            # 1. Carrier Sense: Wait patiently if someone is currently talking
            # Because Manchester chips have 40ms gaps of silence, the RX light will flicker.
            # We must wait for 0.5 seconds of UNINTERRUPTED silence to know the packet is truly over.
            continuous_silence = 0.0
            while continuous_silence < 0.5:
                if self.is_channel_busy():
                    continuous_silence = 0.0 # Someone is talking (or it flickered back on), reset stopwatch!
                else:
                    continuous_silence += 0.05
                time.sleep(0.05)
            
            
            # 2. Collision Avoidance (The Backoff)
            # The channel just cleared! Wait a random amount of time to ensure 
            # we don't accidentally transmit at the exact same time as another waiting node.
            backoff_time = random.uniform(0.7, 1.5)
            time.sleep(backoff_time)
            
            # 3. Final Check: Is the channel STILL clear?
            if not self.is_channel_busy():
                break # We successfully claimed the channel! Break the loop and transmit.
            # If someone else started talking during our backoff, the loop repeats.
        

              
# 4. INSTANT TRANSMISSION (Gapless One-Shot!)
        if self.set_led:
            self.set_led("TX", "red")
            
        # ========================================================
        # THE FIX: GAPLESS TRANSMISSION
        # Destroy any old buffers, resize the hardware pipe to the EXACT 
        # length of our packet, and push the whole thing at once. 
        # No more Python for-loops, no more Windows 10 USB micro-stutters!
        # ========================================================
        try:
            self.sdr.tx_destroy_buffer()
        except Exception:
            pass
            
        # Dynamically allocate the SDR buffer to swallow the entire array
        self.sdr.tx_buffer_size = len(rf_wave)
        
        # Fire it in one solid, uninterrupted beam
        self.sdr.tx(rf_wave)

        # Because we gave the SDR the whole file at once, Python doesn't block.
        # We must manually wait for the radio to physically finish playing!
        # ========================================================
        tx_duration = len(rf_wave) / self.samp_rate
        time.sleep(tx_duration)

        self.sdr.tx_destroy_buffer()
        
        if self.set_led:
            self.set_led("TX", "gray")