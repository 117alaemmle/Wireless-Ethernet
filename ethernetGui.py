import os, time, random, threading, queue, uuid
import tkinter as tk
from tkinter import scrolledtext
import zlib
import numpy as np  #pip install numpy pyadi-iio
import adi
import marconiAudio
from tkinter import ttk  # Required for the Combobox
import teletype_protocol # New module to handle teletype.
import marconi_rx, marconi_tx, marconi_audio #Play audio tone through PC speakers
import teletype_rx, teletype_tx
import ethernet_tx, ethernet_rx
import config

class MarconiNode:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Wireless Node {config.MY_ADDRESS}")
        
        # Hardware Setup
        try:
            self.sdr = adi.Pluto(config.URI)
            self.sdr.sample_rate = int(config.SAMP_RATE)
            self.sdr.tx_lo = int(config.FREQ)
            self.sdr.rx_lo = int(config.FREQ)
            self.sdr.tx_hardwaregain_chan0 = -10 #-10DB for direct wired connection
            #self.sdr.tx_hardwaregain_chan0 = 0 #0DB for antenna use, gives it a boost to be able to hear anything at all.
            self.sdr.rx_hardwaregain_chan0 = -20 #25DB gain for direct connection.
            #self.sdr.rx_hardwaregain_chan0 = 55 #bigger gain for antennas.
            self.sdr.rx_buffer_size = 500 # Increasing buffer size to prevent dropping samples
            #self.sdr.rx_buffer_size = 32768 #We need to change buffer size depending on the type of protocol. Marconi requires precise timing, smaller buffer size.
        except Exception as e:
            print(f"Hardware Error: {e}")
            
        # --- THE QUEUE ---
        # This stores (target, message) tuples
        self.tx_queue = queue.Queue()

        ###########################################
        # --- Indicator Lights Setup ---
        ###########################################
        indicator_frame = tk.Frame(root)
        indicator_frame.pack(pady=5)

        # TX Light (Red when sending)
        tk.Label(indicator_frame, text="TX").pack(side="left", padx=5)
        self.tx_light = tk.Canvas(indicator_frame, width=20, height=20, bg=root["bg"], highlightthickness=0)
        self.tx_led = self.tx_light.create_oval(2, 2, 18, 18, fill="gray")
        self.tx_light.pack(side="left", padx=5)

        # RX Light (Green when signal detected)
        tk.Label(indicator_frame, text="RX").pack(side="left", padx=20)
        self.rx_light = tk.Canvas(indicator_frame, width=20, height=20, bg=root["bg"], highlightthickness=0)
        self.rx_led = self.rx_light.create_oval(2, 2, 18, 18, fill="gray")
        self.rx_light.pack(side="left", padx=5)

        ###########################
        # --- Power Meter Setup ---
        ############################

        # --- LIVE THRESHOLD FIX ---
        self.current_threshold = 200.0 # Instance variable replaces the global THRESHOLD

        meter_frame = tk.Frame(root)
        meter_frame.pack(pady=5, fill="x", padx=20)
        
        tk.Label(meter_frame, text="RX Power:").pack(side="left")
        
        # 300px wide canvas, assuming a max visual power of ~2000 for the ADALM-PLUTO
        self.pwr_canvas = tk.Canvas(meter_frame, width=300, height=20, bg="black", highlightthickness=1)
        self.pwr_canvas.pack(side="left", padx=10)
        
        # The dynamic bar (height 20)
        self.pwr_bar = self.pwr_canvas.create_rectangle(0, 0, 0, 20, fill="blue")

        self.max_graph_pwr = self.current_threshold * 4 # Adjust this if your signal regularly blows past the end of the bar
        
        # Draw the Static Scale Ticks and Labels
        for val in range(0, int(self.max_graph_pwr) + 1, int(int(self.max_graph_pwr)// 10)):
            x_pos = (val / self.max_graph_pwr) * 300
            # Small white tick line
            self.pwr_canvas.create_line(x_pos, 20, x_pos, 25, fill="white")
            # Text label for the scale
            self.pwr_canvas.create_text(x_pos, 32, text=str(val), fill="white", font=("Arial", 8))
        
        # Draw the Threshold Line
        self.thresh_x = (self.current_threshold / self.max_graph_pwr) * 300
        self.pwr_thresh_line = self.pwr_canvas.create_line(self.thresh_x, 0, self.thresh_x, 20, fill="red", width=2)

        # Add the Live Value Label next to the canvas
        self.live_pwr_label = tk.Label(meter_frame, text="0", width=6, font=("Courier", 10, "bold"), fg="blue")
        self.live_pwr_label.pack(side="left")
               
        
        self.threshold_scale = tk.Scale(
            meter_frame, 
            from_=0, to=self.max_graph_pwr, 
            orient="horizontal", 
            label="Live RX Detection Threshold", 
            command=self.update_threshold
        )
        self.threshold_scale.set(self.current_threshold)
        self.threshold_scale.pack(fill="x", padx=10)

        # Timer to prevent UI flooding
        self.last_meter_update = time.time()

        ######################################
        # Audio Controls between modes, GUI gets drawn in order it is in the code, so it goes before the GUI draw to ensure it stays on top.
        ######################################
        self.audio_mode = tk.StringVar(value="Cinema")
        audio_frame = tk.LabelFrame(root, text="Morse Code Sound Profile")
        audio_frame.pack(padx=10, pady=10, fill="x")
        
        for mode in ["Marconi", "Cinema", "Silent"]:
            tk.Radiobutton(audio_frame, text=mode, variable=self.audio_mode, value=mode).pack(side="left", padx=10)

        # Protocol Selection Drop-down
        protocol_frame = tk.LabelFrame(root, text="Transmission Protocol")
        protocol_frame.pack(padx=10, pady=5, fill="x")
        
        self.protocol_var = tk.StringVar(value="Marconi (OOK)")
        self.protocol_dropdown = ttk.Combobox(
            protocol_frame, 
            textvariable=self.protocol_var, 
            values=["Marconi (OOK)", "Wireless Ethernet (CSMA/CA)"], #"Teletype (FSK)", "ALOHAnet (OOK)", 
            state="readonly"
        )
        self.protocol_dropdown.pack(padx=10, pady=5, side="left")

        self.channel_busy = False
        self.last_rx_state = False  # Tracks previous state to prevent UI flooding
        self.is_transmitting = False
        self.just_finished_tx = False

        # --- Marconi (OOK) Receiver State ---
        self.m_stream = ""
        self.m_symbols = ""
        self.m_in_pulse = False
        self.m_p_start = time.time()
        self.m_s_start = time.time()
        self.m_live_buffer = ""
        self.m_header_printed = False

        # Initialize Decoders for decoding incoming messages...

        # Initialize Decoders for decoding incoming messages
        self.marconi_decoder = marconi_rx.MarconiDecoder(config.UNIT_TIME)
        self.teletype_decoder = teletype_rx.TeletypeDecoder(config.SAMP_RATE)
        self.ethernet_decoder = ethernet_rx.EthernetDecoder(config.SAMP_RATE, config.ETHERNET_UNIT_TIME)

        # Initialize Transmitters
        self.marconi_transmitter = marconi_tx.MarconiTransmitter(
            self.sdr, config.SAMP_RATE, config.UNIT_TIME, 
            self.log, self.set_led, lambda: self.channel_busy, lambda: self.audio_mode.get()
        )
        self.teletype_transmitter = teletype_tx.TeletypeTransmitter(
            self.sdr, config.SAMP_RATE, self.log, self.set_led
        )
        self.ethernet_transmitter = ethernet_tx.EthernetTransmitter(
            self.sdr, config.SAMP_RATE, config.ETHERNET_UNIT_TIME, self.log, self.set_led, lambda: self.channel_busy
        )

        # --- Teletype (FSK) Receiver State ---
        self.t_buffer = np.array([], dtype=np.complex128)

        
        # GUI
        self.history = scrolledtext.ScrolledText(root, state='disabled', height=20, width=75)
        self.history.pack(padx=10, pady=10)
        
        # Create a frame to hold both the dropdown and the text entry
        input_frame = tk.Frame(root)
        input_frame.pack(padx=10, pady=(0, 10), fill="x")
        
        tk.Label(input_frame, text="To:").pack(side="left", padx=(0, 5))
        
        # Target Selection Dropdown
        self.target_var = tk.StringVar(value="A")
        self.target_dropdown = ttk.Combobox(
            input_frame, 
            textvariable=self.target_var, 
            values=["A", "B", "C"],
            state="readonly",
            width=5
        )
        self.target_dropdown.pack(side="left", padx=(0, 10))
        
        # The Message Entry Box
        self.entry = tk.Entry(input_frame)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self.on_send)
        
        self.log(f"*** Node {config.MY_ADDRESS} Listening (Promiscuous Mode) ***")

        # --- EFTP State Tracker ---
        self.unacked_packet = None
        self.tx_seq_nums = {} # Tracks the next seq number to SEND to a target
        self.rx_seq_nums = {} # Tracks the expected seq number to RECEIVE from a source

        # Start background threads
        threading.Thread(target=self.receiver_loop, daemon=True).start()
        time.sleep(0.5)  # Allow receiver to stabilize between hardware calls
        threading.Thread(target=self.tx_daemon, daemon=True).start()
        # Start the EFTP timeout monitor loop
        self.root.after(500, self.check_eftp_timeouts)



    def log(self, message, tag="status"):
        def append():
            ts = time.strftime("[%H:%M:%S]")
            self.history.configure(state='normal')

            # Define the color palette
            self.history.tag_config("status", foreground="gray")
            self.history.tag_config("received", foreground="blue")
            self.history.tag_config("sniffed", foreground="purple")
            self.history.tag_config("error", foreground="red")
            
            # Insert the text with the assigned tag
            self.history.insert(tk.END, f"{ts} {message}\n", tag)
            self.history.configure(state='disabled')
            self.history.see(tk.END)
        self.root.after(0, append)


    # Set LED colors in a thread-safe manner depending on the action taken by the code
    def set_led(self, led_type, color):
        """Thread-safe method to change LED colors."""
        if led_type == "TX":
            self.is_transmitting = (color == "red")
        target = self.tx_led if led_type == "TX" else self.rx_led
        canvas = self.tx_light if led_type == "TX" else self.rx_light
        self.root.after(0, lambda: canvas.itemconfig(target, fill=color))

    def update_threshold(self, val):
        """Updates the math variable and moves the red line on the meter."""
        self.current_threshold = float(val)
        new_x = (self.current_threshold / self.max_graph_pwr) * 300
        self.pwr_canvas.coords(self.pwr_thresh_line, new_x, 0, new_x, 20)

    # Update the real-time power meter to display received strength.
    def update_power_meter(self, pwr):
        """Thread-safe method to update the real-time power bar graph."""
        # Cap the visual power so it doesn't draw off the edge of the canvas
        graph_pwr = min(pwr, self.max_graph_pwr)
        bar_width = (graph_pwr / self.max_graph_pwr) * 300
        
        def draw():
            self.pwr_canvas.coords(self.pwr_bar, 0, 0, bar_width, 20)
            # Turn the bar Red if it crosses the threshold, Lime if it's below
            color = "lime" if pwr > self.current_threshold else "blue"
            self.pwr_canvas.itemconfig(self.pwr_bar, fill=color)

            # Update the text label with the exact integer value
            self.live_pwr_label.config(text=f"{int(pwr)}")
            
        self.root.after(0, draw)

    def handle_marconi_live(self, text):
        """Buffers the MAC addresses, prints the header, then streams the payload."""
        self.m_live_buffer += text
        self.history.configure(state='normal')
        
        if not self.m_header_printed:
            # THE FIX: Wait until we have exactly 2 MAC address characters (Dest + Src)
            if len(self.m_live_buffer) >= 2:
                dest = self.m_live_buffer[:1]
                src = self.m_live_buffer[1:2]
                
                tag = "received" if dest == config.MY_ADDRESS else "sniffed"
                ts = time.strftime("[%H:%M:%S]")
                
                header = f"{ts} *** FROM {src} **** (TO: {dest}) ***: "
                self.history.insert(tk.END, header, tag)
                
                # Print leftover payload characters (starting at index 2)
                payload = self.m_live_buffer[2:]
                if payload:
                    self.history.insert(tk.END, payload, tag)
                    
                self.m_header_printed = True
        else:
            dest = self.m_live_buffer[:1]
            tag = "received" if dest == config.MY_ADDRESS else "sniffed"
            self.history.insert(tk.END, text, tag)
            
        self.history.configure(state='disabled')
        self.history.see(tk.END)

    def finalize_live_line(self):
        """Appends a newline when a transmission finishes so the next log starts clean."""
        self.history.configure(state='normal')
        self.history.insert(tk.END, "\n")
        self.history.configure(state='disabled')


    def on_send(self, event):
        msg = self.entry.get().strip()
        if len(msg) == 0: return 
        self.entry.delete(0, tk.END)
        target = self.target_var.get()
        
        # Pass None for seq_hex so the daemon knows to generate a new one
        self.tx_queue.put((target, msg, "DT", None, 0))
        self.log(f"[Queued] -> {target}: {msg}")

    def tx_daemon(self):
            while True:
                # Unpack all 4 variables
                target, msg, ptype, seq_hex, retries = self.tx_queue.get()
                current_protocol = self.protocol_var.get()
                
                if current_protocol == "Marconi (OOK)":
                    self.marconi_transmitter.transmit(target, config.MY_ADDRESS, msg)
                elif current_protocol == "Teletype (FSK)":
                    self.teletype_transmitter.transmit(target, config.MY_ADDRESS, msg)     
                elif current_protocol == "Wireless Ethernet (CSMA/CA)":
                    
                    # Generate a new Sequence Number for fresh DATA packets
                    if ptype == "DT" and seq_hex is None:
                        seq_int = self.tx_seq_nums.get(target, 0)
                        seq_hex = f"{seq_int:04x}"

                    self.ethernet_transmitter.transmit(target, config.MY_ADDRESS, msg, packet_type=ptype, seq_hex=seq_hex)
                    
                    if ptype == "DT":
                        self.unacked_packet = {
                            "target": target, 
                            "msg": msg, 
                            "time": time.time(), 
                            "retries": retries,
                            "seq_hex": seq_hex # Store the sequence number!
                        }

                self.tx_queue.task_done()
                #Increase delay time from 15 to 35 tto ensure enqueued messages to not get muddled.
                if current_protocol == "Marconi (OOK)":
                   time.sleep(config.UNIT_TIME * 35)
                else:
                    time.sleep(config.UNIT_TIME * 15)  # Short delay after teletype transmission


    def receiver_loop(self):
        """Master RX loop that routes data to the external decoders."""
        
        # Track the protocol so we only rebuild the hardware buffer when it changes
        self.last_protocol = self.protocol_var.get()
        
        while True:
            current_protocol = self.protocol_var.get()
            
            # =========================================================
            # DYNAMIC BUFFER SWITCHER
            # =========================================================
            if current_protocol != self.last_protocol:
                try:
                    self.sdr.rx_destroy_buffer()
                except Exception:
                    pass
                
                # Marconi needs a tiny buffer for high-speed OS stopwatch timing
                if current_protocol == "Marconi (OOK)" or current_protocol == "ALOHAnet (OOK)":
                    self.sdr.rx_buffer_size = 500
                # Ethernet/Teletype need giant buffers so no array data is dropped
                else:
                    #self.sdr.rx_buffer_size = 1048576 big as can be
                    self.sdr.rx_buffer_size = 262144 # 262,144 provides 0.26s latency for rapid CSMA carrier sensing, but is large enough to prevent math from dropping USB samples!
                    
                self.last_protocol = current_protocol
            samples = self.sdr.rx()
            
            if self.is_transmitting:
                # We are blasting RF. Ignore the incoming math so we don't 
                # deafen our CPU trying to decode our own echo!
                self.channel_busy = False
                self.ethernet_decoder.receiving = False
                self.ethernet_decoder.buffer = []
                self.just_finished_tx = True 
                continue
            
            if self.just_finished_tx:
                # The exact millisecond TX finishes, destroy the hardware buffer
                # so we don't accidentally process the tail-end of the echo!
                self.just_finished_tx = False
                try:
                    self.sdr.rx_destroy_buffer()
                except Exception:
                    pass
                continue # Skip to the next clean buffer
            # Subtracting the mean instantly removes the LO Leakage from the 
            # other SDR, dropping the noise floor back down to near-zero 
            # and completely eliminating the destructive phase beating!
            #dc_blocked = samples - np.mean(samples)
            filtered_samples = np.diff(samples)
            
            pwr = np.percentile(np.abs(filtered_samples), 95)
            #pwr = np.max(np.abs(dc_blocked))
            #Evaluate whether the channel is busy by comparing to the current slider value.
            self.channel_busy = (pwr > self.current_threshold)
            
            # Update power meter at ~20 FPS (every 0.05 seconds) to prevent GUI freezing
            current_time = time.time()
            if current_time - self.last_meter_update > 0.05:
                self.update_power_meter(pwr)
                self.last_meter_update = current_time

            # Only update the GUI if the state actually flipped
            if self.channel_busy != self.last_rx_state:
                self.last_rx_state = self.channel_busy
                self.set_led("RX", "green" if self.channel_busy else "gray")

           # Route to the appropriate external decoder object
            current_protocol = self.protocol_var.get()
            packet_data = None
            
            if current_protocol == "Marconi (OOK)":
                new_m_text, packet_done = self.marconi_decoder.process(self.channel_busy)
                
                if new_m_text:
                    self.root.after(0, lambda t=new_m_text: self.handle_marconi_live(t))
                    
                if packet_done:
                    # If packet finished before 6 characters arrived, it's a runt!
                    if not self.m_header_printed and len(self.m_live_buffer) > 0:
                        self.root.after(0, lambda: self.log(f"?? Runt Marconi Packet: {self.m_live_buffer}", "error"))
                    elif self.m_header_printed:
                        # Lock in the line by dropping a \n character
                        self.root.after(0, self.finalize_live_line)
                        
                    # Reset the GUI state for the next message
                    self.m_live_buffer = ""
                    self.m_header_printed = False

            elif current_protocol == "Teletype (FSK)":
                packet_data = self.teletype_decoder.process(samples, self.channel_busy)
            elif current_protocol == "Wireless Ethernet (CSMA/CA)":
                # Ethernet uses raw samples to calculate the Manchester transitions
                packet_data = self.ethernet_decoder.process(samples, self.channel_busy, self.current_threshold)
                
            # If either Ethernet or Teletype finished assembling a packet, process it
            if packet_data and current_protocol in ["Wireless Ethernet (CSMA/CA)", "Teletype (FSK)"]:
                self.parse_fixed_packet(packet_data, current_protocol)

                # ==========================================
                # FLUSH THE SDR HARDWARE BUFFER
                # ==========================================
                try:
                    self.sdr.rx_destroy_buffer()
                except Exception as e:
                    pass

    def parse_fixed_packet(self, data, protocol):
        """Standardized Parsing with Ethernet CRC logic (No ACKs)."""
        data = data.rstrip('\x00')
        if len(data) >= (config.ADDR_LEN * 2):
            # Dynamically slice based on the config length!
            dest = data[:config.ADDR_LEN]
            src = data[config.ADDR_LEN : config.ADDR_LEN*2]
            
            # ----------------------------------------------------
            # ETHERNET MODE: EFTP PACKET ROUTING & CRC LOGIC 
            # ----------------------------------------------------
            if protocol == "Wireless Ethernet (CSMA/CA)":
                # Min length: (Dest + Src) + 2 Type + 4 Seq + 8 CRC = 16
                min_len = (config.ADDR_LEN * 2) + 2 + 4 + 8
                if len(data) < min_len: 
                    self.log(f"?? Runt Ethernet Packet: {data}", "error")
                    return
                
                ptype_start = config.ADDR_LEN * 2
                ptype = data[ptype_start : ptype_start + 2]
                seq_hex = data[ptype_start + 2 : ptype_start + 6]
                payload = data[ptype_start + 6 : -8]
                received_crc = data[-8:]
                
                frame_to_check = f"{dest}{src}{ptype}{seq_hex}{payload}".encode()
                calculated_crc = f"{zlib.crc32(frame_to_check) & 0xFFFFFFFF:08x}"
                
                if received_crc != calculated_crc:
                    self.log(f"[CRC FAILED] Received: {received_crc.upper()} != Calculated: {calculated_crc.upper()}", "error")
                    return 
                
                eftp_types = {"DT": "DATA", "AK": "ACK", "AB": "ABORT", "EN": "END", "ER": "ENDREPLY"}
                ptype_name = eftp_types.get(ptype, f"UNKNOWN({ptype})")
                msg = payload
                
                if dest == config.MY_ADDRESS:
                    if ptype == "DT":
                        seq_int = int(seq_hex, 16)
                        expected_seq = self.rx_seq_nums.get(src, 0)
                        
                        if seq_int == expected_seq:
                            self.log(f"[CRC VERIFIED] Received: {received_crc.upper()} == Calculated: {calculated_crc.upper()}", "status")
                            self.log(f"*** FROM {src} [{ptype_name} {seq_hex}] ***: {msg}", "received")
                            self.rx_seq_nums[src] = expected_seq + 1 # Increment expected sequence!
                        else:
                            self.log(f"[EFTP] Duplicate DATA packet {seq_hex} received from {src}. Ignoring payload.", "error")
                            
                        # ALWAYS auto-reply with an ACK, even for duplicates!
                        self.log(f"[EFTP] Auto-replying with ACK for {seq_hex}...", "status")
                        self.tx_queue.put((src, "", "AK", seq_hex, 0))
                        
                    elif ptype == "AK":
                        if self.unacked_packet and self.unacked_packet["target"] == src and self.unacked_packet["seq_hex"] == seq_hex:
                            self.log(f"[EFTP] ACK {seq_hex} received from {src}! Delivery confirmed.", "status")
                            self.unacked_packet = None 
                            self.tx_seq_nums[src] = self.tx_seq_nums.get(src, 0) + 1 # Ready next sequence!
                            
                else:
                    self.log(f"[Sniffed] {src}->{dest} [{ptype_name} {seq_hex}]: {msg} (CRC Verified)", "sniffed")

            # ----------------------------------------------------
            # MARCONI / ALOHA MODE (No Checksums)
            # ----------------------------------------------------
            else:
                msg = data[(config.ADDR_LEN * 2):]
                if dest == config.MY_ADDRESS:
                    self.log(f"*** FROM {src} ***: {msg}", "received")
                else:
                    self.log(f"[Sniffed] {src}->{dest}: {msg}", "sniffed")
        else:
            self.log(f"?? Runt Packet: {data}", "error")

    def check_eftp_timeouts(self):
        """Monitors pending transmissions and automatically re-queues them if they time out."""
        if self.unacked_packet:
            elapsed_time = time.time() - self.unacked_packet["time"]
            
            if elapsed_time > 10.0:
                target = self.unacked_packet["target"]
                msg = self.unacked_packet["msg"]
                self.unacked_packet["retries"] += 1
                retries = self.unacked_packet["retries"]
                
                self.log(f"[EFTP] Timeout: No ACK from {target} in 10s! Retransmitting (Attempt {retries})...", "error")
                
                # Re-queue the exact same message WITH ITS ORIGINAL SEQUENCE NUMBER
                self.tx_queue.put((target, msg, "DT", self.unacked_packet["seq_hex"], retries))
                self.unacked_packet = None
                
                # Clear the tracker so the loop doesn't enqueue multiple copies 
                # while waiting for the tx_daemon to physically transmit this retry!
                self.unacked_packet = None
                
        # Loop this check every 500ms
        self.root.after(500, self.check_eftp_timeouts)

if __name__ == "__main__":
    root = tk.Tk()
    app = MarconiNode(root)
    root.mainloop()